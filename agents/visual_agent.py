"""
agents/visual_agent.py — Build a dynamic video bed for the final podcast video
using AI-generated stills (Phase 2) and AI-generated clips (Phase 3).

Pipeline:
  1. Read visual_cues.json (written by post_production) + audio duration.
  2. Partition the audio timeline into intervals:
       cue intervals — driven by [VISUAL: prompt] markers
       gap intervals — between cue intervals; prompt synthesized from segment text
  3. For each interval, produce a 16:9 image (SDXL).
       Phase 3 will replace cue intervals with CogVideoX-5B clips while leaving
       gap intervals as Ken-Burns stills.
  4. FFmpeg renders each interval (Ken-Burns zoom for stills, passthrough for
     clips) and crossfades them into a single _visual_bed.mp4 matching the
     audio's full duration.

GPU choreography mirrors the TTS / Whisper unload pattern in
post_production_agent — every model is loaded, used, then unloaded so the
next stage has the full 16 GB of VRAM to itself.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from constants import (
    SDXL_MODEL_ID,
    SDXL_WIDTH,
    SDXL_HEIGHT,
    SDXL_STEPS,
    SDXL_GUIDANCE,
    SDXL_NEGATIVE_PROMPT,
    VISUAL_STYLE_SUFFIX,
    VISUAL_KEN_BURNS_ZOOM,
    VISUAL_KEN_BURNS_FPS,
    VISUAL_BED_WIDTH,
    VISUAL_BED_HEIGHT,
    VISUAL_CROSSFADE_MS,
)
from utils import get_logger

logger = get_logger("VisualAgent")


# ---------------------------------------------------------------------------
# SDXL still generator
# ---------------------------------------------------------------------------

class _SDXLBackend:
    """Lazily-loaded SDXL base pipeline. Singleton, with explicit unload."""

    _pipe = None
    _loaded = False

    @classmethod
    def load(cls) -> bool:
        if cls._loaded:
            return True
        try:
            import torch
            from diffusers import StableDiffusionXLPipeline

            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if device == "cuda" else torch.float32
            logger.info("[SDXL] Loading %s on %s (%s)...", SDXL_MODEL_ID, device, dtype)
            pipe = StableDiffusionXLPipeline.from_pretrained(
                SDXL_MODEL_ID,
                torch_dtype=dtype,
                use_safetensors=True,
                variant="fp16" if device == "cuda" else None,
            )
            if device == "cuda":
                pipe = pipe.to("cuda")
                # Memory-friendly settings for 16 GB VRAM
                try:
                    pipe.enable_attention_slicing()
                except Exception:
                    pass
                try:
                    pipe.enable_vae_tiling()
                except Exception:
                    pass
            cls._pipe = pipe
            cls._loaded = True
            logger.info("[SDXL] Loaded.")
            return True
        except ImportError as exc:
            logger.warning("[SDXL] diffusers/transformers missing (%s) — visual bed will be skipped.", exc)
        except Exception as exc:
            logger.warning("[SDXL] Failed to load: %s — visual bed will be skipped.", exc)
        return False

    @classmethod
    def generate(cls, prompt: str, seed: int = 42) -> Optional["Image.Image"]:
        """Return a PIL Image or None on failure. Caller decides what to do on None."""
        if not cls._loaded:
            return None
        try:
            import torch
            generator = torch.Generator(device=cls._pipe.device).manual_seed(seed)
            with torch.inference_mode():
                result = cls._pipe(
                    prompt=prompt,
                    negative_prompt=SDXL_NEGATIVE_PROMPT,
                    width=SDXL_WIDTH,
                    height=SDXL_HEIGHT,
                    num_inference_steps=SDXL_STEPS,
                    guidance_scale=SDXL_GUIDANCE,
                    generator=generator,
                )
            return result.images[0]
        except Exception as exc:
            logger.warning("[SDXL] generate failed (%s) — returning None.", exc)
            return None

    @classmethod
    def unload(cls) -> None:
        # Drop refs + clear CUDA cache so the next stage (CogVideoX or just
        # FFmpeg) has the full VRAM. Same pattern as TTS unload.
        cls._pipe = None
        cls._loaded = False
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Interval planning
# ---------------------------------------------------------------------------

def _audio_duration_ms(audio_path: Path) -> int:
    """Use ffprobe to read the duration of the master audio in milliseconds."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        if r.returncode == 0:
            return int(float(r.stdout.strip()) * 1000)
    except Exception as exc:
        logger.warning("ffprobe failed (%s) — falling back to 0 ms.", exc)
    return 0


def _plan_intervals(
    visual_cues: list[dict],
    audio_duration_ms: int,
    script_segments: list[dict] | None = None,
    max_interval_ms: int = 12_000,
) -> list[dict]:
    """Carve the audio timeline into a sequence of visual intervals.

    Each interval has:
        kind  — 'cue' (had an explicit [VISUAL:] marker) or 'gap' (filler)
        prompt — what to send to the image/video model
        start_ms, end_ms — position on the master audio timeline

    Gaps longer than `max_interval_ms` are split so a single still doesn't
    drag on for the whole intro/outro.
    """
    intervals: list[dict] = []

    if not visual_cues:
        # No markers at all — fall back to evenly-spaced gap intervals.
        cursor = 0
        gap_prompt = _derive_gap_prompt(script_segments or [], 0)
        while cursor < audio_duration_ms:
            end = min(cursor + max_interval_ms, audio_duration_ms)
            intervals.append({
                "kind": "gap",
                "prompt": gap_prompt,
                "start_ms": cursor,
                "end_ms": end,
            })
            cursor = end
        return intervals

    # First: leading gap before the first cue (if any audio precedes it).
    first = visual_cues[0]
    if first["start_ms"] > 0:
        _emit_gap_intervals(
            intervals,
            start_ms=0,
            end_ms=first["start_ms"],
            script_segments=script_segments or [],
            max_interval_ms=max_interval_ms,
        )

    # Walk through cues, emitting one cue interval per marker and gap
    # intervals for any audio that sits between two adjacent cues.
    for i, cue in enumerate(visual_cues):
        intervals.append({
            "kind": "cue",
            "prompt": cue["prompt"],
            "start_ms": cue["start_ms"],
            "end_ms": cue["end_ms"],
        })

    # Trailing gap after the last cue, if the cue ended before the audio did.
    last = visual_cues[-1]
    if last["end_ms"] < audio_duration_ms:
        _emit_gap_intervals(
            intervals,
            start_ms=last["end_ms"],
            end_ms=audio_duration_ms,
            script_segments=script_segments or [],
            max_interval_ms=max_interval_ms,
        )

    # Sort defensively in case _emit_gap_intervals appended out of order.
    intervals.sort(key=lambda iv: iv["start_ms"])
    return intervals


def _emit_gap_intervals(
    intervals: list[dict],
    *,
    start_ms: int,
    end_ms: int,
    script_segments: list[dict],
    max_interval_ms: int,
) -> None:
    """Split a [start_ms, end_ms] gap into one or more gap intervals."""
    cursor = start_ms
    while cursor < end_ms:
        nxt = min(cursor + max_interval_ms, end_ms)
        intervals.append({
            "kind": "gap",
            "prompt": _derive_gap_prompt(script_segments, cursor),
            "start_ms": cursor,
            "end_ms": nxt,
        })
        cursor = nxt


def _derive_gap_prompt(script_segments: list[dict], at_ms: int) -> str:
    """Best-effort prompt for a gap interval — pulls a phrase from script text.

    With no script context we return a generic atmospheric prompt so the
    visual bed never has a hole.
    """
    if not script_segments:
        return "ambient cinematic landscape, soft volumetric light, atmospheric mood"
    # Use the first segment's first sentence as a generic theme anchor; a
    # smarter version (Phase 4) would pick the segment that contains `at_ms`.
    raw = (script_segments[0].get("text") or "").strip()
    if not raw:
        return "ambient cinematic landscape, soft volumetric light, atmospheric mood"
    # First ~10 words, no markers.
    import re as _re
    raw = _re.sub(r'\[[^\]]+\]', '', raw)
    words = raw.split()[:10]
    seed = " ".join(words).rstrip(".!?,;:")
    return f"establishing shot inspired by: {seed}"


# ---------------------------------------------------------------------------
# Image-to-clip rendering (Ken-Burns)
# ---------------------------------------------------------------------------

def _ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None


def _ken_burns_clip(
    image_path: Path,
    duration_ms: int,
    out_path: Path,
    fps: int = VISUAL_KEN_BURNS_FPS,
) -> bool:
    """Render a Ken-Burns clip from `image_path` lasting `duration_ms`.

    zoompan does the actual zoom. We pre-scale the input 4x so the zoompan
    interpolation has enough source pixels to stay sharp; final output is
    cropped to VISUAL_BED_WIDTH×VISUAL_BED_HEIGHT.
    """
    if duration_ms <= 0:
        return False
    duration_s = duration_ms / 1000.0
    total_frames = max(1, int(duration_s * fps))
    zoom_end = VISUAL_KEN_BURNS_ZOOM
    # zoom expression: 1.0 → zoom_end linearly across the clip
    zoom_expr = f"min(zoom+{(zoom_end - 1.0) / total_frames:.6f},{zoom_end})"

    vf = (
        # Upscale first so zoompan has room to interpolate without softening.
        f"scale={VISUAL_BED_WIDTH * 4}:{VISUAL_BED_HEIGHT * 4}:flags=lanczos,"
        f"zoompan=z='{zoom_expr}':d={total_frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={VISUAL_BED_WIDTH}x{VISUAL_BED_HEIGHT}:fps={fps}"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-t", f"{duration_s:.3f}",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        logger.warning("Ken-Burns render failed:\n%s", r.stderr[-800:])
        return False
    return True


def _concat_with_crossfade(
    clip_paths: list[Path],
    out_path: Path,
    crossfade_ms: int = VISUAL_CROSSFADE_MS,
    fps: int = VISUAL_KEN_BURNS_FPS,
) -> bool:
    """Concatenate per-interval clips with a short xfade between them."""
    if not clip_paths:
        return False
    if len(clip_paths) == 1:
        shutil.copy(str(clip_paths[0]), str(out_path))
        return True

    xfade_s = crossfade_ms / 1000.0
    # Probe durations
    durations: list[float] = []
    for p in clip_paths:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                capture_output=True, text=True, encoding="utf-8", timeout=20,
            )
            durations.append(float(r.stdout.strip()) if r.returncode == 0 else 0.0)
        except Exception:
            durations.append(0.0)

    # Build inputs and a chained xfade filter graph.
    inputs: list[str] = []
    for p in clip_paths:
        inputs.extend(["-i", str(p)])

    # Each xfade consumes the cumulative offset of all prior clips minus
    # the per-step crossfade overlap so transitions actually overlap.
    label_prev = "[0:v]"
    filt_parts: list[str] = []
    cumulative = durations[0]
    for i in range(1, len(clip_paths)):
        off = max(0.0, cumulative - xfade_s)
        label_curr = f"[{i}:v]"
        out_label = f"[v{i}]" if i < len(clip_paths) - 1 else "[vout]"
        filt_parts.append(
            f"{label_prev}{label_curr}xfade=transition=fade:duration={xfade_s}:offset={off:.3f}{out_label}"
        )
        label_prev = out_label
        cumulative = cumulative + durations[i] - xfade_s

    filt = ";".join(filt_parts)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *inputs,
        "-filter_complex", filt,
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        logger.warning("Crossfade concat failed:\n%s", r.stderr[-1500:])
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_visual_bed(
    audio_path: Path,
    output_dir: Path,
    visual_cues: list[dict] | None = None,
    script_segments: list[dict] | None = None,
    progress: Optional[Callable[[str, int], None]] = None,
) -> Optional[Path]:
    """Build _visual_bed.mp4 spanning the full audio duration.

    Phase 2 implementation: every interval gets an SDXL still + Ken-Burns
    motion. Phase 3 will swap cue intervals for CogVideoX clips.

    Returns the path to the rendered bed, or None on failure (caller should
    fall back to the static-PNG flow in video_agent).
    """
    if not _ffmpeg_ok():
        logger.warning("ffmpeg not in PATH — cannot build visual bed.")
        return None

    output_dir = Path(output_dir)
    audio_path = Path(audio_path)
    if not audio_path.exists():
        logger.warning("Audio file missing — cannot build visual bed.")
        return None

    # Load visual_cues from disk if not provided in-memory
    if visual_cues is None:
        cue_file = output_dir / "visual_cues.json"
        if cue_file.exists():
            try:
                visual_cues = json.loads(cue_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Could not read visual_cues.json: %s", exc)
                visual_cues = []
        else:
            visual_cues = []

    duration_ms = _audio_duration_ms(audio_path)
    if duration_ms <= 0:
        logger.warning("Could not determine audio duration — aborting visual bed.")
        return None

    intervals = _plan_intervals(visual_cues, duration_ms, script_segments or [])
    if not intervals:
        return None
    logger.info(
        "Planned %d visual interval(s) across %.1fs of audio (%d cue, %d gap).",
        len(intervals), duration_ms / 1000,
        sum(1 for iv in intervals if iv["kind"] == "cue"),
        sum(1 for iv in intervals if iv["kind"] == "gap"),
    )

    if progress:
        progress("Loading SDXL...", 5)
    if not _SDXLBackend.load():
        return None

    images_dir = output_dir / "_visual_images"
    clips_dir = output_dir / "_visual_clips"
    images_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    clip_paths: list[Path] = []
    try:
        for i, iv in enumerate(intervals):
            pct = 10 + int(80 * (i / len(intervals)))
            if progress:
                progress(f"Visual {i+1}/{len(intervals)} ({iv['kind']})...", pct)

            prompt = (iv.get("prompt") or "").strip()
            if not prompt.endswith(VISUAL_STYLE_SUFFIX):
                prompt = f"{prompt}{VISUAL_STYLE_SUFFIX}"

            img_path = images_dir / f"interval_{i:03d}.png"
            seed = 1000 + i  # deterministic so reruns are stable
            img = _SDXLBackend.generate(prompt, seed=seed)
            if img is None:
                logger.warning("SDXL returned no image for interval %d — using neutral fill.", i)
                from PIL import Image
                img = Image.new("RGB", (SDXL_WIDTH, SDXL_HEIGHT), (12, 12, 24))
            img.save(str(img_path), "PNG")

            clip_path = clips_dir / f"interval_{i:03d}.mp4"
            if not _ken_burns_clip(
                img_path,
                iv["end_ms"] - iv["start_ms"],
                clip_path,
            ):
                logger.warning("Ken-Burns failed for interval %d.", i)
                continue
            clip_paths.append(clip_path)
    finally:
        _SDXLBackend.unload()

    if not clip_paths:
        logger.warning("No visual clips were produced — aborting bed render.")
        return None

    bed_path = output_dir / "_visual_bed.mp4"
    if progress:
        progress("Stitching visual bed...", 92)
    if not _concat_with_crossfade(clip_paths, bed_path):
        return None

    # Cleanup intermediates; keep images_dir for inspection / re-roll cache.
    try:
        for p in clips_dir.glob("*.mp4"):
            p.unlink()
        clips_dir.rmdir()
    except Exception:
        pass

    if progress:
        progress("Visual bed ready", 100)
    logger.info("Visual bed saved -> %s", bed_path)
    return bed_path
