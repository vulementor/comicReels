param(
    [string]$Root = 'D:\StableApp\ThoRemix',
    [string]$PythonHome = 'C:\Users\vulem\AppData\Local\Programs\Python\Python312',
    [string]$AffiliateProfile = '',
    [switch]$SkipRuntime,
    [switch]$InstallSchedule,
    [switch]$LockCheckOnly,
    [Alias('NoPromote')][switch]$StageOnly,
    [string]$StageOutputRoot = '',
    [string]$RuntimeSource = '',
    [string]$DependencyLock = (Join-Path $PSScriptRoot 'dependencies.lock.json'),
    [string]$KrpSource = '',
    [string]$GptFullProxySource = '',
    [string]$KbsSource = '',
    [string]$KatSource = ''
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

function Initialize-ThoRemixPathNative {
    if ('ThoRemixPathNative' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class ThoRemixPathNative {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr CreateFileW(string name, uint access, uint share, IntPtr security,
        uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern uint GetFinalPathNameByHandleW(IntPtr handle, StringBuilder path, uint size, uint flags);
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool CloseHandle(IntPtr handle);
}
'@
}

function Resolve-PhysicalBuildPath {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [switch]$AllowMissing
    )
    if (-not [IO.Path]::IsPathRooted($Path)) { throw 'BUILD_PATH_MUST_BE_ABSOLUTE' }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $probe = $full
    $missing = [Collections.Generic.List[string]]::new()
    while (-not (Test-Path -LiteralPath $probe)) {
        if (-not $AllowMissing) { throw "BUILD_PATH_NOT_FOUND: $Path" }
        $leaf = Split-Path -Leaf $probe
        $parent = Split-Path -Parent $probe
        if ([string]::IsNullOrWhiteSpace($leaf) -or [string]::IsNullOrWhiteSpace($parent) -or $parent -eq $probe) {
            throw "BUILD_PATH_UNRESOLVABLE: $Path"
        }
        $missing.Insert(0, $leaf)
        $probe = $parent
    }
    $item = Get-Item -LiteralPath $probe -Force -ErrorAction Stop
    if (-not $item.PSIsContainer) { throw "BUILD_PATH_ANCESTOR_NOT_DIRECTORY: $probe" }

    Initialize-ThoRemixPathNative
    $handle = [ThoRemixPathNative]::CreateFileW(
        $item.FullName, 0, [uint32]7, [IntPtr]::Zero, [uint32]3, [uint32]0x02000000, [IntPtr]::Zero)
    if ($handle -eq [IntPtr]::new(-1)) { throw "BUILD_PATH_RESOLUTION_FAILED: $probe" }
    try {
        $buffer = [Text.StringBuilder]::new(32768)
        $length = [ThoRemixPathNative]::GetFinalPathNameByHandleW($handle, $buffer, $buffer.Capacity, 0)
        if ($length -eq 0 -or $length -ge $buffer.Capacity) { throw "BUILD_PATH_RESOLUTION_FAILED: $probe" }
        $resolved = $buffer.ToString()
    } finally {
        [ThoRemixPathNative]::CloseHandle($handle) | Out-Null
    }
    if ($resolved.StartsWith('\\?\UNC\', [StringComparison]::OrdinalIgnoreCase)) {
        $resolved = '\\' + $resolved.Substring(8)
    } elseif ($resolved.StartsWith('\\?\', [StringComparison]::OrdinalIgnoreCase)) {
        $resolved = $resolved.Substring(4)
    }
    foreach ($part in $missing) { $resolved = Join-Path $resolved $part }
    return [IO.Path]::GetFullPath($resolved).TrimEnd([IO.Path]::DirectorySeparatorChar)
}

function Assert-StageOutputIsolated {
    param(
        [Parameter(Mandatory=$true)][string]$StageOutputRoot,
        [Parameter(Mandatory=$true)][string]$LiveRoot
    )
    $stage = Resolve-PhysicalBuildPath -Path $StageOutputRoot -AllowMissing
    $live = Resolve-PhysicalBuildPath -Path $LiveRoot -AllowMissing
    $comparison = [StringComparison]::OrdinalIgnoreCase
    $separator = [IO.Path]::DirectorySeparatorChar
    $stageChild = $stage.Equals($live, $comparison) -or $stage.StartsWith($live + $separator, $comparison)
    $liveChild = $live.StartsWith($stage + $separator, $comparison)
    if ($stageChild -or $liveChild) { throw 'STAGE_OUTPUT_OVERLAPS_LIVE_STABLE' }
    return [ordered]@{stage=$stage; live=$live}
}

function Normalize-GitRemote {
    param([Parameter(Mandatory=$true)][string]$Remote)
    $value = $Remote.Trim().TrimEnd('/')
    if ($value.EndsWith('.git', [StringComparison]::OrdinalIgnoreCase)) {
        $value = $value.Substring(0, $value.Length - 4)
    }
    if ($value -match '^https://github\.com/(?<slug>[^/]+/[^/]+)$') {
        return ('github.com/' + $Matches.slug).ToLowerInvariant()
    }
    if ($value -match '^git@github\.com:(?<slug>[^/]+/[^/]+)$') {
        return ('github.com/' + $Matches.slug).ToLowerInvariant()
    }
    if ($value -match '^ssh://git@github\.com/(?<slug>[^/]+/[^/]+)$') {
        return ('github.com/' + $Matches.slug).ToLowerInvariant()
    }
    throw 'DEPENDENCY_REMOTE_UNSUPPORTED'
}

function Read-DependencyLock {
    param([Parameter(Mandatory=$true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'DEPENDENCY_LOCK_MISSING' }
    try { $lock = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw 'DEPENDENCY_LOCK_INVALID' }
    if ($lock.schema_version -ne 1 -or
            ([string]$lock.source_validated_base) -notmatch '^[0-9a-f]{40}$') {
        throw 'DEPENDENCY_LOCK_INVALID'
    }
    $expected = @('krp','gpt_fullproxy','kbs','kat')
    $actual = @($lock.dependencies.PSObject.Properties.Name | Sort-Object)
    if (($actual -join ',') -ne (($expected | Sort-Object) -join ',')) { throw 'DEPENDENCY_LOCK_INVALID' }
    foreach ($name in $expected) {
        $entry = $lock.dependencies.$name
        if ($null -eq $entry -or
                ([string]$entry.repository) -notmatch '^https://github\.com/[^/]+/[^/]+\.git$' -or
                ([string]$entry.commit) -notmatch '^[0-9a-f]{40}$' -or
                [string]::IsNullOrWhiteSpace([string]$entry.package)) {
            throw 'DEPENDENCY_LOCK_INVALID'
        }
    }
    return $lock
}

function Assert-DependencyCheckout {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Source,
        [Parameter(Mandatory=$true)]$Spec
    )
    $codeName = $Name.ToUpperInvariant().Replace('-', '_')
    if ([string]::IsNullOrWhiteSpace($Source) -or -not [IO.Path]::IsPathRooted($Source)) {
        throw ('DEPENDENCY_' + $codeName + '_SOURCE_REQUIRED')
    }
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw ('DEPENDENCY_' + $codeName + '_SOURCE_MISSING')
    }
    $sourcePath = (Resolve-Path -LiteralPath $Source).Path
    $inside = (& git -C $sourcePath rev-parse --is-inside-work-tree 2>$null)
    if ($LASTEXITCODE -ne 0 -or ($inside | Select-Object -First 1).Trim() -ne 'true') {
        throw ('DEPENDENCY_' + $codeName + '_NOT_GIT')
    }
    $dirty = @(& git -C $sourcePath status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw ('DEPENDENCY_' + $codeName + '_DIRTY') }
    $head = (& git -C $sourcePath rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne ([string]$Spec.commit)) { throw ('DEPENDENCY_' + $codeName + '_SHA_MISMATCH') }
    $origin = (& git -C $sourcePath remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0 -or
            (Normalize-GitRemote $origin) -ne (Normalize-GitRemote ([string]$Spec.repository))) {
        throw ('DEPENDENCY_' + $codeName + '_ORIGIN_MISMATCH')
    }
    return [ordered]@{
        name=$Name; path=$sourcePath; repository=[string]$Spec.repository
        commit=$head; package=[string]$Spec.package
    }
}

function Assert-StagedPackageMatchesSource {
    param(
        [Parameter(Mandatory=$true)][string]$SourcePackageRoot,
        [Parameter(Mandatory=$true)][string]$InstalledPackageRoot,
        [Parameter(Mandatory=$true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $SourcePackageRoot -PathType Container) -or
            -not (Test-Path -LiteralPath $InstalledPackageRoot -PathType Container)) {
        throw ($Label + '_PIN_VERIFICATION_FAILED')
    }
    $sourceFiles = @(
        Get-ChildItem -LiteralPath $SourcePackageRoot -Recurse -File |
        Where-Object { $_.Extension -in @('.py','.json','.js') } |
        ForEach-Object {
            [pscustomobject]@{
                relative=$_.FullName.Substring($SourcePackageRoot.Length + 1)
                hash=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    )
    if ($sourceFiles.Count -eq 0) { throw ($Label + '_PIN_VERIFICATION_FAILED') }
    foreach ($row in $sourceFiles) {
        $installed = Join-Path $InstalledPackageRoot $row.relative
        if (-not (Test-Path -LiteralPath $installed -PathType Leaf)) {
            throw ($Label + '_PIN_VERIFICATION_FAILED')
        }
        $actual = (Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $row.hash) { throw ($Label + '_PIN_VERIFICATION_FAILED') }
    }
    return $true
}

function Assert-KbsSourcePinMatchesRequirements {
    param(
        [Parameter(Mandatory=$true)][string]$Repo,
        [Parameter(Mandatory=$true)]$KbsSpec
    )
    $requirements = Get-Content -LiteralPath (Join-Path $Repo 'requirements-flow-browser.txt') -Raw -Encoding UTF8
    $matches = [regex]::Matches(
        $requirements,
        'kabin-browser-semantic\s*@\s*git\+https://github\.com/vulementor/kabin_browser_semantic\.git@(?<sha>[0-9a-f]{40})')
    if ($matches.Count -ne 1 -or $matches[0].Groups['sha'].Value -ne ([string]$KbsSpec.commit)) {
        throw 'KBS_PIN_MISMATCH_WITH_FLOW_REQUIREMENTS'
    }
}

function New-BuildManifest {
    param(
        [Parameter(Mandatory=$true)][string]$SourceCommit,
        [Parameter(Mandatory=$true)][string]$ValidatedBase,
        [Parameter(Mandatory=$true)][bool]$StageOnlyMode,
        [Parameter(Mandatory=$true)][string]$StagePath,
        [Parameter(Mandatory=$true)]$DependencyLockData,
        [Parameter(Mandatory=$true)][hashtable]$Files
    )
    $dependencies = [ordered]@{}
    foreach ($name in @('krp','gpt_fullproxy','kbs','kat')) {
        $spec = $DependencyLockData.dependencies.$name
        $dependencies[$name] = [ordered]@{
            repository=[string]$spec.repository
            commit=[string]$spec.commit
            package=[string]$spec.package
        }
    }
    return [ordered]@{
        schema_version=2
        built_at=[DateTime]::UtcNow.ToString('o')
        source_commit=$SourceCommit
        validated_base=$ValidatedBase
        source_state='clean'
        stage_only=$StageOnlyMode
        promotion_performed=(-not $StageOnlyMode)
        stage_path=$StagePath
        dependencies=$dependencies
        files=$Files
        ai_provider='gpt_fullproxy'
    }
}

function Assert-ManifestHashes {
    param(
        [Parameter(Mandatory=$true)][string]$Stage,
        [Parameter(Mandatory=$true)][string]$ManifestPath
    )
    try { $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw 'BUILD_MANIFEST_INVALID' }
    if ($manifest.schema_version -ne 2 -or $null -eq $manifest.files) { throw 'BUILD_MANIFEST_INVALID' }
    $stageFull = [IO.Path]::GetFullPath($Stage).TrimEnd([IO.Path]::DirectorySeparatorChar)
    foreach ($property in $manifest.files.PSObject.Properties) {
        $candidate = [IO.Path]::GetFullPath((Join-Path $Stage ([string]$property.Name)))
        $insideStage = $candidate.StartsWith(
            $stageFull + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)
        $exists = Test-Path -LiteralPath $candidate -PathType Leaf
        if (-not $insideStage -or -not $exists) {
            throw 'BUILD_MANIFEST_HASH_MISMATCH'
        }
        $actual = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne ([string]$property.Value)) { throw 'BUILD_MANIFEST_HASH_MISMATCH' }
    }
    return $true
}


$liveDestination = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
if ($liveDestination -ne 'D:\StableApp\ThoRemix') {
    throw 'This deployment is scoped to D:\StableApp\ThoRemix.'
}
if ($StageOnly -and $LockCheckOnly) { throw 'StageOnly and LockCheckOnly are mutually exclusive.' }
if ($StageOnly -and $InstallSchedule) { throw 'StageOnly never installs or changes schedules.' }

if ($LockCheckOnly) {
    $dataDirectory = Join-Path $liveDestination 'data'
    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
    $checkLease = [IO.File]::Open((Join-Path $dataDirectory 'runner.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
    try {
        try { $checkLease.Lock(0, 1) }
        catch { throw 'ThoRemix operation or login is active; bundle upgrade refused before installed files were changed.' }
        try { Write-Output 'Upgrade lock available; no bundle files changed.' }
        finally { $checkLease.Unlock(0, 1) }
    } finally { $checkLease.Dispose() }
    return
}

$dependencyLockData = Read-DependencyLock -Path $DependencyLock
$revision = (& git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') { throw 'SOURCE_REVISION_UNAVAILABLE' }
$sourceDirty = @(& git -C $repo status --porcelain)
if ($LASTEXITCODE -ne 0 -or $sourceDirty.Count -ne 0) { throw 'SOURCE_NOT_CLEAN' }
$validatedBase = [string]$dependencyLockData.source_validated_base
& git -C $repo merge-base --is-ancestor $validatedBase $revision
if ($LASTEXITCODE -ne 0) { throw 'SOURCE_VALIDATED_BASE_NOT_ANCESTOR' }

Assert-KbsSourcePinMatchesRequirements -Repo $repo -KbsSpec $dependencyLockData.dependencies.kbs
$dependencies = [ordered]@{
    krp = Assert-DependencyCheckout -Name 'krp' -Source $KrpSource -Spec $dependencyLockData.dependencies.krp
    gpt_fullproxy = Assert-DependencyCheckout -Name 'gpt_fullproxy' -Source $GptFullProxySource -Spec $dependencyLockData.dependencies.gpt_fullproxy
    kbs = Assert-DependencyCheckout -Name 'kbs' -Source $KbsSource -Spec $dependencyLockData.dependencies.kbs
    kat = Assert-DependencyCheckout -Name 'kat' -Source $KatSource -Spec $dependencyLockData.dependencies.kat
}

$workspaceRoot = Split-Path -Parent (Split-Path -Parent $workspace)
$stageBase = $null
if ($StageOnly) {
    if ([string]::IsNullOrWhiteSpace($StageOutputRoot)) {
        $StageOutputRoot = Join-Path $workspaceRoot 'validation\thoremix-stageonly'
    }
    $isolation = Assert-StageOutputIsolated -StageOutputRoot $StageOutputRoot -LiveRoot $liveDestination
    $stageBase = $isolation.stage
    New-Item -ItemType Directory -Path $stageBase -Force | Out-Null
}

$lease = $null
$locked = $false
try {
    if (-not $StageOnly) {
        $dataDirectory = Join-Path $liveDestination 'data'
        New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
        $lease = [IO.File]::Open((Join-Path $dataDirectory 'runner.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
        try { $lease.Lock(0, 1); $locked = $true }
        catch { throw 'ThoRemix operation or login is active; bundle upgrade refused before installed files were changed.' }
        if ($lease.Length -eq 0) { $lease.WriteByte(48); $lease.Flush() }
        if (Get-Process -Name ThoRemix -ErrorAction SilentlyContinue) { throw 'Close ThoRemix before upgrading its bundle.' }
    }

    $stage = if ($StageOnly) {
        Join-Path $stageBase ('stage-' + $revision.Substring(0,12) + '-' + [Guid]::NewGuid().ToString('N'))
    } else {
        Join-Path $liveDestination ('.upgrade-stage-' + [Guid]::NewGuid().ToString('N'))
    }
    if ($StageOnly) {
        Assert-StageOutputIsolated -StageOutputRoot $stage -LiveRoot $liveDestination | Out-Null
    }
    foreach ($folder in @('app', 'source\agent\thoremix', 'runtime\python', 'runtime\bin', 'config')) {
        New-Item -ItemType Directory -Path (Join-Path $stage $folder) -Force | Out-Null
    }
    $runtime = Join-Path $stage 'runtime\python'
    if ($SkipRuntime) {
        if ($StageOnly -and [string]::IsNullOrWhiteSpace($RuntimeSource)) {
            throw 'STAGE_ONLY_RUNTIME_SOURCE_REQUIRED'
        }
        $runtimeSourcePath = if ([string]::IsNullOrWhiteSpace($RuntimeSource)) {
            Join-Path $liveDestination 'runtime'
        } else {
            if (-not [IO.Path]::IsPathRooted($RuntimeSource) -or -not (Test-Path -LiteralPath $RuntimeSource -PathType Container)) {
                throw 'RUNTIME_SOURCE_INVALID'
            }
            (Resolve-Path -LiteralPath $RuntimeSource).Path
        }
        if ($StageOnly) {
            Assert-StageOutputIsolated -StageOutputRoot $runtimeSourcePath -LiveRoot $liveDestination | Out-Null
        }
        & robocopy $runtimeSourcePath (Join-Path $stage 'runtime') /E /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -gt 7) { throw 'Existing runtime staging failed.' }
    } else {
        & robocopy $PythonHome $runtime /E /XD (Join-Path $PythonHome 'Lib\site-packages') (Join-Path $PythonHome 'Doc') (Join-Path $PythonHome 'Scripts') (Join-Path $PythonHome 'Lib\test') __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -gt 7) { throw 'Python runtime staging failed.' }
        & "$runtime\python.exe" -m ensurepip --upgrade | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Staged pip bootstrap failed.' }
        & "$runtime\python.exe" -m pip install --disable-pip-version-check 'httpx==0.28.1' 'pillow==12.3.0' 'tzdata==2026.4' 'pydantic==2.13.5' 'PyYAML==6.0.3' 'camoufox==0.5.6'
        if ($LASTEXITCODE -ne 0) { throw 'Staged dependencies failed.' }
        foreach ($binary in @('ffmpeg.exe', 'ffprobe.exe')) {
            Copy-Item -LiteralPath (Join-Path 'C:\ffmpeg\bin' $binary) -Destination (Join-Path $stage 'runtime\bin') -Force
        }
    }

    & "$runtime\python.exe" -m pip install --disable-pip-version-check 'pystray==0.19.5' 'faster-whisper==1.2.1' 'aiosqlite==0.22.1' 'ffpyplayer==4.5.3' $dependencies.gpt_fullproxy.path $dependencies.kbs.path
    if ($LASTEXITCODE -ne 0) { throw 'Staged system tray dependency installation failed.' }
    & "$runtime\python.exe" -m pip install --disable-pip-version-check --force-reinstall --no-deps $dependencies.krp.path
    if ($LASTEXITCODE -ne 0) { throw 'Staged KRP refresh failed; installed bundle was not replaced.' }
    $krpSourcePackage = Join-Path $dependencies.krp.path 'src\kabin_reel_poster'
    $krpInstalledPackage = Join-Path $runtime 'Lib\site-packages\kabin_reel_poster'
    Assert-StagedPackageMatchesSource -SourcePackageRoot $krpSourcePackage -InstalledPackageRoot $krpInstalledPackage -Label 'KRP' | Out-Null
    & "$runtime\python.exe" -m pip install --disable-pip-version-check --force-reinstall --no-deps $dependencies.kat.path
    if ($LASTEXITCODE -ne 0) { throw 'Staged KAT refresh failed; installed bundle was not replaced.' }

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
    foreach ($name in @('PYTHONPATH', 'PYTHONUTF8', 'PYTHONTZPATH', 'PATH', 'THOREMIX_BUILD_ROOT', 'THOREMIX_BUILD_STAGE', 'THOREMIX_AFF_PROFILE', 'THOREMIX_STAGE_ONLY')) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    try {
        $env:PYTHONPATH = Join-Path $stage 'source'
        $env:PYTHONUTF8 = '1'
        $env:PYTHONTZPATH = Join-Path $runtime 'Lib\site-packages\tzdata\zoneinfo'
        $env:PATH = (Join-Path $stage 'runtime\bin') + ';' + $env:PATH
        $env:THOREMIX_BUILD_ROOT = $liveDestination
        $env:THOREMIX_BUILD_STAGE = $stage
        $env:THOREMIX_AFF_PROFILE = $AffiliateProfile
        $env:THOREMIX_STAGE_ONLY = if ($StageOnly) { '1' } else { '0' }
        $validation = @'
import compileall, os, pathlib, subprocess
from dataclasses import asdict, replace
import tkinter, ssl, sqlite3, PIL, httpx, tzdata, pydantic, yaml, camoufox, pystray
import kabin_reel_poster, kabin_affiliate_toolkit
import gpt_fullproxy, kabin_browser_semantic, faster_whisper
from kabin_reel_poster.sdk import KRPClient
from kabin_affiliate_toolkit.models import SelectionPolicy
from kabin_affiliate_toolkit.providers.shopee import ShopeeProviderConfig, ShopeeVNProvider
from ffpyplayer.player import MediaPlayer
from agent.services.flow_story_browser import FlowStoryBrowser
from agent.thoremix.story_operations import StoryOperations
from agent.thoremix import core, cli, sdk, desktop, producer, publishing, affiliate
from agent.thoremix.config import Settings, atomic_json
stage = pathlib.Path(os.environ['THOREMIX_BUILD_STAGE'])
root = pathlib.Path(os.environ['THOREMIX_BUILD_ROOT'])
stage_only = os.environ.get('THOREMIX_STAGE_ONLY') == '1'
assert pathlib.Path(core.__file__).resolve().is_relative_to(stage.resolve())
assert callable(getattr(KRPClient, 'recover_pre_submit', None)), 'KRP runtime lacks durable pre-submit recovery'
kat_fields = SelectionPolicy.model_fields
assert {'sold_min', 'commission_min'} <= set(kat_fields), 'KAT runtime lacks catalog-first hard-filter contract'
kat_config = ShopeeProviderConfig()
assert kat_config.catalog_first is True, 'KAT runtime must default to Product Offer catalog-first'
assert kat_config.legacy_public_search_fallback is False, 'KAT legacy detail-first fallback must remain opt-in'
assert ShopeeVNProvider.product_offer_url == 'https://affiliate.shopee.vn/offer/product_offer', 'KAT Product Offer surface mismatch'
assert compileall.compile_dir(stage / 'source', quiet=1)
if stage_only:
    s = Settings(root=str(root))
else:
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
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($stage.Length + 1)
        $hashes[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $manifest = New-BuildManifest -SourceCommit $revision -ValidatedBase $validatedBase -StageOnlyMode ([bool]$StageOnly) -StagePath $stage -DependencyLockData $dependencyLockData -Files $hashes
    $manifestPath = Join-Path $stage 'build-manifest.json'
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Assert-ManifestHashes -Stage $stage -ManifestPath $manifestPath | Out-Null

    if ($StageOnly) {
        Write-Output ("STAGE_ONLY_READY|" + $stage + "|source=" + $revision + "|validated_base=" + $validatedBase + "|promotion_performed=false")
        return
    }

    $backup = Join-Path $liveDestination ('.upgrade-backup-' + [Guid]::NewGuid().ToString('N'))
    $parts = @('runtime', 'source', 'app', 'ThoRemix.exe')
    if ($AffiliateProfile -or -not (Test-Path -LiteralPath (Join-Path $liveDestination 'config\settings.json'))) { $parts += 'config\settings.json' }
    $parts += 'build-manifest.json'
    $promoted = [Collections.Generic.List[object]]::new()
    New-Item -ItemType Directory -Path $backup | Out-Null
    try {
        foreach ($part in $parts) {
            $incoming = [IO.Path]::GetFullPath((Join-Path $stage $part))
            $live = [IO.Path]::GetFullPath((Join-Path $liveDestination $part))
            $old = [IO.Path]::GetFullPath((Join-Path $backup $part))
            foreach ($path in @($incoming, $live, $old)) {
                if (-not $path.StartsWith($liveDestination + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Upgrade path escaped its owned destination.' }
            }
            New-Item -ItemType Directory -Path (Split-Path -Parent $live) -Force | Out-Null
            New-Item -ItemType Directory -Path (Split-Path -Parent $old) -Force | Out-Null
            $entry = @{live=$live; incoming=$incoming; old=$old; hadOld=(Test-Path -LiteralPath $live); installed=$false; mode='move'}
            if ($entry.hadOld) {
                try {
                    Move-UpgradePart -Source $live -Destination $old -Label "$part live->backup"
                } catch {
                    if ($part -ne 'runtime') { throw }
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
                if ($entry.installed) { Move-UpgradePart -Source $entry.live -Destination $entry.incoming -Label 'rollback live->stage' }
                if ($entry.hadOld) { Move-UpgradePart -Source $entry.old -Destination $entry.live -Label 'rollback backup->live' }
            }
        }
        throw
    }
    if ($InstallSchedule) { & (Join-Path $PSScriptRoot 'Install-Schedule.ps1') -Root $liveDestination }
    Write-Output "Built $liveDestination\ThoRemix.exe; prior bundle preserved at $backup"
} finally {
    if ($locked) { $lease.Unlock(0, 1) }
    if ($null -ne $lease) { $lease.Dispose() }
}
