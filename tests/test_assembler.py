"""
tests/test_assembler.py — Tests for AssemblerAgent output artifacts
"""
import json
import pytest
from pathlib import Path

from config import PipelineConfig
from agents.search_agent import Source
from agents.writer_agent import Script, ScriptSegment
from agents.assembler_agent import AssemblerAgent


@pytest.fixture
def tmp_config(tmp_path):
    cfg = PipelineConfig(
        podcast_topic="Test Podcast Topic",
        target_minutes=3,
        dry_run=True,
        output_base_dir=str(tmp_path),
    )
    return cfg


@pytest.fixture
def mock_script(tmp_config):
    sources = [
        Source(
            index=1,
            title="AI Overview",
            publisher="Techcrunch",
            url="https://techcrunch.com/ai",
            date="2025-01-01",
            snippet="AI is transforming industries.",
        )
    ]
    segments = [
        ScriptSegment(name="Intro", target_seconds=18, target_words=45,
                      text="Welcome to the show! Today we explore AI. [SRC-1]"),
        ScriptSegment(name="Chapter 1", target_seconds=120, target_words=300,
                      text="AI is changing healthcare, finance, and education rapidly. " * 10),
        ScriptSegment(name="Outro", target_seconds=42, target_words=105,
                      text="Thanks for listening. See you next time."),
    ]
    script = Script(
        episode_title="Test Podcast Topic",
        segments=segments,
        sources_used=sources,
    )
    return script


@pytest.fixture
def mock_tts_result():
    return {"audio_path": None, "tts_text_path": None, "sample_rate": 48000}


def test_assembler_creates_srt(tmp_config, mock_script, mock_tts_result):
    agent = AssemblerAgent(tmp_config)
    result = agent.run(mock_script, mock_tts_result)
    srt_path = Path(result["srt_path"])
    assert srt_path.exists()
    content = srt_path.read_text(encoding="utf-8")
    assert "1\n" in content
    assert "-->" in content


def test_assembler_creates_transcript(tmp_config, mock_script, mock_tts_result):
    agent = AssemblerAgent(tmp_config)
    result = agent.run(mock_script, mock_tts_result)
    txt_path = Path(result["txt_path"])
    assert txt_path.exists()
    content = txt_path.read_text(encoding="utf-8")
    assert "Test Podcast Topic" in content
    assert "[00:" in content


def test_assembler_creates_show_notes(tmp_config, mock_script, mock_tts_result):
    agent = AssemblerAgent(tmp_config)
    result = agent.run(mock_script, mock_tts_result)
    notes_path = Path(result["notes_path"])
    assert notes_path.exists()
    content = notes_path.read_text(encoding="utf-8")
    assert "## ⏱️ Key Timestamps" in content
    assert "## 🔗 Sources" in content
    assert "AI Overview" in content


def test_assembler_metadata_schema(tmp_config, mock_script, mock_tts_result):
    agent = AssemblerAgent(tmp_config)
    result = agent.run(mock_script, mock_tts_result)
    meta_path = Path(result["meta_path"])
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    required_keys = [
        "episode_title", "duration_seconds", "duration_hms",
        "target_words", "wpm_used", "file_format",
        "transcript_format", "source_count", "run_id",
    ]
    for key in required_keys:
        assert key in meta, f"Missing metadata key: {key}"


def test_assembler_srt_index_sequential(tmp_config, mock_script, mock_tts_result):
    agent = AssemblerAgent(tmp_config)
    result = agent.run(mock_script, mock_tts_result)
    srt_content = Path(result["srt_path"]).read_text(encoding="utf-8")
    # Extract indices
    import re
    indices = [int(m) for m in re.findall(r'^(\d+)$', srt_content, re.MULTILINE)]
    assert indices == list(range(1, len(indices) + 1)), "SRT indices must be sequential"
