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
$sitePackages=Join-Path $runtimeRoot 'Lib\site-packages'
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
& $hostPython -m venv --copies $runtimeRoot
if($LASTEXITCODE -ne 0){ throw 'fixture venv creation failed' }
$stagedPython=Join-Path $runtimeRoot 'Scripts\python.exe'
Assert-Check (Test-Path -LiteralPath $stagedPython -PathType Leaf) 'staged test interpreter exists'

$wheel=Join-Path $wheelDir 'stage_probe-0.0.0-py3-none-any.whl'
Add-Type -AssemblyName System.IO.Compression
$wheelStream=[IO.File]::Open($wheel,[IO.FileMode]::Create,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$archive=[IO.Compression.ZipArchive]::new($wheelStream,[IO.Compression.ZipArchiveMode]::Create,$false)
try {
    $entries=[ordered]@{
        'stage_probe/__init__.py'="VALUE='inside-stage'"
        'stage_probe-0.0.0.dist-info/METADATA'=([string]::Join([Environment]::NewLine,@(
            'Metadata-Version: 2.1','Name: stage-probe','Version: 0.0.0',''
        )))
        'stage_probe-0.0.0.dist-info/WHEEL'=([string]::Join([Environment]::NewLine,@(
            'Wheel-Version: 1.0','Generator: thoremix-contract','Root-Is-Purelib: true','Tag: py3-none-any',''
        )))
        'stage_probe-0.0.0.data/data/share/stage_probe/prefix-data.txt'='PREFIX-DATA-OK'
        'stage_probe-0.0.0.dist-info/RECORD'=([string]::Join([Environment]::NewLine,@(
            'stage_probe/__init__.py,,',
            'stage_probe-0.0.0.data/data/share/stage_probe/prefix-data.txt,,',
            'stage_probe-0.0.0.dist-info/METADATA,,',
            'stage_probe-0.0.0.dist-info/WHEEL,,',
            'stage_probe-0.0.0.dist-info/RECORD,,',
            ''
        )))
    }
    foreach($name in $entries.Keys){
        $entry=$archive.CreateEntry($name,[IO.Compression.CompressionLevel]::Optimal)
        $writer=[IO.StreamWriter]::new($entry.Open(),[Text.UTF8Encoding]::new($false))
        try { $writer.Write([string]$entries[$name]) } finally { $writer.Dispose() }
    }
} finally {
    $archive.Dispose()
    $wheelStream.Dispose()
}
Assert-Check (Test-Path -LiteralPath $wheel -PathType Leaf) 'fixture wheel created'

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

    $runtimeEvidence=Assert-StagedPythonRuntime -StageRoot $stage -Interpreter $stagedPython -SitePackages $sitePackages
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

    Invoke-StagedPipInstall -StageRoot $stage -Interpreter $stagedPython -InstallPrefix $runtimeRoot -Options @('--no-index','--no-deps') -Packages @($wheel) | Out-Null

    $importCode=@'
import json, pathlib, stage_probe, sys
print(json.dumps({
    "value": stage_probe.VALUE,
    "module": str(pathlib.Path(stage_probe.__file__).resolve()),
    "prefix": str(pathlib.Path(sys.prefix).resolve()),
    "executable": str(pathlib.Path(sys.executable).resolve()),
}))
'@
    $importResult=Invoke-IsolatedStagedPython -StageRoot $stage -Interpreter $stagedPython -Arguments @('-c',$importCode)
    Assert-Check ($importResult.ExitCode -eq 0) 'installed module import exits zero'
    $importData=$importResult.Stdout.Trim() | ConvertFrom-Json
    Assert-Check ($importData.value -eq 'inside-stage') 'stage module wins over poisoned PYTHONPATH'
    Assert-Check ([IO.Path]::GetFullPath($importData.module).StartsWith([IO.Path]::GetFullPath($sitePackages),[StringComparison]::OrdinalIgnoreCase)) 'module file is inside staged sys.prefix site-packages'
    Assert-Check ([IO.Path]::GetFullPath($importData.prefix).StartsWith([IO.Path]::GetFullPath($stage),[StringComparison]::OrdinalIgnoreCase)) 'import validation sys.prefix inside stage'
    Assert-Check ([IO.Path]::GetFullPath($importData.executable).StartsWith([IO.Path]::GetFullPath($stage),[StringComparison]::OrdinalIgnoreCase)) 'import validation executable inside stage'

    $prefixData=Join-Path $runtimeRoot 'share\stage_probe\prefix-data.txt'
    Assert-Check (Test-Path -LiteralPath $prefixData -PathType Leaf) 'wheel data_files installed under staged sys.prefix share'
    Assert-Check ((Get-Content -LiteralPath $prefixData -Raw).Trim() -eq 'PREFIX-DATA-OK') 'wheel data_files content preserved'

    $outsidePrefix=Join-Path $poisonRoot 'outside-prefix'
    New-Item -ItemType Directory -Path $outsidePrefix -Force | Out-Null
    $outsideCaught=$null
    try {
        Invoke-StagedPipInstall -StageRoot $stage -Interpreter $stagedPython -InstallPrefix $outsidePrefix -Options @('--no-index','--no-deps') -Packages @($wheel) | Out-Null
    } catch {
        $outsideCaught=$_.Exception.Message
    }
    Assert-Check ($null -ne $outsideCaught -and $outsideCaught.Contains('STAGED_CHILD_PATH_ESCAPES_STAGE')) 'pip prefix outside stage rejected before install'

    Invoke-StagedPipInstall -StageRoot $stage -Interpreter $stagedPython -InstallPrefix $runtimeRoot -Options @('--upgrade') -Packages @('ffpyplayer==4.5.3') | Out-Null
    $ffProbeCode=@'
import json, pathlib, sys, ffpyplayer
from ffpyplayer.player import MediaPlayer
prefix = pathlib.Path(sys.prefix).resolve()
site = (prefix / "Lib" / "site-packages").resolve()
module = pathlib.Path(ffpyplayer.__file__).resolve()
dep_bins = [pathlib.Path(p).resolve() for p in ffpyplayer.dep_bins]
def inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
print(json.dumps({
    "module": str(module),
    "prefix": str(prefix),
    "dep_bins": [str(p) for p in dep_bins],
    "module_inside_site": inside(module, site),
    "all_dep_bins_inside_prefix": bool(dep_bins) and all(inside(p, prefix) for p in dep_bins),
    "prefix_ffmpeg": (prefix / "share" / "ffpyplayer" / "ffmpeg" / "bin").is_dir(),
    "prefix_sdl": (prefix / "share" / "ffpyplayer" / "sdl" / "bin").is_dir(),
    "media_player_loaded": MediaPlayer is not None,
}))
'@
    $ffProbe=Invoke-IsolatedStagedPython -StageRoot $stage -Interpreter $stagedPython -Arguments @('-c',$ffProbeCode)
    Assert-Check ($ffProbe.ExitCode -eq 0) 'ffpyplayer MediaPlayer imports in isolated staged prefix'
    $ffData=$ffProbe.Stdout.Trim() | ConvertFrom-Json
    Assert-Check ($ffData.module_inside_site -eq $true) 'ffpyplayer module imported from staged sys.prefix site-packages'
    Assert-Check ($ffData.all_dep_bins_inside_prefix -eq $true) 'ffpyplayer dependency bins remain inside staged sys.prefix'
    Assert-Check ($ffData.prefix_ffmpeg -eq $true -and $ffData.prefix_sdl -eq $true) 'ffpyplayer wheel data installed under staged sys.prefix share'
    Assert-Check ($ffData.media_player_loaded -eq $true) 'ffpyplayer MediaPlayer native module loaded'

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
    Write-Output 'PASS|wheel_data_files_land_under_staged_prefix'
    Write-Output 'PASS|ffpyplayer_real_wheel_import_and_dep_bins'
    Write-Output 'RESULT|passed=5|failed=0|build_executed=False|stable_touched=False'
} finally {
    foreach($name in $poisonNames){ [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') }
    Remove-Item -LiteralPath $owned -Recurse -Force -ErrorAction SilentlyContinue
}
