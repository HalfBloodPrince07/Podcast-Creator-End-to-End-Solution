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
    """Lazily-loaded SDXL base pipeline. Singleton, with explicit unload.

    `_load_lock` serializes concurrent load() calls. Without it, two
    simultaneous build_visual_bed invocations (e.g. frontend auto-fire
    racing a manual click) both pass the `if _loaded` check and try to
    materialize the same meta-tensor pipeline in parallel, which crashes
    with "Cannot copy out of meta tensor; no data!" on one of them.
    """

    import threading as _threading
    _pipe = None
    _loaded = False
    _load_lock = _threading.Lock()

    @classmethod
    def load(cls) -> bool:
        if cls._loaded:
            return True
        with cls._load_lock:
            # Recheck under the lock — the racing caller may have already loaded.
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
    def _encode_long_prompt(cls, prompt: str, negative_prompt: str):
        """Chunked CLIP encoding so prompts longer than 77 tokens aren't truncated.

        Both SDXL text encoders (CLIP-L and OpenCLIP-G) cap at 77 tokens
        each. Our detailed beat-director prompts run 100-150+ tokens after
        the style suffix is appended, so the tail (palette, texture, mood,
        style words) was being silently dropped. Standard fix: split the
        prompt into 75-token chunks, encode each through both encoders,
        and concatenate along the token dimension. The SDXL pipeline
        accepts the result as `prompt_embeds` + `pooled_prompt_embeds`.
        """
        import torch
        import logging as _logging
        pipe = cls._pipe
        device = pipe.device

        # Tokenizing without truncation logs a "sequence length > 77" warning
        # every call. We KNOW it's >77 — that's why we're chunking. Mute it
        # only for the duration of this encode, then restore.
        _tok_logger = _logging.getLogger("transformers.tokenization_utils_base")
        _prev_level = _tok_logger.level
        _tok_logger.setLevel(_logging.ERROR)

        def _encode_one(text: str):
            emb_l, emb_g = [], []
            pooled_g = None
            for tok, enc, sink in (
                (pipe.tokenizer,   pipe.text_encoder,   emb_l),
                (pipe.tokenizer_2, pipe.text_encoder_2, emb_g),
            ):
                ids_full = tok(text, padding=False, truncation=False, return_tensors="pt").input_ids[0]
                # Strip BOS/EOS that the tokenizer added; we re-wrap each chunk.
                core = ids_full
                if len(core) >= 1 and tok.bos_token_id is not None and core[0].item() == tok.bos_token_id:
                    core = core[1:]
                if len(core) >= 1 and tok.eos_token_id is not None and core[-1].item() == tok.eos_token_id:
                    core = core[:-1]
                max_len = tok.model_max_length  # 77 for both SDXL tokenizers
                inner = max_len - 2  # leave room for BOS + EOS
                if len(core) == 0:
                    chunks_core = [torch.tensor([], dtype=torch.long)]
                else:
                    chunks_core = [core[i:i + inner] for i in range(0, len(core), inner)]
                for chunk_core in chunks_core:
                    pad_len = max_len - len(chunk_core) - 2
                    ids = torch.cat([
                        torch.tensor([tok.bos_token_id], dtype=torch.long),
                        chunk_core.to(torch.long),
                        torch.tensor([tok.eos_token_id], dtype=torch.long),
                        torch.full((pad_len,), tok.pad_token_id or 0, dtype=torch.long),
                    ]).unsqueeze(0).to(device)
                    out = enc(ids, output_hidden_states=True)
                    # SDXL uses the penultimate hidden state, not the last.
                    sink.append(out.hidden_states[-2])
                    # Pooled output comes from the OpenCLIP-G encoder's
                    # FIRST chunk only — encodes the overall sentence semantics.
                    if tok is pipe.tokenizer_2 and pooled_g is None:
                        # text_embeds is the pooled output for CLIPTextModelWithProjection
                        pooled_g = out[0]
            # Token-dim concat per encoder
            e_l = torch.cat(emb_l, dim=1)
            e_g = torch.cat(emb_g, dim=1)
            # Tokenizers can split slightly differently; trim to common length.
            n = min(e_l.shape[1], e_g.shape[1])
            embeds = torch.cat([e_l[:, :n, :], e_g[:, :n, :]], dim=-1)
            return embeds, pooled_g

        try:
            pos_embeds, pos_pooled = _encode_one(prompt)
            neg_embeds, neg_pooled = _encode_one(negative_prompt or "")
        finally:
            _tok_logger.setLevel(_prev_level)

        # Positive and negative must have matching token counts. Pad the shorter
        # one with zeros (SDXL's negative pad is just absence of signal).
        diff = pos_embeds.shape[1] - neg_embeds.shape[1]
        if diff > 0:
            pad = torch.zeros(neg_embeds.shape[0], diff, neg_embeds.shape[2],
                              device=device, dtype=neg_embeds.dtype)
            neg_embeds = torch.cat([neg_embeds, pad], dim=1)
        elif diff < 0:
            pad = torch.zeros(pos_embeds.shape[0], -diff, pos_embeds.shape[2],
                              device=device, dtype=pos_embeds.dtype)
            pos_embeds = torch.cat([pos_embeds, pad], dim=1)

        return pos_embeds, pos_pooled, neg_embeds, neg_pooled

    @classmethod
    def generate(cls, prompt: str, seed: int = 42) -> Optional["Image.Image"]:
        """Return a PIL Image or None on failure. Caller decides what to do on None."""
        if not cls._loaded:
            return None
        try:
            import torch
            generator = torch.Generator(device=cls._pipe.device).manual_seed(seed)
            with torch.inference_mode():
                # Chunked encoding -> long prompts (palette, texture, mood,
                # and the style suffix) survive without 77-token truncation.
                p_emb, p_pool, n_emb, n_pool = cls._encode_long_prompt(
                    prompt, SDXL_NEGATIVE_PROMPT,
                )
                result = cls._pipe(
                    prompt_embeds=p_emb,
                    pooled_prompt_embeds=p_pool,
                    negative_prompt_embeds=n_emb,
                    negative_pooled_prompt_embeds=n_pool,
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
    # Two flavours of failure:
    #  - HARD: import missing or CUDA absent. These don't change at runtime,
    #          cache forever (until process restart) so we don't reimport on
    #          every cue. Recorded as a string.
    #  - SOFT: model download in flight, transient OOM, HF cache corruption.
    #          These DO change at runtime (the next request might succeed),
    #          so we don't cache them — every load() re-attempts.
    _unavailable_reason: str | None = None  # only set for HARD failures
    _last_soft_failure: str | None = None    # informational; not a short-circuit

    @classmethod
    def load(cls) -> bool:
        if cls._loaded:
            return True
        # Hard failures persist across the process — never retry.
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
            # SOFT failure — could be a download still in flight, transient OOM,
            # or cache corruption that gets cleaned up on retry. Don't latch
            # _unavailable_reason; the next request might succeed.
            cls._last_soft_failure = f"CogVideoX failed to load: {exc}"
            logger.warning(
                "[CogVideoX] %s — will retry on next request "
                "(not caching the failure; restart the server only if the same "
                "error reappears).", cls._last_soft_failure,
            )
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
# Visual director (whisper-driven) — group spoken audio into ~12s "beats" at
# sentence boundaries, then ask the LLM for one cinematic prompt per beat
# grounded in the literal text of that beat. Beat ms-bounds come from
# Whisper word timings, so visuals fire exactly when the words are spoken.
# ---------------------------------------------------------------------------

BEAT_DIRECTOR_SYSTEM = """You are the visual director for a podcast video. \
You will receive a numbered list of short audio beats — each one is the exact \
text the speaker says during a ~12 second window. For each beat, write ONE \
extremely detailed, image-model-ready cinematic prompt depicting exactly what \
the speaker is talking about at that moment.

OUTPUT FORMAT (must follow exactly):
- Output exactly one prompt per beat, numbered "1. ", "2. ", "3. ", ... in order.
- One prompt per line. No headers, no commentary, no code fences, no blank \
lines between, no quotation marks around the prompt.

EACH PROMPT MUST INCLUDE, IN THIS ORDER (comma-separated descriptors):
  1. SUBJECT — a specific person, object, or creature with concrete attributes: \
age, gender, expression, posture, clothing material and color, hands and what \
they hold, what they are physically doing right now. Avoid pronouns and \
generic nouns ("a man" → "a weathered Roman general in his fifties, deep \
furrowed brow, bronze cuirass with embossed laurels, scarlet wool cloak \
clasped at one shoulder, gripping a vellum scroll").
  2. SETTING — a specific place with architectural / environmental detail: \
era, materials, props, foreground and background elements, weather, time of \
day. ("a candlelit Senate chamber, travertine columns, mosaic floor, late \
afternoon sun slanting through high windows, dust motes suspended in the air").
  3. LIGHTING — direction + quality + color temperature: "warm tungsten key \
light from camera-left, deep shadows on the right, soft golden bounce from \
the marble floor" or "cold overcast daylight through tall windows, soft \
wraparound, faint blue rim from a snowy courtyard outside."
  4. COMPOSITION — shot size + camera angle + framing: "medium close-up, \
slight low angle, rule-of-thirds with subject on the right, soft bokeh \
foreground" or "wide establishing shot, eye-level, symmetrical, leading \
lines down the colonnade."
  5. COLOR PALETTE — 2–3 dominant colors with adjectives: "muted ochre and \
ivory with deep oxblood accents" or "desaturated steel-blue and slate-grey \
with a single warm amber highlight."
  6. ATMOSPHERE / TEXTURE — particulates, surfaces, micro-detail: "fine dust \
motes catching the light, wax dripping down brass candle sticks, faint \
woodsmoke in the air, pores and stubble visible on the subject's skin."
  7. MOOD — one phrase: "solemn, weight of decision."

CRITICAL RULES:
- PHOTOGRAPHABLE ONLY — describe physical things a camera could capture. \
NEVER describe text, slides, charts, logos, UI, captions, words on screen, \
icons, infographics, abstract diagrams, or symbolic illustrations.
- Stay grounded in the LITERAL spoken content of the beat. If the beat says \
"the Roman Senate voted to extend the war," depict the Senate chamber and \
its senators — not a generic city skyline, not text floating in space.
- Each prompt must be DISTINCT from its neighbors. No two consecutive prompts \
may share the same subject, location, lighting setup, camera angle, OR color \
palette. Vary deliberately.
- Be SPECIFIC, never generic. "A soldier" is wrong; "a young legionary, \
sweat-streaked face, bronze helmet dented on one side, gripping a pilum" is \
right.
- Target 45–80 words per prompt. Pack detail; do not pad with filler.
- Do NOT append style suffixes like "cinematic, 35mm film, photorealistic, \
8k, dramatic lighting" — those are added automatically. Spend your tokens on \
the SCENE, not on style boilerplate.

EXAMPLE OUTPUT (for two beats about Roman politics):
1. A grey-bearded Roman senator in his sixties, brow furrowed in concern, \
ivory toga draped over his left shoulder, right hand resting on the pommel \
of a ceremonial dagger at his belt, standing alone in a marble Senate \
chamber, travertine columns receding into shadow, late afternoon sun \
slanting through high clerestory windows, warm amber key light from \
camera-right, deep umber shadows pooling on the mosaic floor, medium shot \
at eye level slightly from the side, palette of warm ivory, oxblood, and \
travertine cream, fine dust motes visible in the shafts of light, mood: \
weight of an irrevocable decision.
2. A young Roman messenger on horseback, leather lorica streaked with mud, \
helmet hanging from the saddle, reins gripped in chapped hands, galloping \
along a wet stone road cutting through a misted Italian valley at dawn, \
cypress trees in silhouette on the ridges behind, low cold blue ambient \
light, single warm shaft of rising sun breaking through cloud on the left, \
wide tracking shot at low angle level with the horse's chest, palette of \
slate blue, wet-stone grey, and saddle leather brown, dew on the grass and \
mist clinging to the horse's flanks, mood: urgency under a still cold \
sky."""


_SENTENCE_END_RE = re.compile(r'[.!?]["\')\]]*\s*$')
_NUM_PREFIX_RE = re.compile(r'^\s*(\d{1,3})\s*[.\)\]:]?\s+')


def _load_whisper_words(output_dir: Path) -> list[dict]:
    """Read whisper_words.json from the episode dir; return [] if missing."""
    p = output_dir / "whisper_words.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.info("Could not read whisper_words.json: %s", exc)
        return []


def _build_beats_from_whisper(
    words: list[dict],
    min_seconds: float = 9.0,
    max_seconds: float = 16.0,
) -> list[dict]:
    """Group whisper words into ~12s beats, closing on sentence punctuation.

    A beat closes when either:
      (a) the running duration crosses min_seconds AND the last word ends in
          sentence punctuation (. ! ?), or
      (b) the running duration reaches max_seconds (forced close mid-sentence).

    Returns list of {start_ms, end_ms, text}. The text is the literal joined
    spoken transcript of the beat.
    """
    if not words:
        return []

    beats: list[dict] = []
    buf_start_ms: Optional[int] = None
    buf_end_ms = 0
    buf_words: list[str] = []

    for w in words:
        w_text = (w.get("word") or "").strip()
        if not w_text:
            continue
        try:
            w_start_ms = int(float(w.get("start") or 0.0) * 1000)
            w_end_ms = int(float(w.get("end") or 0.0) * 1000)
        except (TypeError, ValueError):
            continue
        if buf_start_ms is None:
            buf_start_ms = w_start_ms
        buf_words.append(w_text)
        buf_end_ms = w_end_ms

        elapsed = (buf_end_ms - buf_start_ms) / 1000.0
        sentence_end = bool(_SENTENCE_END_RE.search(w_text))
        if (elapsed >= min_seconds and sentence_end) or elapsed >= max_seconds:
            beats.append({
                "start_ms": buf_start_ms,
                "end_ms": buf_end_ms,
                "text": " ".join(buf_words),
            })
            buf_start_ms = None
            buf_words = []

    # Glue a tiny remainder onto the previous beat so we don't end with a
    # 2-second flash, but only if there IS a previous beat to extend.
    if buf_words and buf_start_ms is not None:
        tail_ms = buf_end_ms - buf_start_ms
        if beats and tail_ms < min_seconds * 1000:
            beats[-1]["end_ms"] = buf_end_ms
            beats[-1]["text"] = beats[-1]["text"] + " " + " ".join(buf_words)
        else:
            beats.append({
                "start_ms": buf_start_ms,
                "end_ms": buf_end_ms,
                "text": " ".join(buf_words),
            })
    return beats


def _carve_cue_ranges_from_beats(
    beats: list[dict],
    cues: list[dict],
    *,
    min_keep_ms: int = 2000,
) -> list[dict]:
    """Subtract every cue's [start_ms, end_ms] range from each beat.

    Cues are authoritative — they keep their exact slot. A beat fully inside
    a cue is dropped; a beat that straddles a cue boundary is trimmed (and
    split, if the cue sits inside the beat). Trimmed pieces shorter than
    min_keep_ms are discarded so we don't ship sub-2-second visual flashes.
    """
    if not cues:
        return list(beats)

    ranges = sorted((int(c["start_ms"]), int(c["end_ms"])) for c in cues if c.get("end_ms", 0) > c.get("start_ms", 0))
    if not ranges:
        return list(beats)

    out: list[dict] = []
    for beat in beats:
        b_start = int(beat["start_ms"])
        b_end = int(beat["end_ms"])
        pieces: list[tuple[int, int]] = [(b_start, b_end)]
        for r_start, r_end in ranges:
            if r_end <= b_start or r_start >= b_end:
                continue
            new_pieces: list[tuple[int, int]] = []
            for p_start, p_end in pieces:
                if r_end <= p_start or r_start >= p_end:
                    new_pieces.append((p_start, p_end))
                    continue
                if r_start > p_start:
                    new_pieces.append((p_start, r_start))
                if r_end < p_end:
                    new_pieces.append((r_end, p_end))
            pieces = new_pieces
            if not pieces:
                break

        for p_start, p_end in pieces:
            if p_end - p_start < min_keep_ms:
                continue
            out.append({
                "start_ms": p_start,
                "end_ms": p_end,
                "text": beat.get("text", ""),
            })
    return out


def _parse_numbered_prompts(raw: str, expected: int) -> list[str]:
    """Parse 'N. <prompt>' lines into a parallel list. Missing slots are ''."""
    out = [""] * expected
    if not raw:
        return out
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("```"):
            continue
        m = _NUM_PREFIX_RE.match(s)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if not 0 <= idx < expected:
            continue
        body = s[m.end():].strip()
        # Strip a leading bracketed tag like "[Scene 1]" if the model added one.
        body = re.sub(r"^\[[^\]]{1,20}\]\s*", "", body).rstrip(",.")
        if len(body.split()) >= 3 and not body.lower().startswith(("here", "okay", "sure")):
            out[idx] = body
    return out


def _rule_based_beat_prompt(text: str) -> str:
    """LLM-free fallback prompt: phrase-seeded establishing shot."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    seed = " ".join(cleaned.split()[:14]).rstrip(".!?,;:")
    if not seed:
        return "ambient cinematic landscape, soft volumetric light, atmospheric mood"
    return f"establishing shot inspired by: {seed}"


def _llm_beat_prompts_sync(
    beats: list[dict],
    batch_size: int = 10,
) -> Optional[list[str]]:
    """Generate one cinematic prompt per beat via batched LLM calls.

    Returns a list of prompts parallel to `beats`, or None if the LLM is
    completely unavailable. Slots the LLM failed on are filled with the
    rule-based fallback so the caller always gets a usable prompt per beat.
    """
    if not beats:
        return []
    try:
        from llm_client import get_client
        client = get_client()
    except Exception:
        return None
    if client is None:
        return None

    import asyncio

    out: list[str] = [""] * len(beats)
    for batch_start in range(0, len(beats), batch_size):
        batch = beats[batch_start:batch_start + batch_size]
        n = len(batch)
        user_lines = [f"{i+1}. {b['text']}" for i, b in enumerate(batch)]
        user_prompt = (
            f"Here are {n} consecutive audio beats from the podcast. Each line "
            f"is the literal spoken text of that beat. Write exactly {n} "
            f"extremely detailed cinematic prompts — one per beat, in order — "
            f"following the SUBJECT / SETTING / LIGHTING / COMPOSITION / "
            f"COLOR / ATMOSPHERE / MOOD structure from the system prompt. "
            f"Each prompt must be 45–80 words. Do not skip any of the seven "
            f"elements. Stay literal to the spoken text.\n\n"
            f"BEATS:\n" + "\n".join(user_lines)
        )
        batch_idx = batch_start // batch_size
        try:
            raw = asyncio.run(client.system_user(
                BEAT_DIRECTOR_SYSTEM,
                user_prompt,
                temperature=0.75,
                # Generous budget: thinking models can spend 2-3 KB reasoning
                # before they emit the numbered prompts. n*300 = ~3000 for
                # a full batch of 10 detailed prompts, plus a 4 KB floor for
                # the reasoning preamble.
                max_tokens=max(8000, n * 300),
            ))
        except Exception as exc:
            logger.warning("[BeatDirector] batch %d LLM call failed: %s", batch_idx, exc)
            continue

        parsed = _parse_numbered_prompts(raw, n)
        filled = sum(1 for p in parsed if p)
        logger.info("[BeatDirector] batch %d -> %d/%d prompts parsed", batch_idx, filled, n)
        for i, p in enumerate(parsed):
            if p:
                out[batch_start + i] = p

    for i, p in enumerate(out):
        if not p:
            out[i] = _rule_based_beat_prompt(beats[i]["text"])
    return out


def _beat_cache_fingerprint(words: list[dict], cues: list[dict]) -> str:
    """Fingerprint over whisper word timings + cue ranges.

    Cue *prompts* are intentionally excluded — editing a cue's prompt via the
    re-roll endpoint should not invalidate the beat director's prompt cache,
    only the cue's own clip. Cue *ranges* are included because they determine
    which beats get carved out.
    """
    import hashlib
    h = hashlib.sha256()
    h.update(f"v2|{len(words)}|".encode("ascii"))
    for i, w in enumerate(words):
        # Sample word text every 20 words to keep the digest cheap.
        if i % 20 == 0:
            h.update((w.get("word") or "").encode("utf-8"))
        h.update(f"{float(w.get('start',0)):.2f}-{float(w.get('end',0)):.2f}|".encode("ascii"))
    for c in cues:
        h.update(f"|{int(c.get('start_ms',0))}-{int(c.get('end_ms',0))}".encode("ascii"))
    return h.hexdigest()[:16]


def _load_cached_beats(output_dir: Path) -> list[dict]:
    """Read the on-disk beat cache without rebuilding.

    Returned for app.py's cue-regen path so it can re-derive the same
    interval ordering used by the original build without paying for a
    second LLM pass. Returns [] if the cache is missing or malformed.
    """
    cache = output_dir / "visual_director.json"
    if not cache.exists():
        return []
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        return []
    if data.get("version") != 3:
        return []
    return data.get("beats") or []


def _load_or_build_beat_schedule(
    output_dir: Path,
    words: list[dict],
    cues: list[dict],
    audio_duration_ms: int,
    progress: Optional[Callable[[str, int], None]] = None,
) -> list[dict]:
    """Build (or load from cache) the beat schedule for this episode.

    Cache file:  outputs/<episode>/visual_director.json
    Schema:      {"version": 3, "fingerprint": "...", "beats": [...]}
    Each beat:   {start_ms, end_ms, text, prompt}.

    Version bumps to force a clean rebuild whenever the system prompt or
    output structure changes (so already-rendered episodes don't keep
    serving prompts written under the old style).
    """
    if not words or audio_duration_ms <= 0:
        return []

    cache = output_dir / "visual_director.json"
    fp = _beat_cache_fingerprint(words, cues)
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("version") == 3 and data.get("fingerprint") == fp:
                cached_beats = data.get("beats") or []
                if cached_beats:
                    logger.info("[BeatDirector] Loaded %d cached beat(s).", len(cached_beats))
                    return cached_beats
        except Exception as exc:
            logger.info("[BeatDirector] Cache read failed (%s) — rebuilding.", exc)

    if progress:
        progress("Visual director: planning beats from audio...", 3)

    beats = _build_beats_from_whisper(words)
    beats = _carve_cue_ranges_from_beats(beats, cues)
    if not beats:
        logger.info("[BeatDirector] No beats survived cue carving — episode is fully cued.")
        return []

    if progress:
        progress(f"Visual director: generating prompts for {len(beats)} beat(s)...", 4)
    prompt_list = _llm_beat_prompts_sync(beats)
    if prompt_list is None:
        logger.info("[BeatDirector] LLM unavailable — using rule-based fallback.")
        prompt_list = [_rule_based_beat_prompt(b["text"]) for b in beats]

    for beat, prompt in zip(beats, prompt_list):
        beat["prompt"] = prompt

    try:
        cache.write_text(
            json.dumps({"version": 3, "fingerprint": fp, "beats": beats}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("[BeatDirector] Could not write cache: %s", exc)

    logger.info("[BeatDirector] Built %d beat(s) with LLM prompts.", len(beats))
    return beats


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
    beat_schedule: list[dict] | None = None,
    max_interval_ms: int = 16_000,
) -> list[dict]:
    """Merge cue intervals + beat intervals into a chronological interval list.

    Each cue becomes an interval with kind='cue' (CogVideoX-eligible). Each
    beat becomes an interval with kind='gap' (SDXL still + Ken-Burns). Beats
    are already cue-carved by the caller, so there's no overlap to resolve.

    When `beat_schedule` is empty (no Whisper word timings, LLM unavailable)
    any audio range not covered by cues is filled with last-resort fallback
    gap intervals derived from the script text — same legacy behavior the
    pipeline had before the beat planner existed.
    """
    intervals: list[dict] = []

    for cue in (visual_cues or []):
        intervals.append({
            "kind": "cue",
            "prompt": cue["prompt"],
            "start_ms": int(cue["start_ms"]),
            "end_ms": int(cue["end_ms"]),
        })

    if beat_schedule:
        for beat in beat_schedule:
            prompt = beat.get("prompt") or _rule_based_beat_prompt(beat.get("text", ""))
            intervals.append({
                "kind": "gap",
                "prompt": prompt,
                "start_ms": int(beat["start_ms"]),
                "end_ms": int(beat["end_ms"]),
            })

    intervals.sort(key=lambda iv: iv["start_ms"])

    # Fill any uncovered audio (leading silence, trailing music tail, or the
    # whole timeline if we got no beats and no cues) with fallback gaps so
    # the bed always spans the full duration.
    filled: list[dict] = []
    cursor = 0
    for iv in intervals:
        if iv["start_ms"] > cursor:
            _emit_fallback_gaps(filled, cursor, iv["start_ms"], script_segments or [], max_interval_ms)
        filled.append(iv)
        cursor = max(cursor, iv["end_ms"])
    if cursor < audio_duration_ms:
        _emit_fallback_gaps(filled, cursor, audio_duration_ms, script_segments or [], max_interval_ms)
    return filled


def _emit_fallback_gaps(
    intervals: list[dict],
    start_ms: int,
    end_ms: int,
    script_segments: list[dict],
    max_interval_ms: int,
) -> None:
    """Cover [start_ms, end_ms] with generic gap intervals.

    Last-resort path used when no beat schedule is available (no Whisper
    word timings, LLM down). Each sub-gap gets a phrase-seeded prompt from
    the script so the bed isn't a single static image for the gap.
    """
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


def _xfade_single_pass(
    clip_paths: list[Path],
    out_path: Path,
    crossfade_ms: int,
    fps: int,
) -> bool:
    """One ffmpeg invocation: xfade-concat the given clips into out_path.

    Caller must keep len(clip_paths) small enough that the resulting
    command line stays under the OS limit (~32 KB on Windows). Use
    `_concat_with_crossfade` for arbitrary-length inputs — it chunks.
    """
    if not clip_paths:
        return False
    if len(clip_paths) == 1:
        shutil.copy(str(clip_paths[0]), str(out_path))
        return True

    xfade_s = crossfade_ms / 1000.0
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

    inputs: list[str] = []
    for p in clip_paths:
        inputs.extend(["-i", str(p)])

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


# Chunk size for batched xfade. 25 inputs keeps the ffmpeg command line
# well under Windows' ~32 KB CreateProcess limit even with long episode
# paths, while staying large enough that a 60-min episode finishes in
# 2 passes (chunks + final stitch). Picked empirically.
_XFADE_CHUNK_SIZE = 25


def _concat_with_crossfade(
    clip_paths: list[Path],
    out_path: Path,
    crossfade_ms: int = VISUAL_CROSSFADE_MS,
    fps: int = VISUAL_KEN_BURNS_FPS,
    *,
    _chunk_size: int = _XFADE_CHUNK_SIZE,
) -> bool:
    """Crossfade-concat clips into out_path, chunking to dodge cmdline limits.

    For long episodes (hundreds of intervals) a single ffmpeg invocation
    with `-i` per clip plus a chained xfade filter exceeds Windows'
    CreateProcess argument-length cap (WinError 206). We stitch in
    batches of `_chunk_size`, then xfade the batch outputs together —
    visually identical because each chunk boundary becomes a normal
    xfade transition between the last frames of chunk N and the first
    frames of chunk N+1.
    """
    if not clip_paths:
        return False
    if len(clip_paths) == 1:
        shutil.copy(str(clip_paths[0]), str(out_path))
        return True
    if len(clip_paths) <= _chunk_size:
        return _xfade_single_pass(clip_paths, out_path, crossfade_ms, fps)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_path.parent / "_xfade_chunks"
    tmp_dir.mkdir(exist_ok=True)
    batch_outputs: list[Path] = []
    try:
        for batch_idx, start in enumerate(range(0, len(clip_paths), _chunk_size)):
            batch = clip_paths[start:start + _chunk_size]
            batch_out = tmp_dir / f"chunk_{batch_idx:03d}.mp4"
            if len(batch) == 1:
                shutil.copy(str(batch[0]), str(batch_out))
            elif not _xfade_single_pass(batch, batch_out, crossfade_ms, fps):
                logger.warning("Batch xfade failed at chunk %d", batch_idx)
                return False
            batch_outputs.append(batch_out)

        # Recurse if the batch count itself is still too large (very long episodes).
        if len(batch_outputs) > _chunk_size:
            return _concat_with_crossfade(
                batch_outputs, out_path, crossfade_ms, fps, _chunk_size=_chunk_size,
            )
        return _xfade_single_pass(batch_outputs, out_path, crossfade_ms, fps)
    finally:
        for p in batch_outputs:
            try:
                p.unlink()
            except Exception:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

import threading as _threading
_BUILD_LOCK = _threading.Lock()


def build_visual_bed(
    audio_path: Path,
    output_dir: Path,
    visual_cues: list[dict] | None = None,
    script_segments: list[dict] | None = None,
    progress: Optional[Callable[[str, int], None]] = None,
    use_cogvideox: bool = False,
) -> Optional[Path]:
    """Build _visual_bed.mp4 spanning the full audio duration.

    `use_cogvideox`: when True, cue intervals get overwritten with
    CogVideoX-5B text-to-video clips (~10-15 min per cue on a 5060 Ti).
    When False (the slideshow default), the bed is SDXL stills only +
    Ken-Burns motion — orders of magnitude faster; a 30-minute episode
    finishes in minutes instead of hours.

    Serialized by a process-wide lock: if a second caller arrives while
    one bed is being built (frontend auto-fire racing a manual click, or
    duplicate /api/generate-video posts), it blocks until the first
    finishes. Two parallel SDXL/CogVideoX pipelines won't fit in 16 GB
    VRAM anyway, and racing on shared backend singletons caused the
    "Cannot copy out of meta tensor" failure observed in the wild.
    """
    if not _BUILD_LOCK.acquire(blocking=False):
        logger.info(
            "build_visual_bed: another build is in progress — waiting for it."
        )
        _BUILD_LOCK.acquire()
    try:
        return _build_visual_bed_impl(
            audio_path, output_dir, visual_cues, script_segments, progress,
            use_cogvideox=use_cogvideox,
        )
    finally:
        _BUILD_LOCK.release()


def _build_visual_bed_impl(
    audio_path: Path,
    output_dir: Path,
    visual_cues: list[dict] | None,
    script_segments: list[dict] | None,
    progress: Optional[Callable[[str, int], None]],
    use_cogvideox: bool = False,
) -> Optional[Path]:
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

    # ── Beat director: ground every gap visual in what's actually being said ──
    # Group Whisper words into ~12 s sentence-aligned beats, then ask the LLM
    # for one cinematic prompt per beat. Beat ms-bounds come straight from
    # Whisper so visuals fire exactly when the words are spoken. Cached to
    # visual_director.json (v2 schema) keyed by whisper-words + cue-range
    # fingerprint, so script-text edits and cue-prompt edits don't
    # invalidate the cache unnecessarily.
    words = _load_whisper_words(output_dir)
    if not words:
        logger.info(
            "No whisper_words.json — beat director disabled, falling back to "
            "phrase-seeded gap prompts. Re-run post-production to enable."
        )
    beat_schedule = _load_or_build_beat_schedule(
        output_dir, words, visual_cues, duration_ms, progress=progress,
    )

    # The director was the last LLM consumer for this episode (script editing
    # via /api/regenerate-segment is a separate request). Free LM Studio's
    # weights now so SDXL + (optionally) CogVideoX get the full 16 GB.
    try:
        from llm_client import unload_model
        unload_model()
    except Exception as exc:
        logger.info("LLM unload before SDXL skipped: %s", exc)

    intervals = _plan_intervals(
        visual_cues,
        duration_ms,
        script_segments=script_segments or [],
        beat_schedule=beat_schedule,
    )
    if not intervals:
        return None
    logger.info(
        "Planned %d visual interval(s) across %.1fs of audio (%d cue, %d beat, beats=%s).",
        len(intervals), duration_ms / 1000,
        sum(1 for iv in intervals if iv["kind"] == "cue"),
        sum(1 for iv in intervals if iv["kind"] == "gap"),
        "on" if beat_schedule else "off",
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

    # ── Pass 2: CogVideoX overwrites cue intervals (when enabled + available). ──
    cue_indices = [i for i, iv in enumerate(intervals) if iv["kind"] == "cue"]
    if cue_indices and not use_cogvideox:
        logger.info(
            "Slideshow mode: skipping CogVideoX for %d cue interval(s) "
            "(SDXL stills + Ken-Burns only).", len(cue_indices),
        )
    if cue_indices and use_cogvideox and _CogVideoXBackend.load():
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
    elif cue_indices and use_cogvideox:
        logger.info(
            "CogVideoX requested but unavailable — falling back to SDXL stills "
            "for %d cue interval(s).", len(cue_indices),
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
