param(
    [string]$BuildScript = (Join-Path $PSScriptRoot 'Build-Stable.ps1')
)
$ErrorActionPreference = 'Stop'
# Import ONLY top-level function definitions. Never execute the build body,
# runner lock, dependency installation, or operations on an installed bundle.
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $BuildScript).Path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Build script has parser errors.' }
$definitions = @($ast.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.FunctionDefinitionAst]
})
foreach ($definition in $definitions) { . ([scriptblock]::Create($definition.Extent.Text)) }
function Assert-Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "ASSERTION_FAILED: $Message" }
}
function Read-MoveEvents {
    foreach ($line in ($capture.ToString() -split '\r?\n')) {
        if ($line.StartsWith('THOREMIX_MOVE_FAILURE ')) {
            $line.Substring('THOREMIX_MOVE_FAILURE '.Length) | ConvertFrom-Json
        }
    }
}
$owned = Join-Path ([IO.Path]::GetTempPath()) ('thoremix-move-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $owned | Out-Null
$originalError = [Console]::Error
$capture = [IO.StringWriter]::new()
[Console]::SetError($capture)
$passed = 0
try {
    # 1. Real successful rename: no diagnostic and no success-stream pollution.
    $source = Join-Path $owned 'success-source'; $target = Join-Path $owned 'success-target'
    New-Item -ItemType Directory -Path $source | Out-Null
    [IO.File]::WriteAllText((Join-Path $source 'keep.txt'), 'unchanged')
    $result = @(Move-UpgradePart -Source $source -Destination $target -Label 'source stage->live')
    Assert-Check ($result.Count -eq 0) 'successful helper must have no output'
    Assert-Check ([IO.File]::ReadAllText((Join-Path $target 'keep.txt')) -eq 'unchanged') 'successful move'
    Assert-Check ($capture.ToString().Length -eq 0) 'success must not emit failure records'
    $passed++; Write-Output 'PASS|successful_move'

    # Controlled faults avoid sleeping; preserve and assert the original schedule.
    function Start-Sleep { param([int]$Milliseconds) $script:delays += $Milliseconds }
    function Move-Item {
        [CmdletBinding()] param([string]$LiteralPath, [string]$Destination)
        $script:moveCalls++
        if ($script:moveCalls -le $script:failCount) { throw $script:moveFailure }
        Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination -ErrorAction Stop
    }
    $source = Join-Path $owned 'failure-source'; $target = Join-Path $owned 'failure-target'
    New-Item -ItemType Directory -Path $source | Out-Null
    $script:moveCalls = 0; $script:delays = @(); $script:failCount = 99
    $script:moveFailure = [IO.IOException]::new('synthetic-sharing-failure', -2147024864)
    $caught = $null
    try { Move-UpgradePart -Source $source -Destination $target -Label 'source live->backup' }
    catch { $caught = $_ }
    $events = @(Read-MoveEvents)
    Assert-Check ($events.Count -eq 8) 'every failed move attempt must emit a diagnostic'
    Assert-Check ($script:moveCalls -eq 8) 'retry count must remain eight'
    Assert-Check (($script:delays -join ',') -eq '250,500,750,1000,1250,1500,1750') 'backoff must remain unchanged'
    Assert-Check ($caught.Exception.Message -eq 'synthetic-sharing-failure') 'original failure must be rethrown'
    foreach ($event in $events) {
        Assert-Check ($event.source.path -eq $source -and $event.destination.path -eq $target) 'paths bound'
        Assert-Check ($event.label -eq 'source live->backup') 'phase label bound'
        Assert-Check ($event.source.state -eq 'present' -and $event.destination.state -eq 'missing') 'path observations'
        Assert-Check ($event.exceptions[0].hresult -eq '0x80070020') 'HRESULT retained'
        Assert-Check ($event.exceptions[0].hresult_win32_code -eq 32) 'HRESULT-derived code'
        Assert-Check ($null -eq $event.exceptions[0].native_win32_code) 'do not invent NativeErrorCode'
        Assert-Check ($event.pid -eq $PID -and $event.utc -and $event.process_cwd) 'failure-time context'
    }
    Assert-Check ($events[0].attempt -eq 1 -and $events[7].attempt -eq 8) 'attempt ordering'
    Assert-Check ((Test-Path -LiteralPath $source) -and -not (Test-Path -LiteralPath $target)) 'failed source retained'
    $passed++; Write-Output 'PASS|failure_context_and_retry_invariants'

    # 3. A later successful retry logs failures only and returns normally.
    $capture.GetStringBuilder().Clear() | Out-Null
    $script:moveCalls = 0; $script:delays = @(); $script:failCount = 2
    $script:moveFailure = [UnauthorizedAccessException]::new('synthetic-access-denied')
    $result = @(Move-UpgradePart -Source $source -Destination $target -Label 'source stage->live')
    $events = @(Read-MoveEvents)
    Assert-Check ($script:moveCalls -eq 3 -and $events.Count -eq 2 -and $result.Count -eq 0) 'recovered retry'
    Assert-Check ($events[0].exceptions[0].hresult_win32_code -eq 5) 'access HRESULT code'
    $passed++; Write-Output 'PASS|retry_then_success'

    # 4. Broken logging must not mask the original error or disable retries.
    $capture.GetStringBuilder().Clear() | Out-Null
    function Write-UpgradeMoveDiagnostic { throw 'synthetic-logger-failure' }
    $source = Join-Path $owned 'logger-source'; $target = Join-Path $owned 'logger-target'
    New-Item -ItemType Directory -Path $source | Out-Null
    $script:moveCalls = 0; $script:delays = @(); $script:failCount = 99
    $script:moveFailure = [IO.IOException]::new('original-move-still-wins', -2147024864)
    $caught = $null
    try { Move-UpgradePart -Source $source -Destination $target -Label 'rollback live->stage' }
    catch { $caught = $_ }
    Assert-Check ($caught.Exception.Message -eq 'original-move-still-wins') 'logger must not mask move error'
    Assert-Check ($script:moveCalls -eq 8) 'logger failure must not alter retries'
    Assert-Check ($capture.ToString().Contains('THOREMIX_MOVE_DIAGNOSTIC_UNAVAILABLE')) 'logger failure must be visible'
    $passed++; Write-Output 'PASS|logging_failure_preserves_error'
    foreach ($definition in $definitions) { . ([scriptblock]::Create($definition.Extent.Text)) }

    # 5. Generic managed HRESULT is not a native Win32 error; inner code is explicit.
    $capture.GetStringBuilder().Clear() | Out-Null
    $inner = [ComponentModel.Win32Exception]::new(32, 'synthetic native error')
    $outer = [Exception]::new('synthetic wrapper', $inner)
    $record = [System.Management.Automation.ErrorRecord]::new(
        $outer, 'SyntheticMove', [System.Management.Automation.ErrorCategory]::WriteError, $source)
    Write-UpgradeMoveDiagnostic -Failure $record -Source $source -Destination $target -Label 'source live->backup' -Attempt 1
    $events = @(Read-MoveEvents)
    Assert-Check ($events.Count -eq 1) 'single diagnostic record'
    Assert-Check ($null -eq $events[0].exceptions[0].hresult_win32_code) 'managed HRESULT is not Win32'
    Assert-Check ($events[0].exceptions[1].native_win32_code -eq 32) 'inner native code retained'
    Assert-Check (-not $capture.ToString().Contains('command_line')) 'no command-line collection'
    $passed++; Write-Output 'PASS|native_and_managed_error_distinction'

    # 6. Real Windows sharing failure, entirely under an owned temporary folder.
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        Remove-Item Function:\Move-Item
        $capture.GetStringBuilder().Clear() | Out-Null
        $source = Join-Path $owned 'locked.bin'; $target = Join-Path $owned 'locked-moved.bin'
        [IO.File]::WriteAllText($source, 'keep-locked-file')
        $handle = [IO.File]::Open($source, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
        $caught = $null
        try { Move-UpgradePart -Source $source -Destination $target -Label 'locked-file live->backup' }
        catch { $caught = $_ }
        finally { $handle.Dispose() }
        $events = @(Read-MoveEvents)
        Assert-Check ($null -ne $caught -and $events.Count -eq 8) 'real sharing failure captured'
        Assert-Check ($events[0].exceptions[0].hresult -match '^0x[0-9A-F]{8}$') 'real HRESULT recorded'
        Assert-Check ([IO.File]::ReadAllText($source) -eq 'keep-locked-file') 'locked file unchanged'
        Assert-Check (-not (Test-Path -LiteralPath $target)) 'no unintended move'
        $passed++; Write-Output 'PASS|real_windows_sharing_failure'
    }
    Write-Output ("RESULT|passed=$passed|failed=0|build_executed=False|stable_touched=False")
} finally {
    [Console]::SetError($originalError)
    $capture.Dispose()
    # Only delete the uniquely owned test directory, never any caller path.
    Remove-Item -LiteralPath $owned -Recurse -Force
}
