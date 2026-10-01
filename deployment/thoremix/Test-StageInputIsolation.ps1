param(
    [string]$BuildScript = (Join-Path $PSScriptRoot 'Build-Stable.ps1')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "ASSERTION_FAILED: $Message" }
}
function Expect-Overlap([scriptblock]$Action, [string]$Label) {
    $caught=$null
    try { & $Action | Out-Null } catch { $caught=$_.Exception.Message }
    $expected='STAGE_OUTPUT_OVERLAPS_INPUT:' + $Label
    if ($null -eq $caught -or -not $caught.Contains($expected)) {
        throw "ASSERTION_FAILED: expected $expected, got $caught"
    }
}

$tokens=$null; $parseErrors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $BuildScript).Path,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){ throw 'Build script has parser errors.' }
$definitions=@($ast.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.FunctionDefinitionAst]
})
foreach($definition in $definitions){ . ([scriptblock]::Create($definition.Extent.Text)) }

$source=Get-Content -LiteralPath $BuildScript -Raw -Encoding UTF8
$mkdirStage=$source.IndexOf('New-Item -ItemType Directory -Path $stageBase -Force')
Assert-Check ($mkdirStage -gt 0) 'stageBase mkdir exists'
foreach($required in @(
    'Assert-StageInputDisjoint -StageOutputRoot $stageBase -InputPath $repo -InputLabel ''source_repo''',
    'Assert-StageInputDisjoint -StageOutputRoot $stageBase -InputPath $PythonHome -InputLabel ''python_home''',
    'Assert-StageInputDisjoint -StageOutputRoot $stageBase -InputPath $RuntimeSource -InputLabel ''runtime_source''',
    'Assert-StageInputDisjoint -StageOutputRoot $stageBase -InputPath ([string]$dependencies[$dependencyName].path)'
)) {
    $position=$source.IndexOf($required)
    Assert-Check ($position -ge 0 -and $position -lt $mkdirStage) "guard must execute before stage mkdir: $required"
}
$runtimeRequired=$source.IndexOf('STAGE_ONLY_RUNTIME_SOURCE_REQUIRED')
Assert-Check ($runtimeRequired -ge 0 -and $runtimeRequired -lt $mkdirStage) 'RuntimeSource required gate must precede stage mkdir'

$owned=Join-Path ([IO.Path]::GetTempPath()) ('thoremix-input-isolation-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $owned -Force | Out-Null
$labels=@(
    'runtime_source',
    'python_home',
    'source_repo',
    'dependency_krp',
    'dependency_gpt_fullproxy',
    'dependency_kbs',
    'dependency_kat'
)
$passed=0
try {
    foreach($label in $labels){
        $caseRoot=Join-Path $owned $label
        $inputPath=Join-Path $caseRoot 'input'
        $validStage=Join-Path $caseRoot 'valid-stage'
        New-Item -ItemType Directory -Path $inputPath,$validStage -Force | Out-Null
        $sentinel=Join-Path $inputPath 'sentinel.txt'
        [IO.File]::WriteAllText($sentinel,('unchanged-' + $label))
        $before=(Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash

        Expect-Overlap {
            Assert-StageInputDisjoint -StageOutputRoot $inputPath -InputPath $inputPath -InputLabel $label
        } $label
        Assert-Check ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -eq $before) "$label equal sentinel unchanged"

        $stageUnderInput=Join-Path $inputPath 'stage-child'
        Expect-Overlap {
            Assert-StageInputDisjoint -StageOutputRoot $stageUnderInput -InputPath $inputPath -InputLabel $label
        } $label
        Assert-Check (-not (Test-Path -LiteralPath $stageUnderInput)) "$label guard must not mkdir descendant stage"
        Assert-Check ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -eq $before) "$label input-ancestor sentinel unchanged"

        $stageAncestor=Join-Path $caseRoot 'stage-ancestor'
        $inputUnderStage=Join-Path $stageAncestor 'input-child'
        New-Item -ItemType Directory -Path $inputUnderStage -Force | Out-Null
        $descSentinel=Join-Path $inputUnderStage 'sentinel.txt'
        [IO.File]::WriteAllText($descSentinel,('desc-' + $label))
        $descBefore=(Get-FileHash -LiteralPath $descSentinel -Algorithm SHA256).Hash
        Expect-Overlap {
            Assert-StageInputDisjoint -StageOutputRoot $stageAncestor -InputPath $inputUnderStage -InputLabel $label
        } $label
        Assert-Check ((Get-FileHash -LiteralPath $descSentinel -Algorithm SHA256).Hash -eq $descBefore) "$label output-ancestor sentinel unchanged"

        $junctionTarget=Join-Path $caseRoot 'junction-target'
        New-Item -ItemType Directory -Path $junctionTarget -Force | Out-Null
        $junctionSentinel=Join-Path $junctionTarget 'sentinel.txt'
        [IO.File]::WriteAllText($junctionSentinel,('junction-' + $label))
        $junctionBefore=(Get-FileHash -LiteralPath $junctionSentinel -Algorithm SHA256).Hash
        $junctionAlias=Join-Path $caseRoot 'junction-alias'
        New-Item -ItemType Junction -Path $junctionAlias -Target $junctionTarget | Out-Null
        $junctionStage=Join-Path $junctionAlias 'nested-stage'
        Expect-Overlap {
            Assert-StageInputDisjoint -StageOutputRoot $junctionStage -InputPath $junctionTarget -InputLabel $label
        } $label
        Assert-Check (-not (Test-Path -LiteralPath $junctionStage)) "$label junction guard must not create stage"
        Assert-Check ((Get-FileHash -LiteralPath $junctionSentinel -Algorithm SHA256).Hash -eq $junctionBefore) "$label junction sentinel unchanged"

        $valid=Assert-StageInputDisjoint -StageOutputRoot $validStage -InputPath $inputPath -InputLabel $label
        Assert-Check ($valid.label -eq $label) "$label valid disjoint label"
        Assert-Check ($valid.stage -ne $valid.input) "$label valid disjoint physical paths differ"
        Assert-Check ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -eq $before) "$label valid path sentinel unchanged"

        $passed++
        Write-Output ("PASS|input_disjoint_" + $label)
    }
    Write-Output ("RESULT|passed=" + $passed + "|failed=0|build_executed=False|stable_touched=False")
} finally {
    Remove-Item -LiteralPath $owned -Recurse -Force -ErrorAction SilentlyContinue
}
