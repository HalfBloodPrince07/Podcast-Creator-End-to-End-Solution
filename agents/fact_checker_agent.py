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
from utils import get_logger, count_words, async_retry_llm_call, strip_llm_noise, make_error_record

logger = get_logger("FactCheckerAgent")


SYSTEM_PROMPT = """You are a rigorous fact-checker for a podcast script. Your job has TWO parts.

PART 1 — Inline citations:
- Insert [SRC-N] markers directly after claims that are supported by the provided sources.
- If two sources CONTRADICT on a claim, add: "(Note: sources differ — [SRC-A] says X while [SRC-B] says Y.)"
- Ensure no verbatim quote exceeds 25 words from a single source. Shorten if needed.
- Keep original wording as close as possible; only add markers/notes.
- If a specific factual claim has NO source support, leave the wording AS-IS for now (do not fabricate citations).

PART 2 — Flag unsupported factual claims:
- After the annotated script, output a separator line exactly: ---FLAGGED---
- Below the separator, list each FACTUAL CLAIM (specific numbers, dates, names, events) that
  appears in the script but is NOT supported by any provided source, one per line as a bullet "- ".
- Quote the offending sentence verbatim (one sentence max per bullet).
- If every factual claim is supported, write a single bullet "- NONE" after the separator.
- DO NOT flag opinions, rhetorical questions, transitions, or general framing — only verifiable facts.

CRITICAL OUTPUT RULES:
- Start IMMEDIATELY with the first word of the script. No preamble.
- No stage directions, no [CUE:] markers, no markdown headers.
- The ---FLAGGED--- separator and the bullet list MUST appear at the very end of your output."""

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

def _parse_annotated_output(raw: str) -> tuple[str, list[str]]:
    """
    Split fact-checker output into (annotated_script, flagged_claims).
    Looks for the ---FLAGGED--- separator. If absent, returns (raw, []).
    """
    sep_match = re.search(r"-{2,}\s*FLAGGED\s*-{2,}", raw, re.IGNORECASE)
    if not sep_match:
        return raw.strip(), []

    script_part = raw[:sep_match.start()].strip()
    flagged_part = raw[sep_match.end():].strip()

    flagged: list[str] = []
    for line in flagged_part.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip bullet markers and quotes
        line = re.sub(r"^[-*•]\s*", "", line)
        line = line.strip(' "\'')
        if not line or line.upper() == "NONE":
            continue
        flagged.append(line)

    return script_part, flagged


async def _check_segment(client, seg_name: str, text: str, sources_block: str) -> tuple[str, list[str]]:
    """Returns (annotated_text, flagged_unsupported_claims).

    If the LLM returns empty or substantially-shorter output (truncation, refusal,
    or model only echoing the FLAGGED block), the original text is preserved so
    downstream stages don't operate on a wiped segment.
    """
    user_prompt = f"""Segment name: {seg_name}

Available sources:
{sources_block}

Script text to annotate:
\"\"\"
{text}
\"\"\"

Return the annotated script followed by the ---FLAGGED--- block. Nothing else."""

    raw = await async_retry_llm_call(
        lambda: client.system_user(
            SYSTEM_PROMPT,
            user_prompt,
            temperature=FACT_CHECKER_TEMPERATURE,
            # Floor 4000 leaves room for thinking models to reason before
            # emitting the annotated script + FLAGGED block. The 800 floor
            # was sized for non-thinking models and would starve Gemma-4.
            max_tokens=max(10000, count_words(text) * 4),
        ),
        logger_inst=logger,
    )
    cleaned = strip_llm_noise(raw)
    annotated, flagged = _parse_annotated_output(cleaned)

    original_words = count_words(text)
    annotated_words = count_words(annotated)
    if original_words >= 20 and annotated_words < int(original_words * 0.5):
        logger.warning(
            "[%s] Fact-checker output dropped %d→%d words — likely truncation/refusal; keeping original text.",
            seg_name, original_words, annotated_words,
        )
        return text, flagged

    return annotated, flagged

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
    total_flagged = 0
    total_revised = 0

    # Lazy-import the writer's revision helper to avoid circular import at module load
    from agents.writer_agent import revise_segment_text

    for seg in script_segments:
        logger.info("Fact-checking: %s", seg["name"])
        text = seg.get("text", "")
        if not text.strip():
            out_segments.append(seg)
            continue

        try:
            annotated, flagged = await _check_segment(client, seg["name"], text, sources_block)
            if flagged:
                total_flagged += len(flagged)
                logger.warning(
                    "[%s] %d unsupported claim(s) flagged — running revision pass:",
                    seg["name"], len(flagged),
                )
                for f in flagged:
                    logger.warning("  - %s", f[:120])

                # Single revision pass
                target_words = int(seg.get("target_words") or count_words(text))
                revised = await revise_segment_text(
                    client, seg["name"], text, flagged, sources_block, target_words,
                )
                # Re-cite the revised text (single pass, even if it surfaces new flags)
                re_annotated, re_flagged = await _check_segment(
                    client, seg["name"], revised, sources_block,
                )
                annotated = re_annotated
                total_revised += 1
                if re_flagged:
                    logger.warning(
                        "[%s] %d claim(s) still flagged after revision; accepting as-is.",
                        seg["name"], len(re_flagged),
                    )

            new_seg = dict(seg)
            new_seg["text"] = annotated
            new_seg["actual_words"] = count_words(annotated)
            new_seg["flagged_after_check"] = flagged if not flagged else []
            out_segments.append(new_seg)
        except Exception as exc:
            logger.error("Fact-check error in '%s': %s", seg["name"], exc)
            out_segments.append(seg)

    logger.info(
        "Fact check summary: %d total flagged, %d segments revised.",
        total_flagged, total_revised,
    )

    errors: list[dict] = []
    if total_flagged:
        errors.append(make_error_record(
            "fact_check",
            f"{total_flagged} unsupported claim(s) flagged; {total_revised} segment(s) revised",
            "info" if total_revised == total_flagged else "warning",
            details={"flagged": total_flagged, "revised": total_revised},
        ))

    return {
        "current_status": f"Fact Check Complete ({total_revised} revised)",
        "script_segments": out_segments,
        "errors": errors,
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
                async def _do_check():
                    annotated, _flagged = await _check_segment(
                        self.client, seg.name, seg.text, sources_block,
                    )
                    return annotated
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            future = pool.submit(asyncio.run, _do_check())
                            seg.text = future.result()
                    else:
                        seg.text = loop.run_until_complete(_do_check())
                except RuntimeError:
                    seg.text = asyncio.run(_do_check())
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
