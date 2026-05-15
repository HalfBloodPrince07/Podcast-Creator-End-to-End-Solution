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
    CHATTERBOX_DEFAULT_TEMPERATURE,
    CHATTERBOX_PROSODY_ENABLED,
    CHATTERBOX_EXAGGERATION_RANGE,
    CHATTERBOX_CFG_WEIGHT_RANGE,
    CHATTERBOX_TEMPERATURE_RANGE,
    CHATTERBOX_DELTA_INTIMATE,
    CHATTERBOX_DELTA_QUESTION,
    CHATTERBOX_DELTA_EXCLAIM,
    CHATTERBOX_DELTA_EMPHASIS,
    CHATTERBOX_DELTA_REVEAL,
    CHATTERBOX_DELTA_HOOK,
    CHATTERBOX_DELTA_CLOSING,
    CHATTERBOX_JITTER_EXAGGERATION,
    CHATTERBOX_JITTER_CFG_WEIGHT,
    CHATTERBOX_JITTER_TEMPERATURE,
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


_EMPHASIS_RE = re.compile(r'\[EMPHASIS\](.*?)\[/EMPHASIS\]', re.IGNORECASE | re.DOTALL)
_PAUSE_SPLIT_RE = re.compile(r'\[PAUSE\s+([\d.]+)\s*(m?s)\]', re.IGNORECASE)

# ---------------------------------------------------------------------------
# Seasoned-podcaster prosody — content-driven per-chunk delivery parameters
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass(frozen=True)
class _DeliveryParams:
    """Chatterbox prosody parameters for a single TTS chunk.

    These map directly onto ChatterboxTTS.generate() args:
      - exaggeration: emotion intensity (0.25 monotone -> 2.0 over-the-top)
      - cfg_weight:   reference-voice adherence (lower = more variation)
      - temperature:  sampling stochasticity (higher = more variation)
    """
    exaggeration: float
    cfg_weight: float
    temperature: float
    mode_tags: tuple = ()  # human-readable mode names for logging


# Content patterns that drive specific delivery modes. These are intentionally
# conservative to avoid over-classifying — when nothing matches we fall back
# to the neutral baseline (which itself gets a small per-chunk jitter for
# natural inconsistency between sentences).
_RE_QUESTION = re.compile(r'\?')
_RE_EXCLAIM  = re.compile(r'!')
# Legacy ALL-CAPS run detector. Kept as a fallback signal for unusual content
# (acronyms, abbreviations in the source) — the PRIMARY emphasis signal is
# now the explicit `has_emphasis` flag passed into the classifier, because
# uppercasing the inner word made Chatterbox spell it letter-by-letter.
_RE_EMPHASIS_CAPS = re.compile(r'\b[A-Z]{3,}\b')
# "Revelation" cues: phrases a seasoned podcaster lands harder.
_RE_REVELATION = re.compile(
    r"\b("
    r"but\s+here[''](?:s| is)|"
    r"here[''](?:s| is)\s+(?:the|why|where|what|how)|"
    r"and\s+yet|"
    r"except|"
    r"surprisingly|"
    r"the\s+catch\s+is|"
    r"it\s+turns\s+out|"
    r"the\s+truth\s+is|"
    r"plot\s+twist"
    r")\b",
    re.IGNORECASE,
)
# "Hook" cues: openers and attention grabs delivered with more energy.
_RE_HOOK = re.compile(
    r"\b("
    r"imagine|"
    r"picture\s+this|"
    r"wait[,.]|"
    r"hold\s+on|"
    r"stop[,.]|"
    r"you\s+won[''](?:t| not)\s+believe|"
    r"get\s+this|"
    r"check\s+this\s+out|"
    r"listen[,.]"
    r")\b",
    re.IGNORECASE,
)
# "Intimate" cues: lines a podcaster pulls IN on (softer, more confidential).
_RE_INTIMATE = re.compile(
    r"\b("
    r"honestly|"
    r"truthfully|"
    r"between\s+you\s+and\s+me|"
    r"let\s+me\s+tell\s+you|"
    r"i[''](?:ll| will)\s+be\s+honest|"
    r"to\s+be\s+real"
    r")\b",
    re.IGNORECASE,
)


def _classify_chunk_delivery(
    text: str,
    chunk_index: int,
    total_chunks: int,
    *,
    seed: int = 0,
    has_emphasis: bool = False,
) -> _DeliveryParams:
    """Pick Chatterbox prosody parameters that match what this chunk is saying.

    Mimics how a seasoned podcaster modulates delivery on the fly: questions
    rise, exclamations punch, revelations land harder, intimate confessions
    pull in, hooks lean forward. Each modulation is a small delta stacked on
    the baseline; the final params get a tiny deterministic jitter so two
    adjacent neutral sentences don't sound identical (human inconsistency).

    Returns the same params regardless of seed — only the per-chunk jitter
    uses the seed so the voice-consistency reroll can use a different TTS
    seed without re-shuffling the prosody choices.
    """
    if not CHATTERBOX_PROSODY_ENABLED:
        return _DeliveryParams(
            exaggeration=CHATTERBOX_DEFAULT_EXAGGERATION,
            cfg_weight=CHATTERBOX_DEFAULT_CFG_WEIGHT,
            temperature=CHATTERBOX_DEFAULT_TEMPERATURE,
            mode_tags=("disabled",),
        )

    has_q = bool(_RE_QUESTION.search(text))
    has_excl = bool(_RE_EXCLAIM.search(text))
    # Primary signal: caller's explicit `has_emphasis` flag (from [EMPHASIS]
    # tag detection BEFORE stripping). Fallback: ALL-CAPS run in the cleaned
    # text — catches genuine acronyms/abbreviations that should also punch.
    has_emph = has_emphasis or bool(_RE_EMPHASIS_CAPS.search(text))
    is_reveal = bool(_RE_REVELATION.search(text))
    is_hook = bool(_RE_HOOK.search(text))
    is_intimate = bool(_RE_INTIMATE.search(text))
    is_opening = chunk_index == 0
    is_closing = chunk_index == total_chunks - 1 and total_chunks > 1

    exaggeration = CHATTERBOX_DEFAULT_EXAGGERATION
    cfg_weight   = CHATTERBOX_DEFAULT_CFG_WEIGHT
    temperature  = CHATTERBOX_DEFAULT_TEMPERATURE
    tags: list[str] = []

    def _apply(delta: dict, tag: str) -> None:
        nonlocal exaggeration, cfg_weight, temperature
        exaggeration += delta.get("exaggeration", 0.0)
        cfg_weight   += delta.get("cfg_weight", 0.0)
        temperature  += delta.get("temperature", 0.0)
        tags.append(tag)

    # Intimate is applied FIRST because subsequent cues (questions etc.) may
    # override it — a question inside an "honestly..." line should still rise.
    if is_intimate:
        _apply(CHATTERBOX_DELTA_INTIMATE, "intimate")
    if has_q:
        _apply(CHATTERBOX_DELTA_QUESTION, "question")
    if has_excl:
        _apply(CHATTERBOX_DELTA_EXCLAIM, "exclaim")
    if has_emph:
        _apply(CHATTERBOX_DELTA_EMPHASIS, "emphasis")
    if is_reveal:
        _apply(CHATTERBOX_DELTA_REVEAL, "revelation")
    if is_hook or is_opening:
        _apply(CHATTERBOX_DELTA_HOOK, "hook" if is_hook else "opening")
    if is_closing:
        _apply(CHATTERBOX_DELTA_CLOSING, "closing")
    if not tags:
        tags.append("neutral")

    # Deterministic jitter so two adjacent neutral chunks still sound slightly
    # different — that micro-inconsistency is what stops the output from
    # sounding like the same line read twice.
    import random
    rng = random.Random((seed * 1000003) ^ (chunk_index + 1) * 2654435761)
    exaggeration += rng.uniform(-CHATTERBOX_JITTER_EXAGGERATION, CHATTERBOX_JITTER_EXAGGERATION)
    cfg_weight   += rng.uniform(-CHATTERBOX_JITTER_CFG_WEIGHT,   CHATTERBOX_JITTER_CFG_WEIGHT)
    temperature  += rng.uniform(-CHATTERBOX_JITTER_TEMPERATURE,  CHATTERBOX_JITTER_TEMPERATURE)

    return _DeliveryParams(
        exaggeration=max(CHATTERBOX_EXAGGERATION_RANGE[0], min(CHATTERBOX_EXAGGERATION_RANGE[1], exaggeration)),
        cfg_weight=max(CHATTERBOX_CFG_WEIGHT_RANGE[0],     min(CHATTERBOX_CFG_WEIGHT_RANGE[1],   cfg_weight)),
        temperature=max(CHATTERBOX_TEMPERATURE_RANGE[0],   min(CHATTERBOX_TEMPERATURE_RANGE[1],  temperature)),
        mode_tags=tuple(tags),
    )


def _strip_emphasis_tags(text: str) -> str:
    """Remove [EMPHASIS]...[/EMPHASIS] tags but keep the inner word in its
    original case.

    Earlier versions of this code uppercased the inner word as a hack to
    drive stronger Chatterbox delivery. That backfired badly: Chatterbox's
    BPE tokenizer treats ALL-CAPS words like acronyms (FBI, ATM, USA), so
    "MYSTERY" came out pronounced "M-Y-stery". Better to leave the word
    alone and lift the WHOLE CHUNK'S exaggeration via the classifier when
    emphasis is present — the moment lands, the word stays a word.
    """
    return _EMPHASIS_RE.sub(lambda m: m.group(1), text)


def _has_emphasis(text: str) -> bool:
    """True if `text` contains at least one [EMPHASIS]...[/EMPHASIS] tag."""
    return bool(_EMPHASIS_RE.search(text))


def _split_by_pauses(text: str) -> list[tuple[str, float]]:
    """Split text on [PAUSE Xms] / [PAUSE Xs] markers into (piece, silence_after_seconds).

    The last piece always has silence_after=0.0 (nothing to pause for at the
    end). Pieces preserve any OTHER markers (CUE, VISUAL, SRC, EMPHASIS) for
    a later strip pass — only the pause markers are consumed here so we can
    drive real numpy silence between TTS chunks instead of letting the
    markers get stripped away unused.
    """
    parts = _PAUSE_SPLIT_RE.split(text)
    # _PAUSE_SPLIT_RE has 2 capture groups, so split() interleaves:
    #   [text0, dur0, unit0, text1, dur1, unit1, ..., textN]
    result: list[tuple[str, float]] = []
    i = 0
    while i < len(parts):
        piece = parts[i] if i < len(parts) else ""
        if i + 2 < len(parts):
            try:
                dur = float(parts[i + 1])
                unit = (parts[i + 2] or "s").lower()
                silence_s = dur / 1000.0 if unit == "ms" else dur
                # Clamp to sane range — accept up to 4s even if writer overcooks.
                silence_s = max(0.0, min(4.0, silence_s))
            except (ValueError, TypeError, AttributeError):
                silence_s = 0.0
            result.append((piece, silence_s))
            i += 3
        else:
            result.append((piece, 0.0))
            i += 1
    return result


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

    @classmethod
    def unload(cls) -> None:
        cls._pipe = None
        cls._loaded = False
        _gpu_cleanup()


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

    @classmethod
    def unload(cls) -> None:
        cls._model = None
        cls._processor = None
        cls._loaded = False
        _gpu_cleanup()


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

    @classmethod
    def unload(cls) -> None:
        cls._model = None
        cls._loaded = False
        _gpu_cleanup()


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
        temperature: float = CHATTERBOX_DEFAULT_TEMPERATURE,
        seed: int = 42,
    ) -> tuple:
        """Returns (np.ndarray, sample_rate). audio_prompt_path is optional reference WAV.
        `seed` is settable so the consistency checker can re-roll the same chunk."""
        import torch

        kwargs: dict = {
            "exaggeration": exaggeration,
            "cfg_weight": cfg_weight,
            "temperature": temperature,
        }
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

    @classmethod
    def unload(cls) -> None:
        # Chatterbox stays resident on CUDA after synthesis; explicit drop +
        # cache empty is required before another CUDA model (Whisper) loads
        # or it can silently stall inside CTranslate2's decode loop on Windows.
        cls._model = None
        cls._loaded = False
        _gpu_cleanup()


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

_BACKENDS = {
    "kokoro": _KokoroBackend,
    "bark": _BarkBackend,
    "qwen": _QwenBackend,
    "chatterbox": _ChatterboxBackend,
}


def unload_all_backends() -> None:
    """Free every loaded TTS backend's model and clear CUDA cache.

    Call this between heavy GPU stages (e.g. before Whisper alignment) so that
    a TTS model still resident on the GPU doesn't starve the next consumer.
    Backends are reloadable on the next synthesise() call via load().
    """
    for name, cls in _BACKENDS.items():
        try:
            if getattr(cls, "_loaded", False):
                cls.unload()
                logger.info("[TTS] Unloaded backend '%s'.", name)
        except Exception as exc:
            logger.warning("[TTS] Failed to unload backend '%s': %s", name, exc)
    # Final sweep — also releases anything dangling from voice consistency check, etc.
    _gpu_cleanup()
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            torch.cuda.ipc_collect()
    except Exception:
        pass


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

        # Build (chunk_text, silence_after_seconds, has_emphasis) triples that
        # honor the audio-designer's [PAUSE Xms] markers as real variable
        # silence AND track [EMPHASIS] presence per chunk (used by the
        # classifier to lift exaggeration on emphasised chunks). We deliberately
        # do NOT uppercase the emphasised word — Chatterbox's BPE tokenizer
        # reads ALL-CAPS as acronyms and spells the letters out.
        raw_text = seg.get("text", "") or ""
        pieces = _split_by_pauses(raw_text)
        chunks_with_silence: list[tuple[str, float, bool]] = []
        for piece_idx, (piece, sec_after) in enumerate(pieces):
            # Detect emphasis BEFORE stripping so the flag survives the clean pass.
            piece_has_emphasis = _has_emphasis(piece)
            # Strip emphasis tags but keep inner word in its natural case.
            piece_no_emph = _strip_emphasis_tags(piece)
            piece_clean = _clean_for_tts(piece_no_emph)
            if not piece_clean.strip():
                # Empty piece (just markers) — fold its pause into the prior chunk's silence.
                if chunks_with_silence and sec_after > 0:
                    prev_text, prev_silence, prev_emph = chunks_with_silence[-1]
                    chunks_with_silence[-1] = (prev_text, prev_silence + sec_after, prev_emph)
                continue
            sub_chunks = _chunk_text(piece_clean, max_chars=chunk_max)
            for sub_idx, sub in enumerate(sub_chunks):
                is_last_of_piece = sub_idx == len(sub_chunks) - 1
                if is_last_of_piece and sec_after > 0:
                    # End of an explicit pause boundary — use the marker's duration.
                    silence_after = sec_after
                else:
                    # Mid-piece chunk boundary OR last-piece-of-segment: default inter-chunk silence.
                    silence_after = TTS_INTER_CHUNK_SILENCE_S
                chunks_with_silence.append((sub, silence_after, piece_has_emphasis))
        if not chunks_with_silence:
            # Fall back to the legacy path if the pause split somehow yielded nothing usable.
            chunks_with_silence = [(c, TTS_INTER_CHUNK_SILENCE_S, False) for c in _chunk_text(clean_text, max_chars=chunk_max)]

        chunks = [c for c, _, _ in chunks_with_silence]  # back-compat for logs / voice-check
        total_chars = sum(len(c) for c in chunks)
        marker_pause_total = sum(s for (_, s, _) in chunks_with_silence if s != TTS_INTER_CHUNK_SILENCE_S)
        logger.info(
            "Synthesising [%s] '%s' with voice=%s (%d chunks, %d chars, %.1fs marker-driven silence)...",
            backend_name,
            seg_name,
            voice,
            len(chunks),
            total_chars,
            marker_pause_total,
        )
        seg_start = time.perf_counter()

        seg_audio: list = []
        for i, (chunk, silence_after_s, chunk_has_emphasis) in enumerate(chunks_with_silence, 1):
            try:
                t0 = time.perf_counter()
                if backend_name == "chatterbox":
                    chunk = _ensure_punctuation(chunk)
                    # Seasoned-podcaster prosody: pick delivery params based
                    # on what THIS chunk is saying (question, exclamation,
                    # emphasis, reveal, hook, intimate, closing, opening) +
                    # tiny per-chunk jitter for natural inconsistency.
                    delivery = _classify_chunk_delivery(
                        chunk,
                        chunk_index=i - 1,
                        total_chunks=len(chunks_with_silence),
                        has_emphasis=chunk_has_emphasis,
                    )
                    logger.info(
                        "  chunk %d/%d delivery=%s exag=%.2f cfg=%.2f temp=%.2f",
                        i, len(chunks_with_silence), ",".join(delivery.mode_tags),
                        delivery.exaggeration, delivery.cfg_weight, delivery.temperature,
                    )
                    audio_arr, sr = backend_cls.synthesise(
                        chunk,
                        audio_prompt_path=voice,
                        exaggeration=delivery.exaggeration,
                        cfg_weight=delivery.cfg_weight,
                        temperature=delivery.temperature,
                    )
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
                                chunk,
                                audio_prompt_path=voice,
                                exaggeration=delivery.exaggeration,
                                cfg_weight=delivery.cfg_weight,
                                temperature=delivery.temperature,
                                seed=seed,
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
                # Per-chunk silence is now driven by the audio designer's
                # [PAUSE Xms] markers (variable) instead of a fixed default.
                silence = np.zeros(int(sr * silence_after_s), dtype="float32")
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
    # The audio designer was the last LLM consumer in the graph. Tell LM
    # Studio to unload its weights now so TTS / Whisper / SDXL / CogVideoX
    # have the GPU to themselves. Best-effort — non-LM-Studio servers no-op.
    try:
        from llm_client import unload_model
        if not state.get("dry_run"):
            unload_model()
    except Exception as exc:
        logger.info("LLM unload before TTS skipped: %s", exc)

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
