"""
constants.py — Central location for all tunable pipeline constants.
"""

# ---------------------------------------------------------------------------
# LLM temperatures
# ---------------------------------------------------------------------------
WRITER_TEMPERATURE = 0.75
FACT_CHECKER_TEMPERATURE = 0.2
AUDIO_DESIGNER_TEMPERATURE = 0.3
TITLE_TEMPERATURE = 0.9
DEFAULT_LLM_MAX_TOKENS = 10000

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
SEARCH_MAX_RESULTS = 50
SEARCH_MIN_RESULTS = 30
SEARCH_RETRY_DELAYS = [2, 5, 10]  # seconds between retries on rate-limit

# Source quality scoring
SEARCH_MAX_PER_PUBLISHER = 2     # cap to avoid one outlet dominating the script
SEARCH_RECENCY_BONUS_MONTHS = 12
SEARCH_RECENCY_PENALTY_YEARS = 5

# Domain reputation lists — case-insensitive substring match against the URL host.
# Reputable: established news, academic, government, primary sources.
REPUTABLE_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.co.uk", "bbc.com", "nytimes.com",
    "wsj.com", "ft.com", "theguardian.com", "washingtonpost.com",
    "bloomberg.com", "economist.com", "npr.org", "pbs.org",
    "nature.com", "science.org", "sciencemag.org", "arxiv.org",
    "nih.gov", "cdc.gov", "who.int", "europa.eu", ".gov", ".edu",
    "wired.com", "theverge.com", "arstechnica.com", "technologyreview.com",
    "stanford.edu", "mit.edu", "harvard.edu",
    "ieee.org", "acm.org",
}

# Content farms / low-quality SEO sites
LOW_QUALITY_DOMAINS = {
    "answers.com", "ehow.com", "wikihow.com", "buzzfeed.com",
    "examiner.com", "associatedcontent.com", "hubpages.com",
    "demand-media.com", "ezinearticles.com",
    "medium.com",   # too variable in quality; use sparingly
}

# ---------------------------------------------------------------------------
# WPM (Words Per Minute)
# ---------------------------------------------------------------------------
DEFAULT_WPM = 150
MIN_WPM = 140
MAX_WPM = 170

# ---------------------------------------------------------------------------
# Segment ratios
# ---------------------------------------------------------------------------
SEGMENT_RATIOS = {
    "intro": 0.05,
    "hook": 0.05,
    "outro": 0.10,
}

ALLOWED_DURATION_DRIFT = 0.07  # ±7%

# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
TTS_CHUNK_MAX_CHARS = 800
TTS_INTER_CHUNK_SILENCE_S = 0.3
TTS_INTER_SEGMENT_SILENCE_S = 0.5

# Per-chunk silence trimming — keep at most this much head/tail silence in raw TTS output.
# Chatterbox especially can emit 1-2s of leading/trailing silence per chunk.
TTS_CHUNK_TRIM_HEAD_MS = 200
TTS_CHUNK_TRIM_TAIL_MS = 200
TTS_SILENCE_THRESHOLD = 0.008   # amplitude (peak) below this counts as silence (~ -42 dBFS)

# Crossfade duration between consecutive segments when stitching the final MP3.
TTS_SEGMENT_CROSSFADE_MS = 300

# ---------------------------------------------------------------------------
# Audio output
# ---------------------------------------------------------------------------
AUDIO_SAMPLE_RATE = 48000
AUDIO_BITRATE = "192k"

# ---------------------------------------------------------------------------
# Audio designer cue map
# ---------------------------------------------------------------------------
CUE_MAP = {
    "Intro": "[CUE: INTRO_MUSIC]",
    "Hook": "[CUE: SFX_WHOOSH]",
    "Outro": "[CUE: OUTRO_MUSIC]",
    "Mid-Episode CTA": "[CUE: CTA_JINGLE]",
}
TRANSITION_CUE = "[CUE: CHAPTER_TRANSITION]"

# Mid-episode CTA — inserted automatically when target_minutes >= MID_CTA_MIN_MINUTES.
# This is the sentiment guide; the writer LLM phrases the actual copy itself.
MID_CTA_MIN_MINUTES = 6
MID_CTA_TEXT = (
    "Hey, quick favour — if you're getting value from this episode, "
    "share it with one friend who'd love it too. It genuinely helps the show grow. "
    "Now, back to it."
)

# ---------------------------------------------------------------------------
# Fact checker
# ---------------------------------------------------------------------------
MAX_QUOTE_WORDS = 25

# ---------------------------------------------------------------------------
# Tone options
# ---------------------------------------------------------------------------
TONE_OPTIONS = [
    "conversational",
    "formal",
    "investigative",
    "intimate",
    "humorous",
]

# ---------------------------------------------------------------------------
# Multi-voice speaker roles
# ---------------------------------------------------------------------------
SPEAKERS = ["host", "guest", "narrator"]

# ---------------------------------------------------------------------------
# TTS Backends — shown in the frontend dropdown
# ---------------------------------------------------------------------------
TTS_BACKENDS = ["kokoro", "bark", "qwen", "chatterbox"]
DEFAULT_TTS_BACKEND = "kokoro"

# Kokoro voice IDs (KPipeline, lang_code='a' = American English)
KOKORO_VOICES = {
    "host": "af_heart",  # warm female narrator — great for podcast
    "guest": "am_fenrir",  # calm male expert
    "narrator": "am_michael",  # authoritative male narrator
}

# Bark speaker presets — embed into the text prompt
BARK_VOICES = {
    "host": "[speaker/en_speaker_6]",
    "guest": "[speaker/en_speaker_1]",
    "narrator": "[speaker/en_speaker_9]",
}

# Qwen3-TTS backend variants
TTS_QWEN_BACKENDS = {
    "qwen_voice_design": {
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "description": "Natural language voice design (text prompts)",
    },
    "qwen_base": {
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "description": "Voice cloning (3sec samples) - Best for podcast consistency",
    },
    "qwen_base_small": {
        "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "description": "Voice cloning smaller model (faster, less GPU)",
    },
}
DEFAULT_TTS_QWEN_BACKEND = "qwen_base"

# Qwen3 voice cloning speakers - voice_id from user samples
TTS_VOICE_CLONE_SPEAKERS = {
    "host": "default_host",  # Will map to user's host voice clone
    "guest": "default_guest",  # Will map to user's guest voice clone
    "narrator": "default_narrator",  # Will map to user's narrator voice clone
}

# Qwen3-TTS VoiceDesign natural-language instructions (as fallback)
VOICE_DESCRIPTIONS = {
    "host": "A warm, confident, and energetic podcast host voice. Clear enunciation with natural enthusiasm.",
    "guest": "A calm, thoughtful, and knowledgeable expert voice. Slightly lower pitch with a measured pace.",
    "narrator": "A neutral, clear, and authoritative narrator voice. Even pacing with professional tone.",
}

# Voice cloning configuration
VOICE_CLONE_MIN_SAMPLE_DURATION_MS = 3000  # 3 seconds (from Qwen3 docs)
VOICE_CLONE_MAX_SAMPLE_DURATION_MS = 10000  # 10 seconds (recommendation)
VOICE_CLONE_STABILITY_THRESHOLD = 0.85  # Minimum similarity score for consistency
VOICE_CLONE_REALIGN_INTERVAL = 300  # Re-align after 5 min of generation

# ---------------------------------------------------------------------------
# Voice Gender Selection
# ---------------------------------------------------------------------------
GENDER_VOICES = {
    "kokoro": {
        "female": "af_heart",
        "male": "am_michael",
    },
    "bark": {
        "female": "[speaker/en_speaker_9]",
        "male": "[speaker/en_speaker_6]",
    },
    "qwen": {
        "female": "A clear, natural, and energetic female podcast host voice.",
        "male": "A deep, authoritative, and energetic male podcast host voice.",
    },
    "chatterbox": {
        # None = use Chatterbox built-in voice; replaced by ref audio path when a clone exists
        "female": None,
        "male": None,
    },
}

# ---------------------------------------------------------------------------
# Chatterbox TTS
# ---------------------------------------------------------------------------
CHATTERBOX_DEFAULT_EXAGGERATION = 0.4   # 0.25–2.0; 0.4 gives more expressive, natural delivery
CHATTERBOX_DEFAULT_CFG_WEIGHT = 0.5     # 0.0–1.0; official default is 0.5 — 0.7 caused repetition
CHATTERBOX_CHUNK_MAX_CHARS = 220        # Chatterbox repeats on long inputs; keep well under 250
CHATTERBOX_MAX_REFERENCE_DURATION_S = 900000  # cap merged reference audio at 60 s

# Voice consistency check (Chatterbox only) — opt-in via env. When enabled,
# each synthesised chunk is compared against the reference voice; chunks that
# drift below CHATTERBOX_MIN_SIMILARITY are re-rolled with a different seed
# (up to CHATTERBOX_MAX_REROLLS attempts).
ENABLE_VOICE_CONSISTENCY_CHECK = False
CHATTERBOX_MIN_SIMILARITY = 0.78
CHATTERBOX_MAX_REROLLS = 2
CHATTERBOX_REROLL_SEEDS = [42, 1337, 9001]

# ---------------------------------------------------------------------------
# Audio mastering (LUFS loudness normalization)
# ---------------------------------------------------------------------------
LUFS_TARGET = -16.0      # podcast standard; YouTube auto-normalizes to -14 LUFS
LUFS_TRUE_PEAK = -1.5    # dBTP ceiling
LUFS_LRA = 11.0          # loudness range

# ---------------------------------------------------------------------------
# Whisper alignment (real word-level timings for SRT + music placement)
# ---------------------------------------------------------------------------
WHISPER_MODEL = "base.en"      # tiny.en | base.en | small.en | medium.en
WHISPER_DEVICE = "auto"        # auto | cpu | cuda
WHISPER_COMPUTE_TYPE = "int8"  # int8 on CPU; float16 on GPU
WHISPER_BEAM_SIZE = 5

# Music ducking gain (dB reduction applied to background music under speech)
MUSIC_DUCK_DB = 10
# Sidechain ducking (dynamic, only ducks during speech)
MUSIC_DUCK_MODE = "sidechain"  # "sidechain" | "static"

# Podcast EQ shaping — applied BEFORE loudnorm in mastering pass so the
# normalization measurement reflects what the listener will hear.
# Chain: highpass(80Hz) → presence boost (+2dB @ 3kHz)
PODCAST_EQ_FILTER = "highpass=f=80,equalizer=f=3000:width_type=q:w=1:g=2"

# ---------------------------------------------------------------------------
# Visual generation (AI image/video bed driven by [VISUAL: ...] cues)
# ---------------------------------------------------------------------------
# SDXL is used for stills (gap fillers in Phase 2, and as keyframes / cue
# fallbacks in Phase 3). 16:9 aspect ratio matches the 1920x1080 video frame.
SDXL_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
SDXL_WIDTH = 1152      # supported SDXL aspect bucket close to 16:9 (1.8:1)
SDXL_HEIGHT = 640
SDXL_STEPS = 28
SDXL_GUIDANCE = 7.0
SDXL_NEGATIVE_PROMPT = (
    "text, watermark, signature, logo, low quality, blurry, deformed, "
    "extra limbs, bad anatomy, jpeg artifacts, oversaturated"
)
# Tail style suffix appended to every visual prompt so output stays cohesive.
VISUAL_STYLE_SUFFIX = (
    ", cinematic, photorealistic, dramatic lighting, 35mm film, "
    "shallow depth of field, 8k detail"
)

# Ken-Burns motion for each still inside the video bed.
VISUAL_KEN_BURNS_ZOOM = 1.15    # final zoom factor at end of each still's interval
VISUAL_KEN_BURNS_FPS = 30
VISUAL_BED_WIDTH = 1920
VISUAL_BED_HEIGHT = 1080
VISUAL_CROSSFADE_MS = 600       # crossfade duration between adjacent intervals

# t2v model (Phase 3). When the runtime can't load it, the bed falls back to
# SDXL stills at cue intervals.
COGVIDEOX_MODEL_ID = "THUDM/CogVideoX-5b"
COGVIDEOX_NUM_FRAMES = 49       # ~6 seconds at 8 fps native CogVideoX output
COGVIDEOX_NUM_INFERENCE_STEPS = 50
COGVIDEOX_GUIDANCE = 6.0
