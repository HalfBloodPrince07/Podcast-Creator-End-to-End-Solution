"""
Patch diffusers/pipelines/pipeline_loading_utils.py so that the import of
FLAX_WEIGHTS_NAME from transformers.utils is wrapped in a try/except.

transformers 5.x removed FLAX_WEIGHTS_NAME when Flax support was deprecated.
diffusers 0.31 still imports it for SDXL pipeline metadata. Without this
patch, `from diffusers import StableDiffusionXLPipeline` raises ImportError.

Idempotent: detects an already-patched file and exits 0 without rewriting.
Safe to re-run after `pip install --upgrade diffusers`.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

MARKER = "TRANSFORMERS_FLAX_WEIGHTS_NAME = \"flax_model.msgpack\""
ORIGINAL = (
    "    from transformers.utils import FLAX_WEIGHTS_NAME as "
    "TRANSFORMERS_FLAX_WEIGHTS_NAME"
)
REPLACEMENT = (
    "    # transformers 5.x removed FLAX_WEIGHTS_NAME (Flax support deprecated).\n"
    "    # The constant is only used as a string in HF repo file-pattern lists, so\n"
    "    # we fall back to its historical value when missing.\n"
    "    try:\n"
    "        from transformers.utils import FLAX_WEIGHTS_NAME as "
    "TRANSFORMERS_FLAX_WEIGHTS_NAME\n"
    "    except ImportError:\n"
    "        TRANSFORMERS_FLAX_WEIGHTS_NAME = \"flax_model.msgpack\""
)


def find_target() -> Path:
    spec = importlib.util.find_spec("diffusers.pipelines.pipeline_loading_utils")
    if spec is None or spec.origin is None:
        raise SystemExit(
            "diffusers is not importable in this Python. Activate the right env."
        )
    return Path(spec.origin)


def main() -> int:
    target = find_target()
    text = target.read_text(encoding="utf-8")

    if MARKER in text:
        print(f"[skip] already patched: {target}")
        return 0

    if ORIGINAL not in text:
        print(
            f"[error] could not find the expected import line in {target}.\n"
            "        diffusers may have been upgraded past 0.31. Inspect the file\n"
            "        manually and wrap the FLAX_WEIGHTS_NAME import in try/except.",
            file=sys.stderr,
        )
        return 2

    patched = text.replace(ORIGINAL, REPLACEMENT, 1)
    target.write_text(patched, encoding="utf-8")
    print(f"[ok] patched {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
