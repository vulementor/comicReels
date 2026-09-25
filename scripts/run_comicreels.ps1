$ErrorActionPreference = "Stop"
$SourceRoot = Split-Path -Parent $PSScriptRoot
Set-Location $SourceRoot

$CacheBase = if ($env:LOCALAPPDATA) {
  Join-Path $env:LOCALAPPDATA "ComicReels"
} else {
  Join-Path $HOME ".cache\comicreels"
}
$RuntimeRoot = if ($env:COMICREELS_RUNTIME_DIR) { $env:COMICREELS_RUNTIME_DIR } else { Join-Path $CacheBase "runtime" }
$Venv = if ($env:COMICREELS_VENV) { $env:COMICREELS_VENV } else { Join-Path $CacheBase "venv" }
$RuntimeRef = if ($env:COMICREELS_RUNTIME_REF) { $env:COMICREELS_RUNTIME_REF } else { "HEAD" }

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Venv) | Out-Null

$Commit = (& git -C $SourceRoot rev-parse "$RuntimeRef^{commit}").Trim()
if ($LASTEXITCODE -ne 0) { throw "Cannot resolve runtime ref $RuntimeRef" }

$Manifest = Join-Path $RuntimeRoot ".comicreels-tracked-files"
if (Test-Path $Manifest) {
  Get-Content $Manifest | ForEach-Object {
    if ($_ -ne "") {
      $old = Join-Path $RuntimeRoot $_
      if (Test-Path $old -PathType Leaf) { Remove-Item -Force $old }
    }
  }
}

$Tracked = & git -C $SourceRoot ls-tree -r --name-only $Commit
$Archive = Join-Path $env:TEMP "comicreels-runtime-$PID.zip"
& git -C $SourceRoot archive --format=zip -o $Archive $Commit
if ($LASTEXITCODE -ne 0) { throw "git archive failed" }
Expand-Archive -Force $Archive $RuntimeRoot
Remove-Item -Force $Archive
$Tracked | Set-Content -Encoding UTF8 $Manifest

Set-Location $RuntimeRoot
$VenvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
  $Python = if ($env:COMICREELS_PYTHON) { $env:COMICREELS_PYTHON } else { "python" }
  & $Python -m venv $Venv
}

$ReqHash = (Get-FileHash "requirements.txt" -Algorithm SHA256).Hash
$ReqStamp = Join-Path $Venv ".comicreels-requirements.sha"
$OldReqHash = if (Test-Path $ReqStamp) { (Get-Content -Raw $ReqStamp).Trim() } else { "" }
if ($OldReqHash -ne $ReqHash) {
  & $VenvPython -m pip install -r requirements.txt
  Set-Content -NoNewline -Encoding ASCII $ReqStamp $ReqHash
}

$LockHash = (Get-FileHash "dashboard\package-lock.json" -Algorithm SHA256).Hash
$LockStamp = Join-Path $RuntimeRoot ".comicreels-package-lock.sha"
$OldLockHash = if (Test-Path $LockStamp) { (Get-Content -Raw $LockStamp).Trim() } else { "" }
if ((-not (Test-Path "dashboard\node_modules")) -or ($OldLockHash -ne $LockHash)) {
  if (Test-Path "dashboard\node_modules") { Remove-Item -Recurse -Force "dashboard\node_modules" }
  Push-Location dashboard
  npm ci
  Pop-Location
  Set-Content -NoNewline -Encoding ASCII $LockStamp $LockHash
}

$backend = Start-Process -PassThru -NoNewWindow $VenvPython -ArgumentList "-m","agent.main" -WorkingDirectory $RuntimeRoot
$frontend = Start-Process -PassThru -NoNewWindow "npm" -WorkingDirectory "$RuntimeRoot\dashboard" -ArgumentList "run","dev","--","--host","127.0.0.1"

Write-Host "ComicReels source:  $SourceRoot"
Write-Host "Runtime commit:     $Commit"
Write-Host "ComicReels runtime: $RuntimeRoot"
Write-Host "Backend PID $($backend.Id), Frontend PID $($frontend.Id)"
Write-Host "Open http://127.0.0.1:5173/"
Write-Host "Stop both child processes when finished."
