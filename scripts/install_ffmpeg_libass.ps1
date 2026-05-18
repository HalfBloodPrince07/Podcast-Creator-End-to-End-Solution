<#
.SYNOPSIS
    Replace the conda-shipped ffmpeg with a Gyan.dev essentials build that
    includes libass (required for burned subtitles in the video pipeline).

.DESCRIPTION
    The conda-forge ffmpeg is built without --enable-libass, so the
    `subtitles` / `ass` filters silently produce empty video. This script
    drops in Gyan.dev's release-essentials build (~97 MB) and backs up
    the originals as *.condabak.

    Idempotent: if a .condabak already exists AND the current binary
    already reports libass, the script skips. Use -Force to redownload.

.PARAMETER EnvName
    Conda env name. Default: Podcast.

.PARAMETER CondaRoot
    Anaconda/Miniconda install root. Default: $env:USERPROFILE\Anaconda3.

.PARAMETER Force
    Redownload and replace even if libass is already present.
#>
[CmdletBinding()]
param(
    [string]$EnvName = 'Podcast',
    [string]$CondaRoot = "$env:USERPROFILE\Anaconda3",
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$envBin = Join-Path $CondaRoot "envs\$EnvName\Library\bin"
if (-not (Test-Path $envBin)) {
    Write-Error "Conda env bin dir not found: $envBin. Check -EnvName and -CondaRoot."
}

$ffmpeg  = Join-Path $envBin 'ffmpeg.exe'
$ffprobe = Join-Path $envBin 'ffprobe.exe'

if (-not (Test-Path $ffmpeg)) {
    Write-Error "ffmpeg.exe not found at $ffmpeg. Did `conda install -c conda-forge ffmpeg` run?"
}

# Skip-check: already patched + libass present
if (-not $Force) {
    $hasLibass = $false
    try {
        $filters = & $ffmpeg -hide_banner -filters 2>$null
        $hasLibass = ($filters -match '^\s*\.\.\s+subtitles')
    } catch {
        $hasLibass = $false
    }
    if ($hasLibass -and (Test-Path "$ffmpeg.condabak")) {
        Write-Host "[skip] ffmpeg already has libass and .condabak exists. Use -Force to redo." -ForegroundColor Yellow
        exit 0
    }
}

$tmp     = Join-Path $env:TEMP 'ffmpeg-gyan.zip'
$extract = Join-Path $env:TEMP 'ffmpeg-gyan'

Write-Host "[1/5] Downloading Gyan.dev ffmpeg essentials..." -ForegroundColor Cyan
Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $tmp

Write-Host "[2/5] Extracting to $extract..." -ForegroundColor Cyan
if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
Expand-Archive -Path $tmp -DestinationPath $extract

$srcFfmpeg = Get-ChildItem $extract -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
if (-not $srcFfmpeg) { Write-Error "Could not locate ffmpeg.exe inside the downloaded archive." }
$srcDir = $srcFfmpeg.Directory.FullName

Write-Host "[3/5] Backing up conda originals..." -ForegroundColor Cyan
if (-not (Test-Path "$ffmpeg.condabak"))  { Copy-Item $ffmpeg  "$ffmpeg.condabak"  -Force }
if (-not (Test-Path "$ffprobe.condabak")) { Copy-Item $ffprobe "$ffprobe.condabak" -Force }

Write-Host "[4/5] Installing Gyan.dev binaries..." -ForegroundColor Cyan
Copy-Item $srcFfmpeg.FullName       $ffmpeg  -Force
Copy-Item (Join-Path $srcDir 'ffprobe.exe') $ffprobe -Force

Write-Host "[5/5] Verifying libass is wired up..." -ForegroundColor Cyan
$check = & $ffmpeg -hide_banner -filters | Select-String '^\s*\.\.\s+subtitles'
if (-not $check) {
    Write-Error "ffmpeg installed but 'subtitles' filter is still missing. Something went wrong."
}
Write-Host "[ok] $check" -ForegroundColor Green
Write-Host "[ok] ffmpeg with libass installed at $ffmpeg" -ForegroundColor Green
Write-Host "      Originals preserved at *.condabak. Re-run after any conda ffmpeg upgrade." -ForegroundColor DarkGray
