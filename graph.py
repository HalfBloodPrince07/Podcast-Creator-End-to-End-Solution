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
    tts_backend: str   # 'kokoro' | 'bark' | 'qwen'
    voice_gender: str  # 'male' | 'female'

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

    errors: List[str]

from agents.topic_refiner_agent import run_topic_refiner_node as topic_refiner_node
from agents.search_agent import run_search_node as search_node
from agents.writer_agent import run_writer_node as writer_node
from agents.fact_checker_agent import run_fact_checker_node as fact_checker_node
from agents.audio_designer_agent import run_audio_designer_node as audio_designer_node
from agents.tts_agent import run_tts_node as tts_node
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
workflow.add_node("assemble", assemble_node)

workflow.add_edge(START, "topic_refine")
workflow.add_edge("topic_refine", "search")
workflow.add_edge("search", "write")
workflow.add_edge("write", "fact_check")
workflow.add_edge("fact_check", "audio_design")
workflow.add_edge("audio_design", "tts")
workflow.add_edge("tts", "assemble")
workflow.add_edge("assemble", END)

app_graph = workflow.compile()
