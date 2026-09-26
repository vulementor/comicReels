param(
  [string]$SdkPath = "$env:LOCALAPPDATA\ComicReels\gpt_fullproxy-src",
  [string]$Python = "$env:LOCALAPPDATA\ComicReels\venv\Scripts\python.exe"
)
$ErrorActionPreference = 'Stop'
$Source = Split-Path -Parent $PSScriptRoot
$Commit = (& git -C $Source rev-parse HEAD).Trim()
$SdkCommit = (& git -C $SdkPath rev-parse HEAD).Trim()
$Evidence = Join-Path $Source "local-test-data\source-batch-$($Commit.Substring(0,7))"
$Isolated = Join-Path $env:LOCALAPPDATA "ComicReels\tests\source-batch-$($Commit.Substring(0,7))"
New-Item -ItemType Directory -Force $Evidence,$Isolated | Out-Null
$Archive = Join-Path $Evidence 'source.zip'
& git -C $Source archive --format=zip -o $Archive HEAD
if ($LASTEXITCODE -ne 0) { throw 'Cannot archive committed source' }
Expand-Archive -Force $Archive $Isolated
$env:PYTHONUTF8 = '1'
$env:FLOW_AGENT_DIR = $Isolated
Push-Location $SdkPath
try {
  & $Python -m pytest tests/test_image_batch.py -q --junitxml="$Evidence\sdk.xml" *> "$Evidence\sdk.log"
  if ($LASTEXITCODE -ne 0) { throw 'SDK regression failed; see sdk.log' }
} finally { Pop-Location }
Push-Location $Isolated
try {
  & $Python -m pytest tests/unit -q --junitxml="$Evidence\unit.xml" *> "$Evidence\unit.log"
  if ($LASTEXITCODE -ne 0) { throw 'ComicReels regression failed; see unit.log' }
} finally { Pop-Location }
# Build the committed frontend using installed dependencies; no browser interaction.
Push-Location (Join-Path $Source 'dashboard')
try {
  & npm.cmd run build *> "$Evidence\build.log"
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed; see build.log' }
  & npm.cmd run lint *> "$Evidence\lint.log"
  if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed; see lint.log' }
} finally { Pop-Location }
@{state='PASS';source_commit=$Commit;sdk_commit=$SdkCommit;host=$env:COMPUTERNAME;live_images='NOT_RUN'} | ConvertTo-Json | Set-Content -Encoding UTF8 "$Evidence\result.json"
Get-Content "$Evidence\result.json"
