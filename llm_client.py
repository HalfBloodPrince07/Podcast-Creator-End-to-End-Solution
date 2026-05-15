"""
llm_client.py — LM Studio / OpenAI-compatible chat client.
QWEN TTS is handled locally via the TTSAgent (transformers), NOT here.
"""
from __future__ import annotations

import os
import re
import threading
from typing import Any, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel

from utils import get_logger

load_dotenv()

logger = get_logger("llm_client")

# ---------------------------------------------------------------------------
# Defaults (override in .env)
# ---------------------------------------------------------------------------
DEFAULT_LLM_BASE_URL = "http://localhost:1234/v1"
DEFAULT_LLM_API_KEY  = "lm-studio"
DEFAULT_MODEL        = "local-model"

# Matches <think>...</think> blocks emitted by reasoning models (DeepSeek-R1, QwQ, etc.)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """Remove model-emitted <think>…</think> reasoning blocks from output."""
    return _THINK_RE.sub("", text).lstrip()


class LMStudioClient:
    """
    Thin OpenAI-compatible client pointed at LM Studio (or any compatible server).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.base_url = base_url or os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
        self.api_key  = api_key  or os.getenv("LLM_API_KEY",  DEFAULT_LLM_API_KEY)
        self.model    = model    or os.getenv("LLM_MODEL",     DEFAULT_MODEL)
        self._client  = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        logger.info("LMStudioClient -> %s (model: %s)", self.base_url, self.model)

    # ------------------------------------------------------------------
    # Core chat call
    # ------------------------------------------------------------------
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        # Generous default — LM Studio supports up to 131072 total context
        # on the user's Gemma-4-e4b setup, so a 32K floor gives any call
        # site that forgot to specify max_tokens plenty of room without
        # risking the empty-content-after-<think>-strip trap.
        max_tokens: int = 32768,
        **kwargs: Any,
    ) -> str:
        """
        Send a chat completion request.  Returns the assistant's reply as a string.
        """
        m = model or self.model
        logger.debug("chat() model=%s tokens=%d msgs=%d", m, max_tokens, len(messages))
        resp = await self._client.chat.completions.create(
            model=m,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        raw = resp.choices[0].message.content or ""
        content = _strip_thinking(raw)
        # If <think> swallowed everything, log loudly so callers know the
        # max_tokens budget was too tight for a thinking model rather than
        # silently returning an empty string downstream.
        if raw and not content.strip():
            logger.warning(
                "chat() returned empty after stripping <think> (raw=%d chars, "
                "max_tokens=%d). The model spent its entire budget reasoning "
                "and produced no answer — increase max_tokens.",
                len(raw), max_tokens,
            )
        logger.debug("chat() raw=%d chars, post-strip=%d chars", len(raw), len(content))
        return content.strip()

    # ------------------------------------------------------------------
    # Structured Generation
    # ------------------------------------------------------------------
    async def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_format: type[BaseModel],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 32768,
        **kwargs: Any,
    ) -> BaseModel:
        """
        Force the LLM to output JSON matching a Pydantic schema using
        OpenAI's Structured Outputs (parse).
        """
        m = model or self.model
        resp = await self._client.beta.chat.completions.parse(
            model=m,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            **kwargs,
        )
        return resp.choices[0].message.parsed


    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    async def system_user(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs: Any,
    ) -> str:
        """Shorthand: one system + one user message."""
        return await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            **kwargs,
        )

    async def system_user_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: type[BaseModel],
        **kwargs: Any,
    ) -> BaseModel:
        """Shorthand: structured outputs with one system + one user message."""
        return await self.chat_structured(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            response_format=response_format,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------
    async def test_connection(self) -> tuple[bool, str]:
        """
        Ping the LM Studio server.
        Returns (success: bool, message: str).
        """
        try:
            models = await self._client.models.list()
            model_ids = [m.id for m in models.data]
            return True, f"✅ Connected. Available models: {', '.join(model_ids[:5]) or 'none listed'}"
        except Exception as exc:
            return False, f"❌ Connection failed: {exc}"

    async def list_models(self) -> list[str]:
        """Return list of model IDs available on the server."""
        try:
            models = await self._client.models.list()
            return [m.id for m in models.data]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Thread-safe module-level singleton (lazy-initialised)
# ---------------------------------------------------------------------------
_client: Optional[LMStudioClient] = None
_lock = threading.Lock()


def get_client(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> LMStudioClient:
    """Return (or create) the global LMStudioClient singleton (thread-safe)."""
    global _client
    with _lock:
        if _client is None or base_url or api_key or model:
            _client = LMStudioClient(base_url=base_url, api_key=api_key, model=model)
        return _client


def reset_client() -> None:
    """Thread-safe reset of the singleton. Next get_client() call creates a fresh instance."""
    global _client
    with _lock:
        _client = None


def unload_model(instance_id: Optional[str] = None) -> bool:
    """Tell LM Studio to unload a loaded model so the GPU/RAM is freed for
    the next stage (TTS / Whisper / SDXL / CogVideoX).

    LM Studio exposes its REST API at `/api/v1/*` (parallel to the
    OpenAI-compatible `/v1/*` we use for chat). When `instance_id` is None,
    we unload the model the singleton client is configured to use.

    Returns True on success. Returns False (and only logs at INFO) when:
      - no client has been initialised yet (nothing was loaded),
      - the server isn't LM Studio (the REST endpoint 404s / connection refused),
      - the model wasn't actually loaded (LM Studio returns non-200).
    Never raises — freeing memory is a hint, not a contract.
    """
    import httpx
    client = _client  # the existing singleton
    if client is None:
        return False

    base = client.base_url.rstrip("/")
    # /v1 (OpenAI-compatible) → /api/v1 (LM Studio REST)
    if base.endswith("/v1"):
        rest_base = base[:-3] + "/api/v1"
    else:
        rest_base = base + "/api/v1"
    target = instance_id or client.model

    try:
        resp = httpx.post(
            f"{rest_base}/models/unload",
            json={"instance_id": target},
            headers={"Authorization": f"Bearer {client.api_key}"},
            timeout=15.0,
        )
        if resp.status_code == 200:
            logger.info("[LM Studio] Unloaded model '%s' to free GPU.", target)
            return True
        # 404 = not LM Studio or model not loaded; 4xx generally = wrong instance_id.
        body = resp.text[:200] if resp.text else ""
        logger.info(
            "[LM Studio] Unload returned HTTP %d for '%s' (%s) — continuing.",
            resp.status_code, target, body,
        )
        return False
    except Exception as exc:
        logger.info("[LM Studio] Unload skipped (%s) — server may not be LM Studio.", exc)
        return False
