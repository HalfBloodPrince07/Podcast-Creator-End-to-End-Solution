"""
agents/post_production_agent.py — Single node that runs three sequential
audio post-production steps after TTS and before assembly:

  A. Whisper alignment    -> real word-level timings
  B. Background music mix -> overlay assets at [CUE:] positions using real timings
  C. LUFS mastering       -> two-pass ffmpeg loudnorm for broadcast loudness

Every step degrades gracefully: missing whisper, missing music assets, or
failed ffmpeg pass all leave the pipeline able to complete with the unmastered
audio and estimated subtitle timings.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from constants import (
    LUFS_TARGET,
    LUFS_TRUE_PEAK,
    LUFS_LRA,
    WHISPER_MODEL,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_BEAM_SIZE,
    MUSIC_DUCK_DB,
    MUSIC_DUCK_MODE,
    PODCAST_EQ_FILTER,
)
from utils import get_logger, make_error_record, strip_markers

logger = get_logger("PostProductionAgent")

ASSETS_DIR = Path("assets")

CUE_ASSET_MAP = {
    "INTRO_MUSIC": "intro_music.mp3",
    "OUTRO_MUSIC": "outro_music.mp3",
    "CHAPTER_TRANSITION": "transition.mp3",
    "SFX_WHOOSH": "whoosh.mp3",
    "CTA_JINGLE": "cta_jingle.mp3",
}

_CUE_RE = re.compile(r'\[CUE:\s*(\w+)\]', re.IGNORECASE)
_VISUAL_RE = re.compile(r'\[VISUAL:\s*([^\]]+)\]', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Step A: Whisper alignment
# ---------------------------------------------------------------------------

def _resolve_whisper_device() -> tuple[str, str]:
    """Return (device, compute_type) — auto-detect CUDA if WHISPER_DEVICE=='auto'.

    Note: TTS backends are unloaded from the GPU before this runs (see
    `unload_all_backends`), otherwise Chatterbox staying resident on CUDA
    would silently stall faster-whisper's decode loop right after VAD on Windows.
    """
    device = WHISPER_DEVICE
    compute = WHISPER_COMPUTE_TYPE
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
    if device == "cuda" and compute == "int8":
        compute = "float16"
    return device, compute


def _run_whisper_alignment(audio_path: str) -> list[dict]:
    """Transcribe audio with word-level timestamps. Returns [] on failure."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning("faster-whisper not installed — skipping alignment.")
        return []

    device, compute = _resolve_whisper_device()
    logger.info("Whisper: loading %s on %s (%s)...", WHISPER_MODEL, device, compute)
    try:
        model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)
        seg_iter, info = model.transcribe(
            audio_path,
            word_timestamps=True,
            language="en",
            beam_size=WHISPER_BEAM_SIZE,
            vad_filter=True,
        )
        words: list[dict] = []
        for seg in seg_iter:
            if not seg.words:
                continue
            for w in seg.words:
                if w.word is None or w.start is None or w.end is None:
                    continue
                words.append({
                    "word": w.word,
                    "start": float(w.start),
                    "end": float(w.end),
                })
        logger.info("Whisper: aligned %d words (audio %.1fs)", len(words), info.duration)
        # Release Whisper's GPU/CPU resources before subsequent steps
        try:
            del model
        except Exception:
            pass
        _gpu_cleanup()
        return words
    except Exception as exc:
        logger.warning("Whisper alignment failed: %s — continuing without it.", exc)
        _gpu_cleanup()
        return []


def _gpu_cleanup() -> None:
    """Best-effort GPU memory release. Safe to call always."""
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Step B: Music mixing using real timings
# ---------------------------------------------------------------------------

def _find_available_assets() -> dict[str, Path]:
    """Return CUE_NAME -> Path for every music asset that exists on disk."""
    found: dict[str, Path] = {}
    for cue_name, filename in CUE_ASSET_MAP.items():
        p = ASSETS_DIR / filename
        if p.exists():
            found[cue_name] = p
    return found


def _cue_positions_from_whisper(
    segments: list[dict],
    words: list[dict],
) -> list[tuple[str, int]]:
    """
    For each segment whose text starts with a [CUE: NAME] marker, look up the
    real audio position (ms) of that segment's first spoken word via Whisper.
    """
    if not words:
        return []

    cues: list[tuple[str, int]] = []
    cumulative_words = 0

    for seg in segments:
        raw = seg.get("text", "") or ""
        m = _CUE_RE.search(raw)
        if m and cumulative_words < len(words):
            cue_name = m.group(1).upper()
            position_ms = int(words[cumulative_words]["start"] * 1000)
            cues.append((cue_name, position_ms))

        actual = int(seg.get("actual_words") or 0)
        if not actual:
            actual = len(strip_markers(raw).split())
        cumulative_words += actual

    return cues


def _visual_cue_positions_from_whisper(
    segments: list[dict],
    words: list[dict],
) -> list[dict]:
    """Extract [VISUAL: prompt] cues and their audio timings.

    Walks each segment in order, computing the cumulative count of spoken
    words (markers stripped) before each [VISUAL:] occurrence, then looks up
    the corresponding word in the Whisper word list to obtain start_ms.
    end_ms is filled in as a second pass — each cue runs until the next
    cue starts (or until the end of the spoken audio for the final cue).

    Returns: list of {prompt, start_ms, end_ms, word_index} dicts.
    Empty list if no Whisper words available.
    """
    if not words:
        return []

    cues: list[dict] = []
    cumulative_words = 0

    for seg in segments:
        raw = seg.get("text", "") or ""
        last_end = 0
        for m in _VISUAL_RE.finditer(raw):
            prefix = raw[last_end:m.start()]
            prefix_clean = strip_markers(prefix)
            prefix_words = len(prefix_clean.split()) if prefix_clean else 0
            cumulative_words += prefix_words
            idx = min(cumulative_words, len(words) - 1)
            start_ms = int(words[idx]["start"] * 1000)
            cues.append({
                "prompt": m.group(1).strip(),
                "start_ms": start_ms,
                "end_ms": 0,  # filled below
                "word_index": idx,
            })
            last_end = m.end()

        # Account for spoken words after the last marker in this segment
        tail_clean = strip_markers(raw[last_end:])
        cumulative_words += len(tail_clean.split()) if tail_clean else 0

    # Fill end_ms as the start of the next cue (or end of audio for the last).
    audio_end_ms = int(words[-1]["end"] * 1000)
    for i, cue in enumerate(cues):
        cue["end_ms"] = cues[i + 1]["start_ms"] if i + 1 < len(cues) else audio_end_ms
        # Guarantee positive duration (Whisper word ordering can rarely produce
        # adjacent markers at the same timestamp on very fast speech).
        if cue["end_ms"] <= cue["start_ms"]:
            cue["end_ms"] = cue["start_ms"] + 1500

    return cues


def _cue_positions_estimated(segments: list[dict]) -> list[tuple[str, int]]:
    """Fallback when Whisper unavailable: estimate from 150 WPM."""
    cues: list[tuple[str, int]] = []
    cumulative_words = 0
    wpm = 150
    for seg in segments:
        raw = seg.get("text", "") or ""
        m = _CUE_RE.search(raw)
        if m:
            cue_name = m.group(1).upper()
            position_ms = int((cumulative_words / wpm) * 60 * 1000)
            cues.append((cue_name, position_ms))
        actual = int(seg.get("actual_words") or 0)
        if not actual:
            actual = len(strip_markers(raw).split())
        cumulative_words += actual
    return cues


def _build_music_bed(
    audio_in: Path,
    cues: list[tuple[str, int]],
    available: dict[str, Path],
    output_path: Path,
) -> tuple[bool, int]:
    """
    Build a silent track the length of the speech audio, overlay each music
    asset at its cue position at FULL volume (no static ducking), and export.
    Returns (success, asset_count_applied).
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        return False, 0

    try:
        speech = AudioSegment.from_file(str(audio_in))
    except Exception as exc:
        logger.warning("Cannot load speech audio: %s", exc)
        return False, 0

    bed = AudioSegment.silent(duration=len(speech), frame_rate=speech.frame_rate)
    applied = 0
    for cue_name, pos_ms in cues:
        asset_path = available.get(cue_name)
        if not asset_path:
            continue
        try:
            asset = AudioSegment.from_file(str(asset_path))
            if pos_ms >= len(bed):
                pos_ms = max(0, len(bed) - len(asset))
            bed = bed.overlay(asset, position=pos_ms)
            applied += 1
            logger.info("Music bed: placed '%s' at %.2fs", cue_name, pos_ms / 1000)
        except Exception as exc:
            logger.warning("Failed to place asset '%s' on bed: %s", cue_name, exc)

    if applied == 0:
        return False, 0

    try:
        bed.export(str(output_path), format="wav")
        return True, applied
    except Exception as exc:
        logger.warning("Failed to export music bed: %s", exc)
        return False, 0


def _mix_sidechain_ducking(
    speech_path: Path,
    music_bed_path: Path,
    output_path: Path,
) -> bool:
    """
    Mix speech + music bed using ffmpeg sidechaincompress so the music
    dynamically ducks when speech is present. Music recovers to full volume
    during natural gaps between words.
    """
    if not _ffmpeg_ok():
        return False

    # Music is the carrier; speech is the sidechain key.
    # threshold=0.04 (~-28dB), ratio=8 (firm), attack=5ms (fast clamp),
    # release=300ms (smooth release between phrases).
    filt = (
        "[1:a]asplit=2[mus1][mus_unused];"
        "[0:a]asplit=2[sp_out][sp_key];"
        "[mus1][sp_key]sidechaincompress=threshold=0.04:ratio=8:attack=5:release=300[ducked];"
        "[sp_out][ducked]amix=inputs=2:duration=first:dropout_transition=0:weights=1.0 0.8[out]"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner",
        "-i", str(speech_path),
        "-i", str(music_bed_path),
        "-filter_complex", filt,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "48000",
        str(output_path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    except Exception as exc:
        logger.warning("Sidechain ducking failed to launch: %s", exc)
        return False
    if r.returncode != 0:
        logger.warning("Sidechain ducking failed:\n%s", r.stderr[-1000:])
        return False
    return True


def _mix_background_music_static(
    audio_in: Path,
    audio_out: Path,
    cues: list[tuple[str, int]],
    available: dict[str, Path],
) -> bool:
    """Legacy static -10dB drop overlay. Used as fallback when sidechain unavailable."""
    try:
        from pydub import AudioSegment
    except ImportError:
        logger.warning("pydub not installed — skipping music mix.")
        return False

    try:
        main = AudioSegment.from_file(str(audio_in))
    except Exception as exc:
        logger.warning("Cannot load audio for mixing: %s", exc)
        return False

    applied = 0
    for cue_name, pos_ms in cues:
        asset_path = available.get(cue_name)
        if not asset_path:
            continue
        try:
            bed = AudioSegment.from_file(str(asset_path)) - MUSIC_DUCK_DB
            if pos_ms >= len(main):
                pos_ms = max(0, len(main) - len(bed))
            main = main.overlay(bed, position=pos_ms)
            applied += 1
            logger.info("Static mix: '%s' at %.2fs", cue_name, pos_ms / 1000)
        except Exception as exc:
            logger.warning("Failed to mix '%s': %s", cue_name, exc)

    if applied == 0:
        return False

    try:
        main.export(str(audio_out), format="mp3", bitrate="192k")
        return True
    except Exception as exc:
        logger.warning("Failed to export mixed audio: %s", exc)
        return False


def _mix_background_music(
    audio_in: Path,
    audio_out: Path,
    segments: list[dict],
    words: list[dict],
) -> bool:
    """
    Overlay music at CUE positions. Returns True if any asset was applied.
    Path A: MUSIC_DUCK_MODE=='sidechain' -> dynamic ffmpeg sidechain ducking
    Path B: MUSIC_DUCK_MODE=='static'    -> legacy -10dB pydub overlay
    Falls back from A to B if ffmpeg or the music-bed step fails.
    """
    available = _find_available_assets()
    if not available:
        logger.info("No music assets in ./assets/ — skipping music mix.")
        return False

    cues = _cue_positions_from_whisper(segments, words) if words else _cue_positions_estimated(segments)
    if not cues:
        logger.info("No CUE markers found in script — skipping music mix.")
        return False

    if MUSIC_DUCK_MODE == "sidechain" and _ffmpeg_ok():
        music_bed = audio_in.parent / "_music_bed.wav"
        ok, n = _build_music_bed(audio_in, cues, available, music_bed)
        if ok:
            logger.info("Sidechain ducking %d music cue(s)...", n)
            if _mix_sidechain_ducking(audio_in, music_bed, audio_out):
                try:
                    music_bed.unlink()
                except Exception:
                    pass
                return True
            logger.warning("Sidechain step failed — falling back to static -%ddB drop.", MUSIC_DUCK_DB)
            try:
                music_bed.unlink()
            except Exception:
                pass

    return _mix_background_music_static(audio_in, audio_out, cues, available)


# ---------------------------------------------------------------------------
# Step C: LUFS mastering via ffmpeg loudnorm (two-pass)
# ---------------------------------------------------------------------------

def _ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None


def _loudnorm_measure(audio_in: Path) -> Optional[dict]:
    """
    Pass 1: run EQ chain + loudnorm in analysis mode, parse JSON measurement.
    The EQ is included BEFORE loudnorm so the measurement reflects what the
    listener will actually hear, keeping pass-2 normalization accurate.
    """
    af = f"{PODCAST_EQ_FILTER},loudnorm=I={LUFS_TARGET}:LRA={LUFS_LRA}:TP={LUFS_TRUE_PEAK}:print_format=json"
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio_in),
        "-af", af,
        "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    except Exception as exc:
        logger.warning("loudnorm measure failed to launch: %s", exc)
        return None

    if r.returncode != 0:
        logger.warning("loudnorm measure non-zero exit: %s", r.stderr[-500:])
        return None

    # The JSON block is printed to stderr at the end
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.DOTALL)
    if not m:
        logger.warning("loudnorm: could not find JSON in ffmpeg output")
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("loudnorm: JSON parse failed: %s", exc)
        return None


def _loudnorm_apply(audio_in: Path, audio_out: Path, measured: dict) -> bool:
    """Pass 2: apply podcast EQ chain + linear loudnorm using measured values."""
    loudnorm = (
        f"loudnorm=I={LUFS_TARGET}:LRA={LUFS_LRA}:TP={LUFS_TRUE_PEAK}:"
        f"measured_I={measured['input_i']}:"
        f"measured_LRA={measured['input_lra']}:"
        f"measured_TP={measured['input_tp']}:"
        f"measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:"
        f"linear=true:print_format=summary"
    )
    # EQ first (shape tone), then loudnorm (final loudness target)
    filt = f"{PODCAST_EQ_FILTER},{loudnorm}"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-i", str(audio_in),
        "-af", filt,
        "-c:a", "libmp3lame", "-b:a", "192k",
        "-ar", "48000",
        str(audio_out),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    except Exception as exc:
        logger.warning("loudnorm apply failed to launch: %s", exc)
        return False
    if r.returncode != 0:
        logger.warning("loudnorm apply failed:\n%s", r.stderr[-1000:])
        return False
    return True


def _master_audio(audio_in: Path, audio_out: Path) -> bool:
    """Two-pass LUFS mastering. Returns True on success."""
    if not _ffmpeg_ok():
        logger.warning("ffmpeg not in PATH — skipping mastering.")
        return False
    logger.info("Mastering pass 1/2: measuring loudness...")
    measured = _loudnorm_measure(audio_in)
    if not measured:
        return False
    logger.info(
        "Measured: I=%s LUFS  LRA=%s  TP=%s dB",
        measured.get("input_i"), measured.get("input_lra"), measured.get("input_tp"),
    )
    logger.info("Mastering pass 2/2: applying loudnorm -> %.1f LUFS...", LUFS_TARGET)
    return _loudnorm_apply(audio_in, audio_out, measured)


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------

def _run_post_production_sync(state: dict) -> dict:
    tts_result = state.get("tts_results", {}) or {}
    audio_path = tts_result.get("audio_path")
    segments = state.get("script_segments", []) or []
    errors: list[dict] = []

    if not audio_path or not Path(audio_path).exists():
        logger.warning("No TTS audio found — skipping post-production.")
        errors.append(make_error_record(
            "post_production", "No TTS audio found, skipping post-production", "warning",
        ))
        return {"current_status": "Post-production skipped (no audio)", "errors": errors}

    audio_in = Path(audio_path)
    output_dir = audio_in.parent

    # Step A — Whisper alignment
    # Free TTS models from GPU first so Whisper doesn't have to fight them
    # for VRAM (a resident Chatterbox model can stall faster-whisper's decode
    # loop indefinitely on Windows + cuDNN).
    try:
        from agents.tts_agent import unload_all_backends
        unload_all_backends()
    except Exception as exc:
        logger.warning("Could not unload TTS backends before Whisper: %s", exc)

    logger.info("[1/3] Running Whisper alignment...")
    words = _run_whisper_alignment(str(audio_in))
    if not words:
        errors.append(make_error_record(
            "post_production", "Whisper alignment unavailable — SRT will use estimated timings", "info",
        ))

    # Step B — Music mixing
    logger.info("[2/3] Mixing background music...")
    mixed_path = output_dir / "episode_mixed.mp3"
    music_applied = _mix_background_music(audio_in, mixed_path, segments, words)
    pre_master = mixed_path if music_applied else audio_in

    # Step C — LUFS mastering
    logger.info("[3/3] LUFS mastering...")
    mastered_path = output_dir / "episode_mastered.mp3"
    mastered_ok = _master_audio(pre_master, mastered_path)
    if not mastered_ok:
        errors.append(make_error_record(
            "post_production", "LUFS mastering failed — delivering unmastered audio", "warning",
        ))

    if mastered_ok:
        final_path = output_dir / "episode.mp3"
        try:
            if final_path.exists() and final_path.resolve() != mastered_path.resolve():
                final_path.unlink()
            shutil.move(str(mastered_path), str(final_path))
        except Exception as exc:
            logger.warning("Could not move mastered file into place: %s", exc)
            final_path = mastered_path
        # Cleanup intermediate mix if both exist
        if music_applied and mixed_path.exists() and mixed_path != final_path:
            try:
                mixed_path.unlink()
            except Exception:
                pass
        new_audio = str(final_path)
    elif music_applied:
        new_audio = str(mixed_path)
    else:
        new_audio = str(audio_in)

    # Visual cue extraction — happens after Whisper alignment because we
    # need real word timings to position each [VISUAL:] cue on the audio.
    visual_cues = _visual_cue_positions_from_whisper(segments, words) if words else []
    if visual_cues:
        logger.info("Extracted %d [VISUAL:] cue(s) from script.", len(visual_cues))
    else:
        logger.info("No [VISUAL:] cues found (or Whisper words unavailable).")

    # Persist artifacts the downstream video step reads. The video endpoint
    # in app.py is invoked separately from LangGraph, so we put the data on
    # disk rather than expecting it to live in the in-memory state.
    try:
        (output_dir / "visual_cues.json").write_text(
            json.dumps(visual_cues, indent=2), encoding="utf-8"
        )
        if words:
            (output_dir / "whisper_words.json").write_text(
                json.dumps(words), encoding="utf-8"
            )
    except Exception as exc:
        logger.warning("Could not persist visual/whisper artifacts: %s", exc)

    updated_tts = {**tts_result, "audio_path": new_audio, "mastered": mastered_ok, "music_mixed": music_applied}

    return {
        "current_status": "Post-production complete",
        "tts_results": updated_tts,
        "whisper_words": words,
        "visual_cues": visual_cues,
        "errors": errors,
    }


async def run_post_production_node(state: dict) -> dict:
    """LangGraph node: align, mix, master. Always returns gracefully."""
    try:
        return await asyncio.to_thread(_run_post_production_sync, state)
    except Exception as exc:
        logger.error("Post-production crashed (%s) — passing audio through unchanged.", exc)
        return {
            "current_status": "Post-production skipped (error)",
            "errors": [make_error_record("post_production", str(exc), "error")],
        }
