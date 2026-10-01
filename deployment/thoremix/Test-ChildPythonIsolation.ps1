param(
    [string]$BuildScript = (Join-Path $PSScriptRoot 'Build-Stable.ps1'),
    [string]$IsolationScript = (Join-Path $PSScriptRoot 'Child-PythonIsolation.ps1')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "ASSERTION_FAILED: $Message" }
}

$tokens=$null; $parseErrors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $BuildScript).Path,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){ throw 'Build script has parser errors.' }
$definitions=@($ast.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.FunctionDefinitionAst]
})
foreach($definition in $definitions){ . ([scriptblock]::Create($definition.Extent.Text)) }
. (Resolve-Path -LiteralPath $IsolationScript).Path

$owned=Join-Path ([IO.Path]::GetTempPath()) ('thoremix-child-env-' + [guid]::NewGuid().ToString('N'))
$stage=Join-Path $owned 'stage'
$runtimeRoot=Join-Path $stage 'runtime\venv'
$installTarget=Join-Path $stage 'runtime\installed'
$wheelDir=Join-Path $stage 'fixture'
$poisonRoot=Join-Path $owned 'live-sentinel'
$poisonTarget=Join-Path $poisonRoot 'pip-target'
$poisonPrefix=Join-Path $poisonRoot 'pip-prefix'
$poisonInstallRoot=Join-Path $poisonRoot 'pip-root'
$poisonPythonHome=Join-Path $poisonRoot 'python-home'
$poisonPythonPath=Join-Path $poisonRoot 'pythonpath'
$poisonAppData=Join-Path $poisonRoot 'appdata'
$pipConfig=Join-Path $poisonAppData 'pip\pip.ini'
$sentinel=Join-Path $poisonRoot 'sentinel.txt'

New-Item -ItemType Directory -Path $stage,$wheelDir,$poisonTarget,$poisonPrefix,$poisonInstallRoot,$poisonPythonHome,$poisonPythonPath,(Split-Path -Parent $pipConfig) -Force | Out-Null
[IO.File]::WriteAllText($sentinel,'DO-NOT-TOUCH')
[IO.File]::WriteAllText((Join-Path $poisonPythonPath 'poison_only.py'),"VALUE='poison'")
[IO.File]::WriteAllLines($pipConfig,@('[global]',('target = ' + $poisonTarget)))
$sentinelHash=(Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
$pipConfigHash=(Get-FileHash -LiteralPath $pipConfig -Algorithm SHA256).Hash

$hostPython=(Get-Command python -ErrorAction Stop).Source
& $hostPython -m venv $runtimeRoot
if($LASTEXITCODE -ne 0){ throw 'fixture venv creation failed' }
$stagedPython=Join-Path $runtimeRoot 'Scripts\python.exe'
Assert-Check (Test-Path -LiteralPath $stagedPython -PathType Leaf) 'staged test interpreter exists'

$wheel=Join-Path $wheelDir 'stage_probe-0.0.0-py3-none-any.whl'
$wheelBuilder=@'
import pathlib, sys, zipfile
path = pathlib.Path(sys.argv[1])
files = {
    "stage_probe/__init__.py": "VALUE='inside-stage'\n",
    "stage_probe-0.0.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: stage-probe\nVersion: 0.0.0\n",
    "stage_probe-0.0.0.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: thoremix-contract\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    "stage_probe-0.0.0.dist-info/RECORD": "stage_probe/__init__.py,,\nstage_probe-0.0.0.dist-info/METADATA,,\nstage_probe-0.0.0.dist-info/WHEEL,,\nstage_probe-0.0.0.dist-info/RECORD,,\n",
}
with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
    for name, value in files.items():
        archive.writestr(name, value)
'@
& $hostPython -c $wheelBuilder $wheel
if($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $wheel)){ throw 'fixture wheel creation failed' }

$poisonNames=@('PIP_TARGET','PIP_PREFIX','PIP_ROOT','PIP_CONFIG_FILE','PYTHONHOME','PYTHONPATH','APPDATA')
$saved=@{}
foreach($name in $poisonNames){ $saved[$name]=[Environment]::GetEnvironmentVariable($name,'Process') }

try {
    $env:PIP_TARGET=$poisonTarget
    $env:PIP_PREFIX=$poisonPrefix
    $env:PIP_ROOT=$poisonInstallRoot
    $env:PIP_CONFIG_FILE=$pipConfig
    $env:PYTHONHOME=$poisonPythonHome
    $env:PYTHONPATH=$poisonPythonPath
    $env:APPDATA=$poisonAppData

    $runtimeEvidence=Assert-StagedPythonRuntime -StageRoot $stage -Interpreter $stagedPython -SitePackages $installTarget
    Assert-Check ($runtimeEvidence.exe_inside_stage -eq $true) 'actual sys.executable is inside stage'
    Assert-Check ($runtimeEvidence.prefix_inside_stage -eq $true) 'actual sys.prefix is inside stage'

    $probeCode=@'
import importlib.util, json, os
keys = ["PIP_TARGET","PIP_PREFIX","PIP_ROOT","PYTHONHOME","PYTHONPATH","PIP_CONFIG_FILE","TEMP","TMP"]
print(json.dumps({
    "env": {k: os.environ.get(k) for k in keys},
    "poison_spec": None if importlib.util.find_spec("poison_only") is None else str(importlib.util.find_spec("poison_only").origin),
}))
'@
    $probe=Invoke-IsolatedStagedPython -StageRoot $stage -Interpreter $stagedPython -Arguments @('-c',$probeCode)
    Assert-Check ($probe.ExitCode -eq 0) 'poison probe child exits zero'
    $probeData=$probe.Stdout.Trim() | ConvertFrom-Json
    foreach($name in @('PIP_TARGET','PIP_PREFIX','PIP_ROOT','PYTHONHOME','PYTHONPATH')){
        Assert-Check ($null -eq $probeData.env.$name) "child clears $name"
    }
    Assert-Check ($probeData.env.PIP_CONFIG_FILE -eq 'NUL') 'child ignores pip config files'
    Assert-Check ($null -eq $probeData.poison_spec) 'parent PYTHONPATH cannot inject imports'

    Invoke-StagedPipInstall -StageRoot $stage -Interpreter $stagedPython -InstallTarget $installTarget -Options @('--no-index','--no-deps') -Packages @($wheel) | Out-Null

    $importCode=@'
import json, pathlib, stage_probe, sys
print(json.dumps({
    "value": stage_probe.VALUE,
    "module": str(pathlib.Path(stage_probe.__file__).resolve()),
    "prefix": str(pathlib.Path(sys.prefix).resolve()),
    "executable": str(pathlib.Path(sys.executable).resolve()),
}))
'@
    $importResult=Invoke-IsolatedStagedPython -StageRoot $stage -Interpreter $stagedPython -Arguments @('-c',$importCode) -PythonPath @($installTarget)
    Assert-Check ($importResult.ExitCode -eq 0) 'installed module import exits zero'
    $importData=$importResult.Stdout.Trim() | ConvertFrom-Json
    Assert-Check ($importData.value -eq 'inside-stage') 'stage module wins over poisoned PYTHONPATH'
    Assert-Check ([IO.Path]::GetFullPath($importData.module).StartsWith([IO.Path]::GetFullPath($installTarget),[StringComparison]::OrdinalIgnoreCase)) 'module file is inside explicit install target'
    Assert-Check ([IO.Path]::GetFullPath($importData.prefix).StartsWith([IO.Path]::GetFullPath($stage),[StringComparison]::OrdinalIgnoreCase)) 'import validation sys.prefix inside stage'
    Assert-Check ([IO.Path]::GetFullPath($importData.executable).StartsWith([IO.Path]::GetFullPath($stage),[StringComparison]::OrdinalIgnoreCase)) 'import validation executable inside stage'

    Assert-Check ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -eq $sentinelHash) 'live sentinel unchanged'
    Assert-Check ((Get-FileHash -LiteralPath $pipConfig -Algorithm SHA256).Hash -eq $pipConfigHash) 'poison pip.ini unchanged'
    Assert-Check (@(Get-ChildItem -LiteralPath $poisonTarget -Force).Count -eq 0) 'PIP_TARGET received no writes'
    Assert-Check (@(Get-ChildItem -LiteralPath $poisonPrefix -Force).Count -eq 0) 'PIP_PREFIX received no writes'
    Assert-Check (@(Get-ChildItem -LiteralPath $poisonInstallRoot -Force).Count -eq 0) 'PIP_ROOT received no writes'

    Assert-Check ($env:PIP_TARGET -eq $poisonTarget) 'parent PIP_TARGET remains unchanged'
    Assert-Check ($env:PIP_PREFIX -eq $poisonPrefix) 'parent PIP_PREFIX remains unchanged'
    Assert-Check ($env:PIP_ROOT -eq $poisonInstallRoot) 'parent PIP_ROOT remains unchanged'
    Assert-Check ($env:PIP_CONFIG_FILE -eq $pipConfig) 'parent PIP_CONFIG_FILE remains unchanged'
    Assert-Check ($env:PYTHONHOME -eq $poisonPythonHome) 'parent PYTHONHOME remains unchanged'
    Assert-Check ($env:PYTHONPATH -eq $poisonPythonPath) 'parent PYTHONPATH remains unchanged'
    Assert-Check ($env:APPDATA -eq $poisonAppData) 'parent APPDATA remains unchanged'

    Write-Output 'PASS|child_env_poison_isolated'
    Write-Output 'PASS|pip_config_ignored_without_tls_disable'
    Write-Output 'PASS|actual_prefix_and_module_paths_inside_stage'
    Write-Output 'RESULT|passed=3|failed=0|build_executed=False|stable_touched=False'
} finally {
    foreach($name in $poisonNames){ [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') }
    Remove-Item -LiteralPath $owned -Recurse -Force -ErrorAction SilentlyContinue
}
