"""
agents/audio_designer_agent.py — Add prosody markers and music/SFX cue points.
Outputs an "audio-designed" version of the script ready for the TTS agent.
Markers used:
  [PAUSE 500ms]   [PAUSE 1s]   [PAUSE 2s]
  [EMPHASIS]...[/EMPHASIS]
  [CUE: INTRO_MUSIC]  [CUE: CHAPTER_TRANSITION]  [CUE: OUTRO_MUSIC]  [CUE: SFX_WHOOSH]
"""
from __future__ import annotations

import re
from typing import Generator

from config import PipelineConfig
from constants import AUDIO_DESIGNER_TEMPERATURE, CUE_MAP, TRANSITION_CUE
from llm_client import get_client
from utils import get_logger, count_words, async_retry_llm_call, strip_llm_noise

logger = get_logger("AudioDesignerAgent")

PROSODY_SYSTEM_PROMPT = """You are the audio director for a hit podcast. Add prosody markers that make the host \
sound like a real person telling an exciting story — not a robot reading text.

PAUSE RULES:
- [PAUSE 500ms] — after a comma in a list or complex clause; after a rhetorical question.
- [PAUSE 1s]    — BEFORE a surprising fact or key revelation (build anticipation before it lands);
                  at the end of a major idea before moving to the next point.
- [PAUSE 2s]    — only for the single most dramatic moment in the whole segment. Use at most once.

EMPHASIS RULES:
- [EMPHASIS]...[/EMPHASIS] — wrap the 1–3 words with the most emotional or informational weight.
  Prefer: numbers and statistics, contrasting words ("but", "except", "only", "never"),
  and the core topic keyword in each paragraph.
- Maximum 2 EMPHASIS tags per paragraph.
- Never emphasise articles (a, the), pronouns, or filler words.

GENERAL RULES:
- Do NOT change any words. Do NOT remove any text. Only INSERT the markers.
- Do NOT add markers inside quoted text.
- Vary pause lengths — a script where every pause is [PAUSE 1s] sounds robotic.
- Return ONLY the marked-up text, no explanations."""


def _rule_based_markers(text: str) -> str:
    """
    Simple rule-based prosody insertion:
    - [PAUSE 500ms] after sentences that end with '?'
    - [PAUSE 1s] after each paragraph
    - [EMPHASIS] on italicised words (if any) or first word of key statements
    """
    # Paragraph breaks → [PAUSE 1s]
    text = re.sub(r'\n{2,}', '\n[PAUSE 1s]\n', text)

    # Rhetorical questions → 500ms pause after
    text = re.sub(r'(\?)\s+', r'\1 [PAUSE 500ms] ', text)

    # After long sentences (>20 words between full-stops) add 500ms
    def maybe_pause(m: re.Match) -> str:
        sentence = m.group(0)
        if len(sentence.split()) > 20:
            return sentence.rstrip('.!') + '. [PAUSE 500ms] '
        return sentence + ' '

    text = re.sub(r'[^.!?]+[.!?]', maybe_pause, text)

    return text.strip()

def strip_cues(text: str) -> str:
    """Remove all audio markers for clean TTS input if needed."""
    text = re.sub(r'\[PAUSE\s+[\d.]+m?s\]', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\[CUE:[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[/?EMPHASIS\]', '', text, flags=re.IGNORECASE)
    return re.sub(r'\s{2,}', ' ', text).strip()

async def _llm_markers(client, seg_name: str, text: str) -> str:
    # Reasoning models can burn the whole budget inside <think>...</think> on a
    # prompt this short, leaving nothing after stripping. Give a generous floor
    # AND a /no_think hint so non-thinking output is preferred when supported.
    word_count = count_words(text)
    budget = max(2048, word_count * 8)
    try:
        raw = await async_retry_llm_call(
            lambda: client.system_user(
                PROSODY_SYSTEM_PROMPT + "\n\n/no_think",
                f"Add prosody markers to this spoken podcast segment:\n\n{text}",
                temperature=AUDIO_DESIGNER_TEMPERATURE,
                max_tokens=budget,
            ),
            logger_inst=logger,
        )
        cleaned = strip_llm_noise(raw)
        if not cleaned.strip():
            logger.warning("LLM returned empty output for '%s' — using rule-based", seg_name)
            return _rule_based_markers(text)
        return cleaned
    except Exception as exc:
        logger.warning("LLM prosody error in '%s': %s — using rule-based", seg_name, exc)
        return _rule_based_markers(text)

async def run_audio_designer_node(state: dict) -> dict:
    """
    LangGraph node that adds pause/emphasis/cue markers to the script to guide TTS prosody.
    """
    script_segments = state.get("script_segments", [])
    dry_run = state.get("dry_run", False)
    
    client = get_client() if not dry_run else None
    out_segments = []

    for i, seg in enumerate(script_segments):
        seg_name = seg.get("name", f"Segment {i}")
        logger.info("Audio design: %s", seg_name)

        # 1. Prepend music/SFX cue
        cue = CUE_MAP.get(seg_name, TRANSITION_CUE if i > 0 else "")
        prefix = f"{cue}\n" if cue else ""

        # 2. Add prosody markers (LLM or rule-based)
        raw_text = seg.get("text", "")
        # Strip citation markers before LLM processing — prevents the LLM from
        # mangling [SRC-N] into spoken text like "SRC 3"
        text = re.sub(r'\[(?:SRC[-\s]?\d+[,\s]*)+\]', '', raw_text, flags=re.IGNORECASE)
        text = re.sub(r'\s{2,}', ' ', text).strip()
        if dry_run or not client:
            marked_text = _rule_based_markers(text)
        else:
            marked_text = await _llm_markers(client, seg_name, text)

        # Guard against LLM truncation/refusal: if output collapsed, fall back to
        # rule-based markers on the original text so the segment isn't lost.
        original_words = count_words(text)
        marked_words = count_words(marked_text)
        if not marked_text.strip() and text.strip():
            logger.warning("Prosody marking produced empty output for '%s' — keeping original text", seg_name)
            marked_text = _rule_based_markers(text) or text
        elif original_words >= 20 and marked_words < int(original_words * 0.7):
            logger.warning(
                "Prosody output for '%s' dropped %d→%d words — likely truncation; falling back to rule-based.",
                seg_name, original_words, marked_words,
            )
            marked_text = _rule_based_markers(raw_text) or raw_text

        new_seg = dict(seg)
        new_seg["text"] = prefix + marked_text
        out_segments.append(new_seg)

    return {
        "current_status": "Audio Design Complete",
        "script_segments": out_segments
    }


# ---------------------------------------------------------------------------
# Backward-compatible class wrapper (used by tests)
# ---------------------------------------------------------------------------
class AudioDesignerAgent:
    """Class-based wrapper around the functional audio designer node for test compatibility."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.client = get_client() if not cfg.dry_run else None

    @staticmethod
    def _rule_based_markers(text: str) -> str:
        return _rule_based_markers(text)

    @staticmethod
    def strip_cues(text: str) -> str:
        return strip_cues(text)

    def _run_gen(self, script):
        """Synchronous generator yielding status strings then the final Script."""
        from agents.writer_agent import Script as _Script, ScriptSegment
        dry_run = self.cfg.dry_run
        out_segments = []

        for i, seg in enumerate(script.segments):
            seg_name = seg.name
            yield f"Audio designing: {seg_name}"

            cue = CUE_MAP.get(seg_name, TRANSITION_CUE if i > 0 else "")
            prefix = f"{cue}\n" if cue else ""
            text = seg.text

            if dry_run or not self.client:
                marked_text = _rule_based_markers(text)
            else:
                import asyncio
                try:
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            import concurrent.futures
                            with concurrent.futures.ThreadPoolExecutor() as pool:
                                future = pool.submit(asyncio.run, _llm_markers(self.client, seg_name, text))
                                marked_text = future.result()
                        else:
                            marked_text = loop.run_until_complete(_llm_markers(self.client, seg_name, text))
                    except RuntimeError:
                        marked_text = asyncio.run(_llm_markers(self.client, seg_name, text))
                except Exception:
                    marked_text = _rule_based_markers(text)

            new_seg = ScriptSegment(
                name=seg.name,
                target_seconds=seg.target_seconds,
                target_words=seg.target_words,
                text=prefix + marked_text,
                speaker=seg.speaker,
            )
            out_segments.append(new_seg)

        result_script = type(script)(
            episode_title=script.episode_title,
            segments=out_segments,
            sources_used=script.sources_used,
        )
        yield result_script

    def run(self, script):
        """Synchronous run: returns a Script with audio markers applied."""
        items = list(self._run_gen(script))
        # Last item is the Script
        for item in reversed(items):
            if not isinstance(item, str):
                return item
        return script
