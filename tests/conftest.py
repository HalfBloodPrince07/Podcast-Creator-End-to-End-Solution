"""
tests/conftest.py — Shared fixtures for all test modules.
"""
import pytest
from config import PipelineConfig
from agents.search_agent import Source
from agents.writer_agent import Script, ScriptSegment


@pytest.fixture
def tmp_config(tmp_path):
    """A PipelineConfig using a temp directory, in dry_run mode."""
    return PipelineConfig(
        podcast_topic="Test Topic",
        target_minutes=3,
        dry_run=True,
        skip_cache=True,
        output_base_dir=str(tmp_path),
    )


@pytest.fixture
def mock_sources():
    """A list of fake Source objects for tests."""
    return [
        Source(
            index=1,
            title="AI Overview",
            publisher="Techcrunch",
            url="https://techcrunch.com/ai",
            date="2025-01-01",
            snippet="AI is transforming industries across the globe.",
        ),
        Source(
            index=2,
            title="Deep Learning Advances",
            publisher="ArXiv",
            url="https://arxiv.org/deep-learning",
            date="2025-02-15",
            snippet="New architectures push the boundaries of deep learning.",
        ),
    ]


@pytest.fixture
def mock_script(mock_sources):
    """A Script with 3 segments and sources."""
    segments = [
        ScriptSegment(
            name="Intro", target_seconds=18, target_words=45,
            text="Welcome to the show! Today we explore AI. [SRC-1]",
        ),
        ScriptSegment(
            name="Chapter 1", target_seconds=120, target_words=300,
            text="AI is changing healthcare, finance, and education rapidly. " * 10,
        ),
        ScriptSegment(
            name="Outro", target_seconds=42, target_words=105,
            text="Thanks for listening. See you next time.",
        ),
    ]
    return Script(
        episode_title="Test Podcast Topic",
        segments=segments,
        sources_used=mock_sources,
    )


@pytest.fixture
def mock_tts_result():
    """Stub TTS result for when audio is not generated."""
    return {"audio_path": None, "tts_text_path": None, "sample_rate": 48000}
