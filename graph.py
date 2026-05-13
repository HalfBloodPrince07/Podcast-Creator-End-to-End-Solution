import operator
from typing import Annotated, TypedDict, Any, Dict, List, Optional
from pydantic import BaseModel, Field

from langgraph.graph import StateGraph, START, END

class PodcastState(TypedDict):
    """
    State representing the entire podcast generation flow.
    We append messages or explicit metadata as we go.
    """
    topic: str
    tone: str
    audience: str
    target_words: int
    target_minutes: int
    constraints: str
    output_dir: str       # absolute path – set once by app.py, reused by all agents
    dry_run: bool
    multi_voice: bool
    tts_backend: str        # 'kokoro' | 'bark' | 'qwen' | 'chatterbox'
    voice_gender: str       # 'male' | 'female'
    voice_id: Optional[str] # voice clone UUID (chatterbox / qwen clones)

    # Refined topic (set by TopicRefinerAgent before search)
    refined_topic: str

    # Progress/UI streaming
    current_status: str

    # Agent Artifacts
    search_queries: List[str]
    sources: List[Dict[str, Any]]

    script_segments: List[Dict[str, Any]]  # The drafted script
    episode_title: str

    # Audio Assets
    tts_results: Dict[str, Any]
    final_assembly: Dict[str, Any]

    # Post-production artifacts
    whisper_words: List[Dict[str, Any]]
    visual_cues: List[Dict[str, Any]]   # [{prompt, start_ms, end_ms, word_index}, …]

    # Structured error records accumulated across nodes (any node can return more).
    errors: Annotated[List[Dict[str, Any]], operator.add]

from agents.topic_refiner_agent import run_topic_refiner_node as topic_refiner_node
from agents.search_agent import run_search_node as search_node
from agents.writer_agent import run_writer_node as writer_node
from agents.fact_checker_agent import run_fact_checker_node as fact_checker_node
from agents.audio_designer_agent import run_audio_designer_node as audio_designer_node
from agents.tts_agent import run_tts_node as tts_node
from agents.post_production_agent import run_post_production_node as post_production_node
from agents.assembler_agent import run_assembler_node as assemble_node

# Node signatures
# (Search node imported above)
# (Writer node imported above)
# (Fact check node imported above)
# (Audio design node imported above)
# (TTS node imported above)
# (Assemble node imported above)

# Create the graph
from langgraph.graph import StateGraph, START, END

workflow = StateGraph(PodcastState)

workflow.add_node("topic_refine", topic_refiner_node)
workflow.add_node("search", search_node)
workflow.add_node("write", writer_node)
workflow.add_node("fact_check", fact_checker_node)
workflow.add_node("audio_design", audio_designer_node)
workflow.add_node("tts", tts_node)
workflow.add_node("post_production", post_production_node)
workflow.add_node("assemble", assemble_node)

workflow.add_edge(START, "topic_refine")
workflow.add_edge("topic_refine", "search")
workflow.add_edge("search", "write")
workflow.add_edge("write", "fact_check")
workflow.add_edge("fact_check", "audio_design")
workflow.add_edge("audio_design", "tts")
workflow.add_edge("tts", "post_production")
workflow.add_edge("post_production", "assemble")
workflow.add_edge("assemble", END)


# ---------------------------------------------------------------------------
# Optional persistent checkpointing — lets the pipeline resume after a crash.
# Requires `pip install langgraph-checkpoint-sqlite`. Silently falls back to
# in-memory if the package isn't installed.
# ---------------------------------------------------------------------------
CHECKPOINTING_BACKEND = "none"
_checkpointer = None
try:
    from pathlib import Path as _PPath
    from langgraph.checkpoint.sqlite import SqliteSaver
    _db_path = _PPath("outputs") / "_checkpoints.sqlite"
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    # Note: SqliteSaver.from_conn_string returns a context manager in some
    # langgraph versions and a plain object in others. Try both shapes.
    try:
        _cm = SqliteSaver.from_conn_string(str(_db_path))
        if hasattr(_cm, "__enter__"):
            _checkpointer = _cm.__enter__()
        else:
            _checkpointer = _cm
        CHECKPOINTING_BACKEND = "sqlite"
    except Exception:
        _checkpointer = None
except ImportError:
    try:
        from langgraph.checkpoint.memory import MemorySaver
        _checkpointer = MemorySaver()
        CHECKPOINTING_BACKEND = "memory"
    except Exception:
        _checkpointer = None

if _checkpointer is not None:
    app_graph = workflow.compile(checkpointer=_checkpointer)
else:
    app_graph = workflow.compile()
