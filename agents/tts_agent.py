"""
agents/tts_agent.py — Multi-backend TTS for the Podcast Pipeline.

Select backend via TTS_BACKEND env var (or via the frontend dropdown which
passes it as `tts_backend` in state):

  kokoro  (default) — Kokoro-82M, CPU-friendly, < 2 GB, Apache 2.0
                      pip install kokoro soundfile
  bark              — Suno Bark via 🤗 Transformers, ~4 GB, expressive
                      pip install transformers scipy soundfile
  qwen              — Qwen3-TTS-12Hz-1.7B-VoiceDesign, ~4 GB GPU, voice-design
                      pip install qwen-tts soundfile

Falls back to writing episode_tts_ready.txt when:
  • required package is missing
  • model fails to load / OOM
  • dry_run=True
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from constants import (
    AUDIO_BITRATE,
    AUDIO_SAMPLE_RATE,
    DEFAULT_TTS_BACKEND,
    TTS_CHUNK_MAX_CHARS,
    TTS_INTER_CHUNK_SILENCE_S,
    TTS_INTER_SEGMENT_SILENCE_S,
    GENDER_VOICES,
)
from utils import get_logger, save_text, strip_markers

logger = get_logger("TTSAgent")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _clean_for_tts(text: str) -> str:
    """Strip all pipeline markers and citations so TTS gets pure speech."""
    return strip_markers(text)


def _chunk_text(text: str, max_chars: int = TTS_CHUNK_MAX_CHARS) -> list[str]:
    """Split text into chunks ≤ max_chars, breaking at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: list[str] = []
    current = ""
    for s in sentences:
        if len(current) + len(s) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = s
        else:
            current = (current + " " + s).strip()
    if current:
        chunks.append(current)
    return chunks


def _normalise(audio_arr) -> "np.ndarray":
    """Normalise audio array to float32 [-1, 1]."""
    import numpy as np
    arr = audio_arr.astype("float32")
    peak = max(float(abs(arr).max()), 1e-6)
    return arr / peak


# ---------------------------------------------------------------------------
# Backend: Kokoro
# ---------------------------------------------------------------------------

class _KokoroBackend:
    """
    Kokoro-82M — best default choice.
    Install: pip install kokoro soundfile
    """
    _pipe = None
    _loaded = False
    SAMPLE_RATE = 24000

    @classmethod
    def load(cls) -> bool:
        if cls._loaded:
            return True
        try:
            from kokoro import KPipeline  # pip install kokoro
            cls._pipe = KPipeline(lang_code="a")   # 'a' = American English
            cls._loaded = True
            logger.info("[Kokoro] Loaded KPipeline (American English).")
            return True
        except ImportError:
            logger.warning("[Kokoro] Not installed. Run: pip install kokoro soundfile")
        except Exception as exc:
            logger.warning("[Kokoro] Failed to load: %s", exc)
        return False

    @classmethod
    def synthesise(cls, text: str, voice_id: str = "af_heart") -> tuple:
        """Returns (np.ndarray, sample_rate)."""
        import numpy as np
        chunks_out = []
        for _, _, audio in cls._pipe(text, voice=voice_id, speed=1.0):
            chunks_out.append(_normalise(audio))
        if not chunks_out:
            return np.zeros(100, dtype="float32"), cls.SAMPLE_RATE
        return np.concatenate(chunks_out), cls.SAMPLE_RATE


# ---------------------------------------------------------------------------
# Backend: Bark
# ---------------------------------------------------------------------------

class _BarkBackend:
    """
    Suno Bark via 🤗 Transformers.
    Install: pip install transformers scipy soundfile
    """
    _processor = None
    _model = None
    _loaded = False
    SAMPLE_RATE = 24000

    @classmethod
    def load(cls) -> bool:
        if cls._loaded:
            return True
        try:
            import torch
            
            try:
                import torchaudio
                torchaudio.set_audio_backend("soundfile")
            except Exception:
                pass
                
            from transformers import AutoModel, AutoProcessor

            if not torch.cuda.is_available():
                logger.warning("[Bark] CUDA not available in this Python environment. It will run on CPU and be very slow. Make sure you are using the 'opensearch' conda environment.")

            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info("[Bark] Loading suno/bark on %s...", device)
            cls._processor = AutoProcessor.from_pretrained("suno/bark")
            cls._model = AutoModel.from_pretrained("suno/bark").to(device)
            cls.SAMPLE_RATE = cls._model.generation_config.sample_rate
            cls._loaded = True
            logger.info("[Bark] Loaded. Sample rate: %d Hz", cls.SAMPLE_RATE)
            return True
        except ImportError:
            logger.warning("[Bark] transformers not installed. Run: pip install transformers scipy")
        except Exception as exc:
            logger.warning("[Bark] Failed to load: %s", exc)
        return False

    @classmethod
    def synthesise(cls, text: str, speaker_preset: str = "[speaker/en_speaker_6]") -> tuple:
        """Returns (np.ndarray, sample_rate)."""
        import torch
        # Bark uses speaker presets embedded in text
        tagged = f"{speaker_preset}\n{text}" if speaker_preset else text
        inputs = cls._processor(text=[tagged], return_tensors="pt")
        inputs = {k: v.to(next(cls._model.parameters()).device) for k, v in inputs.items()}
        with torch.no_grad():
            speech = cls._model.generate(**inputs, do_sample=True)
        audio = speech.cpu().numpy().squeeze().astype("float32")
        return _normalise(audio), cls.SAMPLE_RATE


# ---------------------------------------------------------------------------
# Backend: Qwen3-TTS (VoiceDesign)
# ---------------------------------------------------------------------------

class _QwenBackend:
    """
    Qwen3-TTS-12Hz-1.7B-VoiceDesign via the qwen-tts package.
    Install: pip install qwen-tts soundfile
    """
    _model = None
    _loaded = False
    SAMPLE_RATE = 24000
    MODEL_ID = os.getenv("QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")

    @classmethod
    def load(cls) -> bool:
        if cls._loaded:
            return True
        try:
            import torch
            
            try:
                import torchaudio
                torchaudio.set_audio_backend("soundfile")
            except Exception:
                pass
                
            from qwen_tts import Qwen3TTSModel  # pip install qwen-tts

            if not torch.cuda.is_available():
                logger.error("[Qwen] CUDA is NOT available in this Python environment. QwenVoiceDesign requires a GPU and will fail or run unacceptably slow on CPU.")
                logger.error("[Qwen] Are you sure you ran `conda activate opensearch` before starting app.py?")

            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype  = torch.bfloat16 if torch.cuda.is_available() else torch.float32

            # Enable cuDNN auto-tuner for faster convolutions
            if torch.cuda.is_available():
                torch.backends.cudnn.benchmark = True

            logger.info("[Qwen] Loading %s on %s (dtype=%s)...", cls.MODEL_ID, device, dtype)
            cls._model = Qwen3TTSModel.from_pretrained(
                cls.MODEL_ID, device_map=device, dtype=dtype
            )

            # Log GPU diagnostics so we can verify the model is on GPU
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                allocated = torch.cuda.memory_allocated(0) / 1024**3
                reserved  = torch.cuda.memory_reserved(0) / 1024**3
                logger.info("[Qwen] GPU: %s | VRAM allocated: %.2f GB | reserved: %.2f GB",
                            gpu_name, allocated, reserved)

            # Suppress noisy per-call logs from qwen_tts internals
            # (e.g. "code_predictor_config is None" on every generate call)
            logging.getLogger("qwen_tts").setLevel(logging.WARNING)

            # Probe sample rate (also warms up the model)
            with torch.inference_mode():
                wavs, sr = cls._model.generate_voice_design(
                    text="Hello.", language="English", instruct="Speak naturally."
                )
            cls.SAMPLE_RATE = sr
            cls._loaded = True
            logger.info("[Qwen] Loaded. Sample rate: %d Hz", sr)
            return True
        except ImportError:
            logger.warning("[Qwen] qwen-tts not installed. Run: pip install qwen-tts")
        except Exception as exc:
            logger.warning("[Qwen] Failed to load: %s", exc)
        return False

    @classmethod
    def synthesise(cls, text: str, instruct: str = "Speak naturally in a warm podcast voice.") -> tuple:
        """Returns (np.ndarray, sample_rate)."""
        import torch
        with torch.inference_mode():
            wavs, sr = cls._model.generate_voice_design(
                text=text, language="English", instruct=instruct
            )
        return _normalise(wavs[0]), sr


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

_BACKENDS = {
    "kokoro": _KokoroBackend,
    "bark":   _BarkBackend,
    "qwen":   _QwenBackend,
}


# ---------------------------------------------------------------------------
# Main synchronous runner
# ---------------------------------------------------------------------------

def _run_tts_sync(
    dry_run: bool,
    multi_voice: bool,  # Ignored now as we map directly to a constant single voice
    output_dir: Path,
    segments: list[dict],
    backend_name: str,
    voice_gender: str = "female",
) -> dict:
    """Blocking synthesis runner — offloaded to a thread by run_tts_node."""
    import numpy as np

    backend_name = (backend_name or DEFAULT_TTS_BACKEND).lower().strip()
    voice_gender = (voice_gender or "female").lower().strip()

    # Always write the clean TTS text file
    clean_texts = [_clean_for_tts(seg.get("text", "")) for seg in segments]
    full_clean = "\n\n".join(
        f"[{s.get('name', 'Segment')}]\n{t}" for s, t in zip(segments, clean_texts)
    )
    output_dir.mkdir(exist_ok=True, parents=True)
    tts_txt_path = output_dir / "episode_tts_ready.txt"
    save_text(tts_txt_path, full_clean)
    logger.info("TTS-ready script saved -> %s", tts_txt_path.name)

    if dry_run:
        logger.info("[Dry run] Skipping TTS synthesis.")
        return {"audio_path": None, "tts_text_path": str(tts_txt_path)}

    # Select backend
    backend_cls = _BACKENDS.get(backend_name)
    if backend_cls is None:
        logger.warning("Unknown TTS backend '%s' — falling back to kokoro.", backend_name)
        backend_cls = _KokoroBackend
        backend_name = "kokoro"

    logger.info("TTS backend: %s", backend_name)

    if not backend_cls.load():
        logger.warning(
            "TTS backend '%s' unavailable — audio skipped. TTS text saved.", backend_name
        )
        return {"audio_path": None, "tts_text_path": str(tts_txt_path)}

    try:
        import soundfile as sf
    except ImportError:
        logger.warning("soundfile not installed — pip install soundfile")
        return {"audio_path": None, "tts_text_path": str(tts_txt_path)}

    # Lookup the constant voice to use based on gender and backend
    voice = GENDER_VOICES.get(backend_name, GENDER_VOICES["kokoro"]).get(voice_gender, "af_heart")

    # --- Incremental per-segment synthesis with disk saves ---
    seg_dir = output_dir / "tts_segments"
    seg_dir.mkdir(exist_ok=True, parents=True)

    seg_wav_paths: list[Path] = []
    sample_rate: int = backend_cls.SAMPLE_RATE

    total_start = time.perf_counter()

    for seg_idx, (seg, clean_text) in enumerate(zip(segments, clean_texts)):
        if not clean_text.strip():
            continue
        seg_name = seg.get("name", "Segment")
        safe_name = re.sub(r'[^\w\-]', '_', seg_name).strip('_')
        seg_wav = seg_dir / f"{seg_idx:02d}_{safe_name}.wav"

        # Resume: skip segments already synthesised on a previous run
        if seg_wav.exists():
            logger.info("Segment '%s' cached on disk, skipping -> %s", seg_name, seg_wav.name)
            seg_wav_paths.append(seg_wav)
            continue

        chunks = _chunk_text(clean_text)
        logger.info("Synthesising [%s] '%s' with voice=%s (%d chunks, %d chars)...",
                     backend_name, seg_name, voice, len(chunks), len(clean_text))
        seg_start = time.perf_counter()

        seg_audio: list = []
        for i, chunk in enumerate(chunks, 1):
            try:
                t0 = time.perf_counter()
                audio_arr, sr = backend_cls.synthesise(chunk, voice)
                elapsed = time.perf_counter() - t0
                logger.info("  chunk %d/%d done in %.1fs (%d chars)",
                            i, len(chunks), elapsed, len(chunk))
                seg_audio.append(audio_arr)
                sample_rate = sr
                silence = np.zeros(int(sr * TTS_INTER_CHUNK_SILENCE_S), dtype="float32")
                seg_audio.append(silence)
            except Exception as exc:
                logger.error("TTS error in '%s' chunk %d: %s", seg_name, i, exc)

        if seg_audio:
            # Append inter-segment silence then flush to disk
            seg_audio.append(np.zeros(int(sample_rate * TTS_INTER_SEGMENT_SILENCE_S), dtype="float32"))
            seg_combined = np.concatenate(seg_audio)
            sf.write(str(seg_wav), seg_combined, sample_rate)
            seg_elapsed = time.perf_counter() - seg_start
            logger.info("Segment '%s' saved in %.1fs -> %s", seg_name, seg_elapsed, seg_wav.name)
            seg_wav_paths.append(seg_wav)
            del seg_combined, seg_audio  # free memory

    total_elapsed = time.perf_counter() - total_start
    logger.info("Total TTS synthesis: %.1fs for %d segments", total_elapsed, len(segments))

    if not seg_wav_paths:
        logger.warning("No audio generated.")
        return {"audio_path": None, "tts_text_path": str(tts_txt_path)}

    # --- Stitch segment WAVs into final MP3 ---
    mp3_path = output_dir / "episode.mp3"
    try:
        from pydub import AudioSegment as PydubSeg
        combined = PydubSeg.empty()
        for wav_path in seg_wav_paths:
            combined += PydubSeg.from_wav(str(wav_path))
        combined = combined.set_frame_rate(AUDIO_SAMPLE_RATE)
        combined.export(str(mp3_path), format="mp3", bitrate=AUDIO_BITRATE)
        logger.info("MP3 saved -> %s  (%d segments stitched)", mp3_path.name, len(seg_wav_paths))
    except Exception as exc:
        logger.error("MP3 stitching failed (%s) — falling back to raw WAV.", exc)
        all_arrays = [sf.read(str(p))[0] for p in seg_wav_paths]
        raw_wav = output_dir / "episode_raw.wav"
        sf.write(str(raw_wav), np.concatenate(all_arrays), sample_rate)
        mp3_path = raw_wav
        logger.info("Fallback WAV saved -> %s", raw_wav.name)

    return {
        "audio_path": str(mp3_path),
        "tts_text_path": str(tts_txt_path),
        "sample_rate": sample_rate,
        "backend": backend_name,
    }


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------

async def run_tts_node(state: dict) -> dict:
    """
    LangGraph node: synthesise speech from annotated script segments.
    Backend is chosen from state['tts_backend'] → env TTS_BACKEND → 'kokoro'.
    """
    script_segments = state.get("script_segments", [])
    dry_run     = state.get("dry_run", False)
    multi_voice = state.get("multi_voice", False)
    output_dir  = Path(state.get("output_dir", "./outputs/episode"))

    backend = (
        state.get("tts_backend")
        or os.getenv("TTS_BACKEND", DEFAULT_TTS_BACKEND)
    ).lower().strip()
    voice_gender = state.get("voice_gender", "female").lower().strip()

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("TTS node — backend: %s  gender: %s  output: %s", backend, voice_gender, output_dir)

    results = await asyncio.to_thread(
        _run_tts_sync, dry_run, multi_voice, output_dir, script_segments, backend, voice_gender
    )

    return {
        "current_status": f"TTS Complete [{backend}]",
        "tts_results": results,
    }


# ---------------------------------------------------------------------------
# Backward-compatible class wrapper (used by pipeline.py and tests)
# ---------------------------------------------------------------------------
class TTSAgent:
    """Class-based wrapper around the functional TTS node for pipeline/test compatibility."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def _run_gen(self, script):
        """Synchronous generator yielding status strings then a tts_result dict."""
        segments = [seg.to_dict() if hasattr(seg, "to_dict") else seg for seg in script.segments]
        dry_run = self.cfg.dry_run
        output_dir = Path(str(getattr(self.cfg, "output_dir", "./outputs/episode")))
        backend = os.getenv("TTS_BACKEND", DEFAULT_TTS_BACKEND)
        voice_gender = "female"

        yield f"TTS synthesis — backend: {backend}"
        result = _run_tts_sync(dry_run, False, output_dir, segments, backend, voice_gender)
        yield result

    def run(self, script) -> dict:
        """Blocking run: returns tts_result dict."""
        items = list(self._run_gen(script))
        for item in reversed(items):
            if not isinstance(item, str):
                return item
        return {}
