$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Chưa có .venv. Chạy scripts\comicreels_setup.bat trước." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Không tìm thấy npm." }
$backend = "Set-Location '$Root'; & '$Python' -m agent.main"
$frontendDir = Join-Path $Root "dashboard"
$frontend = "Set-Location '$frontendDir'; npm run dev"
Start-Process powershell -ArgumentList @("-NoExit","-ExecutionPolicy","Bypass","-Command",$backend)
Start-Sleep -Seconds 1
Start-Process powershell -ArgumentList @("-NoExit","-ExecutionPolicy","Bypass","-Command",$frontend)
Start-Sleep -Seconds 2
Start-Process "http://localhost:5173/"
Write-Host "ComicReels đang khởi động ở http://localhost:5173/" -ForegroundColor Green
Write-Host "Google Flow: load unpacked extension tại $Root\extension, mở flow.google.com và chọn project."
