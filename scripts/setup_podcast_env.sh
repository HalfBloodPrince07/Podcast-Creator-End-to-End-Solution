#!/usr/bin/env bash
# One-shot reproducer for the Podcast conda env on Linux/macOS.
#
# Usage:
#     bash scripts/setup_podcast_env.sh [--env-name Podcast] [--cuda auto|cu130-nightly|cu124|cu121|cpu] [--recreate]
#
# Assumes conda is on PATH. ffmpeg swap is skipped on Linux/macOS since
# distro / brew ffmpegs ship with libass by default — verify with
# `ffmpeg -filters | grep subtitles` after this script finishes.

set -euo pipefail

ENV_NAME="Podcast"
CUDA_INDEX="auto"
RECREATE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-name) ENV_NAME="$2"; shift 2 ;;
        --cuda)     CUDA_INDEX="$2"; shift 2 ;;
        --recreate) RECREATE=1; shift ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

step()  { printf '\033[36m[%s] %s\033[0m\n' "$1" "$2"; }
ok()    { printf '\033[32m[ok] %s\033[0m\n'  "$1"; }
warn()  { printf '\033[33m[warn] %s\033[0m\n' "$1"; }

# --- 1. conda ---
step '1/7' 'Checking conda...'
command -v conda >/dev/null || { echo "conda not on PATH" >&2; exit 1; }
ok "$(conda --version)"

# --- 2. detect GPU ---
step '2/7' 'Detecting GPU compute capability...'
DETECTED='cpu'
if command -v nvidia-smi >/dev/null; then
    CC="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ' || true)"
    echo "      nvidia-smi compute_cap: ${CC:-none}"
    case "$CC" in
        9.*|10.*|11.*|12.*) DETECTED='cu130-nightly' ;;
        7.*|8.*)            DETECTED='cu124' ;;
        6.*)                DETECTED='cu121' ;;
        *)                  DETECTED='cu124' ;;
    esac
else
    warn "nvidia-smi not found; defaulting to CPU torch."
fi
[[ "$CUDA_INDEX" == "auto" ]] && CUDA_INDEX="$DETECTED"
ok "torch index: $CUDA_INDEX"

# --- 3. env ---
step '3/7' "Conda env: $ENV_NAME"
if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    if [[ $RECREATE -eq 1 ]]; then
        warn "Removing existing env $ENV_NAME (--recreate)..."
        conda env remove -n "$ENV_NAME" -y >/dev/null
        conda create -n "$ENV_NAME" 'python=3.10.20' -y >/dev/null
        ok "Recreated $ENV_NAME"
    else
        ok "Reusing $ENV_NAME"
    fi
else
    conda create -n "$ENV_NAME" 'python=3.10.20' -y >/dev/null
    ok "Created $ENV_NAME"
fi

# Resolve env python without needing `conda activate` in a non-interactive shell.
ENV_PY="$(conda run -n "$ENV_NAME" python -c 'import sys; print(sys.executable)')"
[[ -x "$ENV_PY" ]] || { echo "Could not resolve env python" >&2; exit 1; }
echo "      env python: $ENV_PY"

# --- 4. torch ---
step '4/7' "Installing torch ($CUDA_INDEX)..."
case "$CUDA_INDEX" in
    cu130-nightly)
        "$ENV_PY" -m pip install --pre \
            'torch==2.11.0+cu130' 'torchvision==0.26.0+cu130' 'torchaudio==2.11.0+cu130' \
            --index-url https://download.pytorch.org/whl/nightly/cu130
        ;;
    cu124) "$ENV_PY" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 ;;
    cu121) "$ENV_PY" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 ;;
    cpu)   "$ENV_PY" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu   ;;
    *) echo "bad --cuda value: $CUDA_INDEX" >&2; exit 2 ;;
esac
ok "torch installed"

# --- 5. lockfile (torch lines stripped) ---
step '5/7' 'Installing remaining packages from requirements.lock.txt...'
TMP_LOCK="$(mktemp)"
grep -Ev '^(torch|torchvision|torchaudio)==' requirements.lock.txt > "$TMP_LOCK"
"$ENV_PY" -m pip install -r "$TMP_LOCK"
rm -f "$TMP_LOCK"
ok "lockfile applied (chatterbox dep warnings are expected)"

# --- 6. FLAX patch ---
step '6/7' 'Applying FLAX_WEIGHTS_NAME patch to diffusers...'
"$ENV_PY" scripts/apply_flax_patch.py

# --- 7. verify ---
step '7/7' 'Verifying imports...'
"$ENV_PY" - <<'PY'
import torch
print('  torch', torch.__version__, 'cuda?', torch.cuda.is_available())
from diffusers import StableDiffusionXLPipeline
print('  diffusers/SDXL import OK')
import chatterbox
print('  chatterbox import OK')
from faster_whisper import WhisperModel
print('  faster-whisper import OK')
PY

echo
ok "Environment '$ENV_NAME' is ready."
cat <<EOF

Next steps:
  1. conda activate $ENV_NAME
  2. cp .env.example .env   # then edit LLM_BASE_URL if needed
  3. cd frontend && npm install && npm run dev
  4. (new shell) python app.py
  5. open http://localhost:5173

ffmpeg note: this script does NOT swap ffmpeg on Linux/macOS. Verify your
system ffmpeg has libass with:
  ffmpeg -filters | grep subtitles
If empty, install via your package manager (apt/dnf/brew install ffmpeg).
EOF
