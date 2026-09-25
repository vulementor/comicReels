$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "ComicReels local launcher" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv }
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
if (-not (Test-Path "dashboard\node_modules")) {
  Push-Location dashboard
  npm install
  Pop-Location
}
$backend = Start-Process -PassThru -NoNewWindow ".\.venv\Scripts\python.exe" -ArgumentList "-m","agent.main"
$frontend = Start-Process -PassThru -NoNewWindow "npm" -WorkingDirectory "$Root\dashboard" -ArgumentList "run","dev"
Write-Host "Backend PID $($backend.Id), Dashboard PID $($frontend.Id)"
Write-Host "Open http://localhost:5173/ . Ctrl+C does not automatically stop child processes; close them when finished."
