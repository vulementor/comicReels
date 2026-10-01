param(
    [string]$BuildScript = (Join-Path $PSScriptRoot 'Build-Stable.ps1')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $BuildScript).Path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Build script has PowerShell parse errors.' }

$katInstalls = @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
    $node.GetCommandName() -eq 'Invoke-StagedPipInstall' -and
    $node.Extent.Text.Contains('$dependencies.kat.path')
}, $true))
if ($katInstalls.Count -ne 1) { throw 'Expected exactly one explicit pinned KAT installation command.' }
$install = $katInstalls[0]

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

if (-not $install.Extent.Text.Contains('-Interpreter $stagedPython') -or
        -not $install.Extent.Text.Contains('-InstallTarget $sitePackages')) {
    throw 'KAT must install through the isolated staged interpreter and target.'
}
if (-not $install.Extent.Text.Contains("'--force-reinstall'") -or
    -not $install.Extent.Text.Contains("'--no-deps'")) {
    throw 'KAT refresh must replace same-version snapshots without upgrading dependency pins.'
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
    'kat_config.legacy_public_search_fallback is False',
    "ShopeeVNProvider.product_offer_url == 'https://affiliate.shopee.vn/offer/product_offer'"
)) {
    if (-not $validation.Extent.Text.Contains($required)) {
        throw "Existing fail-closed KAT validation must remain: $required"
    }
}

$source = Get-Content -LiteralPath $BuildScript -Raw -Encoding UTF8
foreach ($required in @(
    '[string]$KatSource',
    '[string]$KrpSource',
    '[string]$GptFullProxySource',
    '[string]$KbsSource',
    'Read-DependencyLock',
    'Assert-DependencyCheckout'
)) {
    if (-not $source.Contains($required)) {
        throw "Explicit dependency contract missing: $required"
    }
}
foreach ($forbidden in @(
    "(Join-Path `$workspace 'kabin_affiliate_toolkit')",
    "(Join-Path `$workspace 'kabin_reel_poster')",
    "(Join-Path `$workspace 'gpt_fullproxy')",
    "(Join-Path `$workspace 'kabin_browser_semantic')"
)) {
    if ($source.Contains($forbidden)) {
        throw "Build script must not guess dependency sibling-folder names: $forbidden"
    }
}

Write-Output 'KAT_STAGING_CONTRACT_PASS: explicit pinned checkout, shared staged refresh, same-version reinstall, failure gate, contract guards.'
