"""
agents/visual_agent.py — Build a dynamic video bed for the final podcast video
using AI-generated stills (SDXL) plus AI-generated clips (CogVideoX-5B).

Pipeline:
  1. Read visual_cues.json (written by post_production) + audio duration.
  2. Partition the audio timeline into intervals:
       cue intervals — driven by [VISUAL: prompt] markers
       gap intervals — between cue intervals; prompt synthesized from segment text
  3. Pass A — SDXL: generate one 1152x640 still per interval, render
       Ken-Burns zoom to fill its duration. Covers every interval (gaps +
       cue fallbacks).
  4. Pass B — CogVideoX-5B (optional, requires diffusers>=0.31): for each
       cue interval, generate a ~6 s t2v clip in bf16 with sequential CPU
       offload, scale/loop to the cue duration. Cached on disk by
       (prompt, seed) so re-runs and re-rolls are cheap.
  5. FFmpeg xfade-concatenates the per-interval clips (Ken-Burns stills
     + CogVideoX clips) into _visual_bed.mp4 spanning the full audio.

GPU choreography mirrors the TTS / Whisper unload pattern in
post_production_agent — every model is loaded, used, then unloaded so the
next stage has the full 16 GB of VRAM to itself.

CogVideoX gracefully no-ops when diffusers<0.31 or CUDA is unavailable —
the bed then ships as SDXL stills only (Phase 2 behavior).
"""
from __future__ import annotations

import json
import math
import re
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
    COGVIDEOX_MODEL_ID,
    COGVIDEOX_NUM_FRAMES,
    COGVIDEOX_NUM_INFERENCE_STEPS,
    COGVIDEOX_GUIDANCE,
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
# CogVideoX-5B text→video backend (Phase 3)
# ---------------------------------------------------------------------------

class _CogVideoXBackend:
    """CogVideoX-5B in bf16 with sequential CPU offload — fits 16 GB VRAM.

    On Blackwell GPUs (RTX 50-series) bitsandbytes int8 is unreliable, so we
    use bf16 + diffusers' `enable_sequential_cpu_offload()` instead. Slower
    (~10–15 min per 6 s clip) but stable and quality-faithful.

    Requires diffusers>=0.31. If the import fails, `load()` returns False and
    every cue interval falls back to the SDXL still + Ken-Burns path.
    """

    _pipe = None
    _loaded = False
    _unavailable_reason: str | None = None

    @classmethod
    def load(cls) -> bool:
        if cls._loaded:
            return True
        # Once we've recorded a hard unavailability reason, stop retrying so
        # we don't pay the import cost (and log spam) on every cue interval.
        if cls._unavailable_reason is not None:
            return False
        try:
            import torch
            try:
                from diffusers import CogVideoXPipeline
            except ImportError as exc:
                cls._unavailable_reason = (
                    f"CogVideoXPipeline not in installed diffusers ({exc}). "
                    "Run: pip install -U 'diffusers>=0.31' to enable t2v clips."
                )
                logger.info("[CogVideoX] %s", cls._unavailable_reason)
                return False

            if not torch.cuda.is_available():
                cls._unavailable_reason = "CUDA not available — CogVideoX requires a GPU."
                logger.info("[CogVideoX] %s", cls._unavailable_reason)
                return False

            logger.info("[CogVideoX] Loading %s in bf16 with sequential CPU offload...", COGVIDEOX_MODEL_ID)
            pipe = CogVideoXPipeline.from_pretrained(
                COGVIDEOX_MODEL_ID,
                torch_dtype=torch.bfloat16,
            )
            # Sequential offload streams blocks CPU<->GPU per layer. Slow but
            # keeps peak VRAM under 16 GB even on the 5060 Ti.
            try:
                pipe.enable_sequential_cpu_offload()
            except Exception:
                # Older diffusers may not expose this — try the legacy name.
                try:
                    pipe.enable_model_cpu_offload()
                except Exception:
                    logger.warning("[CogVideoX] Could not enable CPU offload; VRAM may exceed 16 GB.")
            try:
                pipe.vae.enable_slicing()
                pipe.vae.enable_tiling()
            except Exception:
                pass
            cls._pipe = pipe
            cls._loaded = True
            logger.info("[CogVideoX] Loaded.")
            return True
        except Exception as exc:
            cls._unavailable_reason = f"CogVideoX failed to load: {exc}"
            logger.warning("[CogVideoX] %s", cls._unavailable_reason)
            return False

    @classmethod
    def generate(cls, prompt: str, out_path: Path, seed: int = 42) -> bool:
        """Render a clip to `out_path` (MP4). Returns True on success.

        The generated MP4 is at CogVideoX's native ~720x480 / 8 fps; the
        Ken-Burns wrapper later upscales/retimes it to the bed's 1920x1080
        / 30 fps before stitching.
        """
        if not cls._loaded:
            return False
        try:
            import torch
            from diffusers.utils import export_to_video
            generator = torch.Generator(device="cuda").manual_seed(seed)
            with torch.inference_mode():
                result = cls._pipe(
                    prompt=prompt,
                    num_videos_per_prompt=1,
                    num_inference_steps=COGVIDEOX_NUM_INFERENCE_STEPS,
                    num_frames=COGVIDEOX_NUM_FRAMES,
                    guidance_scale=COGVIDEOX_GUIDANCE,
                    generator=generator,
                )
            frames = result.frames[0]
            export_to_video(frames, str(out_path), fps=8)
            return out_path.exists() and out_path.stat().st_size > 0
        except Exception as exc:
            logger.warning("[CogVideoX] generate failed (%s)", exc)
            return False

    @classmethod
    def unload(cls) -> None:
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
# Clip cache (CogVideoX is slow — never regenerate the same prompt twice)
# ---------------------------------------------------------------------------

def _cog_cache_dir(output_dir: Path) -> Path:
    d = output_dir / "_visual_cogvideox_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cog_cache_key(prompt: str, seed: int) -> str:
    import hashlib
    h = hashlib.sha256(f"{prompt}|{seed}".encode("utf-8")).hexdigest()
    return h[:16]


def _cog_cached_clip(output_dir: Path, prompt: str, seed: int) -> Optional[Path]:
    p = _cog_cache_dir(output_dir) / f"{_cog_cache_key(prompt, seed)}.mp4"
    return p if p.exists() and p.stat().st_size > 0 else None


def _stretch_clip_to_duration(
    clip_in: Path,
    clip_out: Path,
    duration_ms: int,
    fps: int = VISUAL_KEN_BURNS_FPS,
) -> bool:
    """Resample a CogVideoX clip to 1920x1080 @ `fps` and stretch/loop to
    exactly `duration_ms`.

    CogVideoX outputs ~6 s @ 8 fps. If the cue interval is shorter we trim;
    if longer we hold the last frame (tpad) so the visual stays parked
    rather than looping back. The result lives in the same per-interval
    slot as the SDXL Ken-Burns clips so the xfade concat treats them the
    same.
    """
    if duration_ms <= 0 or not clip_in.exists():
        return False
    duration_s = duration_ms / 1000.0
    # Filter chain: scale to bed res, retime to bed fps, and pad/trim to length.
    vf = (
        f"scale={VISUAL_BED_WIDTH}:{VISUAL_BED_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={VISUAL_BED_WIDTH}:{VISUAL_BED_HEIGHT},"
        f"fps={fps},"
        f"tpad=stop_mode=clone:stop_duration={duration_s:.3f}"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(clip_in),
        "-vf", vf,
        "-t", f"{duration_s:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(clip_out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        logger.warning("Clip stretch failed:\n%s", r.stderr[-800:])
        return False
    return True


# ---------------------------------------------------------------------------
# Visual director (LLM pass — turns each script segment into a sequence of
# detailed, distinct image prompts proportional to that segment's duration)
# ---------------------------------------------------------------------------

DIRECTOR_SYSTEM_PROMPT = """You are the visual director for a podcast video. \
Your job is to turn a spoken script segment into a chronological list of \
photographable scenes the AI image model will render.

OUTPUT RULES (must follow exactly):
- Output ONE prompt per line. No numbering, no bullets, no explanations.
- Output EXACTLY {target_count} lines.
- Each prompt is a single line of comma-separated descriptors.
- Each prompt describes a DIFFERENT physical scene — no two lines may share \
the same subject, setting, or composition. Vary subject, location, time of \
day, camera angle, and color palette.
- Each prompt must be photographable: describe a concrete subject, a setting, \
lighting, and camera/lens style. Translate ideas into physical things a camera \
could capture. Do NOT describe text, slides, charts, logos, UI mockups, or \
abstract concepts.
- Walk chronologically through the segment — line N depicts the moment ~N/{target_count} \
into the segment.
- Do NOT include style suffixes like "cinematic, 35mm" — those are appended later."""


def _seconds_per_visual_default() -> int:
    """How long each director-generated still should sit on screen, in seconds."""
    return 12


def _segment_duration_seconds(seg: dict, fallback_wpm: int = 150) -> float:
    """Best estimate of a segment's spoken duration, in seconds.

    Prefers the writer's `target_seconds`; falls back to actual_words/wpm.
    """
    ts = seg.get("target_seconds")
    if isinstance(ts, (int, float)) and ts > 0:
        return float(ts)
    words = int(seg.get("actual_words") or 0)
    if not words:
        from utils import strip_markers
        words = len(strip_markers(seg.get("text") or "").split())
    return (words / fallback_wpm) * 60 if words else 0.0


def _llm_director_prompts_sync(
    segments: list[dict],
    seconds_per_visual: int = None,
) -> list[list[str]] | None:
    """For each segment, ask the LLM for a list of distinct cinematic prompts
    proportional to the segment's spoken duration.

    Returns a parallel list `out` where `out[i]` is the prompt list for
    `segments[i]`. Returns None if the LLM is unavailable so the caller can
    fall back to the rule-based path.
    """
    if seconds_per_visual is None:
        seconds_per_visual = _seconds_per_visual_default()
    try:
        from llm_client import get_client
        client = get_client()
    except Exception:
        return None
    if client is None:
        return None

    from utils import strip_markers
    import asyncio

    out: list[list[str]] = []
    for i, seg in enumerate(segments):
        duration_s = _segment_duration_seconds(seg)
        target_count = max(1, round(duration_s / seconds_per_visual)) if duration_s > 0 else 1
        # Use the spoken text only — markers would confuse the visual director.
        spoken = strip_markers(seg.get("text") or "").strip()
        if not spoken:
            out.append([])
            continue

        seg_name = seg.get("name") or f"Segment {i+1}"
        sys_prompt = DIRECTOR_SYSTEM_PROMPT.format(target_count=target_count)
        user_prompt = (
            f"Segment name: {seg_name}\n"
            f"Approx duration: {duration_s:.0f}s.\n"
            f"Generate exactly {target_count} chronological visual prompts "
            f"for this segment.\n\n"
            f"Segment text:\n\"\"\"\n{spoken}\n\"\"\""
        )
        try:
            # build_visual_bed runs on a worker thread (asyncio.to_thread),
            # so a fresh asyncio.run is safe here.
            raw = asyncio.run(client.system_user(
                sys_prompt,
                user_prompt,
                temperature=0.7,
                max_tokens=max(256, target_count * 80),
            ))
        except Exception as exc:
            logger.warning("[Director] LLM call failed for '%s': %s", seg_name, exc)
            out.append([])
            continue

        prompts = _parse_director_lines(raw, target_count)
        logger.info("[Director] '%s' -> %d prompt(s) for ~%ds", seg_name, len(prompts), int(duration_s))
        out.append(prompts)
    return out


def _parse_director_lines(raw: str, target_count: int) -> list[str]:
    """Pull `target_count` clean prompt lines out of an LLM response."""
    if not raw:
        return []
    lines: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        # Drop common LLM noise: numbering, bullets, code fences, headings.
        if s.startswith("```"):
            continue
        # Drop common LLM prefixes: "1. foo", "1) foo", "- foo", "* foo", "• foo"
        s = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", s)
        # Drop a leading bracketed prompt index like "[1]" or "[Scene 1]"
        s = re.sub(r"^\[[^\]]{1,20}\]\s*", "", s)
        # Skip preamble lines that don't look like prompts
        if len(s.split()) < 3:
            continue
        if s.lower().startswith(("here are", "here is", "okay", "sure")):
            continue
        lines.append(s)
        if len(lines) >= target_count:
            break

    # If the LLM gave us fewer lines than asked, accept what we got.
    return lines


def _rule_based_segment_prompts(
    segments: list[dict],
    seconds_per_visual: int = None,
) -> list[list[str]]:
    """LLM-free fallback: derive N prompts per segment by chunking its text.

    For each segment we split it into roughly equal chunks and use each
    chunk's first ~12 words as a prompt seed. Better than the old
    one-prompt-fits-all derivation, but still nowhere near LLM quality.
    """
    if seconds_per_visual is None:
        seconds_per_visual = _seconds_per_visual_default()
    from utils import strip_markers
    out: list[list[str]] = []
    for seg in segments:
        duration_s = _segment_duration_seconds(seg)
        target_count = max(1, round(duration_s / seconds_per_visual)) if duration_s > 0 else 1
        spoken = strip_markers(seg.get("text") or "").strip()
        words = spoken.split()
        if not words:
            out.append([])
            continue
        # Slice the word list into target_count near-equal chunks.
        chunks: list[list[str]] = []
        if target_count <= 1:
            chunks = [words]
        else:
            step = max(1, len(words) // target_count)
            for k in range(target_count):
                chunks.append(words[k * step:(k + 1) * step] if k < target_count - 1 else words[k * step:])
        prompts = []
        for chunk in chunks:
            seed = " ".join(chunk[:14]).rstrip(".!?,;:")
            if seed:
                prompts.append(f"establishing shot inspired by: {seed}")
        out.append(prompts)
    return out


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


def _script_fingerprint(script_segments: list[dict]) -> str:
    """Stable hash of the spoken-text content of every segment.

    Used to invalidate the director-prompt cache automatically when the
    user edits a segment via /api/regenerate-segment.
    """
    import hashlib
    from utils import strip_markers
    h = hashlib.sha256()
    for seg in script_segments:
        text = strip_markers(seg.get("text") or "").strip()
        h.update(seg.get("name", "").encode("utf-8") + b"|" + text.encode("utf-8") + b"||")
    return h.hexdigest()[:16]


def _load_or_build_director_schedule(
    output_dir: Path,
    script_segments: list[dict],
    audio_duration_ms: int,
    progress: Optional[Callable[[str, int], None]] = None,
) -> list[tuple[int, int, str, int]] | None:
    """Build (or load from cache) a director schedule for this episode.

    Cache file: outputs/<episode>/visual_director.json
    Schema:   {"fingerprint": "...", "schedule": [[start, end, prompt, seg_i], ...]}
    """
    if not script_segments or audio_duration_ms <= 0:
        return None

    cache = output_dir / "visual_director.json"
    fp = _script_fingerprint(script_segments)
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("fingerprint") == fp and data.get("schedule"):
                schedule = [tuple(row) for row in data["schedule"]]
                logger.info("[Director] Loaded %d cached prompt(s).", len(schedule))
                return schedule
        except Exception as exc:
            logger.info("[Director] Cache read failed (%s) — rebuilding.", exc)

    if progress:
        progress("Visual director: generating prompts...", 3)

    boundaries = _segment_audio_boundaries(script_segments, audio_duration_ms)
    segment_prompts = _llm_director_prompts_sync(script_segments)
    if segment_prompts is None or all(not lst for lst in segment_prompts):
        # Fall back to rule-based per-segment chunking — better than the old
        # one-prompt-fits-all derivation but no LLM creativity.
        logger.info("[Director] LLM unavailable — using rule-based per-segment prompts.")
        segment_prompts = _rule_based_segment_prompts(script_segments)

    schedule = _build_director_schedule(segment_prompts, boundaries)
    if not schedule:
        return None

    # Persist for re-rolls
    try:
        cache.write_text(
            json.dumps({"fingerprint": fp, "schedule": schedule}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("[Director] Could not write cache: %s", exc)

    logger.info("[Director] Built schedule with %d prompt(s) across %d segment(s).",
                len(schedule), len(script_segments))
    return schedule


def _segment_audio_boundaries(
    script_segments: list[dict],
    audio_duration_ms: int,
) -> list[tuple[int, int]]:
    """Estimate (start_ms, end_ms) on the master audio for each script segment.

    Distributes audio time proportionally to each segment's spoken duration
    (preferring `target_seconds`, falling back to actual_words/wpm). Used by
    the director to know which segment a given timestamp belongs to.
    """
    if not script_segments or audio_duration_ms <= 0:
        return []
    weights = [max(0.001, _segment_duration_seconds(s)) for s in script_segments]
    total = sum(weights) or 1.0
    boundaries: list[tuple[int, int]] = []
    cursor = 0
    for i, w in enumerate(weights):
        if i == len(weights) - 1:
            end = audio_duration_ms
        else:
            end = cursor + int((w / total) * audio_duration_ms)
        boundaries.append((cursor, end))
        cursor = end
    return boundaries


def _build_director_schedule(
    segment_prompts: list[list[str]],
    segment_boundaries: list[tuple[int, int]],
) -> list[tuple[int, int, str, int]]:
    """Turn per-segment prompt lists into a flat timeline schedule.

    Returns (start_ms, end_ms, prompt, segment_index) tuples spanning the
    full audio range, sorted by start_ms. Each prompt occupies an equal
    sub-slice of its segment's audio range.
    """
    schedule: list[tuple[int, int, str, int]] = []
    for i, prompts in enumerate(segment_prompts):
        if not prompts or i >= len(segment_boundaries):
            continue
        seg_start, seg_end = segment_boundaries[i]
        seg_dur = max(1, seg_end - seg_start)
        n = len(prompts)
        for j, prompt in enumerate(prompts):
            sub_start = seg_start + (seg_dur * j) // n
            sub_end = seg_start + (seg_dur * (j + 1)) // n
            schedule.append((sub_start, sub_end, prompt, i))
    schedule.sort(key=lambda t: t[0])
    return schedule


def _plan_intervals(
    visual_cues: list[dict],
    audio_duration_ms: int,
    script_segments: list[dict] | None = None,
    max_interval_ms: int = 12_000,
    director_schedule: list[tuple[int, int, str, int]] | None = None,
) -> list[dict]:
    """Carve the audio timeline into a sequence of visual intervals.

    Each interval has:
        kind  — 'cue' (had an explicit [VISUAL:] marker) or 'gap' (filler)
        prompt — what to send to the image/video model
        start_ms, end_ms — position on the master audio timeline

    When `director_schedule` is provided AND there are no `[VISUAL:]` cues,
    the schedule's intervals are used directly — every gap gets a unique,
    LLM-authored prompt instead of all sharing one fallback prompt.

    Gaps longer than `max_interval_ms` are still split so no single still
    drags on for the whole intro/outro.
    """
    intervals: list[dict] = []

    if not visual_cues:
        # Director path: each schedule entry IS one interval, no sub-splitting.
        # The LLM already sized prompts to ~12 s by issuing target_count =
        # round(segment_seconds / 12); duplicating an image across sub-splits
        # of the same interval would defeat the whole point of the director.
        # Any interval >18 s still gets one extra split as a comfort cap so
        # nothing sits totally static for ages.
        if director_schedule:
            soft_cap = max(max_interval_ms, 18_000)
            for (start, end, prompt, _seg_i) in director_schedule:
                if end - start <= soft_cap:
                    intervals.append({
                        "kind": "gap",
                        "prompt": prompt,
                        "start_ms": start,
                        "end_ms": end,
                    })
                else:
                    cur = start
                    while cur < end:
                        nxt = min(cur + soft_cap, end)
                        intervals.append({
                            "kind": "gap",
                            "prompt": prompt,
                            "start_ms": cur,
                            "end_ms": nxt,
                        })
                        cur = nxt
            if not intervals or intervals[-1]["end_ms"] < audio_duration_ms:
                _emit_gap_intervals(
                    intervals,
                    start_ms=intervals[-1]["end_ms"] if intervals else 0,
                    end_ms=audio_duration_ms,
                    script_segments=script_segments or [],
                    max_interval_ms=max_interval_ms,
                )
            return intervals

        # No director, no cues — last-resort evenly-spaced gaps with the
        # legacy single-prompt derivation. Worse but keeps the pipeline alive.
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
            director_schedule=director_schedule,
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
            director_schedule=director_schedule,
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
    director_schedule: list[tuple[int, int, str, int]] | None = None,
) -> None:
    """Split a [start_ms, end_ms] gap into one or more gap intervals.

    When `director_schedule` is provided, each sub-interval gets the prompt
    from the schedule entry whose midpoint falls inside it (or the nearest
    one). That gives every gap a unique LLM-authored prompt instead of all
    sharing one fallback.
    """
    cursor = start_ms
    while cursor < end_ms:
        nxt = min(cursor + max_interval_ms, end_ms)
        prompt = _pick_director_prompt(director_schedule, cursor, nxt) if director_schedule else None
        if not prompt:
            prompt = _derive_gap_prompt(script_segments, cursor)
        intervals.append({
            "kind": "gap",
            "prompt": prompt,
            "start_ms": cursor,
            "end_ms": nxt,
        })
        cursor = nxt


def _pick_director_prompt(
    schedule: list[tuple[int, int, str, int]],
    start_ms: int,
    end_ms: int,
) -> str | None:
    """Find the schedule entry whose midpoint is closest to this gap's midpoint."""
    if not schedule:
        return None
    target = (start_ms + end_ms) // 2
    best = None
    best_dist = None
    for s_start, s_end, prompt, _seg in schedule:
        s_mid = (s_start + s_end) // 2
        d = abs(s_mid - target)
        if best_dist is None or d < best_dist:
            best = prompt
            best_dist = d
    return best


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

    # ── Visual director: ask the LLM for one detailed prompt every ~12 s ──
    # Cached on disk so re-rolls and re-stitches don't re-LLM. The cache key
    # is the script-segment text fingerprint, so editing the script
    # invalidates it automatically.
    director_schedule = _load_or_build_director_schedule(
        output_dir, script_segments or [], duration_ms,
        progress=progress,
    )

    intervals = _plan_intervals(
        visual_cues,
        duration_ms,
        script_segments or [],
        director_schedule=director_schedule,
    )
    if not intervals:
        return None
    logger.info(
        "Planned %d visual interval(s) across %.1fs of audio (%d cue, %d gap, director=%s).",
        len(intervals), duration_ms / 1000,
        sum(1 for iv in intervals if iv["kind"] == "cue"),
        sum(1 for iv in intervals if iv["kind"] == "gap"),
        "on" if director_schedule else "off",
    )

    images_dir = output_dir / "_visual_images"
    clips_dir = output_dir / "_visual_clips"
    images_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    # ── Pass 1: SDXL covers every interval (gaps + cue fallbacks). ────────────
    # Each interval ends with a Ken-Burns clip on disk; cue intervals get
    # overwritten by CogVideoX in pass 2 if available.
    if progress:
        progress("Loading SDXL...", 5)
    if not _SDXLBackend.load():
        return None

    clip_paths: list[Optional[Path]] = [None] * len(intervals)
    try:
        for i, iv in enumerate(intervals):
            pct = 8 + int(40 * (i / len(intervals)))
            if progress:
                progress(f"SDXL still {i+1}/{len(intervals)} ({iv['kind']})...", pct)

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
            clip_paths[i] = clip_path
    finally:
        _SDXLBackend.unload()

    # ── Pass 2: CogVideoX overwrites cue intervals (when available). ──────────
    cue_indices = [i for i, iv in enumerate(intervals) if iv["kind"] == "cue"]
    if cue_indices and _CogVideoXBackend.load():
        try:
            for n, i in enumerate(cue_indices):
                iv = intervals[i]
                pct = 50 + int(40 * (n / max(1, len(cue_indices))))
                if progress:
                    progress(f"CogVideoX clip {n+1}/{len(cue_indices)}...", pct)

                prompt = (iv.get("prompt") or "").strip()
                if not prompt.endswith(VISUAL_STYLE_SUFFIX):
                    prompt = f"{prompt}{VISUAL_STYLE_SUFFIX}"
                seed = 2000 + i

                cached = _cog_cached_clip(output_dir, prompt, seed)
                if cached:
                    raw_clip = cached
                    logger.info("CogVideoX cache hit for interval %d.", i)
                else:
                    raw_clip = _cog_cache_dir(output_dir) / f"{_cog_cache_key(prompt, seed)}.mp4"
                    if not _CogVideoXBackend.generate(prompt, raw_clip, seed=seed):
                        logger.info("CogVideoX failed for interval %d — keeping SDXL still.", i)
                        continue

                stretched = clips_dir / f"interval_{i:03d}_cog.mp4"
                if _stretch_clip_to_duration(
                    raw_clip,
                    stretched,
                    iv["end_ms"] - iv["start_ms"],
                ):
                    clip_paths[i] = stretched
                    logger.info("CogVideoX clip placed at interval %d.", i)
                else:
                    logger.info("Stretch failed for interval %d — keeping SDXL still.", i)
        finally:
            _CogVideoXBackend.unload()
    elif cue_indices:
        logger.info(
            "Skipping CogVideoX pass — falling back to SDXL stills for %d cue interval(s).",
            len(cue_indices),
        )

    # Drop any None slots (intervals where everything failed) so concat works.
    final_clips = [p for p in clip_paths if p is not None]
    if not final_clips:
        logger.warning("No visual clips were produced — aborting bed render.")
        return None

    bed_path = output_dir / "_visual_bed.mp4"
    if progress:
        progress("Stitching visual bed...", 92)
    if not _concat_with_crossfade(final_clips, bed_path):
        return None

    # Keep _visual_clips/ so the per-cue re-roll endpoint can swap a single
    # clip and re-stitch without rebuilding every other interval. The dir
    # is small (~1-3 MB per interval) and lets re-rolls finish in seconds
    # instead of minutes.

    if progress:
        progress("Visual bed ready", 100)
    logger.info("Visual bed saved -> %s", bed_path)
    return bed_path
