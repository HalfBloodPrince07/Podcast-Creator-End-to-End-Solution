"""
tests/test_writer_agent.py — Tests for WriterAgent
"""
from unittest.mock import patch, MagicMock
import pytest

from config import PipelineConfig
from agents.search_agent import Source
from agents.writer_agent import WriterAgent, Script, ScriptSegment


@pytest.fixture
def cfg(tmp_path):
    return PipelineConfig(
        podcast_topic="AI Ethics",
        target_minutes=3,
        dry_run=True,
        output_base_dir=str(tmp_path),
    )


@pytest.fixture
def cfg_live(tmp_path):
    return PipelineConfig(
        podcast_topic="AI Ethics",
        target_minutes=3,
        dry_run=False,
        output_base_dir=str(tmp_path),
    )


@pytest.fixture
def sources():
    return [
        Source(index=1, title="Ethics Paper", publisher="ArXiv", url="https://arxiv.org/1", date="2025", snippet="Ethics in AI."),
    ]


def test_dry_run_produces_script(cfg, sources):
    agent = WriterAgent(cfg)
    script = agent.run(sources)
    assert isinstance(script, Script)
    assert len(script.segments) > 0
    assert all(isinstance(s, ScriptSegment) for s in script.segments)


def test_dry_run_segments_have_text(cfg, sources):
    agent = WriterAgent(cfg)
    script = agent.run(sources)
    for seg in script.segments:
        assert len(seg.text) > 0
        assert seg.actual_words > 0


def test_dry_run_segment_names_include_intro_outro(cfg, sources):
    agent = WriterAgent(cfg)
    script = agent.run(sources)
    names = [s.name for s in script.segments]
    assert "Intro" in names
    assert "Outro" in names


def test_script_segment_speaker_default():
    seg = ScriptSegment(name="Test", target_seconds=30, target_words=50, text="Hello world.")
    assert seg.speaker == "host"


def test_script_segment_estimated_seconds():
    seg = ScriptSegment(name="Test", target_seconds=30, target_words=50, text=" ".join(["word"] * 150))
    assert seg.estimated_seconds > 0
    # 150 words at 150 wpm = 60 seconds
    assert abs(seg.estimated_seconds - 60.0) < 1.0


def test_script_segment_refresh_word_count():
    seg = ScriptSegment(name="Test", target_seconds=30, target_words=50, text="Hello world.")
    assert seg.actual_words == 2
    seg.text = "one two three four five"
    seg.refresh_word_count()
    assert seg.actual_words == 5


def test_script_full_text():
    seg1 = ScriptSegment(name="A", target_seconds=10, target_words=5, text="Hello.")
    seg2 = ScriptSegment(name="B", target_seconds=10, target_words=5, text="World.")
    script = Script(episode_title="T", segments=[seg1, seg2])
    assert script.full_text == "Hello.\n\nWorld."


def test_script_total_actual_words():
    seg1 = ScriptSegment(name="A", target_seconds=10, target_words=5, text="one two three")
    seg2 = ScriptSegment(name="B", target_seconds=10, target_words=5, text="four five")
    script = Script(episode_title="T", segments=[seg1, seg2])
    assert script.total_actual_words == 5


def test_script_to_dict():
    seg = ScriptSegment(name="Intro", target_seconds=10, target_words=5, text="Hello world.")
    script = Script(episode_title="Test EP", segments=[seg], total_target_words=100)
    d = script.to_dict()
    assert d["episode_title"] == "Test EP"
    assert len(d["segments"]) == 1
    assert d["segments"][0]["name"] == "Intro"


def test_format_sources_empty():
    result = WriterAgent._format_sources([])
    assert "No sources" in result


def test_format_sources_with_data(sources):
    result = WriterAgent._format_sources(sources)
    assert "[SRC-1]" in result
    assert "Ethics Paper" in result


def test_dry_run_text():
    text = WriterAgent._dry_run_text("Intro", 50)
    assert len(text.split()) >= 40  # roughly near target


@patch("agents.writer_agent.get_client")
def test_live_run_uses_llm(mock_get_client, cfg_live, sources):
    mock_client = MagicMock()
    mock_client.system_user.return_value = "This is generated segment text from the LLM model."
    mock_get_client.return_value = mock_client

    agent = WriterAgent(cfg_live)
    agent.client = mock_client
    script = agent.run(sources)

    assert isinstance(script, Script)
    assert mock_client.system_user.call_count >= 1  # at least segments + title
