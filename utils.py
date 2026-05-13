"""
utils.py — Shared utilities for the Podcast Pipeline.
"""
from __future__ import annotations

import json
import logging
import re
import textwrap
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_LOG_DATEFMT = "%H:%M:%S"
_logging_initialized = False


def setup_logging(level: str | None = None, log_dir: str = "logs") -> None:
    """
    Configure logging with both console and rotating file handlers.
    Safe to call multiple times — only initializes once.
    """
    global _logging_initialized
    if _logging_initialized:
        return
    _logging_initialized = True

    import os
    from logging.handlers import RotatingFileHandler

    level = level or os.getenv("LOG_LEVEL", "INFO")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear handlers added by basicConfig to avoid duplicate log lines
    root.handlers.clear()

    # Console handler — force UTF-8 so Unicode chars (e.g. →) don't crash on
    # Windows terminals that default to cp1252.
    import sys
    ch = logging.StreamHandler(stream=open(sys.stderr.fileno(), mode='w', encoding='utf-8', closefd=False))
    ch.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
    root.addHandler(ch)

    # File handler (rotating, 5 MB max, 3 backups)
    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            f"{log_dir}/pipeline.log", maxBytes=5 * 1024 * 1024, backupCount=3,
        )
        fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
        root.addHandler(fh)
    except OSError:
        pass  # Skip file logging if directory isn't writable


# Initialize with basicConfig as fallback (for imports before setup_logging).
# Force UTF-8 on the default stderr stream so Windows cp1252 doesn't crash.
import sys as _sys
logging.basicConfig(
    format=_LOG_FORMAT, datefmt=_LOG_DATEFMT, level=logging.INFO,
    stream=open(_sys.stderr.fileno(), mode='w', encoding='utf-8', closefd=False),
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Structured error records (surface failures to the frontend via state['errors'])
# ---------------------------------------------------------------------------
def make_error_record(
    node: str,
    message: str,
    severity: str = "warning",
    details: dict | None = None,
) -> dict:
    """Build a single structured error record for state['errors']."""
    import time as _t
    rec = {
        "node": node,
        "severity": severity,         # "info" | "warning" | "error"
        "message": str(message)[:500],
        "ts": _t.time(),
    }
    if details:
        rec["details"] = details
    return rec


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def seconds_to_srt_timestamp(seconds: float) -> str:
    """Convert float seconds → SRT timestamp string HH:MM:SS,mmm"""
    seconds = max(0.0, seconds)
    millis = int(round((seconds % 1) * 1000))
    total_int = int(seconds)
    hh = total_int // 3600
    mm = (total_int % 3600) // 60
    ss = total_int % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d},{millis:03d}"


def seconds_to_hms(seconds: float) -> str:
    """Convert float seconds → HH:MM:SS string (no millis)."""
    total_int = int(seconds)
    hh = total_int // 3600
    mm = (total_int % 3600) // 60
    ss = total_int % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def hms_to_seconds(hms: str) -> float:
    """HH:MM:SS → float seconds."""
    parts = hms.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def count_words(text: str) -> int:
    """Return word count of a string."""
    return len(text.split())


def chunk_by_sentences(text: str, max_words: int = 50) -> list[str]:
    """
    Split text into chunks where each chunk ends on a sentence boundary
    and contains at most `max_words` words.
    """
    # Split on sentence-ending punctuation followed by whitespace or end
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_count = 0

    for sentence in sentences:
        w = count_words(sentence)
        if current_count + w > max_words and current:
            chunks.append(" ".join(current))
            current = [sentence]
            current_count = w
        else:
            current.append(sentence)
            current_count += w

    if current:
        chunks.append(" ".join(current))
    return chunks


def strip_markers(text: str) -> str:
    """
    Remove audio-designer markers from text for clean TTS input.
    Strips: [PAUSE Xms], [PAUSE Xs], [CUE: ...], [VISUAL: ...], [EMPHASIS], [/EMPHASIS]
    """
    text = re.sub(r'\[PAUSE\s+[\d.]+m?s\]', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\[CUE:[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[VISUAL:[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[/?EMPHASIS\]', '', text, flags=re.IGNORECASE)
    # Remove citation markers: [SRC-N], [SRC-N, SRC-M], [SRC N], etc.
    text = re.sub(r'\[(?:SRC[-\s]?\d+[,\s]*)+\]', '', text, flags=re.IGNORECASE)
    # Also catch bare SRC-N / SRC N that LLMs sometimes write without brackets
    text = re.sub(r'\bSRC[-\s]\d+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


# Preamble phrases that small LLMs use to prefix their responses
_PREAMBLE_RE = re.compile(
    r'^(?:'
    r"okay[,.]?\s*here(?:'s| is)\b[^.!?\n]*[.!?\n]*|"
    r"sure[,.]?\s*here(?:'s| is)\b[^.!?\n]*[.!?\n]*|"
    r"here(?:'s| is)\s+(?:the|your|an?)\b[^.!?\n]*[.!?\n]*|"
    r"certainly[,.]?\s*[^.!?\n]*[.!?\n]*|"
    r"of course[,.]?\s*[^.!?\n]*[.!?\n]*|"
    r"absolutely[,.]?\s*[^.!?\n]*[.!?\n]*|"
    r"i(?:'ve| have) (?:written|created|annotated|drafted)[^.!?\n]*[.!?\n]*"
    r')\s*',
    re.IGNORECASE,
)

# Stage directions between parentheses on their own line or inline
_STAGE_DIRECTION_LINE_RE = re.compile(
    r'^\s*\([^)]{2,120}\)\s*$',
    re.MULTILINE,
)

# Inline stage directions — only strip if NOT a normal sentence aside
_STAGE_DIRECTION_INLINE_RE = re.compile(
    r'\((?:sound\s+of|short\s+pause|sipping|thoughtful\s+tone|slightly\s+more\s+animated'
    r'|another\s+pause|final\s+chuckle|a\s+pause)[^)]*\)',
    re.IGNORECASE,
)

# Markdown code fence lines
_CODE_FENCE_RE = re.compile(r'^```[^\n]*$', re.MULTILINE)

# Footer meta lines (e.g. "Word count: 250")
_META_LINE_RE = re.compile(
    r'^\s*(?:word\s+count|note:|total\s+words|estimated\s+duration)[^\n]*$',
    re.IGNORECASE | re.MULTILINE,
)


def strip_llm_noise(text: str, preserve_visual_markers: bool = False) -> str:
    """
    Remove all common LLM-generated noise from spoken script text:
    - Preamble lines  ("Okay, here's the annotated script...")
    - Stage directions on their own line  ("(Sound of frantic typing)")
    - Known inline stage directions        ("(Short pause, sipping tea)")
    - [CUE: ...] markers (always)
    - [VISUAL: ...] markers (unless `preserve_visual_markers=True`)
    - Markdown code fences
    - Meta commentary lines ("Word count: 250")

    `preserve_visual_markers` is set by the visual-marker LLM pass, which is
    the only caller that *wants* [VISUAL:] markers to survive cleanup. Every
    other caller (prosody pass, fact-checker, writer, etc.) wants them gone.
    """
    # 1. Strip markdown fences
    text = _CODE_FENCE_RE.sub('', text)

    # 2. Strip leading preamble sentence(s)
    text = _PREAMBLE_RE.sub('', text.lstrip())

    # 3. Strip full stage-direction lines
    text = _STAGE_DIRECTION_LINE_RE.sub('', text)

    # 4. Strip known inline stage directions
    text = _STAGE_DIRECTION_INLINE_RE.sub('', text)

    # 5. Strip [CUE: ...] always, [VISUAL: ...] unless preserved
    text = re.sub(r'\[CUE:[^\]]*\]', '', text, flags=re.IGNORECASE)
    if not preserve_visual_markers:
        text = re.sub(r'\[VISUAL:[^\]]*\]', '', text, flags=re.IGNORECASE)

    # 6. Strip meta lines
    text = _META_LINE_RE.sub('', text)

    # 7. Collapse multiple blank lines → single blank line
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def highlight_citations_html(text: str) -> str:
    """
    Convert [SRC-N] markers in text to coloured HTML spans for Gradio HTML component.
    """
    colours = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD", "#98FB98"]

    def replacer(m: re.Match) -> str:
        n = int(m.group(1))
        colour = colours[(n - 1) % len(colours)]
        return (
            f'<sup><span style="background:{colour};color:#000;border-radius:3px;'
            f'padding:1px 4px;font-size:0.7em;font-weight:bold;">[SRC-{n}]</span></sup>'
        )

    return re.sub(r'\[SRC-(\d+)\]', replacer, text)


def wrap_text(text: str, width: int = 80) -> str:
    return textwrap.fill(text, width=width)


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------
def ensure_dir(path: Path | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_text(path: Path | str, content: str, encoding: str = "utf-8") -> Path:
    p = Path(path)
    p.write_text(content, encoding=encoding)
    return p


def save_json(path: Path | str, data: Any, indent: int = 2) -> Path:
    p = Path(path)
    p.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")
    return p


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# SRT helpers
# ---------------------------------------------------------------------------
def build_srt(entries: list[dict]) -> str:
    """
    Build an SRT string from a list of dicts:
        {index, start_s, end_s, text}
    """
    lines: list[str] = []
    for e in entries:
        lines.append(str(e["index"]))
        lines.append(f"{seconds_to_srt_timestamp(e['start_s'])} --> {seconds_to_srt_timestamp(e['end_s'])}")
        lines.append(e["text"].strip())
        lines.append("")
    return "\n".join(lines)


def retry_llm_call(
    fn: Callable[[], T],
    max_retries: int = 3,
    backoff_base: float = 2.0,
    logger_inst: logging.Logger | None = None,
) -> T:
    """Retry an LLM call with exponential backoff on failure."""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries:
                raise
            wait = backoff_base ** attempt
            if logger_inst:
                logger_inst.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt + 1, max_retries, e, wait,
                )
            time.sleep(wait)
    raise RuntimeError("retry_llm_call: unreachable")

import asyncio
from typing import Awaitable

async def async_retry_llm_call(
    fn: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    backoff_base: float = 2.0,
    logger_inst: logging.Logger | None = None,
) -> T:
    """Retry an async LLM call with exponential backoff on failure."""
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            if attempt == max_retries:
                raise
            wait = backoff_base ** attempt
            if logger_inst:
                logger_inst.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt + 1, max_retries, e, wait,
                )
            await asyncio.sleep(wait)
    raise RuntimeError("async_retry_llm_call: unreachable")


def srt_entries_from_whisper(
    words: list[dict],
    max_chunk_s: float = 10.0,
    max_words_per_chunk: int = 14,
) -> list[dict]:
    """
    Build SRT entries from Whisper word-level timings.

    Each word is a dict with keys: 'word' (str), 'start' (float), 'end' (float).
    Chunks are flushed when ANY of:
      - chunk duration >= max_chunk_s
      - chunk reaches max_words_per_chunk
      - last word ends with sentence punctuation . ! ?
    """
    entries: list[dict] = []
    if not words:
        return entries

    buf: list[dict] = []
    idx = 1

    def _flush():
        nonlocal idx, buf
        if not buf:
            return
        text = "".join(w["word"] for w in buf).strip()
        if text:
            entries.append({
                "index": idx,
                "start_s": float(buf[0]["start"]),
                "end_s": float(buf[-1]["end"]),
                "text": text,
            })
            idx += 1
        buf = []

    for w in words:
        buf.append(w)
        token = w["word"].strip()
        duration = float(buf[-1]["end"]) - float(buf[0]["start"])
        ends_sentence = token.endswith((".", "!", "?"))
        if (
            ends_sentence
            or duration >= max_chunk_s
            or len(buf) >= max_words_per_chunk
        ):
            _flush()

    _flush()
    return entries


def srt_entries_from_segments(segments: list[dict]) -> list[dict]:
    """
    Given script segments [{name, duration_s, text}], split each segment into
    SRT blocks of ≤ 30 s or ≤ ~50 words, whichever comes first.
    Returns list of {index, start_s, end_s, text}.
    """
    entries: list[dict] = []
    index = 1
    cursor = 0.0
    words_per_second = 150 / 60  # default 150 wpm

    for seg in segments:
        duration_s = seg.get("duration_s", seg.get("target_seconds", 30))
        text = seg.get("text", "")
        if not text.strip():
            cursor += duration_s
            continue
        # chunk text into ~30 s blocks
        total_words = count_words(text)
        words_per_s = total_words / duration_s if duration_s > 0 else words_per_second
        max_words_per_block = max(10, int(words_per_s * 30))
        chunks = chunk_by_sentences(text, max_words=max_words_per_block)
        chunk_duration = duration_s / len(chunks) if chunks else duration_s
        for chunk in chunks:
            end = cursor + chunk_duration
            entries.append({
                "index": index,
                "start_s": cursor,
                "end_s": end,
                "text": chunk,
            })
            index += 1
            cursor = end

    return entries
