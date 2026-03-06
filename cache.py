"""
cache.py — Simple file-based response cache with TTL.
Stores JSON-serializable values keyed by a hash of the input.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from utils import get_logger

logger = get_logger("Cache")

CACHE_DIR = Path(".cache")
DEFAULT_TTL = 3600  # 1 hour


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def get(key: str, ttl: int = DEFAULT_TTL) -> Optional[Any]:
    """Return cached value if it exists and is not expired, else None."""
    path = CACHE_DIR / f"{_key_hash(key)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) > ttl:
            path.unlink(missing_ok=True)
            return None
        logger.debug("Cache hit: %s", key[:80])
        return data["value"]
    except Exception:
        return None


def put(key: str, value: Any) -> None:
    """Store a JSON-serializable value."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{_key_hash(key)}.json"
    try:
        path.write_text(
            json.dumps({"ts": time.time(), "key": key[:200], "value": value}),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Cache write failed: %s", e)


def clear() -> int:
    """Delete all cache files. Returns number of files removed."""
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for f in CACHE_DIR.glob("*.json"):
        f.unlink(missing_ok=True)
        count += 1
    return count
