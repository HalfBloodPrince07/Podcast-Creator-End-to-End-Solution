"""
agents/video_agent.py - Generate a 1920×1080 podcast video with audio-reactive
waveform visualiser and burned-in subtitles. YouTube-ready MP4 output.

Requirements:
  - ffmpeg in PATH  (mandatory)
  - Pillow          (pip install Pillow)  - for styled background
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

# Ensure this module's logger never crashes on Windows cp1252 terminals,
# even when called from background threads that inherit a raw stream handler.
import logging as _logging, io as _io
_va_logger_root = _logging.getLogger("VideoAgent")
for _h in list(_va_logger_root.handlers) + list(_logging.root.handlers):
    if hasattr(_h, "stream") and hasattr(_h.stream, "reconfigure"):
        try:
            _h.stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from utils import get_logger

logger = get_logger("VideoAgent")

# ── Video constants ────────────────────────────────────────────────────────────
W, H = 1920, 1080
FPS = 30
CRF = 18          # quality: lower = better; 18 ≈ visually lossless
PRESET = "medium"

# NVENC (GPU) equivalents
NVENC_PRESET = "p5"     # p1 (fastest) … p7 (best quality); p5 ≈ medium
NVENC_CQ = 20           # constant-quality; ~18 CRF equivalent for NVENC

# Soothing dark-purple palette
BG_TOP   = (13,  13,  26)   # #0d0d1a  deep near-black
BG_MID   = (20,  10,  40)   # #140a28  deep purple
BG_BOT   = (10,  15,  35)   # #0a0f23  dark navy
ACCENT   = (139, 92, 246)   # #8b5cf6  violet
TEXT_CLR = (248, 248, 242)  # #f8f8f2  warm white
DIM_CLR  = (100, 60, 180)   # dimmed purple for labels

# FFmpeg waveform colour — muted violet so screen-blend stays dark on silence
WAVE_CLR1 = "0x7c3aed"   # deep violet (not too bright)


# ── Path helpers ───────────────────────────────────────────────────────────────

def _ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None


def _probe_encoder(encoder: str) -> tuple[bool, str]:
    """Probe whether FFmpeg can actually encode with a given hardware encoder.

    Writes a few frames to a real temporary MP4 — using `-f null` was unreliable
    because some HW encoders open successfully but flush no packets before the
    null muxer closes, producing a false negative.
    Returns (ok, stderr_tail) for diagnostics.
    """
    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=s=256x256:r=10:d=1",
             "-c:v", encoder, "-frames:v", "10",
             tmp.name],
            capture_output=True, timeout=20, text=True, encoding="utf-8", errors="replace",
        )
        ok = r.returncode == 0 and os.path.getsize(tmp.name) > 0
        if ok:
            return True, ""
        return False, (r.stderr or "").strip()[-400:]
    except FileNotFoundError:
        return False, "ffmpeg not in PATH"
    except subprocess.TimeoutExpired:
        return False, "probe timed out"
    except Exception as exc:
        return False, f"probe error: {exc}"
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# Cache the chosen encoder at module level so we probe only once per process.
# Value is one of: "h264_nvenc", "h264_amf", "h264_qsv", or "" (CPU).
_GPU_ENCODER: str | None = None


def _gpu_encoder() -> str:
    """Pick the best available GPU encoder (NVIDIA → AMD → Intel), or "" for CPU.

    Logs each probe failure so the user can see *why* GPU is unavailable
    (e.g. driver missing, FFmpeg built without nvenc, no NVIDIA GPU).
    """
    global _GPU_ENCODER
    if _GPU_ENCODER is not None:
        return _GPU_ENCODER

    for enc, label in (
        ("h264_nvenc", "NVIDIA NVENC"),
        ("h264_amf",   "AMD AMF"),
        ("h264_qsv",   "Intel QuickSync"),
    ):
        ok, err = _probe_encoder(enc)
        if ok:
            logger.info("GPU encoding enabled: %s (%s)", enc, label)
            _GPU_ENCODER = enc
            return _GPU_ENCODER
        logger.info("GPU probe %s failed: %s", enc, err.splitlines()[-1] if err else "no detail")

    logger.info("GPU encoding unavailable — falling back to libx264 (CPU)")
    _GPU_ENCODER = ""
    return _GPU_ENCODER


def _gpu_encode() -> bool:
    """Boolean shim kept for callers that just want to know GPU is available."""
    return bool(_gpu_encoder())


def _esc(path: str) -> str:
    """Escape an absolute path for use inside an FFmpeg -filter_complex string."""
    p = Path(path).as_posix()
    if sys.platform == "win32":
        # Escape drive-letter colon:  C:/foo  -> C\:/foo
        p = re.sub(r"^([A-Za-z]):", r"\1\\:", p)
    p = p.replace("'", "\\'")
    return p


# ── Background image ──────────────────────────────────────────────────────────

def _get_font(size: int, bold: bool = False):
    from PIL import ImageFont
    candidates: list[Path] = []
    if sys.platform == "win32":
        base = Path("C:/Windows/Fonts")
        if bold:
            candidates = [base / "arialbd.ttf", base / "calibrib.ttf", base / "segoeui.ttf"]
        else:
            candidates = [base / "arial.ttf", base / "calibri.ttf", base / "segoeui.ttf"]
    else:
        if bold:
            candidates = [
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
                Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
            ]
        else:
            candidates = [
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
                Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
            ]
    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap(text: str, font, max_px: int, draw) -> list[str]:
    words = text.split()
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        bb = draw.textbbox((0, 0), test, font=font)
        if (bb[2] - bb[0]) > max_px and cur:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines or [""]


def _build_background(title: str, out: Path) -> None:
    """Render a 1920×1080 PNG: gradient background + radial glow + episode title."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    # Three-stop vertical gradient
    stops = [(0, BG_TOP), (H // 2, BG_MID), (H, BG_BOT)]

    def interp(y: int) -> tuple:
        for i in range(len(stops) - 1):
            y0, c0 = stops[i]
            y1, c1 = stops[i + 1]
            if y0 <= y <= y1:
                t = (y - y0) / (y1 - y0)
                return tuple(int(c0[j] + t * (c1[j] - c0[j])) for j in range(3))
        return BG_BOT

    for row in range(H):
        draw.line([(0, row), (W, row)], fill=interp(row))

    # Single-layer subtle glow - one ellipse only (no loop = no alpha accumulation)
    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.ellipse(
        [(W // 2 - 500, H // 3 - 260), (W // 2 + 500, H // 3 + 260)],
        fill=(*ACCENT, 22),
    )
    img = Image.alpha_composite(img.convert("RGBA"), glow_layer).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Separator line above visualiser zone
    sep_y = H - 360
    for x in range(W):
        t = 1 - abs(x - W // 2) / (W // 2)
        a = int(255 * t * 0.45)
        draw.point((x, sep_y), fill=tuple(int(ACCENT[j] * t) for j in range(3)))

    # Subtle dot-grid texture in visualiser area
    for row in range(sep_y + 20, H - 20, 18):
        for col in range(20, W - 20, 18):
            brightness = int(15 + 10 * ((col / W) * (row / H)))
            draw.point((col, row), fill=(brightness, brightness // 2, brightness * 2))

    # ── Typography ────────────────────────────────────────────────────────────
    font_label = _get_font(28, bold=False)
    font_title = _get_font(68, bold=True)

    # "● PODCAST" label
    label = "● PODCAST"
    bb = draw.textbbox((0, 0), label, font=font_label)
    lx = (W - (bb[2] - bb[0])) // 2
    draw.text((lx, 140), label, font=font_label, fill=ACCENT)

    # Episode title (wrapped, centred)
    title_lines = _wrap(title, font_title, W - 240, draw)
    line_h = 86
    total_h = len(title_lines) * line_h
    title_y = 200 + (sep_y - 200 - total_h) // 2

    for i, line in enumerate(title_lines):
        bb = draw.textbbox((0, 0), line, font=font_title)
        tx = (W - (bb[2] - bb[0])) // 2
        ty = title_y + i * line_h
        # Drop-shadow
        draw.text((tx + 3, ty + 3), line, font=font_title, fill=(0, 0, 0))
        draw.text((tx, ty), line, font=font_title, fill=TEXT_CLR)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out), "PNG")
    logger.info("Background saved ->%s", out.name)


def _build_background_fallback(out: Path) -> None:
    """Fallback solid-colour background if Pillow is unavailable."""
    from PIL import Image
    Image.new("RGB", (W, H), BG_TOP).save(str(out), "PNG")


# ── Video render ──────────────────────────────────────────────────────────────

VIS_H = 300          # visualiser band height
VIS_Y = H - VIS_H - 30   # position from top: lower third with small margin


def _video_enc_args(gpu: bool) -> list[str]:
    """Return the encoder flags for the selected encoder (NVENC/AMF/QSV/CPU)."""
    if not gpu:
        return [
            "-c:v", "libx264",
            "-preset", PRESET,
            "-crf", str(CRF),
            "-pix_fmt", "yuv420p",
        ]
    enc = _gpu_encoder()
    if enc == "h264_nvenc":
        return [
            "-c:v", "h264_nvenc",
            "-preset", NVENC_PRESET,
            "-rc", "vbr",
            "-cq", str(NVENC_CQ),
            "-pix_fmt", "yuv420p",
        ]
    if enc == "h264_amf":
        return [
            "-c:v", "h264_amf",
            "-quality", "balanced",
            "-rc", "cqp",
            "-qp_i", "20", "-qp_p", "22",
            "-pix_fmt", "yuv420p",
        ]
    if enc == "h264_qsv":
        return [
            "-c:v", "h264_qsv",
            "-preset", "medium",
            "-global_quality", "22",
            "-pix_fmt", "nv12",
        ]
    # No GPU encoder picked — fall back to CPU args.
    return [
        "-c:v", "libx264",
        "-preset", PRESET,
        "-crf", str(CRF),
        "-pix_fmt", "yuv420p",
    ]


def _render_video(bg_png: Path, audio: Path, out: Path) -> bool:
    """
    Composite background + animated waveform visualiser using FFmpeg.
    Produces a video without burned subtitles.
    Uses GPU (h264_nvenc) when available, falls back to CPU (libx264).
    """
    # Waveform: mode=line draws vertical bars (clean, no area fill).
    # colorkey removes the black background -> RGBA stream.
    # overlay composites the transparent waveform onto the dark background.
    filt = (
        f"[1:a]showwaves=s={W}x{VIS_H}:mode=line"
        f":colors={WAVE_CLR1}:rate={FPS}:scale=sqrt[wraw];"
        "[wraw]split=2[w1][w2];"
        "[w2]gblur=sigma=3[wblur];"
        "[w1][wblur]blend=all_mode=screen[wglow];"
        "[wglow]colorkey=color=black:similarity=0.08:blend=0.0[walpha];"
        f"[0:v][walpha]overlay=0:{VIS_Y}:format=auto[vout]"
    )

    gpu = _gpu_encode()
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(FPS), "-i", str(bg_png),
        "-i", str(audio),
        "-filter_complex", filt,
        "-map", "[vout]", "-map", "1:a",
        *_video_enc_args(gpu),
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out),
    ]
    tag = "GPU" if gpu else "CPU"
    logger.info("FFmpeg render starting (%s)...", tag)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

    # Auto-fallback: if GPU failed, retry on CPU
    if r.returncode != 0 and gpu:
        logger.warning("GPU encode failed — retrying with CPU (libx264)")
        cmd_cpu = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", str(FPS), "-i", str(bg_png),
            "-i", str(audio),
            "-filter_complex", filt,
            "-map", "[vout]", "-map", "1:a",
            *_video_enc_args(False),
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(out),
        ]
        r = subprocess.run(cmd_cpu, capture_output=True, text=True, encoding="utf-8")
        tag = "CPU-fallback"

    if r.returncode != 0:
        logger.error("FFmpeg render failed:\n%s", r.stderr[-3000:])
        return False
    logger.info("FFmpeg render complete (%s) ->%s", tag, out.name)
    return True


def _burn_subs(video: Path, srt: str, out: Path) -> bool:
    """Burn SRT subtitles into the video using FFmpeg libass."""
    # Always use absolute path so FFmpeg can find the file regardless of cwd.
    srt_abs = str(Path(srt).resolve())
    esc_srt = _esc(srt_abs)

    # Commas inside force_style must be escaped as \, so FFmpeg's filter
    # parser doesn't treat them as option separators.
    style = (
        r"FontName=Arial\,FontSize=26\,"
        r"PrimaryColour=&H00FFFFFF\,"
        r"OutlineColour=&H00000000\,"
        r"BackColour=&H90000000\,"
        r"Outline=2\,Shadow=1\,Alignment=2\,MarginV=50"
    )

    # Use explicit `filename=` keyword - bare positional path confuses
    # FFmpeg's filter parser on Windows.
    vf = f"subtitles=filename='{esc_srt}':force_style='{style}'"

    gpu = _gpu_encode()
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-vf", vf,
        *_video_enc_args(gpu),
        "-c:a", "copy",
        str(out),
    ]
    tag = "GPU" if gpu else "CPU"
    logger.info("Burning subtitles (%s)...", tag)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

    # Auto-fallback: if GPU failed, retry on CPU
    if r.returncode != 0 and gpu:
        logger.warning("GPU subtitle burn failed — retrying with CPU")
        cmd_cpu = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-vf", vf,
            *_video_enc_args(False),
            "-c:a", "copy",
            str(out),
        ]
        r = subprocess.run(cmd_cpu, capture_output=True, text=True, encoding="utf-8")
        tag = "CPU-fallback"

    if r.returncode != 0:
        logger.error("Subtitle burn failed:\n%s", r.stderr[-2000:])
        return False
    logger.info("Subtitle burn complete (%s) -> %s", tag, out.name)
    return True


# ── Public API ────────────────────────────────────────────────────────────────

def generate_podcast_video(
    audio_path: str,
    srt_path: str,
    output_dir: Path,
    episode_title: str,
    progress: Optional[Callable[[str, int], None]] = None,
) -> Optional[str]:
    """
    Generate a 1080p podcast video. Returns the output MP4 path or None on failure.

    Steps:
      1. Build styled background PNG (Pillow)
      2. FFmpeg: background + audio ->MP4 with animated waveform
      3. FFmpeg: burn subtitles from SRT
    """
    if not _ffmpeg_ok():
        logger.error("ffmpeg not found in PATH - cannot generate video.")
        return None

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bg_path   = output_dir / "_video_bg.png"
    raw_path  = output_dir / "_video_raw.mp4"
    final_path = output_dir / "episode.mp4"

    # ── Step 1: background ────────────────────────────────────────────────────
    if progress:
        progress("Rendering background...", 10)
    try:
        _build_background(episode_title, bg_path)
    except Exception as exc:
        logger.warning("Pillow background failed (%s) - using solid colour fallback", exc)
        try:
            _build_background_fallback(bg_path)
        except Exception:
            logger.error("Fallback background also failed - aborting")
            return None

    # ── Step 2: video + waveform ──────────────────────────────────────────────
    if progress:
        progress("Compositing video with waveform...", 20)
    if not _render_video(bg_path, Path(audio_path), raw_path):
        _cleanup(bg_path)
        return None

    # ── Step 3: burn subtitles ────────────────────────────────────────────────
    srt = Path(srt_path)
    if srt.exists():
        if progress:
            progress("Burning subtitles...", 85)
        ok = _burn_subs(raw_path, str(srt), final_path)
        if ok:
            _cleanup(raw_path)
        else:
            logger.warning("Subtitle burn failed - delivering video without subtitles")
            _move(raw_path, final_path)
    else:
        logger.warning("SRT not found at %s - skipping subtitle burn", srt)
        _move(raw_path, final_path)

    _cleanup(bg_path)

    if progress:
        progress("Video ready!", 100)
    logger.info("Podcast video ready ->%s", final_path)
    return str(final_path)


def _move(src: Path, dst: Path) -> None:
    """Move src -> dst, overwriting dst if it already exists (needed on Windows)."""
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))


def _cleanup(*paths: Path) -> None:
    for p in paths:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


async def run_video_node(state: dict) -> dict:
    """Optional LangGraph node - generate video after assembly."""
    asm = state.get("final_assembly", {})
    audio_path = asm.get("audio_path")
    srt_path   = asm.get("srt_path", "")
    title      = state.get("episode_title", "Podcast Episode")
    out_dir    = Path(state.get("output_dir", "./outputs/episode"))

    if not audio_path or not Path(audio_path).exists():
        return {"current_status": "Video skipped (no audio)"}

    video_path = await asyncio.to_thread(
        generate_podcast_video, audio_path, srt_path, out_dir, title
    )

    if video_path:
        updated_asm = {**asm, "video_path": video_path}
        return {"current_status": "Video Complete", "final_assembly": updated_asm}
    return {"current_status": "Video generation failed"}
