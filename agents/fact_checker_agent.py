"""
agents/fact_checker_agent.py — Verify claims and attach citations.
Maps script text to sources, flags contradictions, inserts [SRC-N] markers.
Enforces ≤ 25-word verbatim quote rule.
"""
from __future__ import annotations

import re
from typing import Generator

from config import PipelineConfig
from constants import FACT_CHECKER_TEMPERATURE
from llm_client import get_client
from utils import get_logger, count_words, async_retry_llm_call, strip_llm_noise

logger = get_logger("FactCheckerAgent")


SYSTEM_PROMPT = """You are a rigorous fact-checker for a podcast script. Your job is to:
1. Insert inline citation markers [SRC-N] directly after claims that are supported by the provided sources.
2. If two sources CONTRADICT each other on a claim, add a note in the script: "(Note: sources differ — [SRC-A] says X while [SRC-B] says Y.)"
3. Ensure no verbatim quote in the script exceeds 25 words from a single source. If you find one, shorten it.
4. Return ONLY the revised script text — no commentary, no headers, no JSON.
5. If a claim is not supported by any source, leave it as-is (do not fabricate).
6. Keep all the original wording as close as possible; only add [SRC-N] markers and contradiction notes.

CRITICAL OUTPUT RULES:
- Do NOT write any preamble like "Okay, here is the annotated script..." — start immediately with the first word of the script.
- Do NOT add parenthetical stage directions like (pause), (sound of typing), (chuckles), etc.
- Do NOT add [CUE: ...] markers or any bracketed instructions.
- Output ONLY the spoken script text with [SRC-N] citations inserted inline."""

def _format_sources(sources: list[dict]) -> str:
    lines = []
    for s in sources:
        lines.append(
            f"[SRC-{s.get('index', '?')}] Title: {s.get('title', '')}\n"
            f"  Publisher: {s.get('publisher', '')} | Date: {s.get('date', '')}\n"
            f"  Key content: {s.get('snippet', '')[:300]}"
        )
    return "\n\n".join(lines)

def _add_mock_citations(segments: list[dict], source_count: int) -> list[dict]:
    """In dry-run: sprinkle [SRC-1] markers every N sentences."""
    src_count = max(1, source_count)
    out_segments = []
    for seg in segments:
        text = seg.get("text", "")
        sentences = re.split(r'(?<=[.!?])\s+', text)
        annotated: list[str] = []
        for i, sent in enumerate(sentences):
            annotated.append(sent)
            if i % 3 == 2 and i > 0:
                n = ((i // 3) % src_count) + 1
                annotated[-1] += f" [SRC-{n}]"
        
        new_text = " ".join(annotated)
        new_seg = dict(seg)
        new_seg["text"] = new_text
        new_seg["actual_words"] = count_words(new_text)
        out_segments.append(new_seg)
    return out_segments

async def _check_segment(client, seg_name: str, text: str, sources_block: str) -> str:
    user_prompt = f"""Segment name: {seg_name}

Available sources:
{sources_block}

Script text to annotate:
\"\"\"
{text}
\"\"\"

Return ONLY the annotated script text."""

    return strip_llm_noise(
        await async_retry_llm_call(
            lambda: client.system_user(
                SYSTEM_PROMPT,
                user_prompt,
                temperature=FACT_CHECKER_TEMPERATURE,
                max_tokens=max(512, count_words(text) * 3),
            ),
            logger_inst=logger,
        )
    )

async def run_fact_checker_node(state: dict) -> dict:
    """
    LangGraph node that inserts citations into script segments.
    """
    sources = state.get("sources", [])
    script_segments = state.get("script_segments", [])
    dry_run = state.get("dry_run", False)

    if not sources:
        logger.warning("No sources to fact-check against — skipping citation pass.")
        return {"current_status": "Fact Check Skipped (no sources)"}

    if dry_run:
        logger.info("[Dry run] Skipping LLM fact-check — adding mock citations.")
        annotated_segments = _add_mock_citations(script_segments, len(sources))
        return {
            "current_status": "Fact Check Complete (Dry Run)",
            "script_segments": annotated_segments
        }

    client = get_client()
    sources_block = _format_sources(sources)
    out_segments = []

    for seg in script_segments:
        logger.info("Fact-checking: %s", seg["name"])
        text = seg.get("text", "")
        if not text.strip():
            out_segments.append(seg)
            continue
            
        try:
            annotated = await _check_segment(client, seg["name"], text, sources_block)
            new_seg = dict(seg)
            new_seg["text"] = annotated
            new_seg["actual_words"] = count_words(annotated)
            out_segments.append(new_seg)
        except Exception as exc:
            logger.error("Fact-check error in '%s': %s", seg["name"], exc)
            out_segments.append(seg)

    return {
        "current_status": "Fact Check Complete",
        "script_segments": out_segments
    }


# ---------------------------------------------------------------------------
# Backward-compatible class wrapper (used by tests)
# ---------------------------------------------------------------------------
class FactCheckerAgent:
    """Class-based wrapper around the functional fact checker node for test compatibility."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.client = get_client() if not cfg.dry_run else None

    @staticmethod
    def _format_sources(sources) -> str:
        """Format a list of Source objects or dicts."""
        items = []
        for s in sources:
            d = s.to_dict() if hasattr(s, "to_dict") else s
            items.append(
                f"[SRC-{d.get('index', '?')}] Title: {d.get('title', '')}\n"
                f"  Publisher: {d.get('publisher', '')} | Date: {d.get('date', '')}\n"
                f"  Key content: {d.get('snippet', '')[:300]}"
            )
        return "\n\n".join(items)

    @staticmethod
    def _add_mock_citations(script) -> None:
        """In-place: sprinkle [SRC-N] markers every 3rd sentence into script.segments."""
        sources = script.sources_used
        src_count = max(1, len(sources))
        for seg in script.segments:
            text = seg.text
            sentences = re.split(r'(?<=[.!?])\s+', text)
            annotated: list[str] = []
            for i, sent in enumerate(sentences):
                annotated.append(sent)
                if i % 3 == 2 and i > 0:
                    n = ((i // 3) % src_count) + 1
                    annotated[-1] += f" [SRC-{n}]"
            seg.text = " ".join(annotated)
            seg.refresh_word_count()

    def _run_gen(self, script):
        """Synchronous generator yielding status strings then the final Script."""
        from agents.writer_agent import Script as _Script, ScriptSegment
        sources = script.sources_used
        dry_run = self.cfg.dry_run

        if not sources:
            yield "No sources provided — skipping fact check"
            yield script
            return

        if dry_run:
            import copy
            result_script = copy.deepcopy(script)
            self._add_mock_citations(result_script)
            yield "Fact check complete (dry run — mock citations added)"
            yield result_script
            return

        sources_dicts = [s.to_dict() if hasattr(s, "to_dict") else s for s in sources]
        sources_block = _format_sources(sources_dicts)
        import asyncio, copy
        result_script = copy.deepcopy(script)

        for seg in result_script.segments:
            yield f"Fact-checking: {seg.name}"
            try:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            future = pool.submit(asyncio.run, _check_segment(self.client, seg.name, seg.text, sources_block))
                            seg.text = future.result()
                    else:
                        seg.text = loop.run_until_complete(_check_segment(self.client, seg.name, seg.text, sources_block))
                except RuntimeError:
                    seg.text = asyncio.run(_check_segment(self.client, seg.name, seg.text, sources_block))
                seg.refresh_word_count()
            except Exception as exc:
                yield f"⚠️ Error fact-checking '{seg.name}': {exc}"

        yield result_script

    def run(self, script):
        """Synchronous run: returns a Script with citations inserted."""
        items = list(self._run_gen(script))
        for item in reversed(items):
            if not isinstance(item, str):
                return item
        return script
