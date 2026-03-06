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
from utils import count_words, get_logger, async_retry_llm_call, strip_llm_noise

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

SEGMENT_SYSTEM_PROMPT = """You are an expert podcast scriptwriter. You write in a single-person, first-person
perspective (host only — no guests). Your content is natural, engaging, and matches the requested tone
and audience. Always use contractions, rhetorical questions, and vivid examples.
NEVER fabricate statistics — only reference provided sources. Keep the word count close to the target.

CRITICAL OUTPUT RULES — violating any of these will break the pipeline:
- Output ONLY the spoken words the host says. Nothing else.
- Do NOT write any preamble like "Okay, here is..." or "Sure, here's the script..." — start immediately with the spoken text.
- Do NOT add parenthetical stage directions like (pause), (sound of typing), (chuckles), etc.
- Do NOT add [CUE: ...] markers or any bracketed instructions.
- Do NOT add markdown headers, word counts, or any meta-commentary."""

MULTI_VOICE_SYSTEM_PROMPT = """You are an expert podcast scriptwriter writing a two-person conversation
between a HOST and a GUEST expert. The HOST drives the conversation with questions and transitions.
The GUEST provides expert insight and analysis. Content is natural and engaging.
NEVER fabricate statistics — only reference provided sources. Keep the word count close to the target.
Do NOT include speaker labels like "HOST:" or "GUEST:" in the output text — just write natural dialogue."""

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

async def _write_segment(
    client, seg_name: str, target_words: int, topic: str, tone: str,
    audience: str, sources_block: str, constraints_block: str, dry_run: bool
) -> str:
    if dry_run or not client:
        return _dry_run_text(seg_name, target_words)

    segment_instructions = {
        "Intro": "Open the episode with a warm welcome. Briefly introduce yourself as the host and the episode topic. Make it punchy and inviting.",
        "Hook": "Give listeners a compelling reason to keep listening. Ask a provocative rhetorical question or share a dramatic fact that sets up the episode's central tension.",
        "Outro": "Wrap up warmly. Summarise 2–3 key takeaways, invite the listener to reflect, and sign off. Keep it warm and personal.",
    }
    seg_instruction = segment_instructions.get(
        seg_name,
        f"Cover the '{seg_name}' chapter in depth. Use clear examples, cite the sources where relevant (reference as 'according to [source title]'), and keep the narrative flowing."
    )

    user_prompt = f"""Write the **{seg_name}** section of a podcast episode.

Topic: {topic}
Tone: {tone}
Target audience: {audience}
Target word count: {target_words} words (±10% is acceptable)
{constraints_block}

Segment instructions:
{seg_instruction}

Available sources (paraphrase only, quote max 25 words per source):
{sources_block}

Write ONLY the spoken script text for this segment. No stage directions. No headers. 
No [PAUSE] markers — those will be added later. Just natural spoken prose."""

    try:
        raw = await async_retry_llm_call(
            lambda: client.system_user(
                SEGMENT_SYSTEM_PROMPT, user_prompt,
                temperature=WRITER_TEMPERATURE,
                max_tokens=10000,
            ),
            logger_inst=logger,
        )
        return strip_llm_noise(raw)
    except Exception as exc:
        logger.error("LLM error for segment '%s': %s", seg_name, exc)
        return _dry_run_text(seg_name, target_words)

async def _generate_title(client, topic: str, tone: str, script_preview: str, dry_run: bool) -> str:
    if dry_run or not client:
        return topic.title()
    try:
        title = await async_retry_llm_call(
            lambda: client.system_user(
                "You are a podcast title writer. Return ONLY the title — no quotes, no explanation.",
                f"Create a short, catchy podcast episode title (max 10 words) for a {tone} episode about: {topic}\n\nScript preview:\n{script_preview}",
                temperature=TITLE_TEMPERATURE,
                max_tokens=30,
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
    segment_plan = cfg.build_segment_plan(include_mid_cta=False)

    sources_block = _format_sources(sources)
    constraints_block = f"\nConstraints: {constraints}" if constraints else ""

    client = get_client() if not dry_run else None

    script_segments = []
    for plan_seg in segment_plan:
        seg_name = plan_seg["name"]
        t_words = plan_seg["target_words"]
        t_secs = plan_seg["target_seconds"]
        
        logger.info("Writing segment: %s", seg_name)

        text = await _write_segment(
            client, seg_name, t_words, topic, tone, audience, 
            sources_block, constraints_block, dry_run
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

    return {
        "current_status": "Writing Complete",
        "episode_title": title,
        "script_segments": script_segments,
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
