param(
    [string]$BuildScript = (Join-Path $PSScriptRoot 'Build-Stable.ps1')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Source-contract regression only. Parse the real build script; never dot-source
# or execute its deployment, pip, scheduler, lock, or promotion operations.
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $BuildScript).Path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Build script has PowerShell parse errors.' }

$katInstalls = @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
    $node.Extent.Text -match '\bpip\s+install\b' -and
    $node.Extent.Text.Contains("'kabin_affiliate_toolkit'")
}, $true))
if ($katInstalls.Count -ne 1) { throw 'Expected exactly one canonical KAT installation command.' }
$install = $katInstalls[0]

# KAT must refresh for BOTH a new interpreter and a reused interpreter. A
# command nested in if ($SkipRuntime) / else cannot satisfy this contract.
$parent = $install.Parent
while ($null -ne $parent) {
    if ($parent -is [System.Management.Automation.Language.IfStatementAst]) {
        foreach ($clause in $parent.Clauses) {
            if ($clause.Item1.Extent.Text -match '\$SkipRuntime\b') {
                throw 'KAT_REFRESH_SKIPPED: KAT installation is conditional on SkipRuntime.'
            }
        }
    }
    $parent = $parent.Parent
}

if ($install.CommandElements[0].Extent.Text -ne '"$runtime\python.exe"') {
    throw 'KAT must be installed using the staged interpreter, not the live interpreter.'
}
if (-not $install.Extent.Text.Contains("(Join-Path `$workspace 'kabin_affiliate_toolkit')")) {
    throw 'KAT must come from the canonical workspace checkout.'
}
if ($install.Extent.Text -notmatch '(?<!\S)--force-reinstall(?!\S)' -or
    $install.Extent.Text -notmatch '(?<!\S)--no-deps(?!\S)') {
    throw 'KAT refresh must replace same-version snapshots without upgrading dependency pins.'
}

$pipeline = $install.Parent
while ($null -ne $pipeline -and $pipeline -isnot [System.Management.Automation.Language.PipelineAst]) {
    $pipeline = $pipeline.Parent
}
if ($null -eq $pipeline -or
    $pipeline.Parent -isnot [System.Management.Automation.Language.StatementBlockAst]) {
    throw 'KAT installation must be a direct staged-build statement.'
}
$next = @($pipeline.Parent.Statements | Where-Object {
    $_.Extent.StartOffset -gt $pipeline.Extent.EndOffset
} | Sort-Object { $_.Extent.StartOffset })
if ($next.Count -eq 0 -or
    $next[0].Extent.Text -notmatch '^if\s*\(\$LASTEXITCODE\s+-ne\s+0\)\s*\{\s*throw\b') {
    throw 'Failed KAT installation must stop before validation or promotion.'
}

$validation = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -eq '$validation'
}, $true)
if ($null -eq $validation -or $install.Extent.EndOffset -ge $validation.Extent.StartOffset) {
    throw 'KAT refresh must precede bundle validation.'
}
foreach ($required in @(
    "'sold_min', 'commission_min'",
    'kat_config.catalog_first is True',
    'kat_config.legacy_public_search_fallback is False'
)) {
    if (-not $validation.Extent.Text.Contains($required)) {
        throw "Existing fail-closed KAT validation must remain: $required"
    }
}

Write-Output 'KAT_STAGING_CONTRACT_PASS: shared staged refresh, same-version reinstall, failure gate, contract guards.'
