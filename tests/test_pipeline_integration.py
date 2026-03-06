"""
tests/test_pipeline_integration.py — Integration test for the full pipeline in dry-run mode.
"""
from unittest.mock import patch, MagicMock
import pytest
from pathlib import Path

from config import PipelineConfig
from pipeline import PodcastPipeline, PipelineResult


@pytest.fixture
def cfg(tmp_path):
    return PipelineConfig(
        podcast_topic="Integration Test Topic",
        target_minutes=3,
        dry_run=True,
        output_base_dir=str(tmp_path),
    )


FAKE_RESULTS = [
    {"title": "Source A", "href": "https://example.com/a", "body": "Content for source A."},
    {"title": "Source B", "href": "https://example.com/b", "body": "Content for source B."},
    {"title": "Source C", "href": "https://example.com/c", "body": "Content for source C."},
]


@patch("agents.search_agent.DDGS")
def test_dry_run_pipeline_succeeds(mock_ddgs_cls, cfg):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = FAKE_RESULTS
    mock_ddgs_cls.return_value = mock_ddgs

    pipeline = PodcastPipeline(cfg)
    result = pipeline.run()

    assert isinstance(result, PipelineResult)
    assert result.success
    assert result.error is None


@patch("agents.search_agent.DDGS")
def test_dry_run_pipeline_has_sources(mock_ddgs_cls, cfg):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = FAKE_RESULTS
    mock_ddgs_cls.return_value = mock_ddgs

    result = PodcastPipeline(cfg).run()
    assert len(result.sources) >= 3


@patch("agents.search_agent.DDGS")
def test_dry_run_pipeline_has_script(mock_ddgs_cls, cfg):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = FAKE_RESULTS
    mock_ddgs_cls.return_value = mock_ddgs

    result = PodcastPipeline(cfg).run()
    assert result.script is not None
    assert len(result.script.segments) > 0
    for seg in result.script.segments:
        assert len(seg.text) > 0


@patch("agents.search_agent.DDGS")
def test_dry_run_pipeline_produces_output_files(mock_ddgs_cls, cfg):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = FAKE_RESULTS
    mock_ddgs_cls.return_value = mock_ddgs

    result = PodcastPipeline(cfg).run()
    asm = result.assembly

    # Should have all expected file paths
    assert asm.get("srt_path")
    assert asm.get("txt_path")
    assert asm.get("notes_path")
    assert asm.get("meta_path")

    # Files should actually exist
    assert Path(asm["srt_path"]).exists()
    assert Path(asm["txt_path"]).exists()
    assert Path(asm["notes_path"]).exists()
    assert Path(asm["meta_path"]).exists()


@patch("agents.search_agent.DDGS")
def test_dry_run_pipeline_streaming(mock_ddgs_cls, cfg):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = FAKE_RESULTS
    mock_ddgs_cls.return_value = mock_ddgs

    pipeline = PodcastPipeline(cfg)
    events = list(pipeline.run_streaming())

    # Each event is (stage_key, pct, msg)
    assert len(events) > 0
    for stage_key, pct, msg in events:
        assert isinstance(stage_key, str)
        assert isinstance(pct, (int, float))
        assert isinstance(msg, str)

    # Last event should be "done"
    last_key, last_pct, _ = events[-1]
    assert last_key == "done"
    assert last_pct == 100.0
