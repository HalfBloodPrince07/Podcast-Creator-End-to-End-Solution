"""
agents/topic_refiner_agent.py — LangGraph node that refines / cleans the raw
user-provided podcast topic before any other stage runs.

Takes a potentially vague, misspelled, or under-specified topic string and
returns a concise, descriptive, podcast-ready topic sentence (≤ 15 words).

Falls back to the original topic string if:
  • dry_run is True (no LLM call)
  • The LLM returns an empty or identical response
  • Any exception occurs
"""
from __future__ import annotations

import re
from typing import Any, Dict

from llm_client import get_client
from utils import get_logger

logger = get_logger("TopicRefinerAgent")

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
You are a podcast producer assistant. Your ONLY job is to refine the topic the
user typed into a clean, engaging, podcast-ready topic sentence.

Rules:
1. Output ONLY the refined topic — no preamble, no quotes, no explanation.
2. Keep it to ≤ 15 words.
3. Expand abbreviations and fix obvious typos.
4. Make it clearly descriptive and interesting for listeners.
5. Do NOT add sub-topics or episode numbers.

Examples:
  Input: "ai"            → Output: The Rise and Future Impact of Artificial Intelligence
  Input: "climate stuff" → Output: Understanding Climate Change and Its Global Consequences
  Input: "wwii battles"  → Output: The Most Decisive Battles of World War II
  Input: "The history of the Roman Empire" → Output: The History and Fall of the Roman Empire
"""

_USER_PROMPT_TEMPLATE = """\
Refine this podcast topic (output ONLY the refined topic, ≤15 words):

{raw_topic}
"""

# Max word count we'll accept before falling back to the original
_MAX_REFINED_WORDS = 20


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------
async def run_topic_refiner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: refine raw topic → write refined_topic + updated episode_title.
    """
    raw_topic: str = state.get("topic", "").strip()

    if not raw_topic:
        logger.warning("Empty topic received — skipping refinement.")
        return {
            "refined_topic": raw_topic,
            "current_status": "Topic Refinement Skipped (empty topic)",
        }

    # Dry-run: skip LLM
    if state.get("dry_run", False):
        logger.info("Dry run — skipping topic refinement LLM call.")
        return {
            "refined_topic": raw_topic,
            "episode_title": raw_topic.title(),
            "current_status": f"Topic Refinement Complete (Dry Run): {raw_topic!r}",
        }

    # --- LLM call ---
    try:
        client = get_client()
        raw_response: str = await client.system_user(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_USER_PROMPT_TEMPLATE.format(raw_topic=raw_topic),
            temperature=0.4,
            max_tokens=60,
        )

        # Sanitise: strip quotes/markdown, collapse whitespace
        refined = re.sub(r"[\"'`*_]", "", raw_response).strip()
        refined = re.sub(r"\s+", " ", refined)

        # Safety checks
        word_count = len(refined.split())
        if not refined or word_count > _MAX_REFINED_WORDS or re.fullmatch(r"[\W\d]+", refined):
            logger.warning(
                "LLM returned unusable refinement (%r). Falling back to raw topic.", refined
            )
            refined = raw_topic

        logger.info("Topic refined: %r -> %r", raw_topic, refined)
        return {
            "refined_topic": refined,
            "episode_title": refined.title(),
            "current_status": f"Topic refined: {refined!r}",
        }

    except Exception as exc:
        logger.error("Topic refinement failed (%s). Using raw topic as fallback.", exc)
        return {
            "refined_topic": raw_topic,
            "episode_title": raw_topic.title(),
            "current_status": f"Topic Refinement Failed (fallback): {raw_topic!r}",
        }
