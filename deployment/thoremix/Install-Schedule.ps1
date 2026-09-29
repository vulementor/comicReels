param([string]$Root = 'D:\StableApp\ThoRemix', [switch]$Remove)
$ErrorActionPreference = 'Stop'
$resolved = (Resolve-Path -LiteralPath $Root).Path
$exe = Join-Path $resolved 'ThoRemix.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Missing ThoRemix.exe' }
if ((Get-TimeZone).Id -ne 'SE Asia Standard Time') {
    throw 'Set the Windows time zone to Vietnam (SE Asia Standard Time) before installing this local schedule.'
}
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$taskFolder = $service.GetFolder('\')
foreach ($slot in @('11:00', '18:30', 'production')) {
    $maintenance = $slot -eq 'production'
    $name = if ($maintenance) { 'ThoRemix-Production' } else { 'ThoRemix-' + $slot.Replace(':', '') }
    $existing = $null
    foreach ($candidate in $taskFolder.GetTasks(0)) {
        if ($candidate.Name -eq $name) { $existing = $candidate; break }
    }
    if ($existing -and ($existing.Definition.Actions.Item(1).Path -ne $exe)) { throw "Task name is owned by a different program: $name" }
    if ($Remove) {
        if ($existing) { $taskFolder.DeleteTask($name, 0) }
        continue
    }
    $definition = $service.NewTask(0)
    $definition.RegistrationInfo.Description = if ($maintenance) { 'Thỏ Remix daily completed-clip quota and ready queue; deterministic 5-minute wake-up.' } else { 'Thỏ Remix one package per posting slot; durable source/effect dedupe.' }
    $definition.Principal.UserId = $userId
    $definition.Principal.LogonType = 3
    $definition.Principal.RunLevel = 0
    $definition.Settings.MultipleInstances = 2
    # Never let Task Scheduler kill a paid generation while its result is uncertain.
    $definition.Settings.ExecutionTimeLimit = 'PT0S'
    $definition.Settings.DisallowStartIfOnBatteries = $false
    $definition.Settings.StopIfGoingOnBatteries = $false
    $definition.Settings.StartWhenAvailable = $false
    $trigger = $definition.Triggers.Create(2)
    $trigger.StartBoundary = (Get-Date -Format 'yyyy-MM-dd') + 'T' + $(if ($maintenance) { '00:01' } else { $slot }) + ':00+07:00'
    $trigger.DaysInterval = 1
    $trigger.Enabled = $true
    if ($maintenance) {
        $trigger.Repetition.Interval = 'PT5M'
        $trigger.Repetition.Duration = 'P1D'
        $trigger.Repetition.StopAtDurationEnd = $false
        $logon = $definition.Triggers.Create(9)
        $logon.UserId = $userId
        $logon.Delay = 'PT1M'
    }
    $action = $definition.Actions.Create(0)
    $action.Path = $exe
    $action.Arguments = if ($maintenance) { '--dispatch' } else { "--tick --clock $slot" }
    $action.WorkingDirectory = $resolved
    $registered = $taskFolder.RegisterTaskDefinition($name, $definition, 6, $userId, $null, 3)
    [PSCustomObject]@{TaskName=$registered.Name; State=$registered.State; NextRun=$registered.NextRunTime}
}
