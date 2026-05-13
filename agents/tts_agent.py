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
    TTS_QWEN_BACKENDS,
    DEFAULT_TTS_QWEN_BACKEND,
    TTS_VOICE_CLONE_SPEAKERS,
    VOICE_DESCRIPTIONS,
    VOICE_CLONE_MIN_SAMPLE_DURATION_MS,
    VOICE_CLONE_STABILITY_THRESHOLD,
    VOICE_CLONE_REALIGN_INTERVAL,
    CHATTERBOX_DEFAULT_EXAGGERATION,
    CHATTERBOX_DEFAULT_CFG_WEIGHT,
    CHATTERBOX_CHUNK_MAX_CHARS,
    TTS_CHUNK_TRIM_HEAD_MS,
    TTS_CHUNK_TRIM_TAIL_MS,
    TTS_SILENCE_THRESHOLD,
    TTS_SEGMENT_CROSSFADE_MS,
    ENABLE_VOICE_CONSISTENCY_CHECK,
    CHATTERBOX_MIN_SIMILARITY,
    CHATTERBOX_MAX_REROLLS,
    CHATTERBOX_REROLL_SEEDS,
)
from utils import get_logger, save_text, strip_markers, make_error_record

logger = get_logger("TTSAgent")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_COMMON_TLDS = r'(?:ai|com|io|org|net|dev|co|app|xyz|me|tv|tech|info|biz|edu|gov|uk|us)'


def _normalize_for_tts(text: str) -> str:
    """
    Expand URLs, domain names, and symbols into natural spoken form so TTS
    doesn't read punctuation literally (e.g. "claude.ai" -> "claude dot ai").
    """
    # 1. Full URLs: https://claude.ai/chat -> "claude dot ai"
    def _url_spoken(m: re.Match) -> str:
        raw = m.group(0)
        raw = re.sub(r'^https?://(www\.)?', '', raw)
        domain = raw.split('/')[0].split('?')[0]
        return domain.replace('.', ' dot ')

    text = re.sub(r'https?://[^\s<>"\')\]]+', _url_spoken, text)

    # 2. Bare domain names: claude.ai, openai.com, hugging-face.co
    text = re.sub(
        r'\b([A-Za-z0-9][A-Za-z0-9\-]{0,30})\.(' + _COMMON_TLDS + r')\b',
        lambda m: f"{m.group(1)} dot {m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )

    # 3. Em/en dashes -> ", "
    text = re.sub(r'\s*[–—]\s*', ', ', text)

    # 4. Ampersand -> "and"
    text = re.sub(r'\s*&\s*', ' and ', text)

    # 5. Percentages: 42% -> "42 percent"
    text = re.sub(r'(\d[\d,\.]*)\s*%', r'\1 percent', text)

    # 6. Short financial suffixes: $3B, $1.2T, $500M, $4K
    def _money_suffix(m: re.Match) -> str:
        n, s = m.group(1), m.group(2).upper()
        word = {'B': 'billion', 'M': 'million', 'T': 'trillion', 'K': 'thousand'}.get(s, '')
        return f"{n} {word} dollars" if word else f"{n} dollars"

    text = re.sub(r'\$(\d[\d,\.]*)\s*([BMTKbmtk])\b', _money_suffix, text)

    # 7. Plain dollar amounts: $42 -> "42 dollars"
    text = re.sub(r'\$\s*(\d[\d,\.]*)', r'\1 dollars', text)

    # 8. Forward slash between words: AI/ML -> "AI ML"
    text = re.sub(r'(\w+)/(\w+)', r'\1 \2', text)

    # 9. Collapse extra whitespace
    text = re.sub(r'\s{2,}', ' ', text)

    return text.strip()


def _clean_for_tts(text: str) -> str:
    """Strip pipeline markers, citations, and normalize text for natural TTS output."""
    text = strip_markers(text)
    text = _normalize_for_tts(text)
    return text


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    """Break a single sentence that exceeds max_chars at comma/semicolon boundaries."""
    parts = re.split(r'(?<=[,;:])\s+', sentence)
    chunks: list[str] = []
    current = ""
    for p in parts:
        if len(current) + len(p) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = p
        else:
            current = (current + " " + p).strip() if current else p
    if current:
        chunks.append(current)
    # Last resort: word-boundary split
    result: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            result.append(chunk)
        else:
            words = chunk.split()
            c = ""
            for w in words:
                if len(c) + len(w) + 1 > max_chars and c:
                    result.append(c.strip())
                    c = w
                else:
                    c = (c + " " + w).strip() if c else w
            if c:
                result.append(c.strip())
    return result


def _chunk_text(text: str, max_chars: int = TTS_CHUNK_MAX_CHARS) -> list[str]:
    """
    Split text into chunks <= max_chars, preferring sentence boundaries.
    Falls back to comma/clause splits for sentences that themselves exceed max_chars.
    """
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for s in sentences:
        if len(s) > max_chars:
            # Flush current buffer first
            if current:
                chunks.append(current.strip())
                current = ""
            sub = _split_long_sentence(s, max_chars)
            chunks.extend(sub[:-1])
            current = sub[-1] if sub else ""
        elif len(current) + len(s) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = s
        else:
            current = (current + " " + s).strip() if current else s
    if current:
        chunks.append(current.strip())
    return [c for c in chunks if c]


def _ensure_punctuation(text: str) -> str:
    """Ensure text ends with sentence-closing punctuation to prevent Chatterbox looping."""
    text = text.strip()
    if text and text[-1] not in '.!?':
        text += '.'
    return text


def _normalise(audio_arr) -> "np.ndarray":
    """Normalise audio array to float32 [-1, 1]."""
    import numpy as np

    arr = audio_arr.astype("float32")
    peak = max(float(abs(arr).max()), 1e-6)
    return arr / peak


def _trim_silence(audio_arr, sample_rate: int,
                  max_head_ms: int = TTS_CHUNK_TRIM_HEAD_MS,
                  max_tail_ms: int = TTS_CHUNK_TRIM_TAIL_MS,
                  threshold: float = TTS_SILENCE_THRESHOLD):
    """
    Trim leading and trailing silence to at most max_head_ms / max_tail_ms.
    Detects silence as |sample| < threshold. Returns the same dtype as input.
    """
    import numpy as np

    if audio_arr is None or len(audio_arr) == 0:
        return audio_arr

    abs_arr = np.abs(audio_arr)
    nz = np.where(abs_arr > threshold)[0]
    if nz.size == 0:
        # All silence — return a short token of silence so we don't break stitching
        keep = int(sample_rate * max_head_ms / 1000)
        return audio_arr[:max(1, keep)]

    first_voice = int(nz[0])
    last_voice = int(nz[-1])

    keep_head = int(sample_rate * max_head_ms / 1000)
    keep_tail = int(sample_rate * max_tail_ms / 1000)

    start = max(0, first_voice - keep_head)
    end = min(len(audio_arr), last_voice + 1 + keep_tail)
    return audio_arr[start:end]


def _gpu_cleanup() -> None:
    """Best-effort GPU memory cleanup between heavy synthesis calls. Safe to call always."""
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Voice consistency checker (Chatterbox only, opt-in)
# ---------------------------------------------------------------------------

class _VoiceConsistencyChecker:
    """
    Lightweight speaker-similarity checker using Resemblyzer. Caches the
    reference voice embedding so each chunk only costs one encode pass.

    Disabled silently if resemblyzer isn't installed — synthesis proceeds
    without re-rolls.
    """

    def __init__(self) -> None:
        self._encoder = None
        self._ref_cache: dict[str, "np.ndarray"] = {}
        self._available: bool | None = None

    def available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            from resemblyzer import VoiceEncoder  # noqa: F401
            self._available = True
        except Exception as exc:
            logger.info("[VoiceCheck] resemblyzer unavailable (%s) — consistency check disabled.", exc)
            self._available = False
        return self._available

    def _load(self):
        if self._encoder is not None:
            return self._encoder
        from resemblyzer import VoiceEncoder
        self._encoder = VoiceEncoder(verbose=False)
        logger.info("[VoiceCheck] Resemblyzer encoder loaded.")
        return self._encoder

    def _ref_embedding(self, ref_path: str):
        import numpy as np
        if ref_path in self._ref_cache:
            return self._ref_cache[ref_path]
        from resemblyzer import preprocess_wav
        enc = self._load()
        wav = preprocess_wav(Path(ref_path))
        emb = enc.embed_utterance(wav)
        self._ref_cache[ref_path] = emb
        return emb

    def score(self, audio_arr, sample_rate: int, ref_path: str) -> float:
        """Return cosine similarity in [-1, 1] between generated audio and reference voice."""
        import numpy as np
        if not self.available() or not ref_path:
            return 1.0
        try:
            from resemblyzer import preprocess_wav
            enc = self._load()
            ref_emb = self._ref_embedding(ref_path)
            # Resemblyzer expects mono 16k float
            wav = preprocess_wav(audio_arr.astype("float32"), source_sr=sample_rate)
            cand_emb = enc.embed_utterance(wav)
            sim = float(np.dot(ref_emb, cand_emb))
            return sim
        except Exception as exc:
            logger.warning("[VoiceCheck] scoring failed (%s) — assuming OK.", exc)
            return 1.0


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

            cls._pipe = KPipeline(lang_code="a")  # 'a' = American English
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
                logger.warning(
                    "[Bark] CUDA not available in this Python environment. It will run on CPU and be very slow. Make sure you are using the 'opensearch' conda environment."
                )

            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info("[Bark] Loading suno/bark on %s...", device)
            cls._processor = AutoProcessor.from_pretrained("suno/bark")
            cls._model = AutoModel.from_pretrained("suno/bark").to(device)
            cls.SAMPLE_RATE = cls._model.generation_config.sample_rate
            cls._loaded = True
            logger.info("[Bark] Loaded. Sample rate: %d Hz", cls.SAMPLE_RATE)
            return True
        except ImportError:
            logger.warning(
                "[Bark] transformers not installed. Run: pip install transformers scipy"
            )
        except Exception as exc:
            logger.warning("[Bark] Failed to load: %s", exc)
        return False

    @classmethod
    def synthesise(
        cls, text: str, speaker_preset: str = "[speaker/en_speaker_6]"
    ) -> tuple:
        """Returns (np.ndarray, sample_rate)."""
        import torch

        # Bark uses speaker presets embedded in text
        tagged = f"{speaker_preset}\n{text}" if speaker_preset else text
        inputs = cls._processor(text=[tagged], return_tensors="pt")
        inputs = {
            k: v.to(next(cls._model.parameters()).device) for k, v in inputs.items()
        }
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
                logger.error(
                    "[Qwen] CUDA is NOT available in this Python environment. QwenVoiceDesign requires a GPU and will fail or run unacceptably slow on CPU."
                )
                logger.error(
                    "[Qwen] Are you sure you ran `conda activate opensearch` before starting app.py?"
                )

            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

            # Enable cuDNN auto-tuner for faster convolutions
            if torch.cuda.is_available():
                torch.backends.cudnn.benchmark = True

            logger.info(
                "[Qwen] Loading %s on %s (dtype=%s)...", cls.MODEL_ID, device, dtype
            )
            cls._model = Qwen3TTSModel.from_pretrained(
                cls.MODEL_ID, device_map=device, dtype=dtype
            )

            # Log GPU diagnostics so we can verify the model is on GPU
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                allocated = torch.cuda.memory_allocated(0) / 1024**3
                reserved = torch.cuda.memory_reserved(0) / 1024**3
                logger.info(
                    "[Qwen] GPU: %s | VRAM allocated: %.2f GB | reserved: %.2f GB",
                    gpu_name,
                    allocated,
                    reserved,
                )

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
    def synthesise(
        cls, text: str, instruct: str = "Speak naturally in a warm podcast voice."
    ) -> tuple:
        """Returns (np.ndarray, sample_rate)."""
        import torch

        with torch.inference_mode():
            wavs, sr = cls._model.generate_voice_design(
                text=text, language="English", instruct=instruct
            )
        return _normalise(wavs[0]), sr


# ---------------------------------------------------------------------------
# Backend: Chatterbox
# ---------------------------------------------------------------------------


class _ChatterboxBackend:
    """
    Resemble AI Chatterbox — zero-shot voice cloning from 5-20s reference audio.
    Supports emotion control via `exaggeration` and style control via `cfg_weight`.
    Install: pip install chatterbox-tts
    """

    _model = None
    _loaded = False
    SAMPLE_RATE = 24000

    @classmethod
    def load(cls) -> bool:
        if cls._loaded:
            return True
        try:
            import torch
            from chatterbox.tts import ChatterboxTTS  # pip install chatterbox-tts

            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info("[Chatterbox] Loading on %s...", device)
            try:
                cls._model = ChatterboxTTS.from_pretrained(device=device)
            except RuntimeError as cuda_err:
                # CUDA kernel errors on newer GPUs (e.g. Blackwell RTX 50-series)
                # whose compute capability isn't in the prebuilt PyTorch wheels.
                if device == "cuda" and "CUDA" in str(cuda_err):
                    logger.warning(
                        "[Chatterbox] CUDA failed (%s) — falling back to CPU. "
                        "To fix: install a PyTorch nightly with sm_120 support.",
                        cuda_err,
                    )
                    torch.cuda.empty_cache()
                    device = "cpu"
                    cls._model = ChatterboxTTS.from_pretrained(device=device)
                else:
                    raise
            cls._loaded = True
            logger.info("[Chatterbox] Loaded on %s. Sample rate: %d Hz", device, cls.SAMPLE_RATE)
            return True
        except ImportError:
            logger.warning(
                "[Chatterbox] Not installed. Run: pip install chatterbox-tts"
            )
        except Exception as exc:
            logger.warning("[Chatterbox] Failed to load: %s", exc)
        return False

    @classmethod
    def synthesise(
        cls,
        text: str,
        audio_prompt_path: str | None = None,
        exaggeration: float = CHATTERBOX_DEFAULT_EXAGGERATION,
        cfg_weight: float = CHATTERBOX_DEFAULT_CFG_WEIGHT,
        seed: int = 42,
    ) -> tuple:
        """Returns (np.ndarray, sample_rate). audio_prompt_path is optional reference WAV.
        `seed` is settable so the consistency checker can re-roll the same chunk."""
        import torch

        kwargs: dict = {"exaggeration": exaggeration, "cfg_weight": cfg_weight}
        if audio_prompt_path:
            kwargs["audio_prompt_path"] = audio_prompt_path

        with torch.inference_mode():
            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed(seed)
            wav = cls._model.generate(text, **kwargs)

        # wav is a torch.Tensor of shape (1, T) or (T,)
        arr = wav.squeeze().cpu().numpy().astype("float32")
        return _normalise(arr), cls.SAMPLE_RATE


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

_BACKENDS = {
    "kokoro": _KokoroBackend,
    "bark": _BarkBackend,
    "qwen": _QwenBackend,
    "chatterbox": _ChatterboxBackend,
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
    voice_id: str | None = None,
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
        logger.warning(
            "Unknown TTS backend '%s' — falling back to kokoro.", backend_name
        )
        backend_cls = _KokoroBackend
        backend_name = "kokoro"

    logger.info("TTS backend: %s", backend_name)

    if not backend_cls.load():
        logger.warning(
            "TTS backend '%s' unavailable — audio skipped. TTS text saved.",
            backend_name,
        )
        return {"audio_path": None, "tts_text_path": str(tts_txt_path)}

    try:
        import soundfile as sf
    except ImportError:
        logger.warning("soundfile not installed — pip install soundfile")
        return {"audio_path": None, "tts_text_path": str(tts_txt_path)}

    # Resolve voice for this backend
    if backend_name == "chatterbox":
        # For Chatterbox the "voice" is a reference audio path (or None for built-in)
        voice: str | None = None
        if voice_id:
            try:
                from voice_manager import get_voice_manager
                clone = get_voice_manager().get_voice_clone(voice_id)
                if clone:
                    voice = clone.ref_audio_path
                    logger.info("[Chatterbox] Using voice clone '%s' -> %s", clone.name, voice)
                else:
                    logger.warning("[Chatterbox] voice_id '%s' not found, using built-in voice", voice_id)
            except Exception as exc:
                logger.warning("[Chatterbox] Could not load voice clone: %s", exc)
    else:
        voice = GENDER_VOICES.get(backend_name, GENDER_VOICES["kokoro"]).get(
            voice_gender, "af_heart"
        )

    # --- Incremental per-segment synthesis with disk saves ---
    seg_dir = output_dir / "tts_segments"
    seg_dir.mkdir(exist_ok=True, parents=True)

    seg_wav_paths: list[Path] = []
    sample_rate: int = backend_cls.SAMPLE_RATE

    # Voice consistency checker — only meaningful for Chatterbox + reference voice
    use_voice_check = (
        ENABLE_VOICE_CONSISTENCY_CHECK
        and backend_name == "chatterbox"
        and isinstance(voice, str)
        and Path(voice).exists() if isinstance(voice, str) else False
    )
    voice_checker = _VoiceConsistencyChecker() if use_voice_check else None
    if voice_checker and not voice_checker.available():
        voice_checker = None  # silent disable when resemblyzer missing

    total_start = time.perf_counter()

    for seg_idx, (seg, clean_text) in enumerate(zip(segments, clean_texts)):
        if not clean_text.strip():
            continue
        seg_name = seg.get("name", "Segment")
        safe_name = re.sub(r"[^\w\-]", "_", seg_name).strip("_")
        seg_wav = seg_dir / f"{seg_idx:02d}_{safe_name}.wav"

        # Resume: skip segments already synthesised on a previous run
        if seg_wav.exists():
            logger.info(
                "Segment '%s' cached on disk, skipping -> %s", seg_name, seg_wav.name
            )
            seg_wav_paths.append(seg_wav)
            continue

        chunk_max = CHATTERBOX_CHUNK_MAX_CHARS if backend_name == "chatterbox" else TTS_CHUNK_MAX_CHARS
        chunks = _chunk_text(clean_text, max_chars=chunk_max)
        logger.info(
            "Synthesising [%s] '%s' with voice=%s (%d chunks, %d chars)...",
            backend_name,
            seg_name,
            voice,
            len(chunks),
            len(clean_text),
        )
        seg_start = time.perf_counter()

        seg_audio: list = []
        for i, chunk in enumerate(chunks, 1):
            try:
                t0 = time.perf_counter()
                if backend_name == "chatterbox":
                    chunk = _ensure_punctuation(chunk)
                    audio_arr, sr = backend_cls.synthesise(chunk, audio_prompt_path=voice)
                    # Voice consistency: re-roll up to MAX_REROLLS times on drift
                    if voice_checker is not None:
                        score = voice_checker.score(audio_arr, sr, voice)
                        attempts = 0
                        while score < CHATTERBOX_MIN_SIMILARITY and attempts < CHATTERBOX_MAX_REROLLS:
                            attempts += 1
                            seed = CHATTERBOX_REROLL_SEEDS[attempts % len(CHATTERBOX_REROLL_SEEDS)]
                            logger.warning(
                                "[VoiceCheck] '%s' chunk %d drift score=%.2f < %.2f, re-roll %d/%d (seed=%d)",
                                seg_name, i, score, CHATTERBOX_MIN_SIMILARITY,
                                attempts, CHATTERBOX_MAX_REROLLS, seed,
                            )
                            audio_arr, sr = backend_cls.synthesise(
                                chunk, audio_prompt_path=voice, seed=seed,
                            )
                            score = voice_checker.score(audio_arr, sr, voice)
                        logger.info("[VoiceCheck] chunk %d final score=%.2f", i, score)
                else:
                    audio_arr, sr = backend_cls.synthesise(chunk, voice)
                # Trim excessive head/tail silence the model may emit
                audio_arr = _trim_silence(audio_arr, sr)
                elapsed = time.perf_counter() - t0
                logger.info(
                    "  chunk %d/%d done in %.1fs (%d chars, %.2fs audio)",
                    i,
                    len(chunks),
                    elapsed,
                    len(chunk),
                    len(audio_arr) / sr if sr else 0.0,
                )
                seg_audio.append(audio_arr)
                sample_rate = sr
                silence = np.zeros(int(sr * TTS_INTER_CHUNK_SILENCE_S), dtype="float32")
                seg_audio.append(silence)
            except Exception as exc:
                logger.error("TTS error in '%s' chunk %d: %s", seg_name, i, exc)
            finally:
                # Release GPU memory between heavy generations (Chatterbox / Bark / Qwen on CUDA)
                if backend_name in ("chatterbox", "bark", "qwen"):
                    _gpu_cleanup()

        if seg_audio:
            # Append inter-segment silence then flush to disk
            seg_audio.append(
                np.zeros(
                    int(sample_rate * TTS_INTER_SEGMENT_SILENCE_S), dtype="float32"
                )
            )
            seg_combined = np.concatenate(seg_audio)
            sf.write(str(seg_wav), seg_combined, sample_rate)
            seg_elapsed = time.perf_counter() - seg_start
            logger.info(
                "Segment '%s' saved in %.1fs -> %s", seg_name, seg_elapsed, seg_wav.name
            )
            seg_wav_paths.append(seg_wav)
            del seg_combined, seg_audio  # free memory

    total_elapsed = time.perf_counter() - total_start
    logger.info(
        "Total TTS synthesis: %.1fs for %d segments", total_elapsed, len(segments)
    )

    if not seg_wav_paths:
        logger.warning("No audio generated.")
        return {"audio_path": None, "tts_text_path": str(tts_txt_path)}

    # --- Stitch segment WAVs into final MP3 with crossfades between segments ---
    mp3_path = output_dir / "episode.mp3"
    try:
        from pydub import AudioSegment as PydubSeg

        # Load each segment as pydub AudioSegment
        seg_audios = [PydubSeg.from_wav(str(p)) for p in seg_wav_paths]
        if not seg_audios:
            raise RuntimeError("No segment audio loaded")

        combined = seg_audios[0]
        xfade_ms = TTS_SEGMENT_CROSSFADE_MS
        for nxt in seg_audios[1:]:
            # crossfade can't exceed either side's length
            cf = min(xfade_ms, len(combined), len(nxt))
            if cf >= 50:   # only worth crossfading if there's enough material
                combined = combined.append(nxt, crossfade=cf)
            else:
                combined = combined + nxt

        combined = combined.set_frame_rate(AUDIO_SAMPLE_RATE)
        combined.export(str(mp3_path), format="mp3", bitrate=AUDIO_BITRATE)
        logger.info(
            "MP3 saved -> %s  (%d segments stitched, %dms crossfade)",
            mp3_path.name, len(seg_wav_paths), xfade_ms,
        )
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
    dry_run = state.get("dry_run", False)
    multi_voice = state.get("multi_voice", False)
    output_dir = Path(state.get("output_dir", "./outputs/episode"))

    backend = (
        (state.get("tts_backend") or os.getenv("TTS_BACKEND", DEFAULT_TTS_BACKEND))
        .lower()
        .strip()
    )
    voice_gender = state.get("voice_gender", "female").lower().strip()
    voice_id = state.get("voice_id") or None

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "TTS node — backend: %s  gender: %s  voice_id: %s  output: %s",
        backend,
        voice_gender,
        voice_id or "none",
        output_dir,
    )

    results = await asyncio.to_thread(
        _run_tts_sync,
        dry_run,
        multi_voice,
        output_dir,
        script_segments,
        backend,
        voice_gender,
        voice_id,
    )

    errors: list[dict] = []
    if not results.get("audio_path"):
        errors.append(make_error_record(
            "tts",
            f"TTS backend '{backend}' produced no audio — TTS-ready text saved instead",
            "warning",
        ))

    return {
        "current_status": f"TTS Complete [{backend}]",
        "tts_results": results,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Backward-compatible class wrapper (used by pipeline.py and tests)
# ---------------------------------------------------------------------------
class TTSAgent:
    """Class-based wrapper around the functional TTS node for pipeline/test compatibility."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def _run_gen(self, script, voice_id=None):
        """Synchronous generator yielding status strings then a tts_result dict."""
        segments = [
            seg.to_dict() if hasattr(seg, "to_dict") else seg for seg in script.segments
        ]
        dry_run = self.cfg.dry_run
        output_dir = Path(str(getattr(self.cfg, "output_dir", "./outputs/episode")))
        backend = os.getenv("TTS_BACKEND", DEFAULT_TTS_BACKEND)
        voice_gender = "female"

        if voice_id is None:
            voice_id = getattr(self.cfg, "voice_id", None)

        yield f"TTS synthesis — backend: {backend}"
        result = _run_tts_sync(
            dry_run, False, output_dir, segments, backend, voice_gender, voice_id
        )
        yield result

    def run(self, script, voice_id=None) -> dict:
        """Blocking run: returns tts_result dict."""
        items = list(self._run_gen(script, voice_id))
        for item in reversed(items):
            if not isinstance(item, str):
                return item
        return {}
