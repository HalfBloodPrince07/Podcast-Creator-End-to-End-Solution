"""
agents/search_agent.py — Web research and source collection.
Uses duckduckgo_search (ddgs) — no API key required.
Returns 3–7 high-quality Source objects covering the podcast topic.
"""
from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass, field
from typing import Generator, Dict, Any, List

from ddgs import DDGS

from config import PipelineConfig
from constants import SEARCH_MAX_RESULTS, SEARCH_MIN_RESULTS, SEARCH_RETRY_DELAYS
from utils import get_logger
import cache

logger = get_logger("SearchAgent")


# ---------------------------------------------------------------------------
# Source model
# ---------------------------------------------------------------------------
@dataclass
class Source:
    title: str
    publisher: str
    url: str
    date: str
    snippet: str
    justification: str = ""
    index: int = 0

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "title": self.title,
            "publisher": self.publisher,
            "url": self.url,
            "date": self.date,
            "snippet": self.snippet,
            "justification": self.justification,
        }

    def citation_line(self) -> str:
        return f"[SRC-{self.index}] {self.title} — {self.publisher} ({self.date}) {self.url}"


# ---------------------------------------------------------------------------
# Node implementation
# ---------------------------------------------------------------------------

MAX_RESULTS = SEARCH_MAX_RESULTS
MIN_RESULTS = SEARCH_MIN_RESULTS
RETRY_DELAYS = SEARCH_RETRY_DELAYS


def _search_limits(target_minutes: int) -> tuple[int, int]:
    """Return (max_results, min_results) scaled to podcast length.

    Short  (≤ 5 min) →  15 max /  8 min
    Medium (6–20 min) → linear ramp up to 50 max / 20 min
    Long   (> 20 min) →  80 max / 30 min
    """
    if target_minutes <= 5:
        return 15, 8
    elif target_minutes <= 20:
        frac = (target_minutes - 5) / 15.0
        return int(15 + frac * 35), int(8 + frac * 12)
    else:
        return 80, 30

def _build_queries(topic: str, audience: str) -> list[str]:
    """Generate diverse search queries to get broad coverage (targets 50+ unique sources)."""
    return [
        f"{topic} overview explained",
        f"{topic} recent developments 2025 2026",
        f"{topic} key facts statistics",
        f"{topic} expert analysis",
        f"{topic} {audience} guide",
        f"{topic} history background context",
        f"{topic} impact consequences effects",
        f"{topic} latest news update",
        f"{topic} opinion commentary",
        f"{topic} timeline events chronology",
    ]

def _extract_publisher(url: str) -> str:
    """Extract domain name as publisher."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc
        return host.lstrip("www.").split(".")[0].capitalize()
    except Exception:
        return "Unknown"

def _search_with_retry(query: str, max_results: int, skip_cache: bool) -> list[dict]:
    """Search with exponential backoff on rate-limit errors."""
    if not skip_cache:
        cached = cache.get(f"search:{query}:{max_results}")
        if cached is not None:
            logger.info("Using cached results for: %s", query[:60])
            return cached

    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            if not skip_cache:
                cache.put(f"search:{query}:{max_results}", results)
            return results
        except Exception as exc:
            err = str(exc).lower()
            if "ratelimit" in err or "202" in err:
                if attempt < len(RETRY_DELAYS):
                    retry_delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else 10
                    logger.warning("Rate-limited, retrying in %ds...", retry_delay)
                    continue
            logger.warning("Search error for '%s': %s", query, exc)
            return []
    return []


async def run_search_node(state: dict) -> dict:
    """
    LangGraph node for web research.
    Uses `refined_topic` if available (set by TopicRefinerAgent), else falls
    back to the raw `topic`.  Search result limits scale with `target_minutes`.
    """
    # Prefer the LLM-refined topic; fall back to raw user input
    topic = (state.get("refined_topic") or state.get("topic", "")).strip()
    audience = state.get("audience", "")
    skip_cache = state.get("skip_cache", False)
    target_minutes: int = state.get("target_minutes", 10)

    # Dynamic limits
    max_results, min_results = _search_limits(target_minutes)
    logger.info(
        "Search limits for %d-min podcast: max=%d, min=%d",
        target_minutes, max_results, min_results,
    )

    if state.get("dry_run", False):
        # Stub the search for dry run
        return {
            "current_status": "Search Complete (Dry Run)",
            "sources": [{"title": "Dry Run Source", "url": "https://example.com", "snippet": "Dry run data.", "publisher": "Example", "date": "2025", "index": 1}]
        }

    queries = _build_queries(topic, audience)
    seen_urls: set[str] = set()
    sources: list[dict] = []
    index = 1

    for q in queries:
        if len(sources) >= max_results:
            break
            
        logger.info("Searching: %s", q)
        # Offload sync search to a thread to avoid blocking the event loop
        results = await asyncio.to_thread(_search_with_retry, q, 12, skip_cache)
        
        for r in results:
            url = r.get("href", r.get("url", ""))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            src = Source(
                index=index,
                title=r.get("title", "Untitled"),
                publisher=_extract_publisher(url),
                url=url,
                date=r.get("published", r.get("date", "n.d.")),
                snippet=(r.get("body", r.get("snippet", "")))[:300],
                justification=f"Relevant to '{topic}'",
            )
            sources.append(src.to_dict())
            index += 1
            if len(sources) >= max_results:
                break

    if len(sources) < min_results:
        logger.warning("Only %d sources found (minimum %d)", len(sources), min_results)

    return {
        "current_status": f"Search Complete. Found {len(sources)} sources.",
        "search_queries": queries,
        "sources": sources,
    }


# ---------------------------------------------------------------------------
# Backward-compatible class wrapper (used by tests)
# ---------------------------------------------------------------------------
class SearchAgent:
    """Class-based wrapper around the functional search node for test compatibility."""

    MAX_RESULTS = MAX_RESULTS
    MIN_RESULTS = MIN_RESULTS

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    @staticmethod
    def _build_queries(topic: str, audience: str) -> list[str]:
        return _build_queries(topic, audience)

    @staticmethod
    def _extract_publisher(url: str) -> str:
        return _extract_publisher(url)

    def _run_gen(self):
        """Synchronous generator that yields status strings then a list of Source objects."""
        topic = self.cfg.podcast_topic
        audience = getattr(self.cfg, "audience", "general listeners")
        skip_cache = getattr(self.cfg, "skip_cache", False)
        target_minutes = getattr(self.cfg, "target_minutes", 10)

        max_results, min_results = _search_limits(target_minutes)
        queries = _build_queries(topic, audience)
        seen_urls: set[str] = set()
        sources: list[Source] = []
        index = 1

        for q in queries:
            if len(sources) >= max_results:
                break
            yield f"Searching: {q}"
            results = _search_with_retry(q, 12, skip_cache)
            for r in results:
                url = r.get("href", r.get("url", ""))
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                src = Source(
                    index=index,
                    title=r.get("title", "Untitled"),
                    publisher=_extract_publisher(url),
                    url=url,
                    date=r.get("published", r.get("date", "n.d.")),
                    snippet=(r.get("body", r.get("snippet", "")))[:300],
                    justification=f"Relevant to '{topic}'",
                )
                sources.append(src)
                index += 1
                if len(sources) >= max_results:
                    break

        if len(sources) < min_results:
            yield f"Warning: Only {len(sources)} sources found (minimum {min_results})"

        yield sources
