import os
import sys
import io
import json
import asyncio
from pathlib import Path
from typing import Optional

# Fix Windows cp1252 console encoding so emoji log messages (e.g. from
# chatterbox-tts) don't trigger UnicodeEncodeError.
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    # Also patch any logging handlers that were created before this point
    import logging as _logging
    for _h in _logging.root.handlers:
        if hasattr(_h, "stream") and hasattr(_h.stream, "reconfigure"):
            try:
                _h.stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse as FastAPIFileResponse
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

from contextlib import asynccontextmanager
import logging as _app_logging

_startup_logger = _app_logging.getLogger("Startup")


def _preload_whisper() -> None:
    """Preload the faster-whisper model so the first episode doesn't pay the cold-start tax."""
    try:
        from constants import WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE
        from faster_whisper import WhisperModel
        device = WHISPER_DEVICE
        compute = WHISPER_COMPUTE_TYPE
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        if device == "cuda" and compute == "int8":
            compute = "float16"
        _startup_logger.info("Preloading Whisper %s on %s (%s)...", WHISPER_MODEL, device, compute)
        # Touch the model so the download happens at startup
        WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)
        _startup_logger.info("Whisper preloaded.")
    except ImportError:
        _startup_logger.info("faster-whisper not installed — Whisper preload skipped.")
    except Exception as exc:
        _startup_logger.warning("Whisper preload failed (%s) — first episode will load on demand.", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: preload heavy models on startup."""
    # Run preload in a thread so it doesn't block the event loop
    await asyncio.to_thread(_preload_whisper)
    yield
    # nothing to cleanup


app = FastAPI(title="Podcast Pipeline API", lifespan=lifespan)

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

# Serve voice_samples directory for reference audio playback
VOICE_SAMPLES_DIR = Path("./voice_samples")
VOICE_SAMPLES_DIR.mkdir(exist_ok=True)
app.mount("/voice_samples", StaticFiles(directory=VOICE_SAMPLES_DIR), name="voice_samples")

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
    voice_id: str = ""        # UUID of a saved voice clone (optional)
    output_dir: str = "./outputs"
    llm_url: str = ""
    llm_key: str = ""
    llm_model: str = ""
    pause_for_review: bool = False  # pause after audio_design so user can edit script


class ResumeRequest(BaseModel):
    run_id: str
    segments: Optional[list[dict]] = None  # optional user-edited segments

class SettingsRequest(BaseModel):
    llm_url: str = ""
    llm_key: str = ""
    llm_model: str = ""
    tts_model: str = ""

class VideoRequest(BaseModel):
    audio_url: str
    srt_url: str = ""
    title: str = "Podcast Episode"


class VisualRegenRequest(BaseModel):
    run_id: str
    cue_index: int
    prompt: Optional[str] = None    # None → keep existing prompt, just re-seed
    seed: Optional[int] = None      # None → random new seed
    use_cogvideox: bool = True      # if False, skip the t2v pass for this cue


class EstimateRequest(BaseModel):
    minutes: int = 5
    tts_backend: str = "kokoro"
    dry_run: bool = False
    multi_voice: bool = False


class RegenerateSegmentRequest(BaseModel):
    run_id: str
    segment_name: str
    edited_text: Optional[str] = None  # if provided, skip writer and use this exact text


# Rough wall-clock estimates per node, in seconds. Tuned for a modest desktop CPU
# + GPU; users can recalibrate by editing these constants.
_NODE_BASE_COST_S = {
    "topic_refine": 3.0,
    "search":       8.0,
    "write":        4.0,        # plus per-minute below
    "fact_check":   3.0,
    "audio_design": 2.0,
    "tts":          5.0,
    "post_production": 8.0,
    "assemble":     3.0,
}
# Per-minute-of-target-audio multipliers, in seconds per minute.
_NODE_PER_MIN_COST_S = {
    "write":        4.5,
    "fact_check":   3.0,
    "audio_design": 2.0,
    "assemble":     0.4,
}
# TTS realtime factors: seconds of synthesis per second of audio output.
_TTS_RT_FACTOR = {
    "kokoro":     0.30,
    "chatterbox": 0.55,
    "bark":       1.70,
    "qwen":       1.20,
}
# Post-production (whisper + ffmpeg loudnorm) realtime factor: seconds of work
# per second of input audio.
_POST_PROD_RT_FACTOR = 0.20

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/estimate")
async def estimate_run(req: EstimateRequest):
    """
    Estimate generation time before the user kicks off a full run.
    Returns total seconds and a per-node breakdown so the frontend can
    show 'Est. X minutes' next to the Generate button.
    """
    minutes = max(1, int(req.minutes))
    backend = (req.tts_backend or "kokoro").lower()

    if req.dry_run:
        # Dry run skips LLM + TTS heavy work; mostly file I/O
        breakdown = {n: 0.5 for n in _NODE_BASE_COST_S}
        breakdown["assemble"] = 2.0
        total = sum(breakdown.values())
        return {
            "total_seconds": int(total),
            "total_human":   _seconds_human(total),
            "breakdown":     breakdown,
            "dry_run":       True,
        }

    audio_seconds = minutes * 60
    rt = _TTS_RT_FACTOR.get(backend, 0.6)

    breakdown: dict[str, float] = {}
    for node, base in _NODE_BASE_COST_S.items():
        per_min = _NODE_PER_MIN_COST_S.get(node, 0.0)
        cost = base + per_min * minutes
        if node == "tts":
            cost = base + audio_seconds * rt
        elif node == "post_production":
            cost = base + audio_seconds * _POST_PROD_RT_FACTOR
        breakdown[node] = round(cost, 1)

    total = sum(breakdown.values())
    return {
        "total_seconds": int(total),
        "total_human":   _seconds_human(total),
        "breakdown":     breakdown,
        "tts_backend":   backend,
        "minutes":       minutes,
    }


def _seconds_human(secs: float) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"

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
            ep_dir = meta_path.parent
            rel = ep_dir.relative_to(OUTPUTS_DIR).as_posix()
            # Probe for files served via /outputs/...
            audio_url     = f"/outputs/{rel}/episode.mp3" if (ep_dir / "episode.mp3").exists() else None
            thumbnail_url = f"/outputs/{rel}/thumbnail.png" if (ep_dir / "thumbnail.png").exists() else None
            video_url     = f"/outputs/{rel}/episode.mp4" if (ep_dir / "episode.mp4").exists() else None
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
                "has_audio": bool(audio_url),
                "audio_url": audio_url,
                "thumbnail_url": thumbnail_url,
                "video_url": video_url,
            })
        except Exception:
            continue
    episodes.sort(key=lambda e: e.get("generated_at", ""), reverse=True)
    return {"episodes": episodes}


@app.post("/api/regenerate-segment")
async def regenerate_segment(req: RegenerateSegmentRequest):
    """
    Regenerate a single segment of an existing episode.
    Steps: writer (or use edited_text) -> audio_design -> invalidate TTS cache for that segment
           -> TTS (synthesizes only the missing chunk) -> post_production -> assemble.
    Streams progress via SSE.
    """
    # Locate the episode
    ep_dir = None
    metadata = None
    for meta_path in OUTPUTS_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("run_id") == req.run_id or meta_path.parent.name == req.run_id:
            ep_dir = meta_path.parent
            metadata = meta
            break

    if not ep_dir or not metadata:
        raise HTTPException(status_code=404, detail=f"Episode '{req.run_id}' not found")

    segments = list(metadata.get("segments") or [])
    if not segments:
        raise HTTPException(status_code=400, detail="Episode metadata has no segments — regenerate not possible")

    target_idx = next((i for i, s in enumerate(segments) if s.get("name") == req.segment_name), -1)
    if target_idx < 0:
        raise HTTPException(status_code=404, detail=f"Segment '{req.segment_name}' not found in episode")

    # Invalidate the TTS WAV for this segment so the cache miss forces re-synth
    import re as _re
    safe_name = _re.sub(r"[^\w\-]", "_", req.segment_name).strip("_")
    seg_wav = ep_dir / "tts_segments" / f"{target_idx:02d}_{safe_name}.wav"
    if seg_wav.exists():
        try:
            seg_wav.unlink()
        except Exception:
            pass

    async def event_stream():
        yield json.dumps({"stage": "Starting", "pct": 2, "msg": f"Regenerating '{req.segment_name}'..."})

        # Build a minimal state from metadata + a writer call
        from agents.writer_agent import _write_segment, _format_sources
        from agents.audio_designer_agent import _llm_markers, _rule_based_markers
        from agents.tts_agent import run_tts_node
        from agents.post_production_agent import run_post_production_node
        from agents.assembler_agent import run_assembler_node
        from constants import CUE_MAP, TRANSITION_CUE
        from llm_client import get_client

        client = get_client() if not metadata.get("dry_run") else None
        sources = metadata.get("sources", [])
        sources_block = _format_sources(sources)

        seg = segments[target_idx]
        topic = metadata.get("podcast_topic", "")
        tone = metadata.get("tone", "conversational")
        audience = metadata.get("audience", "general listeners")

        # Step 1: writer (or edited override)
        yield json.dumps({"stage": "Writing", "pct": 12, "msg": "Generating new copy for the segment..."})
        if req.edited_text and req.edited_text.strip():
            new_text = req.edited_text.strip()
        else:
            new_text = await _write_segment(
                client, req.segment_name, int(seg.get("target_words", 200)),
                topic, tone, audience, sources_block, "",
                bool(metadata.get("dry_run")),
                narrative_arc=metadata.get("narrative_arc", ""),
            )

        # Step 2: audio design (prosody markers + cue)
        yield json.dumps({"stage": "Audio design", "pct": 30, "msg": "Adding prosody markers..."})
        cue = CUE_MAP.get(req.segment_name, TRANSITION_CUE if target_idx > 0 else "")
        prefix = f"{cue}\n" if cue else ""
        marked = _rule_based_markers(new_text) if (metadata.get("dry_run") or not client) else \
                 await _llm_markers(client, req.segment_name, new_text)
        seg["text"] = prefix + marked
        from utils import count_words as _cw
        seg["actual_words"] = _cw(seg["text"])
        segments[target_idx] = seg

        # Step 3: rebuild state for TTS/post-production/assemble
        state = {
            "topic": topic,
            "refined_topic": topic,
            "tone": tone,
            "audience": audience,
            "target_minutes": metadata.get("target_minutes", 5),
            "target_words": metadata.get("target_words", 1000),
            "dry_run": bool(metadata.get("dry_run")),
            "multi_voice": False,
            "tts_backend": metadata.get("tts_backend") or "kokoro",
            "voice_gender": metadata.get("voice_gender") or "female",
            "voice_id": metadata.get("voice_id"),
            "output_dir": str(ep_dir),
            "episode_title": metadata.get("episode_title", "Episode"),
            "script_segments": segments,
            "sources": sources,
            "current_status": "Regenerate",
            "errors": [],
            "narrative_arc": metadata.get("narrative_arc", ""),
        }

        # Step 4: TTS — cached WAVs for OTHER segments stay; only target re-synthesizes
        yield json.dumps({"stage": "TTS", "pct": 45, "msg": "Synthesising replacement audio..."})
        tts_update = await run_tts_node(state)
        state.update(tts_update)

        # Step 5: post-production
        yield json.dumps({"stage": "Post-production", "pct": 75, "msg": "Re-mixing and remastering..."})
        pp_update = await run_post_production_node(state)
        state.update(pp_update)

        # Step 6: re-assemble
        yield json.dumps({"stage": "Assembly", "pct": 92, "msg": "Updating transcripts and metadata..."})
        asm_update = await run_assembler_node(state)
        state.update(asm_update)

        asm = state.get("final_assembly", {}) or {}
        def _rel(p):
            if not p: return None
            try:
                base = OUTPUTS_DIR.resolve()
                ap = Path(p).resolve()
                return f"/outputs/{ap.relative_to(base).as_posix()}"
            except Exception:
                return None

        yield json.dumps({
            "stage": "Complete",
            "pct": 100,
            "msg": f"'{req.segment_name}' regenerated successfully",
            "done": True,
            "audio_url": _rel(asm.get("audio_path")),
            "srt_url":   _rel(asm.get("srt_path")),
            "notes_url": _rel(asm.get("notes_path")),
            "run_id": req.run_id,
        })

    return EventSourceResponse(event_stream())


@app.post("/api/resume-generation")
async def resume_generation(req: ResumeRequest):
    """
    Resume a paused generation. Reads the stashed `_pending.json` for the run,
    optionally swaps in user-edited segments, then streams the remaining
    TTS → post-production → assembly stages via SSE.
    """
    # Locate pending state
    pending_path = None
    for p in OUTPUTS_DIR.rglob("_pending.json"):
        if p.parent.name == req.run_id:
            pending_path = p
            break
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("run_id") == req.run_id or data.get("episode_title"):
                # Fallback: match by output_dir containing run_id
                if req.run_id in str(p.parent):
                    pending_path = p
                    break
        except Exception:
            continue

    if not pending_path:
        raise HTTPException(status_code=404, detail=f"No paused state found for run '{req.run_id}'")

    try:
        state = json.loads(pending_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not load paused state: {exc}")

    # Optional override: user-edited segments from the script editor
    if req.segments:
        # Preserve any unspecified fields from the original segments
        original = {s.get("name"): s for s in state.get("script_segments", [])}
        merged = []
        for edited in req.segments:
            base = dict(original.get(edited.get("name"), {}))
            base.update(edited)
            merged.append(base)
        if merged:
            state["script_segments"] = merged

    async def event_stream():
        from agents.tts_agent import run_tts_node
        from agents.post_production_agent import run_post_production_node
        from agents.assembler_agent import run_assembler_node

        yield json.dumps({"stage": "Resuming", "pct": 72, "msg": "Starting TTS with reviewed script..."})

        # TTS
        try:
            update = await run_tts_node(state)
            state.update(update)
        except Exception as exc:
            yield json.dumps({"error": f"TTS failed: {exc}", "done": True})
            return
        yield json.dumps({"stage": "Post-production", "pct": 86, "msg": state.get("current_status", "TTS complete")})

        # Post-production
        try:
            update = await run_post_production_node(state)
            state.update(update)
        except Exception as exc:
            yield json.dumps({"error": f"Post-production failed: {exc}", "done": True})
            return
        yield json.dumps({"stage": "Assembly", "pct": 95, "msg": state.get("current_status", "Post-production complete")})

        # Assemble
        try:
            update = await run_assembler_node(state)
            state.update(update)
        except Exception as exc:
            yield json.dumps({"error": f"Assembly failed: {exc}", "done": True})
            return

        asm = state.get("final_assembly", {}) or {}
        def _rel(p):
            if not p: return None
            try:
                base = OUTPUTS_DIR.resolve()
                ap = Path(p).resolve()
                return f"/outputs/{ap.relative_to(base).as_posix()}"
            except Exception:
                return None

        # Cleanup the pending stash
        try:
            pending_path.unlink()
        except Exception:
            pass

        yield json.dumps({
            "stage": "Complete",
            "pct": 100,
            "msg": "Episode generation complete",
            "done": True,
            "audio_url": _rel(asm.get("audio_path")),
            "srt_url":   _rel(asm.get("srt_path")),
            "notes_url": _rel(asm.get("notes_path")),
            "run_id": req.run_id,
        })

    return EventSourceResponse(event_stream())


@app.delete("/api/episodes/{run_id}")
async def delete_episode(run_id: str):
    """Delete an episode directory by run_id. Returns the number of files removed."""
    import shutil
    for meta_path in OUTPUTS_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        ep_dir = meta_path.parent
        if meta.get("run_id") == run_id or ep_dir.name == run_id:
            # Safety: ensure the directory is actually inside OUTPUTS_DIR
            try:
                ep_dir.resolve().relative_to(OUTPUTS_DIR.resolve())
            except ValueError:
                raise HTTPException(status_code=400, detail="Refusing to delete: path escapes outputs/")
            removed = sum(1 for _ in ep_dir.rglob("*"))
            shutil.rmtree(ep_dir, ignore_errors=True)
            return {"deleted": True, "run_id": run_id, "files_removed": removed}
    raise HTTPException(status_code=404, detail=f"Episode '{run_id}' not found")


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
                    ("episode.mp4", "video_url"),
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


# ── Video generation ──────────────────────────────────────────────────────────

@app.post("/api/generate-video")
async def generate_video(req: VideoRequest):
    """
    Stream video generation progress via SSE.
    Accepts URLs served by /outputs/* and converts them to server paths.
    """
    def url_to_path(url: str) -> Optional[str]:
        if not url:
            return None
        # e.g. /outputs/episode_xxxx/episode.mp3  →  ./outputs/episode_xxxx/episode.mp3
        if url.startswith("/outputs/"):
            rel = url[len("/outputs/"):]
            return str(OUTPUTS_DIR / rel)
        return None

    audio_path = url_to_path(req.audio_url)
    srt_path   = url_to_path(req.srt_url) or ""

    if not audio_path or not Path(audio_path).exists():
        raise HTTPException(status_code=400, detail="Audio file not found")

    # Derive output directory from the audio file location
    out_dir = Path(audio_path).parent

    async def event_stream():
        import queue, threading

        q: queue.Queue = queue.Queue()

        def progress_cb(msg: str, pct: int) -> None:
            q.put({"msg": msg, "pct": pct})

        def _run():
            from agents.video_agent import generate_podcast_video
            # Pull the segments persisted by the assembler so the visual_agent
            # can derive gap-filler prompts from real script context.
            script_segments: list[dict] = []
            try:
                meta_file = out_dir / "metadata.json"
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    script_segments = meta.get("segments") or []
            except Exception:
                script_segments = []
            try:
                video_path = generate_podcast_video(
                    audio_path, srt_path, out_dir, req.title,
                    progress=progress_cb,
                    script_segments=script_segments,
                )
                q.put({"done": True, "video_path": video_path})
            except Exception as exc:
                q.put({"done": True, "error": str(exc)})

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        while True:
            try:
                item = q.get(timeout=0.5)
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue

            if item.get("done"):
                vp = item.get("video_path")
                if vp:
                    # Convert absolute path back to a /outputs/… URL
                    try:
                        rel = Path(vp).resolve().relative_to(OUTPUTS_DIR.resolve())
                        video_url = f"/outputs/{rel.as_posix()}"
                    except ValueError:
                        video_url = None
                    yield json.dumps({"done": True, "pct": 100, "video_url": video_url})
                else:
                    yield json.dumps({"done": True, "error": item.get("error", "Video generation failed")})
                break
            else:
                yield json.dumps({"done": False, "pct": item.get("pct", 0), "msg": item.get("msg", "")})
            await asyncio.sleep(0)

    return EventSourceResponse(event_stream())


# ── Visual cues (per-cue thumbnails + re-roll) ────────────────────────────────

def _find_episode_dir(run_id: str) -> Optional[Path]:
    """Locate an episode directory by run_id (or directory name)."""
    for meta_path in OUTPUTS_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("run_id") == run_id or meta_path.parent.name == run_id:
            return meta_path.parent
    return None


@app.get("/api/episodes/{run_id}/visuals")
async def list_visual_cues(run_id: str):
    """Return the [VISUAL:] cues for an episode plus per-cue thumbnail URLs.

    The thumbnail is the SDXL still that visual_agent rendered for this cue
    interval (under _visual_images/). If a CogVideoX clip exists in the
    cache, its URL is returned too.
    """
    ep_dir = _find_episode_dir(run_id)
    if ep_dir is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    cues_path = ep_dir / "visual_cues.json"
    if not cues_path.exists():
        return {"cues": [], "rel": ep_dir.relative_to(OUTPUTS_DIR).as_posix()}

    try:
        cues = json.loads(cues_path.read_text(encoding="utf-8"))
    except Exception:
        cues = []

    rel = ep_dir.relative_to(OUTPUTS_DIR).as_posix()

    # Lazy import so the module isn't loaded for non-visual endpoints.
    from agents.visual_agent import _cog_cache_key
    from constants import VISUAL_STYLE_SUFFIX

    enriched: list[dict] = []
    for i, cue in enumerate(cues):
        # Interval index in build_visual_bed isn't 1:1 with cue index because
        # the planner emits leading + trailing gap intervals around the cues.
        # We don't know the planner's interval id without re-running the plan,
        # so we expose the cue ordering and let the regenerate endpoint do
        # the lookup. Thumbnail name follows the planner's naming scheme.
        prompt = (cue.get("prompt") or "").strip()
        full_prompt = prompt if prompt.endswith(VISUAL_STYLE_SUFFIX) else f"{prompt}{VISUAL_STYLE_SUFFIX}"
        # Try a few seeds — the bed used 2000+i for CogVideoX cache; a re-roll
        # may have used a fresh random seed. We surface whichever clip exists.
        clip_url = None
        cache_dir = ep_dir / "_visual_cogvideox_cache"
        if cache_dir.exists():
            # Prefer the most recent clip whose hash matches *some* seed for
            # this prompt. Cheaper: just glob the cache and pick most-recent.
            matches = sorted(cache_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
            for cand in matches:
                # Recompute hash for default seed to identify the canonical clip.
                if cand.name.startswith(_cog_cache_key(full_prompt, 2000 + i)):
                    clip_url = f"/outputs/{rel}/_visual_cogvideox_cache/{cand.name}"
                    break

        enriched.append({
            "cue_index": i,
            "prompt": prompt,
            "start_ms": cue.get("start_ms", 0),
            "end_ms": cue.get("end_ms", 0),
            "thumbnail_url": None,  # filled below if the planner-named PNG exists
            "clip_url": clip_url,
        })

    # Best-effort thumbnail lookup. The planner inserts leading/trailing gap
    # intervals before the first cue, so cue N maps to interval (lead_gaps + N).
    # We don't know lead_gaps without re-planning, but we can scan
    # _visual_images/ for PNGs and match by chronological cue order: the cue
    # PNGs are interleaved with gap PNGs in start_ms order.
    images_dir = ep_dir / "_visual_images"
    if images_dir.exists():
        # Re-derive interval ordering using start_ms — we need both cues and
        # gaps. Without re-running the planner, fall back to: scan images dir,
        # sort by name (matches planner's "interval_NNN.png"), and pick the
        # ones whose start_ms aligns with each cue's start_ms.
        # Simplest: zip cues with the largest-N PNG that doesn't precede an
        # earlier cue's match. The planner is deterministic, so we re-run it
        # cheaply here to get the exact interval index per cue.
        try:
            from agents.visual_agent import _plan_intervals
            # Read script_segments from metadata so gap-prompt derivation matches
            meta = json.loads((ep_dir / "metadata.json").read_text(encoding="utf-8"))
            script_segs = meta.get("segments") or []
            # Audio duration (ms) — use end of last whisper word, or last cue
            ww_path = ep_dir / "whisper_words.json"
            if ww_path.exists():
                ww = json.loads(ww_path.read_text(encoding="utf-8"))
                duration_ms = int((ww[-1]["end"] if ww else 0) * 1000)
            else:
                duration_ms = max((c.get("end_ms", 0) for c in cues), default=0)
            intervals = _plan_intervals(cues, duration_ms, script_segs)
            cue_iter = iter(range(len(cues)))
            for iv_idx, iv in enumerate(intervals):
                if iv["kind"] != "cue":
                    continue
                try:
                    cue_idx = next(cue_iter)
                except StopIteration:
                    break
                png = images_dir / f"interval_{iv_idx:03d}.png"
                if png.exists():
                    enriched[cue_idx]["thumbnail_url"] = f"/outputs/{rel}/_visual_images/{png.name}"
                    enriched[cue_idx]["interval_index"] = iv_idx
        except Exception:
            pass

    return {"cues": enriched, "rel": rel}


@app.post("/api/visuals/regenerate")
async def regenerate_visual_cue(req: VisualRegenRequest):
    """Re-roll a single [VISUAL:] cue and re-stitch the bed.

    1. Update visual_cues.json with the new prompt (if provided).
    2. Re-run visual_agent on JUST this interval — SDXL still + (optional)
       CogVideoX clip with a fresh seed.
    3. Re-stitch _visual_bed.mp4 from the existing per-interval clips on disk
       so the rest of the bed isn't regenerated.
    Streams progress via SSE.
    """
    ep_dir = _find_episode_dir(req.run_id)
    if ep_dir is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    cues_path = ep_dir / "visual_cues.json"
    if not cues_path.exists():
        raise HTTPException(status_code=404, detail="visual_cues.json not found for this episode")

    try:
        cues = json.loads(cues_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not parse visual_cues.json: {exc}")

    if req.cue_index < 0 or req.cue_index >= len(cues):
        raise HTTPException(status_code=400, detail=f"cue_index {req.cue_index} out of range (0..{len(cues)-1})")

    # Apply prompt edit immediately so the on-disk record matches what the
    # user asked for, even if the regen below crashes mid-way.
    if req.prompt is not None:
        cues[req.cue_index]["prompt"] = req.prompt
        cues_path.write_text(json.dumps(cues, indent=2), encoding="utf-8")

    async def event_stream():
        import queue, threading, random

        q: queue.Queue = queue.Queue()

        def progress_cb(msg: str, pct: int) -> None:
            q.put({"msg": msg, "pct": pct})

        def _run():
            try:
                from agents.visual_agent import (
                    _SDXLBackend, _CogVideoXBackend, _ken_burns_clip,
                    _stretch_clip_to_duration, _cog_cache_dir, _cog_cache_key,
                    _plan_intervals, _concat_with_crossfade,
                )
                from constants import (
                    SDXL_WIDTH, SDXL_HEIGHT, VISUAL_STYLE_SUFFIX,
                )

                # Re-derive intervals so we know which interval index this cue
                # maps to (the planner interleaves gap intervals).
                meta = json.loads((ep_dir / "metadata.json").read_text(encoding="utf-8"))
                script_segs = meta.get("segments") or []
                ww_path = ep_dir / "whisper_words.json"
                if ww_path.exists():
                    ww = json.loads(ww_path.read_text(encoding="utf-8"))
                    duration_ms = int((ww[-1]["end"] if ww else 0) * 1000)
                else:
                    duration_ms = max((c.get("end_ms", 0) for c in cues), default=0)
                intervals = _plan_intervals(cues, duration_ms, script_segs)

                # Find the interval id for this cue (Nth 'cue' interval).
                target_iv_idx = None
                cue_seen = -1
                for iv_idx, iv in enumerate(intervals):
                    if iv["kind"] == "cue":
                        cue_seen += 1
                        if cue_seen == req.cue_index:
                            target_iv_idx = iv_idx
                            break
                if target_iv_idx is None:
                    q.put({"done": True, "error": "Could not locate cue in interval plan"})
                    return

                iv = intervals[target_iv_idx]
                prompt = (iv.get("prompt") or "").strip()
                if not prompt.endswith(VISUAL_STYLE_SUFFIX):
                    prompt = f"{prompt}{VISUAL_STYLE_SUFFIX}"
                seed = req.seed if req.seed is not None else random.randint(1, 1_000_000)

                images_dir = ep_dir / "_visual_images"
                clips_dir = ep_dir / "_visual_clips"
                images_dir.mkdir(parents=True, exist_ok=True)
                clips_dir.mkdir(parents=True, exist_ok=True)

                # ── SDXL still ──
                progress_cb(f"Loading SDXL...", 5)
                if not _SDXLBackend.load():
                    q.put({"done": True, "error": "SDXL failed to load"})
                    return
                try:
                    progress_cb("Generating still...", 25)
                    img = _SDXLBackend.generate(prompt, seed=seed)
                    if img is None:
                        q.put({"done": True, "error": "SDXL returned no image"})
                        return
                    img_path = images_dir / f"interval_{target_iv_idx:03d}.png"
                    img.save(str(img_path), "PNG")
                finally:
                    _SDXLBackend.unload()

                # Ken-Burns wrap (used as fallback if CogVideoX is unavailable)
                progress_cb("Rendering Ken-Burns clip...", 45)
                kb_clip = clips_dir / f"interval_{target_iv_idx:03d}.mp4"
                if not _ken_burns_clip(img_path, iv["end_ms"] - iv["start_ms"], kb_clip):
                    q.put({"done": True, "error": "Ken-Burns render failed"})
                    return
                final_clip = kb_clip

                # ── CogVideoX clip (if requested + available) ──
                if req.use_cogvideox and _CogVideoXBackend.load():
                    try:
                        progress_cb("Generating t2v clip (this can take many minutes)...", 55)
                        raw = _cog_cache_dir(ep_dir) / f"{_cog_cache_key(prompt, seed)}.mp4"
                        if _CogVideoXBackend.generate(prompt, raw, seed=seed):
                            stretched = clips_dir / f"interval_{target_iv_idx:03d}_cog.mp4"
                            if _stretch_clip_to_duration(raw, stretched, iv["end_ms"] - iv["start_ms"]):
                                final_clip = stretched
                    finally:
                        _CogVideoXBackend.unload()

                # ── Re-stitch the bed using existing on-disk per-interval clips ──
                progress_cb("Re-stitching visual bed...", 90)
                ordered_clips: list[Path] = []
                for iv_idx in range(len(intervals)):
                    cog_path = clips_dir / f"interval_{iv_idx:03d}_cog.mp4"
                    kb_path = clips_dir / f"interval_{iv_idx:03d}.mp4"
                    if iv_idx == target_iv_idx:
                        ordered_clips.append(final_clip)
                    elif cog_path.exists():
                        ordered_clips.append(cog_path)
                    elif kb_path.exists():
                        ordered_clips.append(kb_path)
                    else:
                        # Per-interval clip got cleaned up after the original
                        # bed render — we can rebuild Ken-Burns from the
                        # cached PNG without re-running SDXL.
                        png = images_dir / f"interval_{iv_idx:03d}.png"
                        if png.exists():
                            rebuild = clips_dir / f"interval_{iv_idx:03d}.mp4"
                            iv_other = intervals[iv_idx]
                            if _ken_burns_clip(png, iv_other["end_ms"] - iv_other["start_ms"], rebuild):
                                ordered_clips.append(rebuild)

                if not ordered_clips:
                    q.put({"done": True, "error": "No per-interval clips on disk to stitch"})
                    return

                bed_path = ep_dir / "_visual_bed.mp4"
                if not _concat_with_crossfade(ordered_clips, bed_path):
                    q.put({"done": True, "error": "Bed stitch failed"})
                    return

                rel = ep_dir.relative_to(OUTPUTS_DIR).as_posix()
                q.put({
                    "done": True,
                    "thumbnail_url": f"/outputs/{rel}/_visual_images/interval_{target_iv_idx:03d}.png",
                    "bed_url": f"/outputs/{rel}/_visual_bed.mp4",
                    "interval_index": target_iv_idx,
                    "seed": seed,
                })
            except Exception as exc:
                q.put({"done": True, "error": str(exc)})

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        while True:
            try:
                item = q.get(timeout=0.5)
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            if item.get("done"):
                yield json.dumps(item)
                break
            yield json.dumps({"done": False, "pct": item.get("pct", 0), "msg": item.get("msg", "")})
            await asyncio.sleep(0)

    return EventSourceResponse(event_stream())


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
            voice_id=gen_req.voice_id.strip() or None,
            current_status="Initializing...",
            search_queries=[],
            sources=[],
            script_segments=[],
            episode_title=cfg.episode_title,
            tts_results={},
            final_assembly={},
            errors=[]
        )

        # Use run_id as the checkpoint thread_id so a crashed run can be resumed.
        graph_config = {"configurable": {"thread_id": cfg.run_id}}
        try:
            async for step_result in app_graph.astream(
                state, stream_mode="updates", config=graph_config,
            ):
                # step_result is a dict with key = node_name, value = state_update
                for node_name, state_update in step_result.items():
                    # Structured error handling: only "error" severity is fatal,
                    # warnings/info get surfaced as non-blocking notices.
                    new_errors = state_update.get("errors") or []
                    fatal = next((e for e in new_errors
                                  if isinstance(e, dict) and e.get("severity") == "error"), None)
                    if fatal:
                        yield json.dumps({
                            "error": fatal.get("message", "Unknown error"),
                            "node": fatal.get("node", node_name),
                            "done": True,
                        })
                        return
                    # Non-fatal notices: pass through as separate SSE events
                    for warn in new_errors:
                        if isinstance(warn, dict):
                            yield json.dumps({
                                "notice": warn.get("message", ""),
                                "severity": warn.get("severity", "info"),
                                "node": warn.get("node", node_name),
                            })

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

                    # Optional pause point — after audio_design, before TTS.
                    # User can review/edit the script in the frontend and POST
                    # to /api/resume-generation to continue.
                    if gen_req.pause_for_review and node_name == "audio_design":
                        pending_path = Path(cfg.output_dir) / "_pending.json"
                        pending_path.parent.mkdir(parents=True, exist_ok=True)
                        # Only stash JSON-serialisable fields
                        snap = {}
                        for k, v in state.items():
                            try:
                                json.dumps(v, default=str)
                                snap[k] = v
                            except Exception:
                                pass
                        pending_path.write_text(json.dumps(snap, default=str), encoding="utf-8")
                        yield json.dumps({
                            "stage": "Awaiting review",
                            "pct": 70,
                            "msg": "Script is ready — edit and click Resume to continue generation",
                            "paused": True,
                            "run_id": cfg.run_id,
                            "script_segments": state.get("script_segments", []),
                            "narrative_arc": state.get("narrative_arc", ""),
                        })
                        return  # client must call /api/resume-generation

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

# ---------------------------------------------------------------------------
# Voice Clone Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/voice-clone/chatterbox")
async def create_chatterbox_clone(
    name: str = Form(...),
    files: list[UploadFile] = File(...),
):
    """
    Upload one or more audio clips (WAV/MP3) to create a Chatterbox voice clone.
    The clips are concatenated into a single reference file (capped at 20 s).
    Returns the voice_id to pass in future /api/generate requests.
    """
    if not name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if not files:
        raise HTTPException(status_code=400, detail="at least one audio file is required")

    audio_clips: list[bytes] = []
    for upload in files:
        content_type = upload.content_type or ""
        if not any(t in content_type for t in ("audio", "octet-stream")):
            raise HTTPException(
                status_code=400,
                detail=f"'{upload.filename}' does not appear to be an audio file",
            )
        audio_clips.append(await upload.read())

    try:
        from voice_manager import get_voice_manager
        clone = get_voice_manager().create_chatterbox_voice_clone(
            name=name.strip(),
            audio_clips=audio_clips,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice clone failed: {e}")

    return {
        "voice_id": clone.voice_id,
        "name": clone.name,
        "duration_ms": clone.sample_duration_ms,
        "clips_merged": len(audio_clips),
    }


@app.get("/api/voice-clones")
async def list_voice_clones():
    """List all saved voice clones."""
    try:
        from voice_manager import get_voice_manager
        clones = get_voice_manager().list_voices()
        return {"voice_clones": [c.to_dict() for c in clones]}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to list voice clones: {e}")


@app.delete("/api/voice-clone/{voice_id}")
async def delete_voice_clone(voice_id: str):
    """Delete a voice clone and its reference audio file."""
    from voice_manager import get_voice_manager
    deleted = get_voice_manager().delete_voice_clone(voice_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Voice clone '{voice_id}' not found")
    return {"deleted": voice_id}


@app.get("/api/voice-clone/{voice_id}/reference")
async def get_voice_reference_audio(voice_id: str):
    """Serve the original reference audio WAV file for a voice clone."""
    from voice_manager import get_voice_manager
    clone = get_voice_manager().get_voice_clone(voice_id)
    if not clone:
        raise HTTPException(status_code=404, detail=f"Voice clone '{voice_id}' not found")
    audio_path = Path(clone.ref_audio_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Reference audio file not found")
    return FastAPIFileResponse(
        path=str(audio_path),
        media_type="audio/wav",
        filename=f"{clone.name}_reference.wav",
    )


@app.post("/api/voice-clone/{voice_id}/add-clips")
async def add_clips_to_voice_clone(
    voice_id: str,
    files: list[UploadFile] = File(...),
):
    """
    Append additional audio clips to an existing voice clone.
    The clips are merged onto the end of the existing reference file.
    If the total exceeds the cap, audio is trimmed from the start (keeping newest).
    """
    if not files:
        raise HTTPException(status_code=400, detail="at least one audio file is required")

    audio_clips: list[bytes] = []
    for upload in files:
        content_type = upload.content_type or ""
        if not any(t in content_type for t in ("audio", "octet-stream")):
            raise HTTPException(
                status_code=400,
                detail=f"'{upload.filename}' does not appear to be an audio file",
            )
        audio_clips.append(await upload.read())

    try:
        from voice_manager import get_voice_manager
        clone = get_voice_manager().append_clips_to_voice_clone(
            voice_id=voice_id,
            audio_clips=audio_clips,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Add clips failed: {e}")

    return {
        "voice_id": clone.voice_id,
        "name": clone.name,
        "duration_ms": clone.sample_duration_ms,
        "clips_added": len(audio_clips),
        "clone_type": clone.clone_type,
    }


class PreviewRequest(BaseModel):
    text: str = ""


@app.post("/api/voice-clone/{voice_id}/preview")
async def preview_voice_clone(voice_id: str, req: PreviewRequest):
    """
    Generate a short TTS preview using Chatterbox with the given voice clone.
    Returns the generated audio as a WAV file.
    """
    from voice_manager import get_voice_manager
    clone = get_voice_manager().get_voice_clone(voice_id)
    if not clone:
        raise HTTPException(status_code=404, detail=f"Voice clone '{voice_id}' not found")

    text = req.text.strip()
    if not text:
        text = "Hello, this is a preview of my voice clone. How does it sound?"

    audio_path = Path(clone.ref_audio_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Reference audio file not found")

    def _generate_preview():
        from agents.tts_agent import _ChatterboxBackend
        if not _ChatterboxBackend.load():
            raise RuntimeError(
                "Chatterbox TTS is not available. Install: pip install chatterbox-tts"
            )
        audio_arr, sr = _ChatterboxBackend.synthesise(
            text=text,
            audio_prompt_path=str(audio_path),
        )
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, audio_arr, sr, format="WAV")
        buf.seek(0)
        return buf.getvalue()

    try:
        wav_bytes = await asyncio.to_thread(_generate_preview)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {e}")

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": f'inline; filename="{clone.name}_preview.wav"'},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
