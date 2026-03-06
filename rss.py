"""
rss.py — Generate a valid RSS 2.0 / iTunes podcast feed from episode outputs.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from utils import get_logger

logger = get_logger("RSS")


def generate_feed(
    outputs_dir: Path,
    base_url: str = "",
    title: str = "Podcast Pipeline",
    description: str = "AI-generated podcast episodes",
    author: str = "Podcast Pipeline",
) -> str:
    """
    Scan outputs_dir for episodes with metadata.json and build an RSS 2.0 XML feed.
    base_url should be the public URL root (e.g. http://localhost:8000).
    Returns XML string.
    """
    rss = Element("rss", version="2.0")
    rss.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")

    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = title
    SubElement(channel, "description").text = description
    SubElement(channel, "language").text = "en"
    SubElement(channel, "generator").text = "Podcast Pipeline"
    itunes_author = SubElement(channel, "itunes:author")
    itunes_author.text = author

    episodes = _collect_episodes(outputs_dir)

    for ep in episodes:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = ep.get("episode_title", "Untitled")
        SubElement(item, "description").text = ep.get("podcast_topic", "")

        # Publication date
        generated_at = ep.get("generated_at", "")
        if generated_at:
            try:
                dt = datetime.fromisoformat(generated_at)
                SubElement(item, "pubDate").text = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
            except (ValueError, TypeError):
                pass

        # Audio enclosure
        audio_filename = ep.get("audio_filename")
        rel_path = ep.get("_rel_path", "")
        if audio_filename and rel_path:
            audio_url = f"{base_url}/outputs/{rel_path}/{audio_filename}"
            enc = SubElement(item, "enclosure")
            enc.set("url", audio_url)
            enc.set("type", "audio/mpeg")
            enc.set("length", "0")

        # Duration
        duration = ep.get("duration_hms") or ep.get("duration_seconds")
        if duration:
            itunes_dur = SubElement(item, "itunes:duration")
            itunes_dur.text = str(duration)

        # GUID
        run_id = ep.get("run_id", "")
        if run_id:
            guid = SubElement(item, "guid", isPermaLink="false")
            guid.text = run_id

    xml_bytes = tostring(rss, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}'


def _collect_episodes(outputs_dir: Path) -> list[dict]:
    """Find all metadata.json files and return sorted episode list."""
    episodes = []
    for meta_path in outputs_dir.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            rel = meta_path.parent.relative_to(outputs_dir).as_posix()
            meta["_rel_path"] = rel
            episodes.append(meta)
        except Exception:
            continue
    episodes.sort(key=lambda e: e.get("generated_at", ""), reverse=True)
    return episodes
