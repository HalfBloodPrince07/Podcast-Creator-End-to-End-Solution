"""
agents/assembler_agent.py — Package all outputs into final episode artifacts.
Generates: SRT, timestamped plain-text transcript, show_notes.md, metadata.json
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from config import PipelineConfig
from agents.search_agent import Source
from utils import (
    get_logger,
    save_text,
    save_json,
    seconds_to_hms,
    seconds_to_srt_timestamp,
    srt_entries_from_segments,
    srt_entries_from_whisper,
    build_srt,
    count_words,
    highlight_citations_html,
)

logger = get_logger("AssemblerAgent")


# ------------------------------------------------------------------
# Transcript builders
# ------------------------------------------------------------------
def _build_plain_transcript(state: dict, cfg: PipelineConfig, entries: list[dict]) -> str:
    """Plain text with [HH:MM:SS] markers every entry."""
    lines = [
        f"# {state.get('episode_title', 'Untitled Episode')}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Topic: {cfg.podcast_topic}",
        f"Duration: ~{cfg.target_minutes} min | WPM: {cfg.target_wpm}",
        "=" * 60,
        "",
    ]
    for entry in entries:
        ts = seconds_to_hms(entry["start_s"])
        lines.append(f"[{ts}] {entry['text']}")
        lines.append("")
        
    sources = state.get("sources", [])
    if sources:
        lines.append("")
        lines.append("— SOURCES —")
        for s in sources:
            # Recreate citation line from dict
            idx = s.get("index", "?")
            url = s.get("url", "")
            title = s.get("title", "Untitled")
            lines.append(f"[SRC-{idx}] {url} | {title}")
    return "\n".join(lines)

def _build_html_transcript(segments: list[dict]) -> str:
    """HTML version with coloured citations for Gradio display."""
    parts = []
    cursor = 0.0
    for seg in segments:
        text = seg.get("text", "")
        html_text = highlight_citations_html(text)
        ts = seconds_to_hms(cursor)
        
        target_s = seg.get("target_seconds", 0)
        seg_name = seg.get("name", "Segment")
        
        parts.append(
            f'<div class="segment">'
            f'<h3 class="seg-title">[{ts}] {seg_name}</h3>'
            f'<p class="seg-text">{html_text}</p>'
            f'</div>'
        )
        cursor += target_s
    return "\n".join(parts)

# ------------------------------------------------------------------
# Show notes
# ------------------------------------------------------------------
def _build_show_notes(state: dict, cfg: PipelineConfig, tts_result: dict) -> str:
    audio_path = tts_result.get("audio_path")
    audio_filename = Path(audio_path).name if audio_path else "episode_tts_ready.txt"
    segments = state.get("script_segments", [])
    sources = state.get("sources", [])

    lines = [
        f"# 🎙️ {state.get('episode_title', 'Untitled Episode')}",
        "",
        f"**Topic:** {cfg.podcast_topic}",
        f"**Duration:** ~{cfg.target_minutes} minutes",
        f"**Tone:** {cfg.tone.capitalize()}",
        f"**Audience:** {cfg.audience}",
        f"**Host:** [Your Name Here]",
        f"**Date:** {datetime.now().strftime('%B %d, %Y')}",
        "",
        "---",
        "",
        "## 📝 Description",
        "",
        f"> An in-depth {cfg.tone} exploration of **{cfg.podcast_topic}** for {cfg.audience}. "
        f"This episode covers the key concepts, recent developments, and key takeaways.",
        "",
        "---",
        "",
        "## ⏱️ Key Timestamps",
        "",
    ]
    cursor = 0.0
    for seg in segments:
        ts = seconds_to_hms(cursor)
        lines.append(f"- `{ts}` — **{seg.get('name', 'Segment')}**")
        cursor += seg.get("target_seconds", 0)

    lines += [
        "",
        "---",
        "",
        "## 📥 Downloads",
        "",
        f"- 🎵 **Audio:** `{audio_filename}`",
        f"- 📄 **Transcript (SRT):** `transcript.srt`",
        f"- 📃 **Transcript (TXT):** `transcript.txt`",
        "",
        "---",
        "",
        "## 🔗 Sources",
        "",
    ]
    
    for s in sources:
        idx = s.get("index", "?")
        title = s.get("title", "Untitled")
        url = s.get("url", "")
        pub = s.get("publisher", "")
        date = s.get("date", "")
        snippet = s.get("snippet", "")
        
        lines.append(f"**[SRC-{idx}]** [{title}]({url})")
        if pub or date:
            lines.append(f"  *{pub}, {date}*")
        if snippet:
            lines.append(f"  > {snippet[:150]}…")
        lines.append("")

    if not sources:
        lines.append("_No external sources used in this episode._")

    lines += [
        "---",
        "",
        f"*Produced by Podcast Pipeline  •  {datetime.now().year}*",
    ]
    return "\n".join(lines)

# ------------------------------------------------------------------
# Metadata
# ------------------------------------------------------------------
def _build_metadata(
    state: dict,
    cfg: PipelineConfig,
    tts_result: dict,
    duration_s: float,
    srt_path: Path,
    txt_path: Path,
    notes_path: Path,
) -> dict:
    audio_path = tts_result.get("audio_path")
    sample_rate = tts_result.get("sample_rate", 48000)
    segments = state.get("script_segments", [])
    total_words = sum(s.get("actual_words", 0) for s in segments)

    return {
        "episode_title":     state.get("episode_title"),
        "podcast_topic":     cfg.podcast_topic,
        "tone":              cfg.tone,
        "audience":          cfg.audience,
        "generated_at":      datetime.now().isoformat(),

        # Duration
        "target_minutes":    cfg.target_minutes,
        "duration_seconds":  round(duration_s, 1),
        "duration_hms":      seconds_to_hms(duration_s),
        "drift_pct":         round(abs(duration_s - cfg.target_minutes * 60) / max(cfg.target_minutes * 60, 1) * 100, 1),

        # Words
        "target_words":      cfg.target_words,
        "actual_words":      total_words,
        "wpm_used":          cfg.target_wpm,

        # Audio
        "file_format":       "mp3" if (audio_path and audio_path.endswith(".mp3")) else ("wav" if audio_path else "none"),
        "bitrate":           "192k" if audio_path else None,
        "sample_rate":       sample_rate,
        "audio_filename":    Path(audio_path).name if audio_path else None,

        # Transcripts
        "transcript_format": ["srt", "txt"],
        "srt_filename":      srt_path.name,
        "txt_filename":      txt_path.name,
        "show_notes_file":   notes_path.name,

        # Sources
        "source_count":      len(state.get("sources", [])),
        "sources":           state.get("sources", []),

        # Full segment payloads — needed for per-segment regenerate
        "segments":          segments,
        "narrative_arc":     state.get("narrative_arc", ""),

        # Original generation knobs for regenerate
        "tts_backend":       state.get("tts_backend"),
        "voice_gender":      state.get("voice_gender"),
        "voice_id":          state.get("voice_id"),

        # Output
        "output_dir":        str(cfg.output_dir),
        "run_id":            cfg.run_id,
        "dry_run":           cfg.dry_run,
    }

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _get_audio_duration(audio_path: Optional[str]) -> Optional[float]:
    """Return audio duration in seconds using pydub, or None."""
    if not audio_path or not Path(audio_path).exists():
        return None
    try:
        from pydub import AudioSegment
        seg = AudioSegment.from_file(audio_path)
        return len(seg) / 1000.0
    except Exception:
        return None

async def run_assembler_node(state: dict) -> dict:
    """
    LangGraph node that packages the final episode: SRT, transcript, show notes, metadata JSON.
    """
    import asyncio

    # Use the shared output directory that was set once by app.py
    out = Path(state.get("output_dir", "./outputs/episode"))
    out.mkdir(parents=True, exist_ok=True)

    # Build a minimal cfg just for metadata/transcript helpers (no new directory created)
    cfg = PipelineConfig(
        podcast_topic=state.get("topic", "Untitled_Podcast"),
        tone=state.get("tone", "conversational"),
        audience=state.get("audience", "general listeners"),
        target_minutes=max(1, state.get("target_minutes", 5)),
        dry_run=state.get("dry_run", False),
        multi_voice=state.get("multi_voice", False),
        output_base_dir=str(out.parent),   # keeps cfg.output_dir from creating a new folder
    )
    # Override output_dir to point at the already-created folder
    cfg.output_dir = out

    segments = state.get("script_segments", [])
    tts_result = state.get("tts_results", {})

    logger.info("Generating SRT transcript...")
    whisper_words = state.get("whisper_words") or []
    if whisper_words:
        logger.info("Using Whisper word-level timings (%d words)", len(whisper_words))
        srt_entries = srt_entries_from_whisper(whisper_words)
    else:
        logger.info("Whisper timings unavailable — using estimated segment timings")
        srt_entries = srt_entries_from_segments(segments)
    srt_content = build_srt(srt_entries)
    
    # Delegate file writing to a thread
    def _write_files():
        srt_path = save_text(out / "transcript.srt", srt_content)

        txt_content = _build_plain_transcript(state, cfg, srt_entries)
        txt_path = save_text(out / "transcript.txt", txt_content)

        show_notes = _build_show_notes(state, cfg, tts_result)
        notes_path = save_text(out / "show_notes.md", show_notes)

        audio_path = tts_result.get("audio_path")
        duration_s = _get_audio_duration(audio_path) or sum(
            s.get("target_seconds", 0) for s in segments
        )

        # YouTube-ready thumbnail (graceful failure if Pillow missing)
        from agents.thumbnail_agent import generate_thumbnail
        title = state.get("episode_title") or cfg.episode_title
        thumb_path = generate_thumbnail(title, out / "thumbnail.png")

        metadata = _build_metadata(state, cfg, tts_result, duration_s, srt_path, txt_path, notes_path)
        if thumb_path:
            metadata["thumbnail_path"] = thumb_path
        meta_path = save_json(out / "metadata.json", metadata)

        html_content = _build_html_transcript(segments)
        html_path = save_text(out / "transcript.html", html_content)

        return {
            "output_dir":     str(out),
            "audio_path":     audio_path,
            "srt_path":       str(srt_path),
            "txt_path":       str(txt_path),
            "notes_path":     str(notes_path),
            "meta_path":      str(meta_path),
            "html_path":      str(html_path),
            "thumbnail_path": thumb_path,
            "tts_text_path":  tts_result.get("tts_text_path"),
            "metadata":       metadata,
        }

    results = await asyncio.to_thread(_write_files)
    logger.info("Assembly complete!")

    return {
        "current_status": "Assembly Complete",
        "final_assembly": results
    }


# ---------------------------------------------------------------------------
# Backward-compatible class wrapper (used by tests)
# ---------------------------------------------------------------------------
class AssemblerAgent:
    """Class-based wrapper around the functional assembler node for test compatibility."""

    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg

    def run(self, script, tts_result: dict) -> dict:
        """
        Synchronous run: builds SRT, transcript, show notes, metadata.
        Returns a dict with srt_path, txt_path, notes_path, meta_path, etc.
        """
        import asyncio

        # Build the state dict the assembler node expects
        segments = [seg.to_dict() if hasattr(seg, "to_dict") else seg for seg in script.segments]
        sources = [s.to_dict() if hasattr(s, "to_dict") else s for s in script.sources_used]

        state = {
            "topic": self.cfg.podcast_topic,
            "tone": getattr(self.cfg, "tone", "conversational"),
            "audience": getattr(self.cfg, "audience", "general listeners"),
            "target_minutes": getattr(self.cfg, "target_minutes", 5),
            "dry_run": self.cfg.dry_run,
            "multi_voice": getattr(self.cfg, "multi_voice", False),
            "episode_title": script.episode_title,
            "script_segments": segments,
            "sources": sources,
            "tts_results": tts_result,
            "output_dir": str(getattr(self.cfg, "output_dir", "./outputs/episode")),
        }

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, run_assembler_node(state))
                    result = future.result()
            else:
                result = loop.run_until_complete(run_assembler_node(state))
        except RuntimeError:
            result = asyncio.run(run_assembler_node(state))

        return result.get("final_assembly", result)

    def _run_gen(self, script, tts_result: dict):
        """Synchronous generator yielding status strings then the final assembly dict."""
        yield "Assembling episode artifacts..."
        assembly = self.run(script, tts_result)
        yield assembly
