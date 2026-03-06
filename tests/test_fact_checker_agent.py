"""
tests/test_fact_checker_agent.py — Tests for FactCheckerAgent
"""
from unittest.mock import patch, MagicMock
import pytest

from config import PipelineConfig
from agents.search_agent import Source
from agents.writer_agent import Script, ScriptSegment
from agents.fact_checker_agent import FactCheckerAgent


@pytest.fixture
def cfg(tmp_path):
    return PipelineConfig(
        podcast_topic="Climate Change",
        target_minutes=3,
        dry_run=True,
        output_base_dir=str(tmp_path),
    )


@pytest.fixture
def cfg_live(tmp_path):
    return PipelineConfig(
        podcast_topic="Climate Change",
        target_minutes=3,
        dry_run=False,
        output_base_dir=str(tmp_path),
    )


@pytest.fixture
def sources():
    return [
        Source(index=1, title="Climate Report", publisher="IPCC", url="https://ipcc.ch/1", date="2025", snippet="Global temps rising."),
        Source(index=2, title="Ocean Study", publisher="Nature", url="https://nature.com/1", date="2025", snippet="Sea levels increase."),
    ]


@pytest.fixture
def script_with_sources(sources):
    segments = [
        ScriptSegment(name="Intro", target_seconds=18, target_words=45,
                      text="Welcome. Today we discuss climate change and its effects."),
        ScriptSegment(name="Chapter 1", target_seconds=120, target_words=300,
                      text="Global temperatures have risen significantly. Sea levels are rising. Experts warn of consequences."),
        ScriptSegment(name="Outro", target_seconds=42, target_words=105,
                      text="Thank you for listening to our deep dive."),
    ]
    return Script(episode_title="Climate EP", segments=segments, sources_used=sources)


@pytest.fixture
def script_no_sources():
    segments = [
        ScriptSegment(name="Intro", target_seconds=18, target_words=45, text="Hello."),
    ]
    return Script(episode_title="No Sources", segments=segments, sources_used=[])


def test_dry_run_adds_mock_citations(cfg, script_with_sources):
    agent = FactCheckerAgent(cfg)
    result = agent.run(script_with_sources)
    assert isinstance(result, Script)
    # At least one segment should have [SRC-N] markers
    all_text = " ".join(s.text for s in result.segments)
    assert "[SRC-" in all_text


def test_no_sources_skips(cfg, script_no_sources):
    agent = FactCheckerAgent(cfg)
    items = list(agent._run_gen(script_no_sources))
    messages = [i for i in items if isinstance(i, str)]
    assert any("No sources" in m for m in messages)
    # Should still yield a script
    scripts = [i for i in items if isinstance(i, Script)]
    assert len(scripts) == 1


def test_format_sources(sources):
    result = FactCheckerAgent._format_sources(sources)
    assert "[SRC-1]" in result
    assert "[SRC-2]" in result
    assert "Climate Report" in result
    assert "Ocean Study" in result


def test_add_mock_citations_every_3rd_sentence(sources):
    segments = [
        ScriptSegment(
            name="Test", target_seconds=60, target_words=100,
            text="First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence. Sixth sentence.",
        ),
    ]
    script = Script(episode_title="T", segments=segments, sources_used=sources)
    FactCheckerAgent._add_mock_citations(script)
    assert "[SRC-" in script.segments[0].text


@patch("agents.fact_checker_agent.get_client")
def test_live_run_calls_llm(mock_get_client, cfg_live, script_with_sources):
    mock_client = MagicMock()
    # Return text with citations added
    mock_client.system_user.return_value = "Global temperatures have risen [SRC-1]. Sea levels are rising [SRC-2]."
    mock_get_client.return_value = mock_client

    agent = FactCheckerAgent(cfg_live)
    agent.client = mock_client
    result = agent.run(script_with_sources)

    assert isinstance(result, Script)
    assert mock_client.system_user.call_count >= 1


@patch("agents.fact_checker_agent.get_client")
def test_llm_error_handled_gracefully(mock_get_client, cfg_live, script_with_sources):
    mock_client = MagicMock()
    mock_client.system_user.side_effect = Exception("LLM timeout")
    mock_get_client.return_value = mock_client

    agent = FactCheckerAgent(cfg_live)
    agent.client = mock_client

    # Should not raise, yields error messages
    items = list(agent._run_gen(script_with_sources))
    messages = [i for i in items if isinstance(i, str)]
    assert any("Error" in m or "⚠️" in m for m in messages)
