param(
    [string]$Root = 'D:\StableApp\ThoRemix',
    [string]$PythonHome = 'C:\Users\vulem\AppData\Local\Programs\Python\Python312',
    [string]$AffiliateProfile = '',
    [switch]$SkipRuntime,
    [switch]$InstallSchedule,
    [switch]$LockCheckOnly
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$workspace = Split-Path -Parent $repo
$destination = [IO.Path]::GetFullPath($Root).TrimEnd('\')
if (-not $LockCheckOnly -and $destination -ne 'D:\StableApp\ThoRemix') {
    throw 'This deployment is scoped to D:\StableApp\ThoRemix.'
}

function Get-UpgradePathObservation {
    param([string]$Path)
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        return [ordered]@{
            path=$Path; state='present'; attributes=$item.Attributes.ToString()
            is_container=[bool]$item.PSIsContainer
        }
    } catch [System.Management.Automation.ItemNotFoundException] {
        return [ordered]@{path=$Path; state='missing'}
    } catch {
        # An inaccessible metadata lookup is not proof that the path is absent.
        return [ordered]@{path=$Path; state='unreadable'; error_type=$_.Exception.GetType().FullName}
    }
}

function Write-UpgradeMoveDiagnostic {
    param(
        [Parameter(Mandatory=$true)][System.Management.Automation.ErrorRecord]$Failure,
        [Parameter(Mandatory=$true)][string]$Source,
        [Parameter(Mandatory=$true)][string]$Destination,
        [Parameter(Mandatory=$true)][string]$Label,
        [Parameter(Mandatory=$true)][int]$Attempt
    )
    $observedAt = [DateTime]::UtcNow.ToString('o')
    $chain = @()
    $exception = $Failure.Exception
    while ($null -ne $exception -and $chain.Count -lt 6) {
        $bits = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int]$exception.HResult), 0)
        $derivedCode = $null
        # Only HRESULT_FROM_WIN32 values encode a Win32 code in the low word.
        # A managed IOException's generic HRESULT must NOT be called native errno.
        # https://learn.microsoft.com/windows/win32/api/winerror/nf-winerror-hresult_from_win32
        if (($bits -band [uint32]4294901760) -eq [uint32]2147942400) {
            $derivedCode = [int]($bits -band 65535)
        }
        $nativeCode = $null
        if ($exception -is [System.ComponentModel.Win32Exception]) {
            $nativeCode = $exception.NativeErrorCode
        }
        $message = [regex]::Replace([string]$exception.Message, '\s+', ' ')
        if ($message.Length -gt 600) { $message = $message.Substring(0, 600) }
        $chain += [ordered]@{
            type=$exception.GetType().FullName; hresult=('0x{0:X8}' -f $bits)
            hresult_win32_code=$derivedCode; native_win32_code=$nativeCode; message=$message
        }
        $exception = $exception.InnerException
    }
    $diagnostic = [ordered]@{
        schema_version=1; event='upgrade_move_failure'; utc=$observedAt
        pid=$PID; powershell_version=$PSVersionTable.PSVersion.ToString()
        process_cwd=[Environment]::CurrentDirectory; powershell_cwd=(Get-Location).Path
        label=$Label; attempt=$Attempt; max_attempts=8
        error_id=$Failure.FullyQualifiedErrorId; category=$Failure.CategoryInfo.Category.ToString()
        exceptions=$chain; exception_chain_truncated=($null -ne $exception)
        source=(Get-UpgradePathObservation -Path $Source)
        destination=(Get-UpgradePathObservation -Path $Destination)
    }
    # One JSON line per failure goes to the existing durable build stderr/log.
    # Do not scan processes, dump environment/command lines, change ACLs, or use
    # GetLastWin32Error here: a cmdlet exception does not preserve that native slot.
    [Console]::Error.WriteLine('THOREMIX_MOVE_FAILURE ' + ($diagnostic | ConvertTo-Json -Depth 7 -Compress))
}

function Move-UpgradePart {
    param(
        [Parameter(Mandatory=$true)][string]$Source,
        [Parameter(Mandatory=$true)][string]$Destination,
        [Parameter(Mandatory=$true)][string]$Label
    )
    $lastError = $null
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        try {
            Move-Item -LiteralPath $Source -Destination $Destination -ErrorAction Stop
            return
        } catch {
            $lastError = $_.Exception
            try {
                Write-UpgradeMoveDiagnostic -Failure $_ -Source $Source -Destination $Destination -Label $Label -Attempt $attempt
            } catch {
                # Logging must never replace the original failure or prevent rollback.
                try { [Console]::Error.WriteLine('THOREMIX_MOVE_DIAGNOSTIC_UNAVAILABLE') } catch {}
            }
            $retryable = ($lastError -is [System.IO.IOException]) -or
                         ($lastError -is [System.UnauthorizedAccessException])
            if (-not $retryable -or $attempt -eq 8 -or -not (Test-Path -LiteralPath $Source) -or
                    (Test-Path -LiteralPath $Destination)) {
                throw
            }
            Start-Sleep -Milliseconds (250 * $attempt)
        }
    }
    throw "Upgrade move failed for ${Label}: $($lastError.GetType().Name)"
}

function Copy-UpgradeMirror {
    param(
        [Parameter(Mandatory=$true)][string]$Source,
        [Parameter(Mandatory=$true)][string]$Destination,
        [Parameter(Mandatory=$true)][string]$Label
    )
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    & robocopy $Source $Destination /MIR /COPY:DAT /DCOPY:DAT /R:3 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    $code = $LASTEXITCODE
    if ($code -gt 7) {
        throw "Upgrade mirror failed for ${Label}: robocopy exit $code"
    }
}
# Same byte and file as Python msvcrt.locking; retained for the whole transaction.
$dataDirectory = Join-Path $destination 'data'
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
$lease = $null
$locked = $false
try {
    $lease = [IO.File]::Open((Join-Path $dataDirectory 'runner.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
    try { $lease.Lock(0, 1); $locked = $true }
    catch { throw 'ThoRemix operation or login is active; bundle upgrade refused before installed files were changed.' }
    if ($lease.Length -eq 0) { $lease.WriteByte(48); $lease.Flush() }
    if ($LockCheckOnly) { Write-Output 'Upgrade lock available; no bundle files changed.'; return }
    if (Get-Process -Name ThoRemix -ErrorAction SilentlyContinue) { throw 'Close ThoRemix before upgrading its bundle.' }

    $stage = Join-Path $destination ('.upgrade-stage-' + [Guid]::NewGuid().ToString('N'))
    $backup = Join-Path $destination ('.upgrade-backup-' + [Guid]::NewGuid().ToString('N'))
    foreach ($folder in @('app', 'source\agent\thoremix', 'runtime\python', 'runtime\bin', 'config')) {
        New-Item -ItemType Directory -Path (Join-Path $stage $folder) -Force | Out-Null
    }
    $runtime = Join-Path $stage 'runtime\python'
    if ($SkipRuntime) {
        & robocopy (Join-Path $destination 'runtime') (Join-Path $stage 'runtime') /E /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -gt 7) { throw 'Existing runtime staging failed.' }
    } else {
        & robocopy $PythonHome $runtime /E /XD (Join-Path $PythonHome 'Lib\site-packages') (Join-Path $PythonHome 'Doc') (Join-Path $PythonHome 'Scripts') (Join-Path $PythonHome 'Lib\test') __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -gt 7) { throw 'Python runtime staging failed.' }
        & "$runtime\python.exe" -m ensurepip --upgrade | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Staged pip bootstrap failed.' }
        & "$runtime\python.exe" -m pip install --disable-pip-version-check 'httpx==0.28.1' 'pillow==12.3.0' 'tzdata==2026.4' 'pydantic==2.13.5' 'PyYAML==6.0.3' 'camoufox==0.5.6' (Join-Path $workspace 'kabin_reel_poster') (Join-Path $workspace 'kabin_affiliate_toolkit')
        if ($LASTEXITCODE -ne 0) { throw 'Staged dependencies failed.' }
        foreach ($binary in @('ffmpeg.exe', 'ffprobe.exe')) {
            Copy-Item -LiteralPath (Join-Path 'C:\ffmpeg\bin' $binary) -Destination (Join-Path $stage 'runtime\bin') -Force
        }
    }
    # Also update desktop-only dependencies when reusing an existing browser runtime.
    & "$runtime\python.exe" -m pip install --disable-pip-version-check 'pystray==0.19.5' 'faster-whisper==1.2.1' 'aiosqlite==0.22.1' 'ffpyplayer==4.5.3' (Join-Path $workspace 'gpt_fullproxy') (Join-Path $workspace 'kabin_browser_semantic')
    if ($LASTEXITCODE -ne 0) { throw 'Staged system tray dependency installation failed.' }
    Copy-Item -LiteralPath (Join-Path $repo 'agent\__init__.py') -Destination (Join-Path $stage 'source\agent')
    Copy-Item -LiteralPath (Join-Path $repo 'agent\config.py') -Destination (Join-Path $stage 'source\agent')
    Copy-Item -LiteralPath (Join-Path $repo 'agent\models.json') -Destination (Join-Path $stage 'source\agent')
    Copy-Item -LiteralPath (Join-Path $repo 'agent\providers.json') -Destination (Join-Path $stage 'source\agent')
    Get-ChildItem -LiteralPath (Join-Path $repo 'agent\thoremix') -Filter '*.py' | Copy-Item -Destination (Join-Path $stage 'source\agent\thoremix')
    foreach ($module in @('comicreels', 'services')) {
        $moduleDestination = Join-Path $stage "source\agent\$module"
        New-Item -ItemType Directory -Path $moduleDestination -Force | Out-Null
        Get-ChildItem -LiteralPath (Join-Path $repo "agent\$module") -File | Where-Object { $_.Extension -in @('.py','.js') } | Copy-Item -Destination $moduleDestination
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'start.py') -Destination (Join-Path $stage 'app')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Install-Schedule.ps1') -Destination (Join-Path $stage 'app')
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    & $compiler /nologo /target:winexe "/out:$stage\ThoRemix.exe" /reference:System.Windows.Forms.dll (Join-Path $PSScriptRoot 'Launcher.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Staged launcher compilation failed.' }

    $savedEnvironment = @{}
    foreach ($name in @('PYTHONPATH', 'PYTHONUTF8', 'PYTHONTZPATH', 'PATH', 'THOREMIX_BUILD_ROOT', 'THOREMIX_BUILD_STAGE', 'THOREMIX_AFF_PROFILE')) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    try {
        $env:PYTHONPATH = Join-Path $stage 'source'
        $env:PYTHONUTF8 = '1'
        $env:PYTHONTZPATH = Join-Path $runtime 'Lib\site-packages\tzdata\zoneinfo'
        $env:PATH = (Join-Path $stage 'runtime\bin') + ';' + $env:PATH
        $env:THOREMIX_BUILD_ROOT = $destination
        $env:THOREMIX_BUILD_STAGE = $stage
        $env:THOREMIX_AFF_PROFILE = $AffiliateProfile
        # Do not invoke lock-taking CLI init from inside the .NET lock.
        $validation = @'
import compileall, os, pathlib, subprocess
from dataclasses import asdict, replace
import tkinter, ssl, sqlite3, PIL, httpx, tzdata, pydantic, yaml, camoufox, pystray
import kabin_reel_poster, kabin_affiliate_toolkit
import gpt_fullproxy, kabin_browser_semantic, faster_whisper
from kabin_reel_poster.sdk import KRPClient
from ffpyplayer.player import MediaPlayer
from agent.services.flow_story_browser import FlowStoryBrowser
from agent.thoremix.story_operations import StoryOperations
from agent.thoremix import core, cli, sdk, desktop, producer, publishing, affiliate
from agent.thoremix.config import Settings, atomic_json
stage = pathlib.Path(os.environ['THOREMIX_BUILD_STAGE'])
root = pathlib.Path(os.environ['THOREMIX_BUILD_ROOT'])
assert pathlib.Path(core.__file__).resolve().is_relative_to(stage.resolve())
assert callable(getattr(KRPClient, 'recover_pre_submit', None)), 'KRP runtime lacks durable pre-submit recovery'
assert compileall.compile_dir(stage / 'source', quiet=1)
s = Settings.load(root) if (root / 'config/settings.json').exists() else Settings(root=str(root))
if os.environ.get('THOREMIX_AFF_PROFILE'):
    s = replace(s, affiliate_profile_dir=os.environ['THOREMIX_AFF_PROFILE'])
s.validate()
atomic_json(stage / 'config/settings.json', asdict(s))
assert (stage / 'ThoRemix.exe').stat().st_size > 1024
for name in ('ffmpeg.exe', 'ffprobe.exe'):
    subprocess.run([str(stage / 'runtime/bin' / name), '-version'], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
'@
        # python -c places cwd ahead of PYTHONPATH. Launch inside staged source
        # so a canonical-repository cwd cannot shadow the bundle being tested.
        Push-Location -LiteralPath (Join-Path $stage 'source')
        try {
            & "$runtime\python.exe" -c $validation
            if ($LASTEXITCODE -ne 0) { throw 'Staged bundle validation failed; installed bundle was not replaced.' }
        } finally { Pop-Location }
    } finally {
        foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    }
    $files = @(Get-ChildItem -LiteralPath (Join-Path $stage 'source') -Recurse -File | Where-Object { $_.Extension -in @('.py','.js','.json') }) + @(Get-Item -LiteralPath (Join-Path $stage 'ThoRemix.exe'))
    foreach ($packageName in @('kabin_reel_poster', 'kabin_affiliate_toolkit', 'pystray', 'gpt_fullproxy', 'kabin_browser_semantic')) {
        $files += @(Get-ChildItem -LiteralPath (Join-Path $runtime "Lib\site-packages\$packageName") -Recurse -File -Filter '*.py')
    }
    $hashes = @{}
    foreach ($file in $files) { $hashes[$file.FullName.Substring($stage.Length + 1)] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLower() }
    $revision = & git -C $repo rev-parse HEAD
    @{schema_version=1; built_at=(Get-Date).ToUniversalTime().ToString('o'); base_commit=$revision; source_state='working-tree'; files=$hashes; ai_provider='gpt_fullproxy'} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stage 'build-manifest.json') -Encoding utf8

    $parts = @('runtime', 'source', 'app', 'ThoRemix.exe')
    if ($AffiliateProfile -or -not (Test-Path -LiteralPath (Join-Path $destination 'config\settings.json'))) { $parts += 'config\settings.json' }
    $parts += 'build-manifest.json'
    $promoted = [Collections.Generic.List[object]]::new()
    New-Item -ItemType Directory -Path $backup | Out-Null
    try {
        foreach ($part in $parts) {
            $incoming = [IO.Path]::GetFullPath((Join-Path $stage $part))
            $live = [IO.Path]::GetFullPath((Join-Path $destination $part))
            $old = [IO.Path]::GetFullPath((Join-Path $backup $part))
            foreach ($path in @($incoming, $live, $old)) {
                if (-not $path.StartsWith($destination + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Upgrade path escaped its owned destination.' }
            }
            New-Item -ItemType Directory -Path (Split-Path -Parent $live) -Force | Out-Null
            New-Item -ItemType Directory -Path (Split-Path -Parent $old) -Force | Out-Null
            $entry = @{live=$live; incoming=$incoming; old=$old; hadOld=(Test-Path -LiteralPath $live); installed=$false; mode='move'}
            if ($entry.hadOld) {
                try {
                    Move-UpgradePart -Source $live -Destination $old -Label "$part live->backup"
                } catch {
                    if ($part -ne 'runtime') { throw }
                    # Windows can hold read handles without delete sharing (for example a diagnostics
                    # reader). The app and runner are already stopped/locked, so preserve a complete
                    # byte-for-byte backup and mirror the validated staged runtime in place instead
                    # of weakening the validation or killing an unrelated diagnostics process.
                    $entry.mode = 'mirror'
                    Copy-UpgradeMirror -Source $live -Destination $old -Label 'runtime live->backup'
                    try {
                        Copy-UpgradeMirror -Source $incoming -Destination $live -Label 'runtime stage->live'
                    } catch {
                        Copy-UpgradeMirror -Source $old -Destination $live -Label 'runtime failed-install rollback'
                        throw
                    }
                    $entry.installed = $true
                    $promoted.Add($entry)
                    continue
                }
            }
            $promoted.Add($entry)
            Move-UpgradePart -Source $incoming -Destination $live -Label "$part stage->live"
            $entry.installed = $true
        }
    } catch {
        for ($index = $promoted.Count - 1; $index -ge 0; $index--) {
            $entry = $promoted[$index]
            if ($entry.mode -eq 'mirror') {
                if ($entry.hadOld) {
                    Copy-UpgradeMirror -Source $entry.old -Destination $entry.live -Label 'rollback runtime backup->live'
                }
            } else {
                if ($entry.installed) { Move-UpgradePart -Source $entry.live -Destination $entry.incoming -Label "rollback live->stage" }
                if ($entry.hadOld) { Move-UpgradePart -Source $entry.old -Destination $entry.live -Label "rollback backup->live" }
            }
        }
        throw
    }
    # Keep the prior bundle for recovery. No recursive cleanup or browser shutdown.
    if ($InstallSchedule) { & (Join-Path $PSScriptRoot 'Install-Schedule.ps1') -Root $destination }
    Write-Output "Built $destination\ThoRemix.exe; prior bundle preserved at $backup"
} finally {
    if ($locked) { $lease.Unlock(0, 1) }
    if ($null -ne $lease) { $lease.Dispose() }
}
