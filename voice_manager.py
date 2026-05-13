"""
voice_manager.py — Voice cloning management for Qwen3-TTS voice clones.

Manages voice sample storage, clone prompt caching, and voice consistency tracking.
Voice clones are persisted in SQLite and stored on disk as reference audio + cached prompts.

Database schema:
- voice_clones: stores metadata, usage stats, and consistency scores
- audio files: stored in VOICE_SAMPLES_DIR by voice_id
- prompts: cached in memory for performance, serialized as needed
"""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from utils import get_logger

logger = get_logger("VoiceManager")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Where voice samples are stored (3-5 second reference audio clips)
VOICE_SAMPLES_DIR = Path("./voice_samples")
VOICE_SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

# SQLite database path
VOICE_DB_PATH = Path("./voice_samples/voice_clones.db")
VOICE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Minimum sample duration for reliable cloning (3 seconds as per Qwen3 docs)
MIN_SAMPLE_DURATION_MS = 3000  # 3 seconds
MAX_SAMPLE_DURATION_MS = 10000  # 10 seconds max

# Stability threshold for detecting voice drift
CONSISTENCY_SCORE_THRESHOLD = 0.85  # Alert if drift >15%


# ---------------------------------------------------------------------------
# Voice Clone Dataclass
# ---------------------------------------------------------------------------
@dataclass
class VoiceClone:
    """Represents a voice clone with metadata and cached prompt."""

    voice_id: str
    name: str
    created_at: float
    ref_audio_path: str
    ref_transcript: str
    sample_duration_ms: int
    clone_type: str  # "instant" (3-sec) or "extended" (10+ sec)
    voice_clone_prompt_blob: bytes  # Pickled/cached prompt for reuse
    usage_count: int = 0
    last_used_at: float = 0.0
    average_consistency_score: float = 0.0  # 0-1.0, updated after each generation
    quality_check_passed: bool = False
    stability_score: float = 0.0

    def to_dict(self):
        """Convert to dict for JSON serialization (strips prompt for size)."""
        d = asdict(self)
        # Don't serialize the full prompt blob in API responses (it's large)
        d.pop("voice_clone_prompt_blob", None)
        return d


# ---------------------------------------------------------------------------
# SQLite DB Manager
# ---------------------------------------------------------------------------
class SQLiteVoiceDB:
    """Thread-safe SQLite wrapper for voice clone persistence."""

    _init_lock = threading.Lock()
    _connection_pool = {}  # thread_id -> connection

    @classmethod
    def _init_db(cls):
        """Create tables if they don't exist."""
        with cls._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS voice_clones (
                    voice_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    ref_audio_path TEXT NOT NULL,
                    ref_transcript TEXT NOT NULL,
                    sample_duration_ms INTEGER NOT NULL,
                    clone_type TEXT NOT NULL,
                    voice_clone_prompt_blob BLOB NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    last_used_at REAL DEFAULT 0.0,
                    average_consistency_score REAL DEFAULT 0.0,
                    quality_check_passed BOOLEAN DEFAULT FALSE,
                    stability_score REAL DEFAULT 0.0
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_name ON voice_clones(name)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_created_at ON voice_clones(created_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_usage ON voice_clones(usage_count)"
            )
            conn.commit()

    @classmethod
    def _get_conn(cls):
        """Get thread-local SQLite connection."""
        thread_id = threading.get_ident()
        if thread_id not in cls._connection_pool:
            conn = sqlite3.connect(str(VOICE_DB_PATH))
            conn.row_factory = sqlite3.Row
            cls._connection_pool[thread_id] = conn
        return cls._connection_pool[thread_id]

    def __enter__(self):
        """Initialize DB on first use within thread."""
        with self._init_lock:
            if not self._connection_pool.get(threading.get_ident()):
                conn = sqlite3.connect(str(VOICE_DB_PATH))
                conn.row_factory = sqlite3.Row
                self._connection_pool[threading.get_ident()] = conn
            self.conn = self._connection_pool[threading.get_ident()]
            # Create tables if they don't exist
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS voice_clones (
                    voice_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    ref_audio_path TEXT NOT NULL,
                    ref_transcript TEXT NOT NULL,
                    sample_duration_ms INTEGER NOT NULL,
                    clone_type TEXT NOT NULL,
                    voice_clone_prompt_blob BLOB NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    last_used_at REAL DEFAULT 0.0,
                    average_consistency_score REAL DEFAULT 0.0,
                    quality_check_passed BOOLEAN DEFAULT FALSE,
                    stability_score REAL DEFAULT 0.0
                )
            """)
            self.conn.commit()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Exit context manager - connection stays in pool for reuse."""
        pass

    def save_voice_clone(self, voice: VoiceClone) -> str:
        """Insert or update a voice clone."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO voice_clones VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """,
            (
                voice.voice_id,
                voice.name,
                voice.created_at,
                voice.ref_audio_path,
                voice.ref_transcript,
                voice.sample_duration_ms,
                voice.clone_type,
                voice.voice_clone_prompt_blob,
                voice.usage_count,
                voice.last_used_at,
                voice.average_consistency_score,
                voice.quality_check_passed,
                voice.stability_score,
            ),
        )
        self.conn.commit()
        return voice.voice_id

    def get_voice_clone(self, voice_id: str) -> Optional[VoiceClone]:
        """Retrieve a voice clone by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM voice_clones WHERE voice_id = ?", (voice_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return VoiceClone(**dict(row))

    def list_voice_clones(self) -> list[VoiceClone]:
        """List all voice clones."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM voice_clones ORDER BY created_at DESC")
        results = []
        for row in cursor.fetchall():
            try:
                results.append(VoiceClone(**dict(row)))
            except Exception as e:
                logger.warning("Skipping corrupt voice clone row: %s", e)
        return results

    def delete_voice_clone(self, voice_id: str) -> bool:
        """Delete a voice clone and its files."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT ref_audio_path FROM voice_clones WHERE voice_id = ?", (voice_id,)
        )
        row = cursor.fetchone()
        if row:
            # Delete sample file
            sample_path = Path(str(row["ref_audio_path"]))
            if sample_path.exists():
                sample_path.unlink()
        cursor.execute("DELETE FROM voice_clones WHERE voice_id = ?", (voice_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def increment_usage(self, voice_id: str) -> None:
        """Increment the usage count for a voice."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE voice_clones 
            SET usage_count = usage_count + 1, last_used_at = ?
            WHERE voice_id = ?
        """,
            (time.time(), voice_id),
        )
        self.conn.commit()

    def update_consistency_score(self, voice_id: str, new_score: float) -> None:
        """Update the running average consistency score."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE voice_clones 
            SET average_consistency_score = 
                (average_consistency_score * usage_count + ?) / (usage_count + 1)
            WHERE voice_id = ?
        """,
            (new_score, voice_id),
        )
        self.conn.commit()


# ---------------------------------------------------------------------------
# Voice Manager
# ---------------------------------------------------------------------------
class VoiceManager:
    """
    Main class for voice cloning operations using Qwen3-TTS.
    Manages reference audio storage, voice cloning, and prompt caching.
    """

    def __init__(self):
        # Initialize database connection accessor
        self.db = SQLiteVoiceDB()
        # Ensure DB is created
        with self.db:
            pass

    def create_voice_clone(
        self,
        name: str,
        ref_audio_bytes: bytes,
        ref_transcript: str,
        qwen_model,  # Qwen3TTSModel instance
    ) -> VoiceClone:
        """
        Create a new voice clone from a short audio sample.

        Args:
            name: Human-readable name for this voice
            ref_audio_bytes: Audio file content (wav/audio)
            ref_transcript: Text transcript of the reference audio
            qwen_model: Loaded Qwen3TTSModel

        Returns:
            VoiceClone with cached prompt, ready for generation
        """
        import soundfile as sf

        # Generate unique voice_id
        voice_id = str(uuid.uuid4())[:8]

        # Save reference audio to disk
        audio_path = VOICE_SAMPLES_DIR / f"{voice_id}_ref.wav"
        with open(audio_path, "wb") as f:
            f.write(ref_audio_bytes)

        # Validate and analyze reference audio
        try:
            audio_data, sample_rate = sf.read(str(audio_path))
            duration_ms = int(len(audio_data) / sample_rate * 1000)
        except Exception as e:
            logger.error(f"Failed to load reference audio: {e}")
            audio_path.unlink()
            raise ValueError("Invalid audio file format")

        # Validate sample duration
        if duration_ms < MIN_SAMPLE_DURATION_MS:
            audio_path.unlink()
            raise ValueError(
                f"Sample too short: {duration_ms}ms < {MIN_SAMPLE_DURATION_MS}ms"
            )

        if duration_ms > MAX_SAMPLE_DURATION_MS:
            logger.warning(
                f"Sample longer than recommended: {duration_ms}ms > {MAX_SAMPLE_DURATION_MS}ms"
            )
            clone_type = "extended"
        else:
            clone_type = "instant"

        # Use Qwen3-Base model to create voice clone prompt
        logger.info(
            f"[VoiceClone] Creating voice clone '{name}' (voice_id: {voice_id}, {duration_ms}ms, {clone_type})"
        )

        try:
            import torch

            with torch.inference_mode():
                # Create reusable prompt from reference
                prompt_items = qwen_model.create_voice_clone_prompt(
                    ref_audio=str(audio_path),
                    ref_text=ref_transcript,
                    x_vector_only_mode=False,  # Use full features for best quality
                )
        except Exception as e:
            logger.error(f"Failed to create voice clone: {e}")
            audio_path.unlink()
            raise

        # Serialize prompt_items for caching
        # Use pickle for now (alternatives: msgpack, cloudpickle)
        import pickle

        prompt_blob = pickle.dumps(prompt_items)

        # Create VoiceClone record
        voice = VoiceClone(
            voice_id=voice_id,
            name=name,
            created_at=time.time(),
            ref_audio_path=str(audio_path),
            ref_transcript=ref_transcript,
            sample_duration_ms=duration_ms,
            clone_type=clone_type,
            voice_clone_prompt_blob=prompt_blob,
            quality_check_passed=True,  # Simple check: no error during cloning
        )

        # Save to database
        with self.db as db:
            db.save_voice_clone(voice)

        logger.info(f"[VoiceClone] ✓ Voice '{name}' created successfully")
        return voice

    def get_voice_clone(self, voice_id: str) -> Optional[VoiceClone]:
        """Retrieve a voice clone by ID."""
        with self.db as db:
            return db.get_voice_clone(voice_id)

    def list_voices(self) -> list[VoiceClone]:
        """List all available voice clones."""
        with self.db as db:
            return db.list_voice_clones()

    def delete_voice_clone(self, voice_id: str) -> bool:
        """Delete a voice clone and its files."""
        logger.info(f"[VoiceClone] Deleting voice clone: {voice_id}")
        with self.db as db:
            return db.delete_voice_clone(voice_id)

    def update_consistency_score(self, voice_id: str, new_score: float):
        """Update voice consistency score after generation."""
        with self.db as db:
            db.increment_usage(voice_id)
            db.update_consistency_score(voice_id, new_score)

    def create_chatterbox_voice_clone(
        self,
        name: str,
        audio_clips: list[bytes],
    ) -> VoiceClone:
        """
        Create a Chatterbox voice clone from one or more short audio clips.

        Multiple clips are concatenated (with 0.3s silence between them) and
        capped at CHATTERBOX_MAX_REFERENCE_DURATION_S seconds so Chatterbox
        receives a single clean reference file.

        Args:
            name: Human-readable label for this voice.
            audio_clips: List of raw audio file bytes (WAV or MP3).
                         At least one clip required; 10-20 s total recommended.

        Returns:
            VoiceClone record with ref_audio_path pointing to the merged WAV.
        """
        import io
        import soundfile as sf
        if not audio_clips:
            raise ValueError("At least one audio clip is required")

        TARGET_SR = 24000  # Chatterbox native sample rate
        SILENCE_S = 0.3

        merged: list = []
        silence = [0.0] * int(TARGET_SR * SILENCE_S)

        for i, clip_bytes in enumerate(audio_clips):
            try:
                audio_data, sr = sf.read(io.BytesIO(clip_bytes))
            except Exception as e:
                raise ValueError(f"Clip {i + 1}: invalid audio format — {e}")

            # Convert stereo to mono
            if audio_data.ndim > 1:
                audio_data = audio_data.mean(axis=1)

            # Resample to TARGET_SR if needed
            if sr != TARGET_SR:
                try:
                    import librosa
                    audio_data = librosa.resample(audio_data.astype("float32"), orig_sr=sr, target_sr=TARGET_SR)
                except ImportError:
                    # Fallback: simple linear interpolation (good enough for reference)
                    import numpy as np
                    ratio = TARGET_SR / sr
                    new_len = int(len(audio_data) * ratio)
                    audio_data = np.interp(
                        np.linspace(0, len(audio_data) - 1, new_len),
                        np.arange(len(audio_data)),
                        audio_data.astype("float32"),
                    )

            merged.extend(audio_data.tolist())
            if i < len(audio_clips) - 1:
                merged.extend(silence)

        import numpy as np
        merged_arr = np.array(merged, dtype="float32")

        # Validate amplitude
        if np.max(np.abs(merged_arr)) < 0.01:
            raise ValueError("Merged audio is silent or extremely quiet")

        # Normalise
        peak = float(np.abs(merged_arr).max())
        merged_arr = merged_arr / peak

        duration_ms = int(len(merged_arr) / TARGET_SR * 1000)
        if duration_ms < MIN_SAMPLE_DURATION_MS:
            raise ValueError(
                f"Total reference audio too short: {duration_ms}ms "
                f"(minimum {MIN_SAMPLE_DURATION_MS}ms)"
            )

        # Persist merged WAV
        voice_id = str(uuid.uuid4())[:8]
        audio_path = VOICE_SAMPLES_DIR / f"{voice_id}_ref.wav"
        sf.write(str(audio_path), merged_arr, TARGET_SR)

        clone_type = "extended" if duration_ms > MAX_SAMPLE_DURATION_MS else "instant"
        voice = VoiceClone(
            voice_id=voice_id,
            name=name,
            created_at=time.time(),
            ref_audio_path=str(audio_path),
            ref_transcript="",  # not required for Chatterbox
            sample_duration_ms=duration_ms,
            clone_type=clone_type,
            voice_clone_prompt_blob=b"",  # Chatterbox uses raw audio; no prompt blob
            quality_check_passed=True,
        )

        with self.db as db:
            db.save_voice_clone(voice)

        logger.info(
            "[Chatterbox] Voice clone '%s' created (id=%s, %d clips, %.1fs total)",
            name,
            voice_id,
            len(audio_clips),
            duration_ms / 1000,
        )
        return voice

    def append_clips_to_voice_clone(
        self,
        voice_id: str,
        audio_clips: list[bytes],
    ) -> VoiceClone:
        """
        Append additional audio clips to an existing Chatterbox voice clone.

        New clips are merged onto the end of the existing reference WAV.
        If the total exceeds CHATTERBOX_MAX_REFERENCE_DURATION_S, audio is
        trimmed from the *beginning* (keeping the newest, presumably
        higher-quality recordings).

        Args:
            voice_id: ID of the existing voice clone.
            audio_clips: List of raw audio file bytes (WAV or MP3).

        Returns:
            Updated VoiceClone record.

        Raises:
            ValueError: If voice_id not found or clips are invalid.
        """
        import io as _io
        import soundfile as sf

        if not audio_clips:
            raise ValueError("At least one audio clip is required")

        with self.db as db:
            clone = db.get_voice_clone(voice_id)
        if not clone:
            raise ValueError(f"Voice clone '{voice_id}' not found")

        audio_path = Path(clone.ref_audio_path)
        if not audio_path.exists():
            raise ValueError("Existing reference audio file not found on disk")

        TARGET_SR = 24000
        SILENCE_S = 0.3

        # ── Load existing reference ──
        existing_data, existing_sr = sf.read(str(audio_path))
        if existing_data.ndim > 1:
            existing_data = existing_data.mean(axis=1)
        if existing_sr != TARGET_SR:
            import numpy as np
            ratio = TARGET_SR / existing_sr
            new_len = int(len(existing_data) * ratio)
            existing_data = np.interp(
                np.linspace(0, len(existing_data) - 1, new_len),
                np.arange(len(existing_data)),
                existing_data.astype("float32"),
            )

        merged: list = list(existing_data.astype("float32"))
        silence = [0.0] * int(TARGET_SR * SILENCE_S)

        # ── Decode and append new clips ──
        clips_added = 0
        for i, clip_bytes in enumerate(audio_clips):
            try:
                audio_data, sr = sf.read(_io.BytesIO(clip_bytes))
            except Exception as e:
                raise ValueError(f"Clip {i + 1}: invalid audio format — {e}")

            if audio_data.ndim > 1:
                audio_data = audio_data.mean(axis=1)

            if sr != TARGET_SR:
                try:
                    import librosa
                    audio_data = librosa.resample(
                        audio_data.astype("float32"), orig_sr=sr, target_sr=TARGET_SR
                    )
                except ImportError:
                    import numpy as np
                    ratio = TARGET_SR / sr
                    new_len = int(len(audio_data) * ratio)
                    audio_data = np.interp(
                        np.linspace(0, len(audio_data) - 1, new_len),
                        np.arange(len(audio_data)),
                        audio_data.astype("float32"),
                    )

            merged.extend(silence)
            merged.extend(audio_data.tolist())
            clips_added += 1

        import numpy as np
        merged_arr = np.array(merged, dtype="float32")

        # Validate
        if np.max(np.abs(merged_arr)) < 0.01:
            raise ValueError("Merged audio is silent or extremely quiet")

        # Normalise
        peak = float(np.abs(merged_arr).max())
        merged_arr = merged_arr / peak

        duration_ms = int(len(merged_arr) / TARGET_SR * 1000)

        # ── Overwrite reference WAV on disk ──
        sf.write(str(audio_path), merged_arr, TARGET_SR)

        # ── Update database record ──
        clone.sample_duration_ms = duration_ms
        clone.clone_type = "extended" if duration_ms > MAX_SAMPLE_DURATION_MS else "instant"

        with self.db as db:
            db.save_voice_clone(clone)

        logger.info(
            "[Chatterbox] Voice clone '%s' updated (+%d clips, now %.1fs total)",
            clone.name,
            clips_added,
            duration_ms / 1000,
        )
        return clone

    def extract_reference_audio(self, audio_path: str, duration_ms: int) -> bytes:
        """
        Extract a segment from audio for use as reference.
        By default, takes first N milliseconds.
        """
        # Could extend to find cleanest segment
        import soundfile as sf

        audio_data, sr = sf.read(audio_path)
        total_samples = len(audio_data)
        target_samples = int(duration_ms / 1000 * sr)

        samples = min(target_samples, total_samples)
        segment = audio_data[:samples]

        # Write to bytes
        buffer_path = "/tmp/segment.wav"
        sf.write(buffer_path, segment, sr)

        with open(buffer_path, "rb") as f:
            return f.read()


# ---------------------------------------------------------------------------
# Utility Functions for Voice Cloning
# ---------------------------------------------------------------------------
def validate_audio_sample(audio_data: np.ndarray, sample_rate: int) -> Tuple[bool, str]:
    """
    Validate audio sample quality for voice cloning.

    Returns: (is_valid, error_message)
    """
    # Check duration
    duration_ms = len(audio_data) / sample_rate * 1000
    if duration_ms < MIN_SAMPLE_DURATION_MS:
        return (
            False,
            f"Sample too short: {duration_ms:.0f}ms (minimum {MIN_SAMPLE_DURATION_MS}ms)",
        )

    if duration_ms > MAX_SAMPLE_DURATION_MS:
        logger.warning(f"Sample longer than recommended: {duration_ms}ms")

    # Check amplitude (not silent)
    max_amplitude = np.max(np.abs(audio_data))
    if max_amplitude < 0.01:
        return False, "Audio sample appears to be silent or very low volume"

    # Check for clipping
    if max_amplitude > 0.95:
        logger.warning("Audio sample may be clipped (high amplitude)")

    return True, ""


# ---------------------------------------------------------------------------
# Global Voice Manager Instance
# ---------------------------------------------------------------------------
_voice_manager = None


def get_voice_manager() -> VoiceManager:
    """Singleton accessor for the voice manager."""
    global _voice_manager
    if _voice_manager is None:
        _voice_manager = VoiceManager()
    return _voice_manager
