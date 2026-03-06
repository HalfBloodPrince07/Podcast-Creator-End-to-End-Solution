"""
tests/test_tts_agent.py — Tests for the TTS agent LangGraph node.
"""
import pytest
from pathlib import Path

from agents.tts_agent import _clean_for_tts, _chunk_text, _run_tts_sync

@pytest.fixture
def dummy_segments():
    return [
        {
            "name": "Intro",
            "speaker": "host",
            "text": "[CUE: INTRO_MUSIC]\nWelcome [PAUSE 500ms] to the show."
        },
        {
            "name": "Chapter 1",
            "speaker": "guest",
            "text": "Neural networks are [EMPHASIS]fascinating[/EMPHASIS]. They power modern AI. [SRC-1]"
        },
        {
            "name": "Outro",
            "speaker": "host",
            "text": "[CUE: OUTRO_MUSIC]\nThanks for listening."
        },
    ]


def test_clean_for_tts_strips_markers():
    text = "[CUE: INTRO_MUSIC]\nWelcome [PAUSE 500ms] to [EMPHASIS]the show[/EMPHASIS]. [SRC-1]"
    clean = _clean_for_tts(text)
    assert "[CUE:" not in clean
    assert "[PAUSE" not in clean
    assert "[EMPHASIS]" not in clean
    assert "[SRC-" not in clean
    assert "Welcome" in clean
    assert "the show" in clean


def test_chunk_text_short():
    text = "This is a short text."
    chunks = _chunk_text(text, max_chars=100)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_long():
    text = "This is sentence one. This is sentence two. This is sentence three. " * 20
    chunks = _chunk_text(text, max_chars=100)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 150  # some tolerance for sentence boundaries


def test_chunk_text_preserves_content():
    text = "Hello world. Goodbye world."
    chunks = _chunk_text(text, max_chars=100)
    combined = " ".join(chunks)
    assert "Hello" in combined
    assert "Goodbye" in combined


def test_dry_run_skips_synthesis_and_writes_text(tmp_path, dummy_segments):
    output_dir = tmp_path / "episode"
    
    result = _run_tts_sync(
        dry_run=True,
        multi_voice=True,
        output_dir=output_dir,
        segments=dummy_segments,
        backend_name="kokoro"
    )

    assert result["audio_path"] is None
    assert result["tts_text_path"] is not None

    tts_path = Path(result["tts_text_path"])
    assert tts_path.exists()
    content = tts_path.read_text(encoding="utf-8")
    
    # Should contain segment headers
    assert "[Intro]" in content
    assert "[Chapter 1]" in content
    
    # Should be clean (no markers)
    assert "[CUE:" not in content
    assert "[PAUSE" not in content
    assert "[EMPHASIS]" not in content
