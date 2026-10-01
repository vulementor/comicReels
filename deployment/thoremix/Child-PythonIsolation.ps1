Set-StrictMode -Version Latest

function ConvertTo-ChildProcessArgument {
    param([AllowEmptyString()][string]$Value)
    if ($Value.Length -eq 0) { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    $builder = [Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $slashes++
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * ($slashes * 2 + 1)))
            [void]$builder.Append('"')
            $slashes = 0
            continue
        }
        if ($slashes) {
            [void]$builder.Append(('\' * $slashes))
            $slashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($slashes) { [void]$builder.Append(('\' * ($slashes * 2))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Resolve-StagedChildPath {
    param(
        [Parameter(Mandatory=$true)][string]$StageRoot,
        [Parameter(Mandatory=$true)][string]$CandidatePath,
        [switch]$AllowMissing
    )
    $stage = Resolve-PhysicalBuildPath -Path $StageRoot
    $candidate = $null
    if (Test-Path -LiteralPath $CandidatePath) {
        $item = Get-Item -LiteralPath $CandidatePath -Force -ErrorAction Stop
        if ($item.PSIsContainer) {
            $candidate = Resolve-PhysicalBuildPath -Path $item.FullName
        } else {
            $parent = Resolve-PhysicalBuildPath -Path $item.DirectoryName
            $candidate = Join-Path $parent $item.Name
        }
    } elseif ($AllowMissing) {
        $candidate = Resolve-PhysicalBuildPath -Path $CandidatePath -AllowMissing
    } else {
        throw "STAGED_CHILD_PATH_MISSING: $CandidatePath"
    }
    $separator = [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($stage + $separator, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'STAGED_CHILD_PATH_ESCAPES_STAGE'
    }
    return $candidate
}

function Invoke-IsolatedStagedPython {
    param(
        [Parameter(Mandatory=$true)][string]$StageRoot,
        [Parameter(Mandatory=$true)][string]$Interpreter,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [string]$WorkingDirectory = '',
        [string]$InstallPrefix = '',
        [string[]]$PythonPath = @(),
        [hashtable]$Environment = @{},
        [switch]$EchoOutput
    )
    $stage = Resolve-PhysicalBuildPath -Path $StageRoot
    $interpreterPath = Resolve-StagedChildPath -StageRoot $stage -CandidatePath $Interpreter
    if (-not (Test-Path -LiteralPath $interpreterPath -PathType Leaf)) {
        throw 'STAGED_PYTHON_INTERPRETER_INVALID'
    }
    $working = if ([string]::IsNullOrWhiteSpace($WorkingDirectory)) {
        $stage
    } else {
        Resolve-StagedChildPath -StageRoot $stage -CandidatePath $WorkingDirectory
    }
    $install = $null
    if (-not [string]::IsNullOrWhiteSpace($InstallPrefix)) {
        $install = Resolve-StagedChildPath -StageRoot $stage -CandidatePath $InstallPrefix -AllowMissing
        New-Item -ItemType Directory -Path $install -Force | Out-Null
        $install = Resolve-StagedChildPath -StageRoot $stage -CandidatePath $install
    }
    $pythonPaths = @()
    foreach ($path in $PythonPath) {
        $pythonPaths += Resolve-StagedChildPath -StageRoot $stage -CandidatePath $path
    }

    $protected = @(
        'PIP_TARGET','PIP_PREFIX','PIP_ROOT','PIP_USER','PIP_CONFIG_FILE',
        'PIP_REQUIRE_VIRTUALENV','PIP_CACHE_DIR','PIP_SRC','PIP_BUILD_TRACKER','PIP_LOG',
        'PIP_TRUSTED_HOST',
        'PYTHONHOME','PYTHONPATH','PYTHONUSERBASE','VIRTUAL_ENV',
        'TEMP','TMP'
    )
    foreach ($name in $Environment.Keys) {
        if ($protected -contains [string]$name) {
            throw "CHILD_ENVIRONMENT_OVERRIDE_FORBIDDEN: $name"
        }
    }

    $childTemp = Join-Path $stage '.child-temp'
    New-Item -ItemType Directory -Path $childTemp -Force | Out-Null

    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $interpreterPath
    $psi.Arguments = (($Arguments | ForEach-Object { ConvertTo-ChildProcessArgument ([string]$_) }) -join ' ')
    $psi.WorkingDirectory = $working
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    foreach ($name in $protected) { [void]$psi.EnvironmentVariables.Remove($name) }
    $psi.EnvironmentVariables['PIP_CONFIG_FILE'] = 'NUL'
    $psi.EnvironmentVariables['PIP_NO_CACHE_DIR'] = '1'
    $psi.EnvironmentVariables['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    $psi.EnvironmentVariables['PIP_NO_INPUT'] = '1'
    $psi.EnvironmentVariables['PYTHONNOUSERSITE'] = '1'
    $psi.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'
    $psi.EnvironmentVariables['TEMP'] = $childTemp
    $psi.EnvironmentVariables['TMP'] = $childTemp
    if ($pythonPaths.Count) {
        $psi.EnvironmentVariables['PYTHONPATH'] = ($pythonPaths -join [IO.Path]::PathSeparator)
    }
    foreach ($name in $Environment.Keys) {
        $psi.EnvironmentVariables[[string]$name] = [string]$Environment[$name]
    }

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $psi
    if (-not $process.Start()) { throw 'STAGED_PYTHON_START_FAILED' }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $result = [pscustomobject]@{
        ExitCode=$process.ExitCode
        Stdout=$stdout
        Stderr=$stderr
        Interpreter=$interpreterPath
        WorkingDirectory=$working
        InstallPrefix=$install
    }
    if ($EchoOutput) {
        if ($stdout) { [Console]::Out.Write($stdout) }
        if ($stderr) { [Console]::Error.Write($stderr) }
    }
    return $result
}

function Invoke-StagedPipInstall {
    param(
        [Parameter(Mandatory=$true)][string]$StageRoot,
        [Parameter(Mandatory=$true)][string]$Interpreter,
        [Parameter(Mandatory=$true)][string]$InstallPrefix,
        [Parameter(Mandatory=$true)][string[]]$Packages,
        [string[]]$Options = @()
    )
    $prefix = Resolve-StagedChildPath -StageRoot $StageRoot -CandidatePath $InstallPrefix -AllowMissing
    New-Item -ItemType Directory -Path $prefix -Force | Out-Null
    $prefix = Resolve-StagedChildPath -StageRoot $StageRoot -CandidatePath $prefix
    $probeCode = @'
import pathlib, sys
print(pathlib.Path(sys.prefix).resolve())
'@
    $probe = Invoke-IsolatedStagedPython -StageRoot $StageRoot -Interpreter $Interpreter -Arguments @('-c',$probeCode)
    if ($probe.ExitCode -ne 0) { throw 'STAGED_PYTHON_PREFIX_UNVERIFIED' }
    $actualPrefix = Resolve-PhysicalBuildPath -Path $probe.Stdout.Trim()
    if (-not $actualPrefix.Equals($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'STAGED_PYTHON_PREFIX_MISMATCH'
    }
    $arguments = @('-m','pip','--isolated','install','--disable-pip-version-check') + $Options + @('--prefix',$prefix) + $Packages
    $result = Invoke-IsolatedStagedPython -StageRoot $StageRoot -Interpreter $Interpreter -Arguments $arguments -InstallPrefix $prefix -EchoOutput
    if ($result.ExitCode -ne 0) { throw 'STAGED_PIP_INSTALL_FAILED' }
    return $result
}

function Assert-StagedPythonRuntime {
    param(
        [Parameter(Mandatory=$true)][string]$StageRoot,
        [Parameter(Mandatory=$true)][string]$Interpreter,
        [Parameter(Mandatory=$true)][string]$SitePackages
    )
    $code = @'
import json, pathlib, sys
stage = pathlib.Path(sys.argv[1]).resolve()
site = pathlib.Path(sys.argv[2]).resolve()
exe = pathlib.Path(sys.executable).resolve()
prefix = pathlib.Path(sys.prefix).resolve()
def inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
print(json.dumps({
    "executable": str(exe),
    "prefix": str(prefix),
    "site": str(site),
    "exe_inside_stage": inside(exe, stage),
    "prefix_inside_stage": inside(prefix, stage),
    "site_inside_stage": inside(site, stage),
}))
if not (inside(exe, stage) and inside(prefix, stage) and inside(site, stage)):
    raise SystemExit(71)
'@
    $result = Invoke-IsolatedStagedPython -StageRoot $StageRoot -Interpreter $Interpreter -Arguments @('-c',$code,$StageRoot,$SitePackages)
    if ($result.ExitCode -ne 0) {
        if ($result.Stdout) { [Console]::Out.Write($result.Stdout) }
        if ($result.Stderr) { [Console]::Error.Write($result.Stderr) }
        throw 'STAGED_PYTHON_RUNTIME_OUTSIDE_STAGE'
    }
    try { $data = $result.Stdout.Trim() | ConvertFrom-Json }
    catch { throw 'STAGED_PYTHON_RUNTIME_UNVERIFIED' }
    if ($data.exe_inside_stage -ne $true -or $data.prefix_inside_stage -ne $true -or $data.site_inside_stage -ne $true) {
        throw 'STAGED_PYTHON_RUNTIME_OUTSIDE_STAGE'
    }
    return $data
}
