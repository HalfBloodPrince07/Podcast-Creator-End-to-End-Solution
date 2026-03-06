"""
tests/test_audio_designer_agent.py — Tests for AudioDesignerAgent
"""
from unittest.mock import patch, MagicMock
import pytest

from config import PipelineConfig
from agents.writer_agent import Script, ScriptSegment
from agents.audio_designer_agent import AudioDesignerAgent


@pytest.fixture
def cfg(tmp_path):
    return PipelineConfig(
        podcast_topic="Space Exploration",
        target_minutes=3,
        dry_run=True,
        output_base_dir=str(tmp_path),
    )


@pytest.fixture
def cfg_live(tmp_path):
    return PipelineConfig(
        podcast_topic="Space Exploration",
        target_minutes=3,
        dry_run=False,
        output_base_dir=str(tmp_path),
    )


@pytest.fixture
def script():
    segments = [
        ScriptSegment(name="Intro", target_seconds=18, target_words=45,
                      text="Welcome to the show. Today we explore space and the future of humanity among the stars."),
        ScriptSegment(name="Chapter 1", target_seconds=120, target_words=300,
                      text="Space exploration has advanced rapidly. What does this mean for us all? The question is profound."),
        ScriptSegment(name="Outro", target_seconds=42, target_words=105,
                      text="Thank you for listening. Until next time."),
    ]
    return Script(episode_title="Space EP", segments=segments, sources_used=[])


def test_dry_run_adds_cue_markers(cfg, script):
    agent = AudioDesignerAgent(cfg)
    result = agent.run(script)
    assert isinstance(result, Script)
    # Intro should have INTRO_MUSIC cue
    assert "[CUE: INTRO_MUSIC]" in result.segments[0].text
    # Outro should have OUTRO_MUSIC cue
    assert "[CUE: OUTRO_MUSIC]" in result.segments[-1].text


def test_dry_run_adds_chapter_transition(cfg, script):
    agent = AudioDesignerAgent(cfg)
    result = agent.run(script)
    # Chapter 1 (index 2) should have CHAPTER_TRANSITION
    assert "[CUE: CHAPTER_TRANSITION]" in result.segments[1].text


def test_rule_based_markers_adds_pauses():
    text = "This is a statement. What about this question? Another idea here. And one more."
    result = AudioDesignerAgent._rule_based_markers(text)
    assert "[PAUSE" in result


def test_rule_based_markers_preserves_text():
    text = "Hello world. This is important."
    result = AudioDesignerAgent._rule_based_markers(text)
    # Original words should still be present
    assert "Hello" in result
    assert "important" in result


def test_strip_cues():
    text = "[CUE: INTRO_MUSIC]\nWelcome [PAUSE 500ms] to [EMPHASIS]the show[/EMPHASIS]."
    clean = AudioDesignerAgent.strip_cues(text)
    assert "[CUE:" not in clean
    assert "[PAUSE" not in clean
    assert "[EMPHASIS]" not in clean
    assert "Welcome" in clean
    assert "the show" in clean


def test_streaming_yields_messages(cfg, script):
    agent = AudioDesignerAgent(cfg)
    items = list(agent._run_gen(script))
    messages = [i for i in items if isinstance(i, str)]
    scripts = [i for i in items if isinstance(i, Script)]
    assert len(messages) >= 3  # at least one per segment
    assert len(scripts) == 1


@patch("agents.audio_designer_agent.get_client")
def test_live_run_uses_llm(mock_get_client, cfg_live, script):
    mock_client = MagicMock()
    mock_client.system_user.return_value = "Welcome [PAUSE 500ms] to the show. [EMPHASIS]Today[/EMPHASIS] we explore."
    mock_get_client.return_value = mock_client

    agent = AudioDesignerAgent(cfg_live)
    agent.client = mock_client
    result = agent.run(script)

    assert isinstance(result, Script)
    assert mock_client.system_user.call_count >= 1


@patch("agents.audio_designer_agent.get_client")
def test_llm_fallback_to_rule_based(mock_get_client, cfg_live, script):
    mock_client = MagicMock()
    mock_client.system_user.side_effect = Exception("LLM unavailable")
    mock_get_client.return_value = mock_client

    agent = AudioDesignerAgent(cfg_live)
    agent.client = mock_client
    result = agent.run(script)

    # Should still produce a script (falls back to rule-based)
    assert isinstance(result, Script)
    # Should have CUE markers from the cue map
    assert "[CUE:" in result.segments[0].text
