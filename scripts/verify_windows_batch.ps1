param(
  [string]$SdkPath = "$env:LOCALAPPDATA\ComicReels\gpt_fullproxy-src",
  [string]$Python = "$env:LOCALAPPDATA\ComicReels\venv\Scripts\python.exe",
  [switch]$FrontendOnly
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
if (-not $FrontendOnly) {
Push-Location $SdkPath
try {
  & $Python -m pytest tests/test_image_batch.py tests/test_builtin_tool_guard.py tests/test_builtin_tools.py -q --junitxml="$Evidence\sdk.xml" *> "$Evidence\sdk.log"
  if ($LASTEXITCODE -ne 0) { throw 'SDK regression failed; see sdk.log' }
} finally { Pop-Location }
Push-Location $Isolated
try {
  & $Python -m pytest tests/unit -q --junitxml="$Evidence\unit.xml" *> "$Evidence\unit.log"
  if ($LASTEXITCODE -ne 0) { throw 'ComicReels regression failed; see unit.log' }
} finally { Pop-Location }
}
# Build the isolated committed frontend; the source checkout may have no npm install.
$Modules = Join-Path $Isolated 'dashboard\node_modules'
$CachedModules = Join-Path $env:LOCALAPPDATA 'ComicReels\runtime\dashboard\node_modules'
if (-not (Test-Path $Modules) -and (Test-Path $CachedModules)) {
  New-Item -ItemType Junction -Path $Modules -Target $CachedModules | Out-Null
}
Push-Location (Join-Path $Isolated 'dashboard')
try {
  # PowerShell 5 turns native stderr warnings into terminating errors under Stop.
  # npm's exit code is the build/lint gate; stderr remains in the log.
  $ErrorActionPreference = 'Continue'
  if (-not (Test-Path 'node_modules\.bin\tsc.cmd')) {
    & npm.cmd ci --no-audit --no-fund *> "$Evidence\npm-ci.log"
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency install failed' }
  }
  & npm.cmd run build *> "$Evidence\build.log"
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed; see build.log' }
  & npm.cmd run lint *> "$Evidence\lint.log"
  if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed; see lint.log' }
} finally { $ErrorActionPreference = 'Stop'; Pop-Location }
@{state='PASS';source_commit=$Commit;sdk_commit=$SdkCommit;host=$env:COMPUTERNAME;scope=$(if($FrontendOnly){'frontend'}else{'unit_and_frontend'});live_images='NOT_RUN'} | ConvertTo-Json | Set-Content -Encoding UTF8 "$Evidence\result.json"
Get-Content "$Evidence\result.json"
