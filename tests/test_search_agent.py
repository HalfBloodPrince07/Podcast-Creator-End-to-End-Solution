"""
tests/test_search_agent.py — Tests for SearchAgent
"""
from unittest.mock import patch, MagicMock
import pytest

from config import PipelineConfig
from agents.search_agent import SearchAgent, Source


@pytest.fixture
def cfg(tmp_path):
    return PipelineConfig(
        podcast_topic="quantum computing",
        target_minutes=5,
        dry_run=True,
        skip_cache=True,
        output_base_dir=str(tmp_path),
    )


FAKE_RESULTS = [
    {"title": "Quantum 101", "href": "https://example.com/q1", "body": "Intro to quantum."},
    {"title": "Quantum Advances", "href": "https://example.com/q2", "body": "Recent progress."},
    {"title": "Quantum Ethics", "href": "https://example.com/q3", "body": "Ethical concerns."},
]


def test_build_queries(cfg):
    agent = SearchAgent(cfg)
    queries = agent._build_queries("quantum computing", "general listeners")
    assert len(queries) >= 5
    assert all("quantum computing" in q for q in queries)


def test_extract_publisher():
    assert SearchAgent._extract_publisher("https://www.techcrunch.com/article") == "Techcrunch"
    assert SearchAgent._extract_publisher("https://arxiv.org/abs/123") == "Arxiv"
    # Invalid URL returns empty string or "Unknown" depending on urlparse behavior
    result = SearchAgent._extract_publisher("not-a-url")
    assert isinstance(result, str)


@patch("agents.search_agent.DDGS")
def test_run_gen_collects_sources(mock_ddgs_cls, cfg):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = FAKE_RESULTS
    mock_ddgs_cls.return_value = mock_ddgs

    agent = SearchAgent(cfg)
    items = list(agent._run_gen())
    # Last item should be a list of Sources
    sources = items[-1]
    assert isinstance(sources, list)
    assert all(isinstance(s, Source) for s in sources)
    assert len(sources) >= 3


@patch("agents.search_agent.DDGS")
def test_deduplicates_urls(mock_ddgs_cls, cfg):
    dup_results = [
        {"title": "A", "href": "https://example.com/same", "body": "Text A."},
        {"title": "B", "href": "https://example.com/same", "body": "Text B."},
        {"title": "C", "href": "https://example.com/other", "body": "Text C."},
    ]
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = dup_results
    mock_ddgs_cls.return_value = mock_ddgs

    agent = SearchAgent(cfg)
    items = list(agent._run_gen())
    sources = items[-1]
    urls = [s.url for s in sources]
    assert len(urls) == len(set(urls)), "URLs should be deduplicated"


@patch("agents.search_agent.DDGS")
def test_respects_max_results(mock_ddgs_cls, cfg):
    many_results = [
        {"title": f"Result {i}", "href": f"https://example.com/{i}", "body": f"Text {i}."}
        for i in range(20)
    ]
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = many_results
    mock_ddgs_cls.return_value = mock_ddgs

    agent = SearchAgent(cfg)
    items = list(agent._run_gen())
    sources = items[-1]
    assert len(sources) <= agent.MAX_RESULTS


@patch("agents.search_agent.DDGS")
def test_warns_on_few_sources(mock_ddgs_cls, cfg):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = [
        {"title": "Only one", "href": "https://example.com/1", "body": "Lonely."}
    ]
    mock_ddgs_cls.return_value = mock_ddgs

    agent = SearchAgent(cfg)
    items = list(agent._run_gen())
    messages = [i for i in items if isinstance(i, str)]
    assert any("Only" in m and "sources found" in m for m in messages)


def test_source_to_dict():
    src = Source(index=1, title="Test", publisher="Pub", url="https://x.com", date="2025", snippet="Snip")
    d = src.to_dict()
    assert d["index"] == 1
    assert d["title"] == "Test"
    assert d["url"] == "https://x.com"


def test_source_citation_line():
    src = Source(index=3, title="My Article", publisher="News", url="https://news.com", date="2025", snippet="Summary.")
    line = src.citation_line()
    assert "[SRC-3]" in line
    assert "My Article" in line
