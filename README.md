# 🎙️ Podcast Production Pipeline

A modular **multi-agent AI system** that produces a full podcast episode end-to-end:
Research → Script → Fact-check → Audio Design → TTS → Assembly

Powered by **LM Studio** (local LLM) + **QWEN TTS** (local transformers) with a modern **React + Vite** frontend and **FastAPI** backend.

---

## ✨ Features

| Feature | Detail |
|---|---|
| 🔍 **SearchAgent** | DuckDuckGo research, 3–7 sourced citations |
| ✍️ **WriterAgent** | Minute-accurate script at 140–170 wpm |
| ✅ **FactCheckerAgent** | Inline [SRC-N] citations, contradiction detection |
| 🎵 **AudioDesignerAgent** | Pause/emphasis/cue markers |
| 🔊 **TTSAgent** | Local QWEN TTS via `transformers` (no API key) |
| 📦 **AssemblerAgent** | SRT, transcript, show_notes.md, metadata.json |
| 🖥️ **React UI** | Modern, responsive interface with dynamic live streaming progress via SSE |

---

## 🚀 Quick Start

### 1. Backend Setup (FastAPI)

```bash
conda activate opensearch
pip install -r requirements.txt
```

**Configure API settings:**

```bash
cp .env.example .env
# Edit .env with your LM Studio URL (default: http://localhost:1234/v1)
```

*Note: You can also configure all settings directly in the **⚙️ Settings** tab of the React UI.*

**Start the Backend Pipeline Server:**

You can start the server using Python (which uses Uvicorn under the hood):

```bash
conda run -n opensearch python app.py
```

Alternatively, you can run it directly using Uvicorn with hot-reload enabled for development. Since the `uvicorn.exe` executable might be blocked by Windows Device Guard policies, we recommend running it via the Python module:

```bash
conda run -n opensearch python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

*The FastAPI backend will start running at **<http://localhost:8000>***

### 2. Frontend Setup (React + Vite)

Open a new terminal window:

```bash
cd frontend
npm install
npm run dev
```

*The React UI will open at **<http://localhost:5173>***

### 3. Start LM Studio

Launch LM Studio, load any instruct/chat model, and enable the local web server on port 1234.

---

## 🎛️ Using the UI

### 🎙️ Create Episode

Fill in your topic, duration, tone, and audience. Optionally add a custom timeline.
Enable **Dry Run** to skip LLM + TTS calls (uses stub text, no API required, useful for testing the UI flow).
Click **▶ Generate Podcast** — watch the live progress log, status messages, and progress bar as each AI agent runs.

### 📄 Script & Transcript

- Viewer for generated segments with citation highlights
- Full timestamped plain-text transcript
- SRT subtitle file preview

### 🔊 Audio Player

- Embedded waveform audio player
- Quick-download buttons for: MP3, TTS-Ready Script, SRT, Transcript, and Metadata

### 📋 Show Notes & Metadata

- Rendered episode show notes in rich text
- Full metadata JSON details (duration, bitrate, sources, wpm…)

### ⚙️ Settings

- LM Studio URL, API key, model selection dropdown
- QWEN TTS model path (HuggingFace ID or local path)
- Test Connection & Refresh Models utility

---

## 📁 Project Structure

```text
Podcast_pipeline/
├── app.py                    # FastAPI Backend (entry point)
├── pipeline.py               # Orchestrator (streaming state machine)
├── config.py                 # PipelineConfig dataclass
├── llm_client.py             # LM Studio client wrapper
├── utils.py                  # Shared utilities + SRT helpers
├── agents/                   # AI Agent logic
│   ├── search_agent.py       # DuckDuckGo web research
│   ├── writer_agent.py       # LLM script writing
│   ├── fact_checker_agent.py # Citation insertion
│   ├── audio_designer_agent.py # Prosody markers
│   ├── tts_agent.py          # QWEN TTS (local transformers)
│   └── assembler_agent.py    # Output packaging
├── frontend/                 # React + Vite Frontend UI
│   ├── package.json
│   ├── vite.config.js
│   └── src/                  # React components, contexts, and hooks
├── tests/                    # Unit & integration tests
├── requirements.txt
├── .env.example
└── outputs/                  # Generated episodes (auto-created)
```

---

## ⚙️ Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:1234/v1` | LM Studio server URL |
| `LLM_API_KEY` | `lm-studio` | Any string for local LM Studio |
| `LLM_MODEL` | `local-model` | Model ID to use for chat completions |
| `QWEN_TTS_MODEL` | `Qwen/Qwen3-TTS` | HuggingFace model ID or local path |
| `TRANSFORMERS_CACHE` | *(system default)* | HuggingFace model cache directory |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed origins for the FastAPI CORS middleware |

---

## 🏃 Running Tests

```bash
conda run -n opensearch python -m pytest tests/ -v
```

---

## 📤 Output Files

Every run creates a timestamped folder in `./outputs/<slug_timestamp>/`:

| File | Description |
|---|---|
| `episode.mp3` | Full audio (48 kHz / 192 kbps) |
| `episode_tts_ready.txt` | Clean text sent to TTS |
| `transcript.srt` | Timestamped SRT subtitles |
| `transcript.txt` | Plain-text transcript with [HH:MM:SS] markers |
| `transcript.html` | HTML transcript with coloured citation badges |
| `show_notes.md` | Rendered show notes with source links |
| `metadata.json` | Full machine-readable episode metadata |

---

## 📝 Script Timing Rules

- **Default WPM:** 150 (range: 140–170)
- **Allowed duration drift:** ±7%
- **Segment structure:** Intro (5%) → Hook (5%) → Chapters → Outro (10%)
- **Citation rule:** ≤ 25 words verbatim per source

---

## 🔊 QWEN TTS Notes

QWEN TTS is run **locally** via the `transformers` library pipeline natively on your machine structure.

- First run will download the model weights from HuggingFace (~several GB)
- GPU strongly recommended for real-time synthesis
- If the model fails to load or there are missing dependencies, the pipeline gracefully writes `episode_tts_ready.txt` and skips audio saving the operation

To use a pre-downloaded model weights directory entirely offline:

```bash
# In .env:
QWEN_TTS_MODEL=/absolute/path/to/local/Qwen3-TTS
```
