# Podcast Studio — Multi-Agent AI Podcast Pipeline

A local-first, end-to-end system that turns a one-line topic into a fully
produced podcast episode — researched, written, fact-checked, narrated,
mixed, captioned, and rendered as a 1080p YouTube-ready video.

Powered by **LM Studio** for the LLM, multiple **local TTS backends**
(Kokoro / Bark / Qwen / Chatterbox), **Whisper** for word-level alignment,
**FFmpeg** for audio/video assembly, and a modern **React + Vite** frontend
streaming live progress over Server-Sent Events.

No API keys. No cloud calls. Runs entirely on your machine.

---

## What it produces

Every run drops a timestamped folder in `./outputs/<slug_timestamp>/`:

| File | Description |
|---|---|
| `episode.mp3` | Full mastered audio with prosody, SFX/music cues |
| `episode.mp4` | 1080p video — gradient backdrop, waveform visualiser, burned subtitles |
| `thumbnail.png` | 1280×720 episode cover |
| `transcript.srt` | Word-accurate SRT (built from Whisper alignment) |
| `transcript.txt` | Plain-text transcript with `[HH:MM:SS]` markers |
| `transcript.html` | HTML transcript with coloured `[SRC-N]` citation badges |
| `show_notes.md` | Markdown show notes (intro, key points, source links) |
| `episode_tts_ready.txt` | Clean text actually sent to the TTS engine |
| `metadata.json` | Full machine-readable episode metadata |

---

## Features at a glance

- **Multi-agent LangGraph pipeline** — each stage is its own node, easy to swap, retry, or resume.
- **Multiple TTS backends** — choose Kokoro (fast, neural), Bark (expressive), Qwen-TTS (multilingual), or Chatterbox (voice cloning).
- **Voice cloning** — record / upload reference clips in the UI, generate episodes in your own voice via Chatterbox.
- **Inline citations** — every factual claim ties back to a `[SRC-N]` source; unsupported claims get flagged and rewritten automatically.
- **Word-accurate captions** — Whisper aligns the final audio so subtitle timing matches the actual speech.
- **Hardware video encoding** — auto-detects NVIDIA NVENC → AMD AMF → Intel QuickSync; falls back to libx264 only when nothing else is usable.
- **Resilient to flaky local LLMs** — fact-checker and audio-designer detect empty/truncated output (a common reasoning-model failure) and preserve the original text instead of wiping segments.
- **Episode library** — browse, preview, regenerate single segments, render video on demand, or delete past episodes.
- **RSS / iTunes feed** — `/api/feed.xml` exposes your local catalogue as a real podcast feed.
- **Crash-resilient** — optional SQLite checkpointing lets the pipeline resume from the last successful node.

---

## Quick start

### 1. Backend

```bash
conda activate opensearch          # or any Python 3.11+ env
pip install -r requirements.txt
cp .env.example .env               # optional — UI can edit settings too
python app.py
```

FastAPI starts at **http://localhost:8000**. With hot-reload:

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

UI opens at **http://localhost:5173**.

### 3. LM Studio

Launch LM Studio, load a chat/instruct model, enable the local server on port `1234`. Recommended models (in priority order):

| Model | Why |
|---|---|
| **Qwen2.5-14B-Instruct** (Q4_K_M, ~9 GB) | Best balance of speed and instruction-following on consumer GPUs |
| **Qwen2.5-7B-Instruct** (Q4_K_M, ~5 GB) | Fits on 8 GB cards |
| **Llama-3.1-8B-Instruct** | Solid alternative if Qwen feels too literal |
| **Mistral-Small-3-24B** (Q4_K_M, ~14 GB) | Highest quality if you have ≥16 GB VRAM |

> Avoid pure reasoning models (DeepSeek-R1 distills, QwQ, Qwen3-thinking, gpt-oss-reasoning) for mechanical tasks like prosody marking — they tend to burn the token budget inside `<think>` blocks. If you must use one, prepend `/no_think` to the system prompt.

### 4. (Optional) FFmpeg

Required for audio assembly and video rendering. On Windows, install a full
build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) — the minimal builds
ship without NVENC, so video will silently fall back to CPU encoding.

---

## The detailed pipeline flow

```
                    ┌──────────────────────────────┐
USER REQUEST  ──▶   │   FastAPI  /api/generate     │   SSE stream → UI
(topic, tone,       └──────────────┬───────────────┘
 minutes, voice…)                  │
                                   ▼
                       ┌──────────────────────┐
                       │  LangGraph workflow  │   PodcastState (TypedDict)
                       └──────────┬───────────┘
                                  │
   ┌──────────────────────────────┼──────────────────────────────┐
   │                              ▼                              │
   │  ┌────────────────────────────────────────────────────────┐ │
   │  │  1. topic_refiner_agent                                │ │
   │  │     Rewrites the raw user topic into a cleaner,        │ │
   │  │     researchable phrase. Sets state.refined_topic.     │ │
   │  └────────────────────────────────────────────────────────┘ │
   │                              ▼                              │
   │  ┌────────────────────────────────────────────────────────┐ │
   │  │  2. search_agent                                       │ │
   │  │     DuckDuckGo queries against the refined topic.      │ │
   │  │     Scrapes 3–7 sources, extracts snippets, ranks for  │ │
   │  │     relevance/recency. Populates state.sources.        │ │
   │  └────────────────────────────────────────────────────────┘ │
   │                              ▼                              │
   │  ┌────────────────────────────────────────────────────────┐ │
   │  │  3. writer_agent                                       │ │
   │  │     (a) Generates a 5-line "narrative arc" spine       │ │
   │  │         (premise / tension / revelation / resolution / │ │
   │  │         callback) so every segment shares one story.   │ │
   │  │     (b) Walks the segment plan from PipelineConfig:    │ │
   │  │         Hook → Intro → Chapter 1..N → (Mid-CTA) →      │ │
   │  │         Outro. Each segment gets its own prompt with   │ │
   │  │         distinct instructions and target word count.   │ │
   │  │     (c) Generates the episode title.                   │ │
   │  │     Output → state.script_segments + episode_title.    │ │
   │  └────────────────────────────────────────────────────────┘ │
   │                              ▼                              │
   │  ┌────────────────────────────────────────────────────────┐ │
   │  │  4. fact_checker_agent                                 │ │
   │  │     For each segment:                                  │ │
   │  │     • Asks the LLM to insert [SRC-N] markers where     │ │
   │  │       claims are supported by sources.                 │ │
   │  │     • Returns a ---FLAGGED--- list of unsupported      │ │
   │  │       factual claims.                                  │ │
   │  │     • If anything is flagged, calls writer's           │ │
   │  │       revise_segment_text() to rewrite the offending   │ │
   │  │       sentences, then re-cites the revised text.       │ │
   │  │     • Guard: if LLM output collapses below 50% of the  │ │
   │  │       original word count (truncation, refusal,        │ │
   │  │       reasoning-loop), the original segment is kept.   │ │
   │  └────────────────────────────────────────────────────────┘ │
   │                              ▼                              │
   │  ┌────────────────────────────────────────────────────────┐ │
   │  │  5. audio_designer_agent                               │ │
   │  │     Inserts prosody markers without changing words:    │ │
   │  │     [PAUSE 500ms|1s|2s], [EMPHASIS]…[/EMPHASIS], and   │ │
   │  │     music/SFX cue tags ([CUE: INTRO_MUSIC] etc).       │ │
   │  │     Strips [SRC-N] before the LLM call so they aren't  │ │
   │  │     spoken as "SRC three", then re-applies them on     │ │
   │  │     fallback so citations survive.                     │ │
   │  └────────────────────────────────────────────────────────┘ │
   │                              ▼                              │
   │  ┌────────────────────────────────────────────────────────┐ │
   │  │  6. tts_agent                                          │ │
   │  │     Routes to the chosen backend:                      │ │
   │  │     • kokoro     — fast neural TTS, multi-voice        │ │
   │  │     • bark       — expressive, music/sfx capable       │ │
   │  │     • qwen       — multilingual via transformers       │ │
   │  │     • chatterbox — voice cloning from reference clips  │ │
   │  │     Per-segment audio clips go to state.tts_results.   │ │
   │  └────────────────────────────────────────────────────────┘ │
   │                              ▼                              │
   │  ┌────────────────────────────────────────────────────────┐ │
   │  │  7. post_production_agent                              │ │
   │  │     Concatenates clips, applies pause durations from   │ │
   │  │     [PAUSE …] markers, then runs Whisper on the final  │ │
   │  │     audio to get word-level timestamps. Result is the  │ │
   │  │     state.whisper_words list used for accurate SRT.    │ │
   │  └────────────────────────────────────────────────────────┘ │
   │                              ▼                              │
   │  ┌────────────────────────────────────────────────────────┐ │
   │  │  8. audio_mixer_agent (invoked from assembler)         │ │
   │  │     Walks [CUE: …] markers in the script, looks up     │ │
   │  │     matching assets in ./assets/, and mixes them into  │ │
   │  │     the master under the narration with ducking.       │ │
   │  └────────────────────────────────────────────────────────┘ │
   │                              ▼                              │
   │  ┌────────────────────────────────────────────────────────┐ │
   │  │  9. assembler_agent                                    │ │
   │  │     Writes the final artifacts:                        │ │
   │  │       episode.mp3, transcript.srt, transcript.txt,     │ │
   │  │       transcript.html, show_notes.md, metadata.json,   │ │
   │  │       episode_tts_ready.txt                            │ │
   │  └────────────────────────────────────────────────────────┘ │
   └─────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                  ┌───────────────────────────────┐
                  │  On-demand stages (UI driven) │
                  └───────────────────────────────┘
   ┌─────────────────────────────────────────────────────────────┐
   │  thumbnail_agent  — generates thumbnail.png                 │
   │  video_agent      — renders episode.mp4 (1080p, waveform,   │
   │                     burned subtitles, hardware-encoded)     │
   │  Per-segment regen — /api/regenerate-segment re-runs only   │
   │                     writer→fact_check→audio_designer→tts    │
   │                     for the selected segment, then rebuilds │
   │                     the master.                             │
   └─────────────────────────────────────────────────────────────┘
```

### Why each stage exists

| Stage | What problem it solves |
|---|---|
| Topic refiner | LLMs research vague topics badly. Cleaning the topic up front improves source quality. |
| Search | Grounds the script in real facts. Sources are required for citation. |
| Writer + narrative arc | Without a shared arc, multi-segment scripts feel disjointed. The arc pass is one extra LLM call that fixes this. |
| Fact-checker + revision loop | Local LLMs hallucinate statistics. Flagging + rewriting is cheaper than human review. |
| Audio designer | Plain TTS sounds robotic. Pause/emphasis markers add cadence. |
| TTS routing | Different backends suit different episodes (clone vs. multilingual vs. fast). |
| Post-production (Whisper) | TTS-engine timestamps are wrong after silence insertion. Whisper realigns to the actual audio. |
| Audio mixer | Cues in the script (`[CUE: INTRO_MUSIC]`) become real audio assets in the master. |
| Assembler | Single source of truth for output paths; downstream UI never has to guess where files live. |
| Thumbnail / video | Optional, billed separately (rendering is slow). Run on demand from the UI. |

### State shape (`graph.py:PodcastState`)

```
topic, refined_topic, tone, audience, target_words, target_minutes,
constraints, output_dir, dry_run, multi_voice, tts_backend,
voice_gender, voice_id,            ← inputs
current_status,                    ← live status string streamed to UI
search_queries, sources,           ← from search_agent
script_segments, episode_title,    ← from writer (mutated by fact_check + audio_design)
tts_results,                       ← from tts_agent
whisper_words,                     ← from post_production
final_assembly,                    ← from assembler (audio_path, srt_path, …)
errors[]                           ← accumulated structured error records
```

---

## Using the UI

The frontend is a single-page React app with three top-level tabs:

### Generate
- Topic / tone / audience / duration form.
- Voice selection (gender + backend, or a custom voice clone).
- "Dry run" toggle skips all LLM and TTS calls — useful for testing the UI flow without burning GPU time.
- Live progress: animated agent avatar, stage timeline, per-stage status messages, real-time log stream.
- Results panel surfaces audio player, video generation card, show notes, citations, and the full script viewer.

### Voice Profiles
- Record or upload reference clips (3–30 seconds each) and tag them with a name.
- Sample voices use Chatterbox under the hood.
- Preview a clone before using it for an episode.

### Library
- Browse every episode in `./outputs/`.
- Detail view shows audio player, video player (or "Generate video" if none yet), full transcript, show notes, citations, and per-segment regenerate buttons.
- Delete or re-render any artifact.

---

## API surface

| Endpoint | Purpose |
|---|---|
| `POST /api/generate` | Start a full pipeline run; streams SSE progress |
| `POST /api/regenerate-segment` | Re-run writer → fact-check → audio → TTS for one segment |
| `POST /api/resume-generation` | Resume from last checkpoint after a crash |
| `POST /api/generate-video` | Render `episode.mp4` (SSE progress) |
| `POST /api/estimate` | Cost / token / duration estimate for a config |
| `GET  /api/episodes` | List all episodes |
| `GET  /api/episodes/{run_id}` | Full episode detail + file URLs |
| `DELETE /api/episodes/{run_id}` | Delete an episode folder |
| `GET  /api/feed.xml` | RSS / iTunes podcast feed |
| `POST /api/voice-clone/chatterbox` | Register a new voice clone |
| `GET  /api/voice-clones` | List clones |
| `GET  /api/voice-clone/{id}/reference` | Download reference clip |
| `POST /api/voice-clone/{id}/add-clips` | Add more clips to an existing clone |
| `POST /api/voice-clone/{id}/preview` | Generate a preview of arbitrary text |
| `DELETE /api/voice-clone/{id}` | Delete a clone |
| `GET  /api/settings` · `POST /api/settings/save` | Read/write `.env` |
| `POST /api/settings/test-connection` | Ping LM Studio |
| `GET  /api/settings/models` | List available LM Studio models |
| `GET  /api/health` · `GET /api/ready` | Liveness / readiness |

---

## Project structure

```
Podcast-Creator-End-to-End-Solution/
├── app.py                         # FastAPI backend (SSE streaming endpoints)
├── graph.py                       # LangGraph workflow + PodcastState shape
├── pipeline.py                    # Legacy streaming orchestrator (kept for tests)
├── config.py                      # PipelineConfig dataclass + segment planner
├── constants.py                   # WPM, cues, TTS backend metadata, temperatures
├── llm_client.py                  # OpenAI-compatible LM Studio client
├── voice_manager.py               # Voice-clone persistence + Chatterbox glue
├── utils.py                       # Logging, SRT helpers, LLM-noise stripping
├── rss.py                         # RSS/iTunes feed generator
├── agents/
│   ├── topic_refiner_agent.py
│   ├── search_agent.py
│   ├── writer_agent.py
│   ├── fact_checker_agent.py
│   ├── audio_designer_agent.py
│   ├── tts_agent.py
│   ├── post_production_agent.py   # Whisper alignment
│   ├── audio_mixer_agent.py       # SFX/music mixing
│   ├── assembler_agent.py
│   ├── thumbnail_agent.py         # On-demand thumbnail render
│   └── video_agent.py             # On-demand 1080p video (NVENC/AMF/QSV/libx264)
├── frontend/
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx                # Tabbed shell (Generate / Voice / Library)
│       ├── motion.js              # Shared framer-motion presets
│       ├── components/
│       │   ├── ui/                # Card, Button, Input, Slider, Tooltip, …
│       │   ├── TopBar.jsx
│       │   ├── SettingsDrawer.jsx
│       │   ├── EpisodeConfigForm.jsx
│       │   ├── ProgressPanel.jsx
│       │   ├── ActiveAgentAvatar.jsx
│       │   ├── BackgroundScene.jsx
│       │   ├── ResultsPanel.jsx   # exports VideoSection reused in Library
│       │   ├── ScriptViewer.jsx
│       │   ├── ScriptEditor.jsx
│       │   ├── AudioPlayer.jsx
│       │   ├── SourcesList.jsx
│       │   ├── EpisodeLibrary.jsx
│       │   └── VoiceProfiles.jsx
│       └── hooks/
│           ├── useGeneration.js
│           ├── useSettings.js
│           └── useVoiceProfiles.js
├── assets/                        # Music / SFX assets referenced by [CUE: …]
├── voice_samples/                 # User-recorded voice clones (gitignored)
├── outputs/                       # Generated episodes (gitignored)
├── tests/
├── requirements.txt
└── docker-compose.yml
```

---

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:1234/v1` | LM Studio server URL |
| `LLM_API_KEY` | `lm-studio` | Any string — LM Studio doesn't check it |
| `LLM_MODEL` | `local-model` | Chat-completion model ID |
| `QWEN_TTS_MODEL` | `Qwen/Qwen3-TTS` | HuggingFace ID or local path |
| `TRANSFORMERS_CACHE` | *(system default)* | HF model cache directory |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Allowed origins for FastAPI |

All of these are editable from the **Settings** drawer in the UI; no need to touch `.env` directly.

---

## Script timing rules

- **Default WPM:** 150 (range 140–170, configurable per backend)
- **Allowed duration drift:** ±10% (writer) / ±7% (final)
- **Segment structure:** Hook → Intro → Chapter 1..N → (Mid-CTA if ≥ N minutes) → Outro
- **Citation rule:** ≤ 25 words verbatim per source

---

## Running tests

```bash
python -m pytest tests/ -v
```

The test suite covers individual agent class wrappers, the LangGraph workflow,
and SRT / metadata generation. Tests run in `dry_run` mode so they don't need
LM Studio or any TTS model.

---

## License

MIT — see LICENSE if present.
