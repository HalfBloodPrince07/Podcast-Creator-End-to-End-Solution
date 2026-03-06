"""
pipeline.py — Orchestrates all six agents sequentially.
Yields (stage, progress_pct, message) for live Gradio streaming.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generator, Optional

from config import PipelineConfig
from agents.search_agent import SearchAgent, Source
from agents.writer_agent import WriterAgent, Script
from agents.fact_checker_agent import FactCheckerAgent
from agents.audio_designer_agent import AudioDesignerAgent
from agents.tts_agent import TTSAgent
from agents.audio_mixer_agent import AudioMixerAgent
from agents.assembler_agent import AssemblerAgent
from utils import get_logger

logger = get_logger("Pipeline")


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------
STAGES = [
    ("search",        "🔍 Researching",       10),
    ("write",         "✍️  Writing Script",    30),
    ("fact_check",    "✅ Fact-Checking",      50),
    ("audio_design",  "🎵 Audio Design",       65),
    ("tts",           "🔊 TTS Synthesis",      82),
    ("audio_mix",     "🎶 Audio Mixing",       90),
    ("assemble",      "📦 Assembling",         95),
    ("done",          "🎉 Done",              100),
]

# Map stage key → (start_pct, end_pct)
_STAGE_RANGE: dict[str, tuple[int, int]] = {}
prev_pct = 0
for _key, _label, _end in STAGES:
    _STAGE_RANGE[_key] = (prev_pct, _end)
    prev_pct = _end


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class PipelineResult:
    config: PipelineConfig
    sources: list[Source] = field(default_factory=list)
    script: Optional[Script] = None
    tts_result: dict = field(default_factory=dict)
    assembly: dict = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def output_dir(self) -> str:
        return str(self.config.output_dir)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class PodcastPipeline:
    """
    Runs all agents in order.  Call run_streaming() for live Gradio progress,
    or run() for blocking execution.
    """

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.result = PipelineResult(config=config)

    # ------------------------------------------------------------------
    # Streaming (primary for Gradio)
    # ------------------------------------------------------------------
    def run_streaming(self) -> Generator[tuple[str, float, str], None, None]:
        """
        Generator that yields (stage_label, progress_pct, log_message).
        The final yield has stage_label == "done" and contains a PipelineResult.
        """
        cfg = self.config
        result = self.result

        # ----------------------------------------------------------------
        # STAGE 1: Search
        # ----------------------------------------------------------------
        yield from self._stage_header("search")
        agent_s = SearchAgent(cfg)
        sources: list[Source] = []
        for item in agent_s._run_gen():
            if isinstance(item, str):
                yield from self._stage_msg("search", item)
            else:
                sources = item
        result.sources = sources
        yield from self._stage_msg("search", f"Found {len(sources)} sources.")

        # ----------------------------------------------------------------
        # STAGE 2: Write
        # ----------------------------------------------------------------
        yield from self._stage_header("write")
        agent_w = WriterAgent(cfg)
        script: Optional[Script] = None
        for item in agent_w._run_gen(sources):
            if isinstance(item, str):
                yield from self._stage_msg("write", item)
            else:
                script = item
        result.script = script

        # ----------------------------------------------------------------
        # STAGE 3: Fact-check
        # ----------------------------------------------------------------
        yield from self._stage_header("fact_check")
        if script:
            agent_fc = FactCheckerAgent(cfg)
            for item in agent_fc._run_gen(script):
                if isinstance(item, str):
                    yield from self._stage_msg("fact_check", item)
                else:
                    script = item
            result.script = script

        # ----------------------------------------------------------------
        # STAGE 4: Audio design
        # ----------------------------------------------------------------
        yield from self._stage_header("audio_design")
        if script:
            agent_ad = AudioDesignerAgent(cfg)
            for item in agent_ad._run_gen(script):
                if isinstance(item, str):
                    yield from self._stage_msg("audio_design", item)
                else:
                    script = item
            result.script = script

        # ----------------------------------------------------------------
        # STAGE 5: TTS
        # ----------------------------------------------------------------
        yield from self._stage_header("tts")
        tts_result: dict = {}
        if script:
            agent_tts = TTSAgent(cfg)
            for item in agent_tts._run_gen(script):
                if isinstance(item, str):
                    yield from self._stage_msg("tts", item)
                else:
                    tts_result = item
        result.tts_result = tts_result

        # ----------------------------------------------------------------
        # STAGE 5.5: Audio Mixing (overlay SFX at CUE positions)
        # ----------------------------------------------------------------
        yield from self._stage_header("audio_mix")
        if script and tts_result.get("audio_path"):
            agent_mix = AudioMixerAgent(cfg)
            for item in agent_mix._run_gen(script, tts_result):
                if isinstance(item, str):
                    yield from self._stage_msg("audio_mix", item)
                elif isinstance(item, dict):
                    tts_result = item
            result.tts_result = tts_result
        else:
            yield from self._stage_msg("audio_mix", "No audio to mix — skipping.")

        # ----------------------------------------------------------------
        # STAGE 6: Assemble
        # ----------------------------------------------------------------
        yield from self._stage_header("assemble")
        assembly: dict = {}
        if script:
            agent_asm = AssemblerAgent(cfg)
            for item in agent_asm._run_gen(script, tts_result):
                if isinstance(item, str):
                    yield from self._stage_msg("assemble", item)
                else:
                    assembly = item
        result.assembly = assembly

        # ----------------------------------------------------------------
        # Done
        # ----------------------------------------------------------------
        yield ("done", 100.0, f"🎉 Pipeline complete! Outputs → {cfg.output_dir}")

    # ------------------------------------------------------------------
    # Blocking (for CLI or tests)
    # ------------------------------------------------------------------
    def run(self) -> PipelineResult:
        for _ in self.run_streaming():
            pass
        return self.result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _stage_header(self, stage_key: str) -> list[tuple[str, float, str]]:
        label = next(lbl for k, lbl, _ in STAGES if k == stage_key)
        start_pct, _ = _STAGE_RANGE[stage_key]
        return [(stage_key, float(start_pct), f"▶ {label}")]

    @staticmethod
    def _stage_msg(stage_key: str, msg: str) -> list[tuple[str, float, str]]:
        _, end_pct = _STAGE_RANGE[stage_key]
        return [(stage_key, float(end_pct), msg)]
