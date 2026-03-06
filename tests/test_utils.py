"""
tests/test_utils.py — Unit tests for utils helpers
"""
import pytest
from utils import (
    seconds_to_srt_timestamp,
    seconds_to_hms,
    hms_to_seconds,
    count_words,
    chunk_by_sentences,
    strip_markers,
    highlight_citations_html,
    srt_entries_from_segments,
    build_srt,
)


# ── Timestamp helpers ──────────────────────────────────────────────────────
def test_srt_timestamp_zero():
    assert seconds_to_srt_timestamp(0) == "00:00:00,000"


def test_srt_timestamp_with_millis():
    assert seconds_to_srt_timestamp(61.5) == "00:01:01,500"


def test_srt_timestamp_hours():
    assert seconds_to_srt_timestamp(3661) == "01:01:01,000"


def test_seconds_to_hms():
    assert seconds_to_hms(3661) == "01:01:01"


def test_hms_roundtrip():
    original = 12345.0
    assert abs(hms_to_seconds(seconds_to_hms(original)) - original) < 1


# ── Text helpers ───────────────────────────────────────────────────────────
def test_count_words_basic():
    assert count_words("Hello world foo bar") == 4


def test_count_words_empty():
    assert count_words("") == 0


def test_chunk_by_sentences_small():
    text = "Short text."
    chunks = chunk_by_sentences(text, max_words=100)
    assert len(chunks) == 1
    assert chunks[0] == "Short text."


def test_chunk_by_sentences_splits():
    # Create text that definitely needs splitting: many short sentences
    sentences = ["This is sentence number {}." .format(i) for i in range(40)]
    text = " ".join(sentences)
    chunks = chunk_by_sentences(text, max_words=20)
    assert len(chunks) > 1
    # Each chunk should be reasonably sized (allow up to 2x for boundary cases)
    for c in chunks:
        assert count_words(c) <= 50


# ── Marker stripping ───────────────────────────────────────────────────────
def test_strip_markers_pause():
    text = "Hello [PAUSE 500ms] world."
    assert "[PAUSE" not in strip_markers(text)
    assert "Hello" in strip_markers(text)


def test_strip_markers_cue():
    text = "[CUE: INTRO_MUSIC] Welcome to the show."
    assert "[CUE:" not in strip_markers(text)


def test_strip_markers_citations():
    text = "AI is growing fast [SRC-1] and shows promise [SRC-2]."
    result = strip_markers(text)
    assert "[SRC-" not in result


def test_strip_markers_emphasis():
    text = "This is [EMPHASIS]really important[/EMPHASIS] stuff."
    result = strip_markers(text)
    assert "[EMPHASIS]" not in result
    assert "really important" in result


# ── Citation HTML ──────────────────────────────────────────────────────────
def test_highlight_citations_html_replaces_markers():
    text = "AI is growing [SRC-1] rapidly."
    html = highlight_citations_html(text)
    # The raw marker should be replaced by an HTML span (it may still appear inside the span label)
    assert "<sup>" in html
    assert "<span" in html
    # The bare marker (not inside HTML) should not appear before the tag
    assert "growing [SRC-1]" not in html


# ── SRT generation ─────────────────────────────────────────────────────────
def test_srt_entries_from_segments_basic():
    segments = [
        {"name": "Intro", "duration_s": 30, "text": "Hello world. This is the intro."}
    ]
    entries = srt_entries_from_segments(segments)
    assert len(entries) >= 1
    assert entries[0]["index"] == 1
    assert entries[0]["start_s"] == 0.0


def test_build_srt_format():
    entries = [
        {"index": 1, "start_s": 0.0, "end_s": 5.0, "text": "Hello world"},
        {"index": 2, "start_s": 5.0, "end_s": 10.0, "text": "Second line"},
    ]
    srt = build_srt(entries)
    assert "1\n" in srt
    assert "00:00:00,000 --> 00:00:05,000" in srt
    assert "Hello world" in srt
    assert "2\n" in srt
