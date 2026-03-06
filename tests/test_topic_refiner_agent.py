"""
tests/test_topic_refiner_agent.py — Tests for the TopicRefinerAgent node.
Uses asyncio.run() directly — no pytest-asyncio plugin required.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from agents.topic_refiner_agent import run_topic_refiner_node, _MAX_REFINED_WORDS
from agents.search_agent import _search_limits


def _run(coro):
    """Helper: run an async coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Topic Refiner Node
# ---------------------------------------------------------------------------

def test_topic_refiner_dry_run():
    """Dry-run should skip LLM and return the raw topic unchanged."""
    state = {"topic": "ai", "dry_run": True}
    result = _run(run_topic_refiner_node(state))
    assert result["refined_topic"] == "ai"
    assert "Dry Run" in result["current_status"]


def test_topic_refiner_uses_llm():
    """Normal run should call LLM and store the refined topic."""
    expected = "The Rise and Future Impact of Artificial Intelligence"
    mock_client = MagicMock()
    mock_client.system_user = AsyncMock(return_value=expected)

    with patch("agents.topic_refiner_agent.get_client", return_value=mock_client):
        state = {"topic": "ai", "dry_run": False}
        result = _run(run_topic_refiner_node(state))

    assert result["refined_topic"] == expected
    assert result["episode_title"] == expected.title()


def test_topic_refiner_fallback_on_empty_llm():
    """Empty LLM response → fallback to original topic."""
    mock_client = MagicMock()
    mock_client.system_user = AsyncMock(return_value="")

    with patch("agents.topic_refiner_agent.get_client", return_value=mock_client):
        state = {"topic": "climate stuff", "dry_run": False}
        result = _run(run_topic_refiner_node(state))

    assert result["refined_topic"] == "climate stuff"


def test_topic_refiner_fallback_on_too_long_llm():
    """LLM returning more than _MAX_REFINED_WORDS words → fallback."""
    too_long = " ".join(["word"] * (_MAX_REFINED_WORDS + 5))
    mock_client = MagicMock()
    mock_client.system_user = AsyncMock(return_value=too_long)

    with patch("agents.topic_refiner_agent.get_client", return_value=mock_client):
        state = {"topic": "original topic", "dry_run": False}
        result = _run(run_topic_refiner_node(state))

    assert result["refined_topic"] == "original topic"


def test_topic_refiner_fallback_on_exception():
    """LLM raising an exception → fallback to original topic, no crash."""
    mock_client = MagicMock()
    mock_client.system_user = AsyncMock(side_effect=RuntimeError("LLM offline"))

    with patch("agents.topic_refiner_agent.get_client", return_value=mock_client):
        state = {"topic": "some topic", "dry_run": False}
        result = _run(run_topic_refiner_node(state))

    assert result["refined_topic"] == "some topic"


def test_topic_refiner_empty_topic():
    """Empty topic string → should skip gracefully without error."""
    state = {"topic": "", "dry_run": False}
    result = _run(run_topic_refiner_node(state))
    assert result["refined_topic"] == ""
    assert "Skipped" in result["current_status"]


# ---------------------------------------------------------------------------
# Dynamic Search Limits
# ---------------------------------------------------------------------------

def test_search_limits_short():
    max_r, min_r = _search_limits(3)
    assert max_r == 15
    assert min_r == 8


def test_search_limits_boundary_five():
    max_r, min_r = _search_limits(5)
    assert max_r == 15
    assert min_r == 8


def test_search_limits_medium():
    max_r, min_r = _search_limits(10)
    assert 15 < max_r < 50
    assert 8 < min_r < 20


def test_search_limits_boundary_twenty():
    max_r, min_r = _search_limits(20)
    assert max_r == 50
    assert min_r == 20


def test_search_limits_long():
    max_r, min_r = _search_limits(30)
    assert max_r == 80
    assert min_r == 30


def test_search_limits_monotonic():
    """Search limits should increase monotonically with duration."""
    durations = [3, 5, 10, 15, 20, 25, 30]
    prev_max = 0
    for d in durations:
        max_r, _ = _search_limits(d)
        assert max_r >= prev_max, (
            f"Expected monotonic increase, but {d}min → {max_r} < {prev_max}"
        )
        prev_max = max_r
