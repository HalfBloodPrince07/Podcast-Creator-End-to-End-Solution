"""
config.py — PipelineConfig dataclass for the Podcast Pipeline.
Holds all user inputs and derived values used by every agent.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from constants import (
    DEFAULT_WPM,
    MIN_WPM,
    MAX_WPM,
    TONE_OPTIONS,
    SEGMENT_RATIOS,
    ALLOWED_DURATION_DRIFT,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _slug(text: str) -> str:
    """Convert arbitrary text to a file-system-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:60]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass
class PipelineConfig:
    # --- user-supplied inputs ---
    podcast_topic: str
    target_minutes: int
    tone: str = "conversational"
    audience: str = "general listeners"
    timeline_or_focus: Optional[str] = None      # e.g. "0:Intro,3:AI Origins,8:Outro" or None
    constraints: Optional[str] = None            # e.g. "avoid jargon; must mention FDA"
    target_wpm: int = DEFAULT_WPM
    output_base_dir: str = "./outputs"
    dry_run: bool = False
    skip_cache: bool = False
    multi_voice: bool = False

    # --- derived (auto-computed in __post_init__) ---
    target_words: int = field(init=False)
    output_dir: Path = field(init=False)
    slug: str = field(init=False)
    run_id: str = field(init=False)
    episode_title: str = field(init=False)

    def __post_init__(self) -> None:
        # Clamp wpm to allowed range
        self.target_wpm = max(MIN_WPM, min(MAX_WPM, self.target_wpm))

        # Derived word-count target
        self.target_words = self.target_minutes * self.target_wpm

        # Slug + unique run id
        self.slug = _slug(self.podcast_topic)
        self.run_id = f"{self.slug}_{int(time.time())}"

        # Episode title (can be overridden later by WriterAgent)
        self.episode_title = self.podcast_topic.title()

        # Output directory
        self.output_dir = Path(self.output_base_dir) / self.run_id
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Validate tone
        if self.tone not in TONE_OPTIONS:
            self.tone = "conversational"

    # ------------------------------------------------------------------
    # Segment plan builder
    # ------------------------------------------------------------------
    def build_segment_plan(self, include_mid_cta: bool = False) -> list[dict]:
        """
        Returns an ordered list of segment dicts:
            {name, ratio, target_words, target_seconds}
        Chapters fill the remainder after fixed segments.
        If timeline_or_focus is provided, chapter names are taken from there.
        """
        total_seconds = self.target_minutes * 60

        fixed: dict[str, float] = {
            "Intro": SEGMENT_RATIOS["intro"],
            "Hook":  SEGMENT_RATIOS["hook"],
        }
        if include_mid_cta:
            fixed["Mid-Episode CTA"] = 0.05
        fixed["Outro"] = SEGMENT_RATIOS["outro"]

        fixed_ratio = sum(fixed.values())
        chapter_ratio = 1.0 - fixed_ratio

        # --- parse timeline_or_focus ---
        chapter_names = self._parse_timeline()
        n_chapters = max(1, len(chapter_names)) if chapter_names else max(1, self.target_minutes // 2)
        if not chapter_names:
            chapter_names = [f"Chapter {i+1}" for i in range(n_chapters)]

        per_chapter_ratio = chapter_ratio / n_chapters

        segments: list[dict] = []

        def _add(name: str, ratio: float) -> None:
            secs = total_seconds * ratio
            words = int(self.target_words * ratio)
            segments.append({
                "name": name,
                "ratio": ratio,
                "target_seconds": round(secs),
                "target_words": words,
            })

        _add("Intro", fixed["Intro"])
        _add("Hook", fixed["Hook"])
        for ch in chapter_names:
            _add(ch, per_chapter_ratio)
        if include_mid_cta:
            # insert mid-CTA after roughly half the chapters
            mid = len(segments) // 2
            cta_seg = {
                "name": "Mid-Episode CTA",
                "ratio": 0.05,
                "target_seconds": round(total_seconds * 0.05),
                "target_words": int(self.target_words * 0.05),
            }
            segments.insert(mid, cta_seg)
        _add("Outro", fixed["Outro"])

        return segments

    def _parse_timeline(self) -> list[str]:
        """
        Parse timeline_or_focus like:
            "0:Intro,3:AI Origins,8:Ethics,10:Outro"
        → ["Intro","AI Origins","Ethics","Outro"]
        Or plain comma-separated chapter names.
        Returns [] if None or "open".
        """
        if not self.timeline_or_focus or self.timeline_or_focus.strip().lower() == "open":
            return []
        names = []
        for part in self.timeline_or_focus.split(","):
            part = part.strip()
            if ":" in part:
                # Either "3:Chapter Name" (time:name) or "Chapter:Sub"
                # Try int prefix first
                head, _, tail = part.partition(":")
                if head.strip().isdigit():
                    names.append(tail.strip())
                else:
                    names.append(part)
            elif part:
                names.append(part)
        # Remove Intro/Outro from chapter list (they're in fixed segments)
        return [n for n in names if n.lower() not in ("intro", "outro")]

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------
    def summary(self) -> str:
        lines = [
            f"Topic      : {self.podcast_topic}",
            f"Duration   : {self.target_minutes} min  ({self.target_words} words @ {self.target_wpm} wpm)",
            f"Tone       : {self.tone}",
            f"Audience   : {self.audience}",
            f"Output dir : {self.output_dir}",
            f"Dry run    : {self.dry_run}",
        ]
        if self.constraints:
            lines.append(f"Constraints: {self.constraints}")
        if self.timeline_or_focus:
            lines.append(f"Timeline   : {self.timeline_or_focus}")
        return "\n".join(lines)
