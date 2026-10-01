param(
    [string]$BuildScript = (Join-Path $PSScriptRoot 'Build-Stable.ps1'),
    [string]$DependencyLock = (Join-Path $PSScriptRoot 'dependencies.lock.json')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "ASSERTION_FAILED: $Message" }
}
function Expect-Failure([scriptblock]$Action, [string]$Code) {
    $caught = $null
    try { & $Action | Out-Null } catch { $caught = $_.Exception.Message }
    if ($null -eq $caught -or -not $caught.Contains($Code)) {
        throw "ASSERTION_FAILED: expected $Code, got $caught"
    }
}

# Import function definitions only. Never execute the deployment body.
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $BuildScript).Path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Build script has parser errors.' }
$definitions = @($ast.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.FunctionDefinitionAst]
})
foreach ($definition in $definitions) { . ([scriptblock]::Create($definition.Extent.Text)) }

$source = Get-Content -LiteralPath $BuildScript -Raw -Encoding UTF8
foreach ($required in @(
    "[Alias('NoPromote')][switch]$StageOnly",
    '[string]$StageOutputRoot',
    '[string]$RuntimeSource',
    'STAGE_ONLY_READY|',
    'promotion_performed=false',
    'Assert-StageOutputIsolated',
    'Read-DependencyLock',
    'Assert-DependencyCheckout',
    'Assert-ManifestHashes'
)) {
    Assert-Check ($source.Contains($required)) "missing StageOnly contract: $required"
}
$ready = $source.IndexOf('STAGE_ONLY_READY|')
$backup = $source.IndexOf('$backup = Join-Path $liveDestination')
Assert-Check ($ready -ge 0 -and $backup -gt $ready) 'StageOnly return must precede backup/promotion transaction'
$stageReturn = $source.IndexOf('return', $ready)
Assert-Check ($stageReturn -gt $ready -and $stageReturn -lt $backup) 'StageOnly must return before promotion'
$lockGuard = $source.IndexOf('if (-not $StageOnly) {')
$runnerLock = $source.IndexOf("runner.lock")
Assert-Check ($lockGuard -ge 0 -and $runnerLock -gt $lockGuard) 'live runner lock must be behind non-StageOnly guard'
foreach ($forbidden in @('Stop-Process','Restart-Service','Restart-Computer','paid_dispatch_enabled=True',
                          'build_paid_validation_session','build_paid_video_validation_session')) {
    Assert-Check (-not $source.Contains($forbidden)) "forbidden StageOnly/release bypass token: $forbidden"
}

$lock = Read-DependencyLock -Path $DependencyLock
$expectedPins = @{
    krp='1a0d6d0004cbe522483890d87743522243221719'
    gpt_fullproxy='412c3642ef0065b256a6bb2befe22a043a839d05'
    kbs='b539e9820d433c8c9d667b4e5d9007b6a80b8abd'
    kat='b89c2b71e6d81b82c24e41bf185d53f0f5682708'
}
Assert-Check ($lock.source_validated_base -eq 'f2a98ca2c623304f5952792139175d53127913b4') 'validated base pin'
foreach ($name in $expectedPins.Keys) {
    Assert-Check ([string]$lock.dependencies.$name.commit -eq $expectedPins[$name]) "exact dependency pin $name"
}
Expect-Failure { Read-DependencyLock -Path (Join-Path $PSScriptRoot 'missing.lock.json') } 'DEPENDENCY_LOCK_MISSING'

$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
Assert-KbsSourcePinMatchesRequirements -Repo $repo -KbsSpec $lock.dependencies.kbs
$wrongKbs = [pscustomobject]@{commit='0000000000000000000000000000000000000000'}
Expect-Failure { Assert-KbsSourcePinMatchesRequirements -Repo $repo -KbsSpec $wrongKbs } 'KBS_PIN_MISMATCH_WITH_FLOW_REQUIREMENTS'

$owned = Join-Path ([IO.Path]::GetTempPath()) ('thoremix-stageonly-contract-' + [guid]::NewGuid().ToString('N'))
$live = Join-Path $owned 'live-stable'
$stageRoot = Join-Path $owned 'isolated-stage'
New-Item -ItemType Directory -Path $live,$stageRoot -Force | Out-Null
$sentinel = Join-Path $live 'sentinel.bin'
[IO.File]::WriteAllText($sentinel, 'stable-must-not-change')
$sentinelBefore = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
$passed = 0
try {
    $observation = Assert-StageOutputIsolated -StageOutputRoot $stageRoot -LiveRoot $live
    Assert-Check ($observation.stage -ne $observation.live) 'isolated paths differ'
    Assert-Check ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -eq $sentinelBefore) 'isolation guard leaves live sentinel unchanged'
    $passed++; Write-Output 'PASS|isolated_stage_sentinel_unchanged'

    Expect-Failure { Assert-StageOutputIsolated -StageOutputRoot (Join-Path $live 'child') -LiveRoot $live } 'STAGE_OUTPUT_OVERLAPS_LIVE_STABLE'
    Expect-Failure { Assert-StageOutputIsolated -StageOutputRoot $owned -LiveRoot $live } 'STAGE_OUTPUT_OVERLAPS_LIVE_STABLE'
    $passed++; Write-Output 'PASS|reject_equal_ancestor_descendant_overlap'

    $junction = Join-Path $owned 'junction-to-live'
    New-Item -ItemType Junction -Path $junction -Target $live | Out-Null
    Expect-Failure { Assert-StageOutputIsolated -StageOutputRoot (Join-Path $junction 'nested') -LiveRoot $live } 'STAGE_OUTPUT_OVERLAPS_LIVE_STABLE'
    Assert-Check ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -eq $sentinelBefore) 'junction guard leaves live sentinel unchanged'
    $passed++; Write-Output 'PASS|junction_overlap_rejected'

    $dep = Join-Path $owned 'dep'
    New-Item -ItemType Directory -Path $dep | Out-Null
    & git -C $dep init -q
    & git -C $dep config user.email 'contract@example.invalid'
    & git -C $dep config user.name 'contract'
    [IO.File]::WriteAllText((Join-Path $dep 'pkg.txt'), 'v1')
    & git -C $dep add pkg.txt
    & git -C $dep commit -q -m 'fixture'
    $depSha = (& git -C $dep rev-parse HEAD).Trim()
    & git -C $dep remote add origin 'https://github.com/example/dependency.git'
    $spec = [pscustomobject]@{repository='https://github.com/example/dependency.git'; commit=$depSha; package='fixture'}
    $valid = Assert-DependencyCheckout -Name 'fixture' -Source $dep -Spec $spec
    Assert-Check ($valid.commit -eq $depSha) 'valid explicit dependency checkout'

    Expect-Failure { Assert-DependencyCheckout -Name 'fixture' -Source (Join-Path $owned 'missing') -Spec $spec } 'DEPENDENCY_FIXTURE_SOURCE_MISSING'
    $wrongSha = [pscustomobject]@{repository=$spec.repository; commit='0000000000000000000000000000000000000000'; package='fixture'}
    Expect-Failure { Assert-DependencyCheckout -Name 'fixture' -Source $dep -Spec $wrongSha } 'DEPENDENCY_FIXTURE_SHA_MISMATCH'
    [IO.File]::AppendAllText((Join-Path $dep 'pkg.txt'), 'dirty')
    Expect-Failure { Assert-DependencyCheckout -Name 'fixture' -Source $dep -Spec $spec } 'DEPENDENCY_FIXTURE_DIRTY'
    & git -C $dep checkout -q -- pkg.txt
    & git -C $dep remote set-url origin 'https://github.com/example/wrong.git'
    Expect-Failure { Assert-DependencyCheckout -Name 'fixture' -Source $dep -Spec $spec } 'DEPENDENCY_FIXTURE_ORIGIN_MISMATCH'
    $passed++; Write-Output 'PASS|dependency_missing_dirty_origin_sha_failclosed'

    $manifestStage = Join-Path $owned 'manifest-stage'
    New-Item -ItemType Directory -Path (Join-Path $manifestStage 'sub') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $manifestStage 'a.txt'), 'alpha')
    [IO.File]::WriteAllText((Join-Path $manifestStage 'sub\b.txt'), 'beta')
    $files = @{
        'a.txt'=(Get-FileHash -LiteralPath (Join-Path $manifestStage 'a.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
        'sub\b.txt'=(Get-FileHash -LiteralPath (Join-Path $manifestStage 'sub\b.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $actualSource = '1111111111111111111111111111111111111111'
    $manifest = New-BuildManifest -SourceCommit $actualSource -ValidatedBase $lock.source_validated_base -StageOnlyMode $true -StagePath $manifestStage -DependencyLockData $lock -Files $files
    $manifestPath = Join-Path $manifestStage 'build-manifest.json'
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Assert-Check ($manifest.source_commit -eq $actualSource) 'manifest records actual source SHA, not hard-coded validated base'
    Assert-Check ($manifest.validated_base -eq $lock.source_validated_base) 'manifest records validated base lineage'
    Assert-Check ($manifest.promotion_performed -eq $false -and $manifest.stage_only -eq $true) 'StageOnly manifest forbids promotion claim'
    foreach ($name in $expectedPins.Keys) {
        Assert-Check ($manifest.dependencies[$name].commit -eq $expectedPins[$name]) "manifest exact pin $name"
    }
    Assert-ManifestHashes -Stage $manifestStage -ManifestPath $manifestPath | Out-Null
    [IO.File]::AppendAllText((Join-Path $manifestStage 'a.txt'), 'tamper')
    Expect-Failure { Assert-ManifestHashes -Stage $manifestStage -ManifestPath $manifestPath } 'BUILD_MANIFEST_HASH_MISMATCH'
    $passed++; Write-Output 'PASS|manifest_pins_source_lineage_and_hash_tamper'

    Assert-Check ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -eq $sentinelBefore) 'all contract tests leave live sentinel unchanged'
    Write-Output ("RESULT|passed=$passed|failed=0|build_executed=False|stable_touched=False")
} finally {
    Remove-Item -LiteralPath $owned -Recurse -Force -ErrorAction SilentlyContinue
}
