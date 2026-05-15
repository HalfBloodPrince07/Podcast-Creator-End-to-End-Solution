"""
agents/writer_agent.py — Creates a minute-accurate script in single-person POV.
Receives PipelineConfig + sources list from SearchAgent.
Produces a structured Script object with per-segment word counts & durations.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, Optional

from config import PipelineConfig
from constants import WRITER_TEMPERATURE, TITLE_TEMPERATURE
from agents.search_agent import Source
from llm_client import get_client
from utils import count_words, get_logger, async_retry_llm_call, strip_llm_noise, make_error_record

logger = get_logger("WriterAgent")

# ---------------------------------------------------------------------------
# DRY-RUN stubs
# ---------------------------------------------------------------------------
DRY_RUN_SEGMENT_TEXT = (
    "This is a placeholder script segment generated in dry-run mode. "
    "In a live run, the LLM would produce rich, natural-sounding content tailored "
    "to the topic, tone, and audience you specified. "
    "The word count for each segment is calibrated so the spoken reading "
    "lands within the target duration window. "
    "Rhetorical questions, contractions, and source references would appear inline here."
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class ScriptSegment:
    name: str
    target_seconds: int
    target_words: int
    text: str = ""
    speaker: str = "host"
    actual_words: int = field(init=False, default=0)
    estimated_seconds: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.actual_words = count_words(self.text)
        self._update_estimated_seconds()

    def refresh_word_count(self) -> None:
        self.actual_words = count_words(self.text)
        self._update_estimated_seconds()

    def _update_estimated_seconds(self) -> None:
        wpm = 150
        self.estimated_seconds = (self.actual_words / wpm) * 60 if self.actual_words else 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "target_seconds": self.target_seconds,
            "target_words": self.target_words,
            "actual_words": self.actual_words,
            "speaker": self.speaker,
            "estimated_seconds": self.estimated_seconds,
            "text": self.text,
        }


@dataclass
class Script:
    episode_title: str
    segments: list[ScriptSegment] = field(default_factory=list)
    total_target_words: int = 0
    sources_used: list[Source] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(s.text for s in self.segments)

    @property
    def total_actual_words(self) -> int:
        return sum(s.actual_words for s in self.segments)

    @property
    def total_actual_seconds(self) -> float:
        return sum(s.target_seconds for s in self.segments)

    def to_dict(self) -> dict:
        return {
            "episode_title": self.episode_title,
            "total_target_words": self.total_target_words,
            "total_actual_words": self.total_actual_words,
            "total_target_seconds": sum(s.target_seconds for s in self.segments),
            "segments": [s.to_dict() for s in self.segments],
        }


# ---------------------------------------------------------------------------
# Node Implementation
# ---------------------------------------------------------------------------

SEGMENT_SYSTEM_PROMPT = """You are a top-tier podcast scriptwriter whose episodes regularly hit #1 on charts.
You write ONLY the host's spoken words — first-person, solo host.

STYLE RULES (every rule is mandatory):
- Sentences: average 15 words or fewer. Vary length — mix short punches with longer flowing ones.
- Direct address: use "you" and "we" constantly. Never write for a third-party reader.
- Contractions always: "it's", "you'll", "we're", "that's", "here's", "don't", "isn't".
- Show don't tell: use one vivid concrete analogy or mini-story for every abstract concept.
- Rhetorical questions: 1–2 per section to pull the listener in.
- Rule of threes: group related points in threes for rhythm and memorability.
- No passive voice. No academic language. No jargon without an immediate plain-English follow-up.
- Numbers: always follow a statistic with what it means in human terms.
  Example: "That's 3 billion dollars — enough to pay 50,000 engineers for a full year."
- NEVER fabricate statistics. Only reference provided sources.
- Word count: hit within ±10% of the target.

ANTI-REPETITION RULES (this is what separates good scripts from amateur ones):
- ONE-AND-DONE ANALOGIES: every analogy, metaphor, or mini-story is single-use across the entire
  episode. If a prior segment used a chef-and-recipes analogy, you must reach for a completely
  different domain (architect, gardener, courtroom, traffic, music — pick one not yet used).
- VARY TRANSITIONS: pick a different opener for every segment. Acceptable signposts include
  "But here's the thing.", "Now picture this.", "So what does that actually mean?",
  "And it gets better.", "Here's where it gets interesting.", "Think about it this way.",
  "Strip away the hype and…", "Here's what most people miss.", "Zoom in on this for a second."
  Use each signpost AT MOST ONCE per episode. Better: invent a fresh one.
- NO RECYCLED FACTS: do not restate a statistic, citation, or framing you have already used.
  Each segment advances the story with NEW information drawn from the sources.

EMPHASIS RULES (hard cap — violations are immediately visible to listeners):
- Maximum TWO [EMPHASIS]…[/EMPHASIS] tags per paragraph. Three or more sounds like a hard sell.
- Never emphasise articles, pronouns, filler words, or whole clauses. Only 1–3 high-weight words.

OUTPUT RULES (violations break the pipeline):
- Output ONLY the spoken script text. Nothing else.
- No preamble ("Okay here is...", "Sure, here's..."). Start immediately with the words.
- No stage directions, no [CUE:] markers, no markdown headers, no meta-commentary."""

MULTI_VOICE_SYSTEM_PROMPT = """You are an expert podcast scriptwriter writing a two-person conversation
between a HOST and a GUEST expert. The HOST drives the conversation with questions and transitions.
The GUEST provides expert insight and analysis. Content is natural and engaging.
NEVER fabricate statistics — only reference provided sources. Keep the word count close to the target.
Do NOT include speaker labels like "HOST:" or "GUEST:" in the output text — just write natural dialogue."""

NARRATIVE_ARC_SYSTEM_PROMPT = """You are a podcast story architect. Given a topic and source snippets,
return a one-paragraph narrative arc the host can ride from intro to outro.

Output PLAIN TEXT only — no JSON, no markdown, no headers. Use these five labels inline,
each on its own line. Keep each line under 25 words.

PREMISE: <one sentence — what this episode is fundamentally about>
TENSION: <the unresolved question or conflict that pulls the listener forward>
REVELATION: <the key insight or surprise the episode delivers>
RESOLUTION: <what it means or what the listener should do with it>
CALLBACK: <a vivid concrete detail to mention in the cold open and refer back to at the end>"""


async def _generate_narrative_arc(
    client,
    topic: str,
    tone: str,
    audience: str,
    sources_block: str,
    dry_run: bool,
) -> str:
    """One-shot LLM call producing a 5-line narrative arc. Returns '' on failure."""
    if dry_run or not client:
        return ""
    try:
        raw = await async_retry_llm_call(
            lambda: client.system_user(
                NARRATIVE_ARC_SYSTEM_PROMPT,
                (
                    f"Topic: {topic}\n"
                    f"Tone: {tone}\n"
                    f"Audience: {audience}\n\n"
                    f"Sources:\n{sources_block}\n\n"
                    "Produce the narrative arc now."
                ),
                temperature=0.5,
                # Thinking models (Gemma-4 reasoning, DeepSeek-R1, QwQ) need
                # headroom for <think>...</think> tokens before the actual
                # output. 350 was too tight — the entire budget got eaten by
                # reasoning, producing an empty answer after _strip_thinking.
                max_tokens=5500,
            ),
            logger_inst=logger,
        )
        arc = strip_llm_noise(raw)
        if not arc.strip():
            logger.warning(
                "Narrative arc came back empty after cleanup — segments will "
                "be written without a shared spine. Raw response length: %d chars.",
                len(raw),
            )
        else:
            logger.info("Narrative arc generated:\n%s", arc)
        return arc
    except Exception as exc:
        logger.warning("Narrative arc generation failed (%s) — continuing without it.", exc)
        return ""


_TONE_CRAFT: dict[str, str] = {
    "conversational": "Write as if talking to a smart friend over coffee — warm, direct, no formality.",
    "storytelling":   "Lead every idea with a scene or anecdote before revealing the insight.",
    "humorous":       "Drop one dry observation or light absurdity per paragraph. Never force it.",
    "analytical":     "Lead with the insight, then walk through the evidence step-by-step.",
    "authoritative":  "Confident and direct. Cut throat-clearing. Every sentence earns its place.",
    "casual":         "Loose, warm, even a little rambly — like a podcast recorded between friends.",
}


def _format_sources(sources: list[dict]) -> str:
    if not sources:
        return "(No sources provided — write from general knowledge, clearly state uncertainty)"
    lines = []
    for s in sources:
        lines.append(
            f"[SRC-{s.get('index', '?')}] {s.get('title', '')} ({s.get('publisher', '')}, {s.get('date', '')})\n"
            f"  Snippet: {s.get('snippet', '')[:200]}\n"
            f"  URL: {s.get('url', '')}"
        )
    return "\n\n".join(lines)

def _dry_run_text(seg_name: str, target_words: int) -> str:
    base = DRY_RUN_SEGMENT_TEXT
    reps = max(1, target_words // count_words(base) + 1)
    text = (base + " ") * reps
    words = text.split()[:target_words]
    prefix = {
        "Intro": "Welcome to the show! Today we're exploring a fascinating topic. ",
        "Hook":  "Here's the question that keeps experts up at night: What if everything we knew was wrong? ",
        "Outro": "And that wraps up today's episode. Thank you so much for listening. ",
    }.get(seg_name, f"Now let's dive into {seg_name}. ")
    return prefix + " ".join(words)

def _format_prior_segments(prior: list[dict], max_chars: int = 3000) -> str:
    """Compact view of segments already written, so the next call can avoid repeating them.

    Trims oldest content first if the combined text exceeds max_chars — recent context
    matters most for avoiding back-to-back duplicates.
    """
    if not prior:
        return ""
    blocks: list[str] = []
    for seg in prior:
        name = seg.get("name", "?")
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        blocks.append(f"--- {name} ---\n{text}")
    joined = "\n\n".join(blocks)
    if len(joined) > max_chars:
        joined = "…(earlier segments truncated)…\n\n" + joined[-max_chars:]
    return joined


async def _write_segment(
    client, seg_name: str, target_words: int, topic: str, tone: str,
    audience: str, sources_block: str, constraints_block: str, dry_run: bool,
    narrative_arc: str = "",
    prior_segments: Optional[list[dict]] = None,
) -> str:
    if dry_run or not client:
        return _dry_run_text(seg_name, target_words)

    segment_instructions = {
        "Hook": (
            "Cold open — drop the listener straight into a surprising fact, counterintuitive claim, "
            "or vivid scene BEFORE any introductions. Do NOT say 'Welcome to the show.' "
            "Do NOT ask a question that could be answered with 'I don't know.' "
            "Use a bold declarative opener: 'In [year], [shocking thing happened].' or "
            "'Here's something almost nobody realises about [topic].' "
            "End with one sentence tease that makes skipping forward feel like a mistake."
        ),
        "Intro": (
            "Now introduce the show and yourself — warmly, briefly (about 10–15 seconds of audio). "
            "Make a specific promise: tell the listener exactly what they'll walk away knowing. "
            "Bridge back to the hook: 'That [hook detail] is exactly what we're unpacking today.' "
            "Make them feel this episode was made for them personally."
        ),
        "Outro": (
            "Call back to the hook from the cold open — close the loop explicitly. "
            "Give exactly 3 key takeaways as short punchy sentences (not a list, woven into speech). "
            "End with one forward-looking thought or open question that stays with the listener. "
            "Warm personal sign-off. No 'like and subscribe' unless the constraints require it."
        ),
        "Mid-Episode CTA": (
            "A brief warm aside — 2 to 3 short sentences — directly addressing the listener. "
            "Acknowledge they're still with you, thank them, and make ONE specific ask: share with "
            "a friend who'd love this, subscribe so they don't miss the next one, or leave a quick rating. "
            "Pick exactly one ask — do not stack multiple. "
            "Then bridge naturally back into the topic with a phrase like 'Okay, back to it.' "
            "Tone is conversational and grateful, never salesy or guilt-trippy."
        ),
    }
    seg_instruction = segment_instructions.get(
        seg_name,
        f"Cover '{seg_name}' as a self-contained story arc: setup → tension or complication → resolution or insight. "
        f"Open with a signpost: 'Now let's talk about...' or 'Here's where [topic] gets fascinating.' "
        f"Use one concrete analogy or real-world mini-story to anchor the main idea. "
        f"Cite sources naturally mid-sentence ('According to [publisher],...') — never as footnotes. "
        f"Close with a one-sentence punch that sets up curiosity for the next section."
    )

    tone_craft = _TONE_CRAFT.get(tone.lower(), "")
    tone_line = f"\nTone guidance: {tone_craft}" if tone_craft else ""
    arc_block = (
        f"\nNARRATIVE ARC for this episode (use the part relevant to this segment, never recite the labels verbatim):\n{narrative_arc}\n"
        if narrative_arc else ""
    )

    prior_block = ""
    prior_view = _format_prior_segments(prior_segments or [])
    if prior_view:
        prior_block = (
            "\nALREADY WRITTEN in earlier segments — do NOT repeat any analogy, opener, "
            "statistic, citation focus, or framing from below. Read this, then take the "
            "story FORWARD with material that is genuinely new:\n"
            f"\"\"\"\n{prior_view}\n\"\"\"\n"
        )

    user_prompt = f"""Write the **{seg_name}** section of a podcast episode.

Topic: {topic}
Tone: {tone}{tone_line}
Target audience: {audience}
Target word count: {target_words} words (±10% is acceptable)
{constraints_block}
{arc_block}{prior_block}
Segment instructions:
{seg_instruction}

Available sources (paraphrase only, quote max 25 words per source):
{sources_block}

Write ONLY the spoken script text for this segment. No stage directions. No headers.
No [PAUSE] markers — those are added later. Just natural spoken prose."""

    try:
        raw = await async_retry_llm_call(
            lambda: client.system_user(
                SEGMENT_SYSTEM_PROMPT, user_prompt,
                temperature=WRITER_TEMPERATURE,
                max_tokens=100000,
            ),
            logger_inst=logger,
        )
        return strip_llm_noise(raw)
    except Exception as exc:
        logger.error("LLM error for segment '%s': %s", seg_name, exc)
        return _dry_run_text(seg_name, target_words)

REVISION_SYSTEM_PROMPT = """You are revising a single podcast segment because the fact-checker flagged
some sentences as containing factual claims unsupported by the provided sources.

Your job:
- Rewrite ONLY the flagged sentences so they no longer make those unsupported claims.
  Either remove the specific unverifiable number/date/name, or replace it with a hedged phrasing
  using language already supported by the sources (e.g. "industry estimates suggest", "many experts agree").
- KEEP every other sentence in the segment unchanged.
- Preserve the same approximate word count and conversational tone.
- Do NOT fabricate new facts. Do NOT add new statistics.

OUTPUT RULES:
- Output ONLY the revised spoken script for this segment. No preamble.
- No stage directions, no [PAUSE], no [CUE:], no [SRC-N] markers — those are added in a later pass.
- No markdown, no headers, no explanations."""


async def revise_segment_text(
    client,
    seg_name: str,
    original_text: str,
    flagged_claims: list[str],
    sources_block: str,
    target_words: int,
) -> str:
    """
    Rewrite a segment so the flagged claims are no longer present in any verifiable form.
    Returns the revised text, or the original on failure.
    """
    if not client or not flagged_claims:
        return original_text
    flagged_block = "\n".join(f"- {c}" for c in flagged_claims)
    user_prompt = f"""Segment name: {seg_name}
Target word count: ~{target_words} words.

Available sources you may rely on:
{sources_block}

FLAGGED unsupported sentences in the current draft:
{flagged_block}

Current segment draft:
\"\"\"
{original_text}
\"\"\"

Rewrite the segment so those flagged sentences no longer make unsupported claims.
Return ONLY the revised spoken text."""

    try:
        raw = await async_retry_llm_call(
            lambda: client.system_user(
                REVISION_SYSTEM_PROMPT,
                user_prompt,
                temperature=WRITER_TEMPERATURE,
                # Floor needs to be high enough for thinking models — Gemma-4
                # reasoning can eat 2-3 KB of tokens before producing output.
                max_tokens=max(8000, target_words * 4),
            ),
            logger_inst=logger,
        )
        return strip_llm_noise(raw) or original_text
    except Exception as exc:
        logger.warning("Segment revision failed (%s) — keeping original.", exc)
        return original_text


async def _generate_title(client, topic: str, tone: str, script_preview: str, dry_run: bool) -> str:
    if dry_run or not client:
        return topic.title()
    try:
        title = await async_retry_llm_call(
            lambda: client.system_user(
                "You are a podcast title writer. Return ONLY the title — no quotes, no explanation.",
                f"Create a short, catchy podcast episode title (max 10 words) for a {tone} episode about: {topic}\n\nScript preview:\n{script_preview}",
                temperature=TITLE_TEMPERATURE,
                # Thinking models can spend 1000s of tokens reasoning about
                # a 10-word title. Give generous headroom — title output is
                # short so the unused budget costs nothing.
                max_tokens=8000,
            ),
            logger_inst=logger,
        )
        return re.sub(r'^["\']|["\']$', '', title.strip())
    except Exception:
        return topic.title()

async def run_writer_node(state: dict) -> dict:
    """
    LangGraph node that produces a full podcast script segmented into Intro, Hook, Chapters, Outro.
    """
    topic = (state.get("refined_topic") or state.get("topic", "")).strip()
    tone = state.get("tone", "conversational")
    audience = state.get("audience", "general listeners")
    target_words = state.get("target_words", 1000)
    target_minutes = state.get("target_minutes", 5)
    constraints = state.get("constraints", "")
    dry_run = state.get("dry_run", False)
    multi_voice = state.get("multi_voice", False)
    sources = state.get("sources", [])
    
    # We must rebuild the segment plan config object just to get the segments, 
    # or recreate the logic here. We'll reconstruct a temporary PipelineConfig
    # to avoid duplicating build_segment_plan.
    from config import PipelineConfig
    cfg = PipelineConfig(
        podcast_topic=topic,
        target_minutes=max(1, target_minutes),  # guard against 0 / missing
        tone=tone,
        audience=audience,
        constraints=constraints,
        dry_run=dry_run,
        multi_voice=multi_voice,
        output_base_dir=str(Path(state.get("output_dir", "./outputs")).parent),
    )
    from constants import MID_CTA_MIN_MINUTES
    include_mid_cta = target_minutes >= MID_CTA_MIN_MINUTES
    segment_plan = cfg.build_segment_plan(include_mid_cta=include_mid_cta)

    sources_block = _format_sources(sources)
    constraints_block = f"\nConstraints: {constraints}" if constraints else ""

    client = get_client() if not dry_run else None

    # Pre-write narrative arc pass — gives every segment a shared spine
    logger.info("Generating narrative arc...")
    narrative_arc = await _generate_narrative_arc(
        client, topic, tone, audience, sources_block, dry_run,
    )

    script_segments = []
    for plan_seg in segment_plan:
        seg_name = plan_seg["name"]
        t_words = plan_seg["target_words"]
        t_secs = plan_seg["target_seconds"]

        logger.info("Writing segment: %s", seg_name)

        text = await _write_segment(
            client, seg_name, t_words, topic, tone, audience,
            sources_block, constraints_block, dry_run,
            narrative_arc=narrative_arc,
            prior_segments=script_segments,
        )

        speaker = "host"
        if multi_voice and seg_name not in ("Intro", "Hook", "Outro", "Mid-Episode CTA"):
            speaker = "guest"
            
        segment = ScriptSegment(
            name=seg_name,
            target_seconds=t_secs,
            target_words=t_words,
            text=text,
            speaker=speaker,
        )
        script_segments.append(segment.to_dict())

    # Generate title
    preview = "\n".join(s["text"] for s in script_segments)[:500]
    title = await _generate_title(client, topic, tone, preview, dry_run)

    errors: list[dict] = []
    short_segs = [s for s in script_segments if s.get("actual_words", 0) < int(s.get("target_words", 0) * 0.6)]
    if short_segs:
        names = ", ".join(s.get("name", "?") for s in short_segs)
        errors.append(make_error_record(
            "write",
            f"{len(short_segs)} segment(s) came in well under target: {names}",
            "warning",
        ))

    return {
        "current_status": "Writing Complete",
        "episode_title": title,
        "script_segments": script_segments,
        "narrative_arc": narrative_arc,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Backward-compatible class wrapper (used by tests)
# ---------------------------------------------------------------------------
class WriterAgent:
    """Class-based wrapper around the functional writer node for test compatibility."""

    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.client = get_client() if not cfg.dry_run else None

    @staticmethod
    def _format_sources(sources) -> str:
        """Format a list of Source objects or dicts for LLM prompts."""
        if not sources:
            return "(No sources provided — write from general knowledge, clearly state uncertainty)"
        lines = []
        for s in sources:
            if hasattr(s, "to_dict"):
                d = s.to_dict()
            else:
                d = s
            lines.append(
                f"[SRC-{d.get('index', '?')}] {d.get('title', '')} ({d.get('publisher', '')}, {d.get('date', '')})\n"
                f"  Snippet: {d.get('snippet', '')[:200]}\n"
                f"  URL: {d.get('url', '')}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _dry_run_text(seg_name: str, target_words: int) -> str:
        return _dry_run_text(seg_name, target_words)

    def run(self, sources) -> Script:
        """Synchronous run: returns a Script object (dry-run only for sync)."""
        import asyncio
        sources_list = [s.to_dict() if hasattr(s, "to_dict") else s for s in sources]
        state = {
            "topic": self.cfg.podcast_topic,
            "tone": getattr(self.cfg, "tone", "conversational"),
            "audience": getattr(self.cfg, "audience", "general listeners"),
            "target_words": getattr(self.cfg, "target_words", 1000),
            "target_minutes": getattr(self.cfg, "target_minutes", 5),
            "constraints": getattr(self.cfg, "constraints", ""),
            "dry_run": self.cfg.dry_run,
            "multi_voice": getattr(self.cfg, "multi_voice", False),
            "sources": sources_list,
            "output_dir": str(getattr(self.cfg, "output_dir", "./outputs")),
        }

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, run_writer_node(state))
                    result = future.result()
            else:
                result = loop.run_until_complete(run_writer_node(state))
        except RuntimeError:
            result = asyncio.run(run_writer_node(state))

        segment_plan = self.cfg.build_segment_plan(include_mid_cta=False)
        src_objects = [
            Source(**s) if isinstance(s, dict) else s for s in sources_list
            if isinstance(s, (dict, Source))
        ]
        # Rebuild Source objects from dict
        src_objects = []
        for s in sources:
            if isinstance(s, Source):
                src_objects.append(s)

        script_segments = []
        raw_segs = result.get("script_segments", [])
        for seg_dict in raw_segs:
            seg = ScriptSegment(
                name=seg_dict["name"],
                target_seconds=seg_dict["target_seconds"],
                target_words=seg_dict["target_words"],
                text=seg_dict.get("text", ""),
                speaker=seg_dict.get("speaker", "host"),
            )
            script_segments.append(seg)

        return Script(
            episode_title=result.get("episode_title", self.cfg.podcast_topic),
            segments=script_segments,
            sources_used=src_objects,
        )

    def _run_gen(self, sources):
        """Synchronous generator yielding status strings then the final Script."""
        yield "Writing script segments..."
        script = self.run(sources)
        yield script
