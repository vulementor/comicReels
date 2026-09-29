param([string]$Root = 'D:\StableApp\ThoRemix')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ThoRemixWindowProbe {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);
}
'@
$window = Get-Process -Name pythonw | Where-Object { $_.MainWindowTitle -eq 'Thỏ Remix — Toolkit' }
if (@($window).Count -ne 1) { throw 'Expected exactly one ThoRemix desktop window.' }
$rectangle = New-Object ThoRemixWindowProbe+RECT
if (-not [ThoRemixWindowProbe]::GetWindowRect($window.MainWindowHandle, [ref]$rectangle)) { throw 'Window bounds unavailable.' }
$bitmap = New-Object System.Drawing.Bitmap(($rectangle.Right-$rectangle.Left), ($rectangle.Bottom-$rectangle.Top))
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$dc = $graphics.GetHdc()
try {
    if (-not [ThoRemixWindowProbe]::PrintWindow($window.MainWindowHandle, $dc, 2)) { throw 'Window capture failed.' }
} finally { $graphics.ReleaseHdc($dc); $graphics.Dispose() }
$evidence = Join-Path $Root 'data\verification'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
try { $bitmap.Save((Join-Path $evidence 'desktop.png'), [System.Drawing.Imaging.ImageFormat]::Png) } finally { $bitmap.Dispose() }
$manifest = Get-Content -LiteralPath (Join-Path $Root 'build-manifest.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest.files.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $Root $entry.Name) -Algorithm SHA256).Hash.ToLower() -ne $entry.Value) {
        throw "Bundle hash mismatch: $($entry.Name)"
    }
}
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder = $service.GetFolder('\')
$tasks = foreach ($name in @('ThoRemix-1100', 'ThoRemix-1830', 'ThoRemix-Production')) {
    $task = $folder.GetTask($name)
    @{name=$task.Name; next_run=$task.NextRunTime.ToString('o'); action=$task.Definition.Actions.Item(1).Path;
      arguments=$task.Definition.Actions.Item(1).Arguments; start=$task.Definition.Triggers.Item(1).StartBoundary;
      logon_type=$task.Definition.Principal.LogonType; multiple_instances=$task.Definition.Settings.MultipleInstances;
      repeat_interval=$task.Definition.Triggers.Item(1).Repetition.Interval;
      execution_limit=$task.Definition.Settings.ExecutionTimeLimit}
}
@{observed_at=(Get-Date).ToUniversalTime().ToString('o'); bundle_hashes_match=$true; window_title=$window.MainWindowTitle;
  process_id=$window.Id; screenshot=(Join-Path $evidence 'desktop.png'); tasks=$tasks} |
  ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidence 'desktop.json') -Encoding utf8
Write-Output (Join-Path $evidence 'desktop.json')
