import os
import json
import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv, set_key

load_dotenv()

from utils import setup_logging
setup_logging()

from config import PipelineConfig
from llm_client import get_client, reset_client
from graph import app_graph, PodcastState

app = FastAPI(title="Podcast Pipeline API")

# Allow CORS for the Vite dev server; override via CORS_ORIGINS env var
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the outputs directory statically so the frontend can download files
OUTPUTS_DIR = Path("./outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")

ENV_PATH = Path(__file__).parent / ".env"

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    topic: str
    minutes: int = 5
    tone: str = "conversational"
    audience: str = "general listeners"
    wpm: int = 150
    timeline: str = ""
    constraints: str = ""
    dry_run: bool = False
    skip_cache: bool = False
    multi_voice: bool = False
    tts_backend: str = "kokoro"
    voice_gender: str = "female"
    output_dir: str = "./outputs"
    llm_url: str = ""
    llm_key: str = ""
    llm_model: str = ""

class SettingsRequest(BaseModel):
    llm_url: str = ""
    llm_key: str = ""
    llm_model: str = ""
    tts_model: str = ""

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/ready")
async def ready():
    try:
        client = get_client()
        ok, msg = await client.test_connection()
        return {"ready": ok, "llm": msg}
    except Exception as e:
        return JSONResponse(status_code=503, content={"ready": False, "error": str(e)})

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def get_settings():
    """Return current settings from env so frontend can pre-populate without user needing to type them."""
    return {
        "llm_url": os.getenv("LLM_BASE_URL", "http://localhost:1234/v1"),
        "llm_model": os.getenv("LLM_MODEL", "local-model"),
        "tts_model": os.getenv("QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"),
    }

@app.post("/api/settings/test-connection")
async def test_connection(req: SettingsRequest):
    if req.llm_url.strip():
        os.environ["LLM_BASE_URL"] = req.llm_url.strip()
    if req.llm_key.strip():
        os.environ["LLM_API_KEY"] = req.llm_key.strip()
    if req.llm_model.strip():
        os.environ["LLM_MODEL"] = req.llm_model.strip()
    reset_client()
    client = get_client()
    ok, msg = await client.test_connection()
    return {"ok": ok, "message": msg}

@app.get("/api/settings/models")
async def get_models(llm_url: str = ""):
    if llm_url.strip():
        os.environ["LLM_BASE_URL"] = llm_url.strip()
    reset_client()
    try:
        models = await get_client().list_models()
        return {"models": models if models else ["local-model"]}
    except Exception as e:
        return {"models": ["local-model"], "error": str(e)}

@app.post("/api/settings/save")
async def save_settings(req: SettingsRequest):
    try:
        env_file = str(ENV_PATH)
        if req.llm_url.strip():
            set_key(env_file, "LLM_BASE_URL", req.llm_url.strip())
        if req.llm_key.strip():
            set_key(env_file, "LLM_API_KEY", req.llm_key.strip())
        if req.tts_model.strip():
            set_key(env_file, "QWEN_TTS_MODEL", req.tts_model.strip())
        if req.llm_model.strip():
            set_key(env_file, "LLM_MODEL", req.llm_model.strip())
        return {"ok": True, "message": "Settings saved to .env"}
    except Exception as e:
        return {"ok": False, "message": str(e)}

# ---------------------------------------------------------------------------
# Episode Library
# ---------------------------------------------------------------------------

@app.get("/api/episodes")
async def list_episodes():
    """Scan outputs/ for episode directories containing metadata.json, return sorted list."""
    episodes = []
    for meta_path in OUTPUTS_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            run_id = meta.get("run_id", meta_path.parent.name)
            episodes.append({
                "run_id": run_id,
                "title": meta.get("episode_title", "Untitled"),
                "topic": meta.get("podcast_topic", ""),
                "tone": meta.get("tone", ""),
                "duration_seconds": meta.get("duration_seconds", 0),
                "duration_hms": meta.get("duration_hms", ""),
                "generated_at": meta.get("generated_at", ""),
                "dry_run": meta.get("dry_run", False),
                "source_count": meta.get("source_count", 0),
                "actual_words": meta.get("actual_words", 0),
                "has_audio": bool(meta.get("audio_filename")),
            })
        except Exception:
            continue
    episodes.sort(key=lambda e: e.get("generated_at", ""), reverse=True)
    return {"episodes": episodes}


@app.get("/api/episodes/{run_id}")
async def get_episode(run_id: str):
    """Return full metadata and file URLs for a specific episode."""
    for meta_path in OUTPUTS_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("run_id") == run_id or meta_path.parent.name == run_id:
                ep_dir = meta_path.parent
                rel = ep_dir.relative_to(OUTPUTS_DIR).as_posix()

                files = {}
                for fname, key in [
                    ("episode.mp3", "audio_url"),
                    ("transcript.srt", "srt_url"),
                    ("transcript.txt", "txt_url"),
                    ("show_notes.md", "notes_url"),
                    ("episode_tts_ready.txt", "tts_txt_url"),
                    ("transcript.html", "html_url"),
                ]:
                    if (ep_dir / fname).exists():
                        files[key] = f"/outputs/{rel}/{fname}"

                notes_path = ep_dir / "show_notes.md"
                show_notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""

                return {**meta, "files": files, "show_notes": show_notes}
        except Exception:
            continue
    raise HTTPException(status_code=404, detail=f"Episode '{run_id}' not found")


# ---------------------------------------------------------------------------
# RSS Feed
# ---------------------------------------------------------------------------

@app.get("/api/feed.xml")
async def rss_feed(req: Request):
    """Generate an RSS 2.0 / iTunes podcast feed from all episodes."""
    from rss import generate_feed
    base_url = str(req.base_url).rstrip("/")
    xml = generate_feed(OUTPUTS_DIR, base_url=base_url)
    return Response(content=xml, media_type="application/xml")


# ---------------------------------------------------------------------------
# Streaming Endpoint
# ---------------------------------------------------------------------------

@app.post("/api/generate")
async def generate_podcast(req: Request):
    """
    We read the JSON request and run the pipeline blocking function. 
    However, we need to stream the results asynchronously over SSE.
    """
    data = await req.json()
    gen_req = GenerateRequest(**data)

    if not gen_req.topic.strip():
        raise HTTPException(status_code=400, detail="Topic is required")

    # Override env vars
    if gen_req.llm_url.strip():
        os.environ["LLM_BASE_URL"] = gen_req.llm_url.strip()
    if gen_req.llm_key.strip():
        os.environ["LLM_API_KEY"] = gen_req.llm_key.strip()
    if gen_req.llm_model.strip():
        os.environ["LLM_MODEL"] = gen_req.llm_model.strip()

    reset_client()

    cfg = PipelineConfig(
        podcast_topic=gen_req.topic.strip(),
        target_minutes=gen_req.minutes,
        tone=gen_req.tone,
        audience=gen_req.audience.strip() or "general listeners",
        target_wpm=gen_req.wpm,
        timeline_or_focus=gen_req.timeline.strip() or None,
        constraints=gen_req.constraints.strip() or None,
        output_base_dir=gen_req.output_dir.strip() or "./outputs",
        dry_run=gen_req.dry_run,
        skip_cache=gen_req.skip_cache,
        multi_voice=gen_req.multi_voice,
    )

    async def event_generator():
        STAGE_LABELS = {
            "topic_refine": "🧹 Refining Topic",
            "search": "🔍 Researching",
            "write": "✍️ Drafting Script",
            "fact_check": "🔎 Fact Checking",
            "audio_design": "🎵 Audio Design",
            "tts": "🔊 Generating Audio",
            "assemble": "📦 Assembling Episode"
        }
        
        # Initialize Graph State
        state = PodcastState(
            topic=cfg.podcast_topic,
            refined_topic="",
            tone=cfg.tone,
            audience=cfg.audience,
            target_words=cfg.target_words,
            target_minutes=cfg.target_minutes,
            constraints=cfg.constraints or "",
            output_dir=str(cfg.output_dir),   # shared across all agents
            dry_run=cfg.dry_run,
            multi_voice=cfg.multi_voice,
            tts_backend=gen_req.tts_backend,
            voice_gender=gen_req.voice_gender,
            current_status="Initializing...",
            search_queries=[],
            sources=[],
            script_segments=[],
            episode_title=cfg.episode_title,
            tts_results={},
            final_assembly={},
            errors=[]
        )

        try:
            # We use .astream to get state updates after each node completes
            async for step_result in app_graph.astream(state, stream_mode="updates"):
                # step_result is a dict with key = node_name, value = state_update
                for node_name, state_update in step_result.items():
                    # Check if error occurred
                    if state_update.get("errors"):
                        err_msg = state_update["errors"][-1]
                        yield json.dumps({"error": err_msg, "done": True})
                        return

                    # Construct progress object for frontend
                    pct_map = {
                        "topic_refine": 5,
                        "search": 15,
                        "write": 35,
                        "fact_check": 52,
                        "audio_design": 67,
                        "tts": 84,
                        "assemble": 96
                    }
                    pct = pct_map.get(node_name, 0)
                    msg = state_update.get("current_status", f"Completed {node_name}")
                    
                    # Transform sources and scripts for FE display incrementally if they exist
                    # (For now we rely on the final graph output, but we can stream partials here later)
                    
                    yield json.dumps({
                        "stage": STAGE_LABELS.get(node_name, node_name),
                        "pct": pct,
                        "msg": msg,
                        "sources": state_update.get("sources", []),
                        "script": state_update.get("script_segments", []),
                        "done": False,
                    })
                    
                    # Update our running state
                    state.update(state_update)

        except Exception as e:
            yield json.dumps({"error": str(e), "done": True})
            return

        # Final state
        asm = state.get("final_assembly", {})
        
        # Convert absolute paths to relative URLs served by StaticFiles (i.e. /outputs/...)
        def relative_output_path(p: str):
            if not p: return None
            try:
                base_outputs = str(Path(cfg.output_base_dir).resolve())
                abs_p = str(Path(p).resolve())
                if abs_p.startswith(base_outputs):
                    rel = Path(abs_p).relative_to(base_outputs)
                    return f"/outputs/{rel.as_posix()}"
                return None
            except Exception:
                return None

        audio_url    = relative_output_path(asm.get("audio_path"))
        tts_txt_url  = relative_output_path(asm.get("tts_text_path"))
        srt_url      = relative_output_path(asm.get("srt_path"))
        txt_url      = relative_output_path(asm.get("txt_path"))
        notes_url    = relative_output_path(asm.get("notes_path"))
        meta_url     = relative_output_path(asm.get("meta_path"))

        final_state = {
            "stage": "Complete",
            "pct": 100,
            "msg": f"✅ Complete! Output saved to {cfg.output_dir}",
            "sources": state.get("sources", []),
            "script": state.get("script_segments", []),
            "done": True,
            "results": {
                "audio_url": audio_url,
                "tts_txt_url": tts_txt_url,
                "srt_url": srt_url,
                "txt_url": txt_url,
                "notes_url": notes_url,
                "meta_url": meta_url,
                "srt_content": asm.get("srt_content", ""),
                "txt_content": asm.get("txt_content", ""),
                "show_notes": asm.get("show_notes", ""),
                "metadata": asm.get("metadata", {}),
            }
        }
        yield json.dumps(final_state)

    return EventSourceResponse(event_generator())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
