"""
agents/thumbnail_agent.py - Generate a 1280x720 YouTube-ready thumbnail PNG
for the episode. Reuses the Pillow font helpers from video_agent.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from utils import get_logger

logger = get_logger("ThumbnailAgent")

# ── Thumbnail constants ───────────────────────────────────────────────────────
W, H = 1280, 720

# Slightly brighter violet palette than the video so the thumbnail pops in
# YouTube's grid (where it's shown at ~320x180 px).
BG_TOP   = (16, 14, 34)     # deep indigo
BG_MID   = (32, 16, 64)     # rich purple
BG_BOT   = (12, 18, 44)     # dark navy
ACCENT_A = (192, 132, 252)  # bright violet for the title glow
ACCENT_B = (139, 92, 246)   # core violet
ACCENT_C = (76, 29, 149)    # deep violet for shadow
TEXT_CLR = (248, 248, 252)  # warm white

LABEL    = "PODCAST"


def _interp(stops: list[tuple[int, tuple[int, int, int]]], y: int) -> tuple[int, int, int]:
    for i in range(len(stops) - 1):
        y0, c0 = stops[i]
        y1, c1 = stops[i + 1]
        if y0 <= y <= y1:
            t = (y - y0) / max(1, (y1 - y0))
            return tuple(int(c0[j] + t * (c1[j] - c0[j])) for j in range(3))
    return stops[-1][1]


def _draw_background(img, draw) -> None:
    """3-stop vertical gradient + a single broad violet glow."""
    from PIL import Image, ImageDraw

    stops = [(0, BG_TOP), (H // 2, BG_MID), (H, BG_BOT)]
    for row in range(H):
        draw.line([(0, row), (W, row)], fill=_interp(stops, row))

    # Soft single-layer glow centred slightly above middle (where the title sits)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse(
        [(W // 2 - 520, H // 2 - 260), (W // 2 + 520, H // 2 + 260)],
        fill=(*ACCENT_A, 38),
    )
    composed = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    img.paste(composed)


def _draw_accent_bar(draw) -> None:
    """Vertical violet bar along the left edge — a clear brand element at glance size."""
    bar_w = 14
    for x in range(bar_w):
        # Gradient from bright top to deep bottom
        t = x / max(1, bar_w - 1)
        col = tuple(int(ACCENT_A[i] + (ACCENT_C[i] - ACCENT_A[i]) * t) for i in range(3))
        draw.line([(x, 0), (x, H)], fill=col)


def _draw_dots_row(draw, y: int) -> None:
    """Subtle row of small accent dots — adds visual rhythm without distraction."""
    spacing = 24
    radius = 3
    start_x = 70
    end_x = W - 70
    for x in range(start_x, end_x, spacing):
        # Fade toward the edges
        dist = abs(x - W // 2) / (W // 2)
        alpha_factor = 1.0 - 0.7 * dist
        col = tuple(int(ACCENT_B[i] * alpha_factor) for i in range(3))
        draw.ellipse([(x - radius, y - radius), (x + radius, y + radius)], fill=col)


def generate_thumbnail(title: str, output_path: Path) -> Optional[str]:
    """
    Render and save a 1280x720 thumbnail. Returns absolute path on success,
    None on failure. Never raises.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow not installed - cannot generate thumbnail.")
        return None

    try:
        # Lazy import so this module doesn't depend on video_agent at import time
        from agents.video_agent import _get_font, _wrap

        img = Image.new("RGB", (W, H))
        draw = ImageDraw.Draw(img)

        _draw_background(img, draw)
        # Re-grab a draw context after the alpha composite paste
        draw = ImageDraw.Draw(img)
        _draw_accent_bar(draw)

        # ── PODCAST label (small, near top) ──────────────────────────────────
        font_label = _get_font(28, bold=False)
        bb = draw.textbbox((0, 0), LABEL, font=font_label)
        label_w = bb[2] - bb[0]
        label_x = (W - label_w) // 2
        # Small accent dot before the label
        dot_r = 6
        dot_x = label_x - 18
        dot_y = 96 + (bb[3] - bb[1]) // 2 - dot_r // 2
        draw.ellipse([(dot_x, dot_y), (dot_x + dot_r * 2, dot_y + dot_r * 2)], fill=ACCENT_A)
        draw.text((label_x, 90), LABEL, font=font_label, fill=ACCENT_A)

        # ── Episode title — large, bold, wrapped, centred ────────────────────
        # Pick a font size that scales down if the title is long
        max_title_w = W - 200
        title_size = 92 if len(title) <= 36 else 76 if len(title) <= 60 else 64
        font_title = _get_font(title_size, bold=True)

        title_lines = _wrap(title, font_title, max_title_w, draw)
        # Cap at 4 lines (ellipsize the rest)
        if len(title_lines) > 4:
            title_lines = title_lines[:4]
            title_lines[-1] = title_lines[-1].rstrip() + "..."

        line_h = int(title_size * 1.18)
        total_h = len(title_lines) * line_h
        # Position block in upper-middle so it doesn't get blocked by YouTube duration overlay
        title_y_start = 180 + (H - 220 - total_h) // 2 - 30

        for i, line in enumerate(title_lines):
            bb = draw.textbbox((0, 0), line, font=font_title)
            line_w = bb[2] - bb[0]
            tx = (W - line_w) // 2
            ty = title_y_start + i * line_h
            # Drop-shadow for legibility on busy thumbnails
            draw.text((tx + 4, ty + 4), line, font=font_title, fill=(0, 0, 0))
            draw.text((tx + 2, ty + 2), line, font=font_title, fill=ACCENT_C)
            draw.text((tx, ty), line, font=font_title, fill=TEXT_CLR)

        # ── Bottom accent: dots row ──────────────────────────────────────────
        _draw_dots_row(draw, H - 60)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "PNG")
        logger.info("Thumbnail saved -> %s (%dx%d)", output_path.name, W, H)
        return str(output_path)
    except Exception as exc:
        logger.warning("Thumbnail generation failed: %s", exc)
        return None
