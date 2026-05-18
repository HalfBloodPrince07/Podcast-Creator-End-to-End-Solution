<#
.SYNOPSIS
    One-shot reproducer for the Podcast conda env on Windows.

.DESCRIPTION
    Creates (or reuses) a conda env, installs torch for the detected GPU,
    installs the rest of requirements.lock.txt, applies the FLAX_WEIGHTS_NAME
    patch to diffusers, and (optionally) swaps the conda ffmpeg for a
    libass-enabled Gyan.dev build. Then verifies imports.

    Run from the repo root:
        powershell -ExecutionPolicy Bypass -File scripts\setup_podcast_env.ps1

.PARAMETER EnvName
    Conda env name to create or reuse. Default: Podcast.

.PARAMETER CondaRoot
    Path to your Anaconda/Miniconda install. Default: $env:USERPROFILE\Anaconda3.

.PARAMETER CudaIndex
    Which torch index to use. Default: auto (detects via nvidia-smi).
    Options: auto | cu130-nightly | cu124 | cu121 | cpu

.PARAMETER SkipFfmpegSwap
    Don't replace ffmpeg.exe. Use this if you have a libass-enabled ffmpeg
    already on PATH that overrides the env's binary.

.PARAMETER Recreate
    Drop and recreate the env if it already exists.
#>
[CmdletBinding()]
param(
    [string]$EnvName = 'Podcast',
    [string]$CondaRoot = "$env:USERPROFILE\Anaconda3",
    [ValidateSet('auto','cu130-nightly','cu124','cu121','cpu')]
    [string]$CudaIndex = 'auto',
    [switch]$SkipFfmpegSwap,
    [switch]$Recreate
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Write-Step($n, $msg) { Write-Host ("[{0}] {1}" -f $n, $msg) -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[ok] $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "[warn] $msg" -ForegroundColor Yellow }

# --- 1. conda check ---
Write-Step '1/8' 'Checking conda...'
$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
    $candidate = Join-Path $CondaRoot 'Scripts\conda.exe'
    if (Test-Path $candidate) { $env:PATH = "$CondaRoot;$CondaRoot\Scripts;$env:PATH" }
    else { throw "conda not found on PATH and not at $candidate. Install Anaconda/Miniconda first." }
}
Write-Ok ("conda: " + (conda --version))

# --- 2. detect GPU ---
Write-Step '2/8' 'Detecting GPU compute capability...'
$detectedIndex = 'cpu'
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
    try {
        $cc = (& nvidia-smi --query-gpu=compute_cap --format=csv,noheader | Select-Object -First 1).Trim()
        Write-Host "      nvidia-smi reports compute capability: $cc" -ForegroundColor DarkGray
        if ($cc -match '^(9|10|11|12)\.') { $detectedIndex = 'cu130-nightly' }
        elseif ($cc -match '^(7|8)\.')    { $detectedIndex = 'cu124' }
        elseif ($cc -match '^6\.')        { $detectedIndex = 'cu121' }
        else                              { $detectedIndex = 'cu124' }
    } catch {
        Write-Warn2 "nvidia-smi failed; defaulting to CPU torch."
    }
} else {
    Write-Warn2 "nvidia-smi not found; defaulting to CPU torch."
}
if ($CudaIndex -eq 'auto') { $CudaIndex = $detectedIndex }
Write-Ok "torch index: $CudaIndex"

# --- 3. create / reuse env ---
Write-Step '3/8' "Conda env: $EnvName"
$envExists = (conda env list) -match "^\s*$([regex]::Escape($EnvName))\s"
if ($envExists -and $Recreate) {
    Write-Warn2 "Removing existing env $EnvName (--Recreate)..."
    conda env remove -n $EnvName -y | Out-Null
    $envExists = $false
}
if (-not $envExists) {
    conda create -n $EnvName 'python=3.10.20' -y | Out-Null
    Write-Ok "Created $EnvName"
} else {
    Write-Ok "Reusing $EnvName"
}

$envPython = Join-Path $CondaRoot "envs\$EnvName\python.exe"
if (-not (Test-Path $envPython)) { throw "Env python not found at $envPython" }

# --- 4. install torch first (correct CUDA) ---
Write-Step '4/8' "Installing torch ($CudaIndex)..."
switch ($CudaIndex) {
    'cu130-nightly' {
        & $envPython -m pip install --pre `
            'torch==2.11.0+cu130' 'torchvision==0.26.0+cu130' 'torchaudio==2.11.0+cu130' `
            --index-url https://download.pytorch.org/whl/nightly/cu130
    }
    'cu124' {
        & $envPython -m pip install torch torchvision torchaudio `
            --index-url https://download.pytorch.org/whl/cu124
    }
    'cu121' {
        & $envPython -m pip install torch torchvision torchaudio `
            --index-url https://download.pytorch.org/whl/cu121
    }
    'cpu' {
        & $envPython -m pip install torch torchvision torchaudio `
            --index-url https://download.pytorch.org/whl/cpu
    }
}
if ($LASTEXITCODE -ne 0) { throw "torch install failed" }
Write-Ok "torch installed"

# --- 5. install everything else (lockfile, torch lines stripped) ---
Write-Step '5/8' 'Installing remaining packages from requirements.lock.txt...'
$lock = Join-Path $repoRoot 'requirements.lock.txt'
if (-not (Test-Path $lock)) { throw "Missing $lock" }
$baseLock = Join-Path $env:TEMP 'requirements.base.txt'
Get-Content $lock | Where-Object { $_ -notmatch '^(torch|torchvision|torchaudio)==' } | Out-File -FilePath $baseLock -Encoding ascii
& $envPython -m pip install -r $baseLock
if ($LASTEXITCODE -ne 0) { throw "pip install from lock failed" }
Write-Ok "lockfile applied (chatterbox dependency warnings are expected)"

# --- 6. FLAX patch ---
Write-Step '6/8' 'Applying FLAX_WEIGHTS_NAME patch to diffusers...'
& $envPython (Join-Path $repoRoot 'scripts\apply_flax_patch.py')
if ($LASTEXITCODE -ne 0) { throw "FLAX patch failed" }

# --- 7. ffmpeg swap ---
if ($SkipFfmpegSwap) {
    Write-Step '7/8' 'ffmpeg swap skipped (-SkipFfmpegSwap).'
} else {
    Write-Step '7/8' 'Swapping conda ffmpeg for Gyan.dev libass build...'
    & (Join-Path $repoRoot 'scripts\install_ffmpeg_libass.ps1') -EnvName $EnvName -CondaRoot $CondaRoot
    if ($LASTEXITCODE -ne 0) { throw "ffmpeg swap failed" }
}

# --- 8. verify imports ---
Write-Step '8/8' 'Verifying imports...'
$verify = @"
import torch
print('  torch', torch.__version__, 'cuda?', torch.cuda.is_available())
from diffusers import StableDiffusionXLPipeline
print('  diffusers/SDXL import OK')
import chatterbox
print('  chatterbox import OK')
from faster_whisper import WhisperModel
print('  faster-whisper import OK')
"@
$verify | & $envPython -
if ($LASTEXITCODE -ne 0) { throw "Verification failed" }

Write-Host ''
Write-Ok "Environment '$EnvName' is ready."
Write-Host ''
Write-Host 'Next steps:' -ForegroundColor White
Write-Host '  1. conda activate ' -NoNewline; Write-Host $EnvName -ForegroundColor Cyan
Write-Host '  2. copy-item .env.example .env   # then edit LLM_BASE_URL if needed'
Write-Host '  3. cd frontend; npm install; npm run dev'
Write-Host '  4. (new shell) python app.py'
Write-Host '  5. open http://localhost:5173'
