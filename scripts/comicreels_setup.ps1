$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
Write-Host "=== ComicReels setup ===" -ForegroundColor Cyan

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "ffmpeg chưa có trong PATH. Hãy cài ffmpeg trước khi ghép video."
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    } else {
        throw "Không tìm thấy Python 3.10+."
    }
}
$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt -r requirements-dev.txt
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Không tìm thấy Node.js/npm." }
Push-Location (Join-Path $Root "dashboard")
try { npm install } finally { Pop-Location }
Write-Host "Setup hoàn tất." -ForegroundColor Green
Write-Host "Chrome Extension: $Root\extension"
Write-Host "Chạy scripts\comicreels_start.bat để mở ComicReels."
