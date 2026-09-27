param(
  [string]$SdkPath = "$env:LOCALAPPDATA\ComicReels\gpt_fullproxy-src",
  [string]$Python = "$env:LOCALAPPDATA\ComicReels\venv\Scripts\python.exe",
  [switch]$FrontendOnly,
  [switch]$WorkingTree
)
$ErrorActionPreference = 'Stop'
$Source = Split-Path -Parent $PSScriptRoot
$Commit = (& git -C $Source rev-parse HEAD).Trim()
$SdkCommit = (& git -C $SdkPath rev-parse HEAD).Trim()
$RunId = "$($Commit.Substring(0,7))-$([guid]::NewGuid().ToString('N'))"
$Evidence = Join-Path $Source "local-test-data\source-batch-$RunId"
$Isolated = Join-Path $env:LOCALAPPDATA "ComicReels\tests\source-batch-$RunId"
New-Item -ItemType Directory -Path $Evidence | Out-Null
$SourceDigest = $null
if ($WorkingTree) {
  $SnapshotJson = & $Python "$Source\scripts\source_snapshot.py" --source $Source --destination $Isolated
  if ($LASTEXITCODE -ne 0) { throw 'Working-tree snapshot failed' }
  $Snapshot = $SnapshotJson | ConvertFrom-Json
  $SourceDigest = $Snapshot.source_digest
  $SnapshotJson | Set-Content -Encoding UTF8 "$Evidence\source.json"
} else {
  New-Item -ItemType Directory -Path $Isolated | Out-Null
  $Archive = Join-Path $Evidence 'source.zip'
  & git -C $Source archive --format=zip -o $Archive HEAD
  if ($LASTEXITCODE -ne 0) { throw 'Cannot archive committed source' }
  Expand-Archive -Force $Archive $Isolated
}
$env:PYTHONUTF8 = '1'
$env:FLOW_AGENT_DIR = $Isolated
if (-not $FrontendOnly) {
Push-Location $SdkPath
try {
  & $Python -m pytest tests/test_image_batch.py tests/test_builtin_tool_guard.py tests/test_builtin_tools.py tests/test_builtin_tool_activation_race.py tests/test_abcef_dom_contract.py -q --junitxml="$Evidence\sdk.xml" *> "$Evidence\sdk.log"
  if ($LASTEXITCODE -ne 0) { throw 'SDK regression failed; see sdk.log' }
} finally { Pop-Location }
Push-Location $Isolated
try {
  & $Python -m pytest tests/unit -q --junitxml="$Evidence\unit.xml" *> "$Evidence\unit.log"
  if ($LASTEXITCODE -ne 0) { throw 'ComicReels regression failed; see unit.log' }
} finally { Pop-Location }
}
# Install from this snapshot's lockfile. Do not borrow mutable runtime node_modules.
Push-Location (Join-Path $Isolated 'dashboard')
try {
  # PowerShell 5 turns native stderr warnings into terminating errors under Stop.
  # npm's exit code is the build/lint gate; stderr remains in the log.
  $ErrorActionPreference = 'Continue'
  & npm.cmd ci --no-audit --no-fund *> "$Evidence\npm-ci.log"
  if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency install failed' }
  & npm.cmd run build *> "$Evidence\build.log"
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed; see build.log' }
  & npm.cmd run lint *> "$Evidence\lint.log"
  if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed; see lint.log' }
} finally { $ErrorActionPreference = 'Stop'; Pop-Location }
if ($WorkingTree) {
  $FinalJson = & $Python "$Source\scripts\source_snapshot.py" --source $Source
  if ($LASTEXITCODE -ne 0) { throw 'Cannot revalidate working source' }
  $FinalSource = $FinalJson | ConvertFrom-Json
  if (($FinalSource.source_digest -ne $SourceDigest) -or ($FinalSource.base_sha -ne $Commit)) {
    throw 'Working source changed during validation; snapshot results do not validate current source'
  }
}
@{state='PASS';source_commit=$Commit;source_kind=$(if($WorkingTree){'working_tree'}else{'committed'});source_digest=$SourceDigest;runtime_snapshot=$Isolated;sdk_commit=$SdkCommit;host=[Environment]::MachineName;scope=$(if($FrontendOnly){'frontend'}else{'unit_and_frontend'});live_images='NOT_RUN'} | ConvertTo-Json | Set-Content -Encoding UTF8 "$Evidence\result.json"
Get-Content "$Evidence\result.json"
