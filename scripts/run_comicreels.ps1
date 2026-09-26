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
$GptfpRequiredRef = if ($env:COMICREELS_GPTFP_REF) {
  $env:COMICREELS_GPTFP_REF
} else {
  "1aa78c8ad512bb8f7171e41bc993b8c4afb10853"
}
$GptfpBranch = if ($env:COMICREELS_GPTFP_BRANCH) { $env:COMICREELS_GPTFP_BRANCH } else { "feature/comicreels-image-attachments" }
$GptfpRepo = if ($env:COMICREELS_GPTFP_REPO) { $env:COMICREELS_GPTFP_REPO } else { "https://github.com/vulementor/gpt_fullproxy.git" }

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

# Browser-native ChatGPT AI integration. Session material stays in the
# physical profile; ComicReels only passes the profile directory to GPT FullProxy.
$GptfpDir = if ($env:COMICREELS_GPTFP_DIR) {
  $env:COMICREELS_GPTFP_DIR
} else {
  Join-Path $CacheBase "gpt_fullproxy-src"
}
if (-not (Test-Path (Join-Path $GptfpDir ".git"))) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $GptfpDir) | Out-Null
  & git clone --filter=blob:none --no-checkout $GptfpRepo $GptfpDir
}
& git -C $GptfpDir fetch --force --depth=1 origin $GptfpBranch
& git -C $GptfpDir checkout --detach $GptfpRequiredRef
$GptfpHead = (& git -C $GptfpDir rev-parse HEAD).Trim()
if (($env:COMICREELS_GPTFP_ALLOW_UNPINNED -ne "1") -and ($GptfpHead -ne $GptfpRequiredRef)) {
  throw "GPT FullProxy HEAD $GptfpHead does not match required $GptfpRequiredRef"
}
$GptfpStamp = Join-Path $Venv ".comicreels-gptfp.sha"
$OldGptfpHead = if (Test-Path $GptfpStamp) { (Get-Content -Raw $GptfpStamp).Trim() } else { "" }
if ($OldGptfpHead -ne $GptfpHead) {
  & $VenvPython -m pip install -e "$GptfpDir[browser]"
  & $VenvPython -m camoufox fetch
  Set-Content -NoNewline -Encoding ASCII $GptfpStamp $GptfpHead
}
$env:COMICREELS_GPTFP_DIR = $GptfpDir

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
Write-Host "GPT FullProxy:       $GptfpDir"
Write-Host "ChatGPT profile:     $env:COMICREELS_GPTFP_PROFILE_DIR"
Write-Host "Backend PID $($backend.Id), Frontend PID $($frontend.Id)"
Write-Host "Open http://127.0.0.1:5173/"
Write-Host "Stop both child processes when finished."
