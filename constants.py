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
TTS_BACKENDS = ["kokoro", "bark", "qwen"]
DEFAULT_TTS_BACKEND = "kokoro"

# Kokoro voice IDs (KPipeline, lang_code='a' = American English)
KOKORO_VOICES = {
    "host":     "af_heart",    # warm female narrator — great for podcast
    "guest":    "am_fenrir",   # calm male expert
    "narrator": "am_michael",  # authoritative male narrator
}

# Bark speaker presets — embed into the text prompt
BARK_VOICES = {
    "host":     "[speaker/en_speaker_6]",
    "guest":    "[speaker/en_speaker_1]",
    "narrator": "[speaker/en_speaker_9]",
}

# Qwen3-TTS VoiceDesign natural-language instructions
VOICE_DESCRIPTIONS = {
    "host":     "A warm, confident, and energetic podcast host voice. Clear enunciation with natural enthusiasm.",
    "guest":    "A calm, thoughtful, and knowledgeable expert voice. Slightly lower pitch with a measured pace.",
    "narrator": "A neutral, clear, and authoritative narrator voice. Even pacing with professional tone.",
}

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
    }
}
