"""
tests/test_config.py — Unit tests for PipelineConfig
"""
import pytest
from config import PipelineConfig, MIN_WPM, MAX_WPM, DEFAULT_WPM


def test_default_wpm_and_word_count():
    cfg = PipelineConfig(podcast_topic="AI in medicine", target_minutes=10)
    assert cfg.target_wpm == DEFAULT_WPM
    assert cfg.target_words == 10 * DEFAULT_WPM


def test_wpm_clamped_low():
    cfg = PipelineConfig(podcast_topic="Test", target_minutes=5, target_wpm=100)
    assert cfg.target_wpm == MIN_WPM


def test_wpm_clamped_high():
    cfg = PipelineConfig(podcast_topic="Test", target_minutes=5, target_wpm=200)
    assert cfg.target_wpm == MAX_WPM


def test_word_count_uses_clamped_wpm():
    cfg = PipelineConfig(podcast_topic="Test", target_minutes=3, target_wpm=160)
    assert cfg.target_words == 3 * 160


def test_output_dir_created(tmp_path):
    cfg = PipelineConfig(
        podcast_topic="Test",
        target_minutes=2,
        output_base_dir=str(tmp_path),
    )
    assert cfg.output_dir.exists()


def test_invalid_tone_falls_back():
    cfg = PipelineConfig(podcast_topic="Test", target_minutes=1, tone="gobbledygook")
    assert cfg.tone == "conversational"


def test_segment_plan_sums_to_minutes():
    cfg = PipelineConfig(podcast_topic="Test", target_minutes=10)
    plan = cfg.build_segment_plan()
    total_sec = sum(s["target_seconds"] for s in plan)
    assert abs(total_sec - 10 * 60) <= 10  # within 10 s


def test_segment_plan_with_timeline():
    cfg = PipelineConfig(
        podcast_topic="Test",
        target_minutes=10,
        timeline_or_focus="2:AI Origins,5:Ethics,8:Future",
    )
    plan = cfg.build_segment_plan()
    names = [s["name"] for s in plan]
    assert "AI Origins" in names
    assert "Ethics" in names
    assert "Future" in names


def test_slug_is_filesafe():
    cfg = PipelineConfig(podcast_topic="Hello, World! & More?", target_minutes=1)
    assert " " not in cfg.slug
    assert "!" not in cfg.slug
    assert "&" not in cfg.slug


def test_dry_run_flag():
    cfg = PipelineConfig(podcast_topic="Test", target_minutes=1, dry_run=True)
    assert cfg.dry_run is True
