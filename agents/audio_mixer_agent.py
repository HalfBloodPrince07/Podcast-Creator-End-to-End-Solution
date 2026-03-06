"""
agents/audio_mixer_agent.py — Post-process TTS audio by inserting sound effects
at [CUE: ...] marker positions.

Maps CUE markers to audio asset files in ./assets/. When an asset file is missing,
falls back to a short silence placeholder so the pipeline never breaks.

Requires pydub (and ffmpeg for MP3 support).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Generator

from config import PipelineConfig
from agents.writer_agent import Script
from utils import get_logger

logger = get_logger("AudioMixerAgent")

ASSETS_DIR = Path("assets")

# Map CUE marker names to asset filenames (place .mp3 files in ./assets/)
CUE_ASSET_MAP = {
    "INTRO_MUSIC": "intro_music.mp3",
    "OUTRO_MUSIC": "outro_music.mp3",
    "CHAPTER_TRANSITION": "transition.mp3",
    "SFX_WHOOSH": "whoosh.mp3",
    "CTA_JINGLE": "cta_jingle.mp3",
}


class AudioMixerAgent:
    """
    Scans the annotated script for [CUE: ...] markers, calculates their timing
    positions, and overlays corresponding audio assets onto the TTS output.
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def run(self, script: Script, tts_result: dict) -> dict:
        """Blocking call — returns updated tts_result with mixed audio path."""
        result = tts_result
        for item in self._run_gen(script, tts_result):
            if isinstance(item, dict):
                result = item
            # else it's a log string, ignore in blocking mode
        return result

    def run_streaming(self, script: Script, tts_result: dict) -> Generator:
        return self._run_gen(script, tts_result)

    def _run_gen(self, script: Script, tts_result: dict) -> Generator:
        audio_path = tts_result.get("audio_path")
        if not audio_path or not Path(audio_path).exists():
            yield "Skipping audio mixing — no audio file to process."
            yield tts_result
            return

        # Check if any assets exist
        available_assets = self._find_available_assets()
        if not available_assets:
            yield "No audio assets found in ./assets/ — skipping mixing. Add .mp3 files to enable."
            yield tts_result
            return

        yield f"Found {len(available_assets)} audio asset(s): {', '.join(available_assets.keys())}"

        try:
            from pydub import AudioSegment
        except ImportError:
            yield "pydub not installed — skipping audio mixing."
            yield tts_result
            return

        # Load main audio
        yield f"Loading main audio: {Path(audio_path).name}..."
        try:
            main_audio = AudioSegment.from_file(audio_path)
        except Exception as e:
            yield f"Failed to load audio: {e}"
            yield tts_result
            return

        # Find CUE markers and their approximate timing positions
        cue_points = self._extract_cue_timing(script)
        yield f"Found {len(cue_points)} CUE marker(s) in script."

        if not cue_points:
            yield tts_result
            return

        # Overlay assets at cue positions
        mixed = main_audio
        applied_count = 0
        for cue_name, position_ms in cue_points:
            asset_file = available_assets.get(cue_name)
            if not asset_file:
                continue

            try:
                asset_audio = AudioSegment.from_file(str(asset_file))
                # Reduce asset volume to mix under speech (-10 dB)
                asset_audio = asset_audio - 10

                # Ensure position is within bounds
                if position_ms >= len(mixed):
                    position_ms = max(0, len(mixed) - len(asset_audio))

                mixed = mixed.overlay(asset_audio, position=position_ms)
                applied_count += 1
                yield f"  Mixed '{cue_name}' at {position_ms / 1000:.1f}s"
            except Exception as e:
                logger.warning("Failed to mix asset '%s': %s", cue_name, e)
                yield f"  Failed to mix '{cue_name}': {e}"

        if applied_count == 0:
            yield "No assets were applied."
            yield tts_result
            return

        # Export mixed audio
        output_path = Path(audio_path).parent / "episode_mixed.mp3"
        try:
            mixed.export(str(output_path), format="mp3", bitrate="192k")
            yield f"Mixed audio saved: {output_path.name} ({applied_count} effects)"
            tts_result["audio_path"] = str(output_path)
            tts_result["mixed"] = True
        except Exception as e:
            yield f"Failed to export mixed audio: {e}"

        yield tts_result

    def _find_available_assets(self) -> dict[str, Path]:
        """Check which CUE assets exist on disk."""
        assets = {}
        for cue_name, filename in CUE_ASSET_MAP.items():
            path = ASSETS_DIR / filename
            if path.exists():
                assets[cue_name] = path
        return assets

    @staticmethod
    def _extract_cue_timing(script: Script) -> list[tuple[str, int]]:
        """
        Extract CUE markers and estimate their position in milliseconds
        based on cumulative word count before each marker.
        """
        cue_pattern = re.compile(r'\[CUE:\s*(\w+)\]')
        cues = []
        cumulative_words = 0
        wpm = 150

        for seg in script.segments:
            text = seg.text
            # Find all CUE markers in this segment
            for match in cue_pattern.finditer(text):
                cue_name = match.group(1)
                # Count words before this marker
                text_before = text[:match.start()]
                words_before = len(text_before.split())
                total_words = cumulative_words + words_before
                # Convert word position to milliseconds
                position_ms = int((total_words / wpm) * 60 * 1000)
                cues.append((cue_name, position_ms))

            # Add this segment's word count to cumulative total
            cumulative_words += seg.actual_words

        return cues
