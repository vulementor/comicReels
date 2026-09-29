param([string]$Root = 'D:\StableApp\ThoRemix', [switch]$ExitOnly)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class ThoRemixTrayProbe {
    public delegate bool EnumProc(IntPtr hwnd, IntPtr arg);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] public struct ICONID { public uint Size; public IntPtr Hwnd; public uint Id; public Guid Guid; }
    public class Window { public IntPtr Handle; public uint Process; public string Class, Title; public bool Visible; }
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc proc, IntPtr arg);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr hwnd, StringBuilder text, int max);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int max);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint msg, IntPtr wparam, IntPtr lparam);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hwnd, uint msg, IntPtr wparam, IntPtr lparam);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT point);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
    [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr menu);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetMenuString(IntPtr menu, uint item, StringBuilder text, int max, uint flags);
    [DllImport("user32.dll")] public static extern uint GetMenuState(IntPtr menu, uint item, uint flags);
    [DllImport("user32.dll")] public static extern bool GetMenuItemRect(IntPtr hwnd, IntPtr menu, uint item, out RECT rect);
    [DllImport("shell32.dll")] public static extern int Shell_NotifyIconGetRect(ref ICONID id, out RECT rect);
    public static Window[] Windows() {
        var items=new List<Window>();
        EnumWindows((h,a)=> { var c=new StringBuilder(256); var n=new StringBuilder(256); uint p;
            GetClassName(h,c,256); GetWindowText(h,n,256); GetWindowThreadProcessId(h,out p);
            items.Add(new Window {Handle=h, Process=p, Class=c.ToString(), Title=n.ToString(), Visible=IsWindowVisible(h)});
            return true; },IntPtr.Zero);
        return items.ToArray();
    }
    public static int IconRect(IntPtr h, out RECT rect) {
        // pystray 0.19.5 Win32 registers each icon under its own HWND with uID=0.
        var id=new ICONID {Size=(uint)Marshal.SizeOf(typeof(ICONID)), Hwnd=h, Id=0};
        return Shell_NotifyIconGetRect(ref id,out rect);
    }
    public static void Click(RECT rect) {
        SetCursorPos((rect.Left+rect.Right)/2,(rect.Top+rect.Bottom)/2);
        mouse_event(2,0,0,0,UIntPtr.Zero); mouse_event(4,0,0,0,UIntPtr.Zero);
    }
}
'@
$evidence = Join-Path $Root 'data\verification'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
function Wait-Until([scriptblock]$Condition, [string]$Failure) {
    for ($i=0; $i -lt 100; $i++) {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 100
    }
    throw $Failure
}
function Get-Desktop {
    $matches = @([ThoRemixTrayProbe]::Windows() | Where-Object { $_.Class -eq 'TkTopLevel' -and $_.Title -eq 'Thỏ Remix — Toolkit' })
    if ($matches.Count -ne 1) { throw 'Expected one desktop, including hidden windows.' }
    $matches[0]
}
function Get-Tray($Desktop) {
    $matches = @([ThoRemixTrayProbe]::Windows() | Where-Object {
        if ($_.Process -ne $Desktop.Process -or $_.Class -notlike 'ThoRemix*SystemTrayIcon') { return $false }
        $rect = New-Object ThoRemixTrayProbe+RECT
        return [ThoRemixTrayProbe]::IconRect($_.Handle, [ref]$rect) -ge 0
    })
    if ($matches.Count -ne 1) { throw 'Expected one shell-registered tray icon.' }
    $matches[0]
}
function Save-Window($Window, [string]$Name) {
    $rect = New-Object ThoRemixTrayProbe+RECT
    if (-not [ThoRemixTrayProbe]::GetWindowRect($Window.Handle, [ref]$rect)) { throw 'Missing capture bounds.' }
    $bitmap = New-Object System.Drawing.Bitmap(($rect.Right-$rect.Left), ($rect.Bottom-$rect.Top))
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $dc = $graphics.GetHdc()
    try {
        if (-not [ThoRemixTrayProbe]::PrintWindow($Window.Handle, $dc, 2)) { throw 'Capture failed.' }
    } finally { $graphics.ReleaseHdc($dc); $graphics.Dispose() }
    try { $bitmap.Save((Join-Path $evidence $Name), [System.Drawing.Imaging.ImageFormat]::Png) }
    finally { $bitmap.Dispose() }
}
function Open-TrayMenu($Tray) {
    $anchor = New-Object ThoRemixTrayProbe+RECT
    if ([ThoRemixTrayProbe]::IconRect($Tray.Handle, [ref]$anchor) -lt 0) { throw 'Tray anchor unavailable.' }
    [ThoRemixTrayProbe]::SetCursorPos(($anchor.Left+$anchor.Right)/2, $anchor.Top) | Out-Null
    [ThoRemixTrayProbe]::PostMessage($Tray.Handle, 0x40b, [IntPtr]::Zero, [IntPtr]0x205) | Out-Null
    Wait-Until { @([ThoRemixTrayProbe]::Windows() | Where-Object { $_.Class -eq '#32768' -and $_.Process -eq $Tray.Process -and $_.Visible }).Count -eq 1 } 'Tray menu did not appear.'
    $window = [ThoRemixTrayProbe]::Windows() | Where-Object { $_.Class -eq '#32768' -and $_.Process -eq $Tray.Process -and $_.Visible }
    $menu = [ThoRemixTrayProbe]::SendMessage($window.Handle, 0x1e1, [IntPtr]::Zero, [IntPtr]::Zero)
    if ($menu -eq [IntPtr]::Zero) { throw 'Native popup menu unavailable.' }
    $items = for ($i=0; $i -lt [ThoRemixTrayProbe]::GetMenuItemCount($menu); $i++) {
        $text = New-Object Text.StringBuilder(256)
        [ThoRemixTrayProbe]::GetMenuString($menu, $i, $text, 256, 0x400) | Out-Null
        @{text=$text.ToString(); index=$i; state=[ThoRemixTrayProbe]::GetMenuState($menu, $i, 0x400)}
    }
    @{window=$window; handle=$menu; items=@($items)}
}
function Click-MenuItem($Menu, [string]$Name) {
    $item = @($Menu.items | Where-Object { $_.text -eq $Name })
    if ($item.Count -ne 1) { throw "Ambiguous menu item: $Name" }
    $rect = New-Object ThoRemixTrayProbe+RECT
    if (-not [ThoRemixTrayProbe]::GetMenuItemRect([IntPtr]::Zero, $Menu.handle, $item[0].index, [ref]$rect)) { throw 'Menu bounds unavailable.' }
    [ThoRemixTrayProbe]::Click($rect)
}
$originalCursor = New-Object ThoRemixTrayProbe+POINT
[ThoRemixTrayProbe]::GetCursorPos([ref]$originalCursor) | Out-Null
$configBefore = (Get-FileHash -LiteralPath (Join-Path $Root 'config/settings.json')).Hash
$enabledBefore = [bool](Get-Content -Raw -LiteralPath (Join-Path $Root 'config/settings.json') | ConvertFrom-Json).enabled
try {
    $desktop = Get-Desktop
    $owner = Get-Process -Id $desktop.Process
    if ($owner.Path -ne (Join-Path $Root 'runtime\python\pythonw.exe')) { throw 'Unexpected desktop owner.' }
    $tray = Get-Tray $desktop
    if ($ExitOnly) {
        $menu = Open-TrayMenu $tray
        Click-MenuItem $menu 'Thoát Thỏ Remix'
        if (-not $owner.WaitForExit(10000)) { throw 'Tray exit did not stop the desktop.' }
        Wait-Until { @(Get-Process -Name ThoRemix -ErrorAction SilentlyContinue).Count -eq 0 } 'Old launcher remains.'
        return
    }
    [ThoRemixTrayProbe]::PostMessage($desktop.Handle, 0x10, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
    Wait-Until { -not [ThoRemixTrayProbe]::IsWindowVisible($desktop.Handle) } 'Close did not hide desktop.'
    if ($owner.HasExited) { throw 'Close terminated the desktop.' }
    $second = Start-Process -FilePath (Join-Path $Root 'ThoRemix.exe') -PassThru -WindowStyle Hidden
    Wait-Until { [ThoRemixTrayProbe]::IsWindowVisible($desktop.Handle) } 'Second launch did not restore desktop.'
    if (-not $second.WaitForExit(10000) -or $second.ExitCode -ne 0) { throw 'Second launcher did not exit cleanly.' }
    if ((Get-Desktop).Process -ne $owner.Id) { throw 'Second launch replaced the primary instance.' }
    [ThoRemixTrayProbe]::PostMessage($desktop.Handle, 0x10, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
    Wait-Until { -not [ThoRemixTrayProbe]::IsWindowVisible($desktop.Handle) } 'Second hide failed.'
    [ThoRemixTrayProbe]::PostMessage($tray.Handle, 0x40b, [IntPtr]::Zero, [IntPtr]0x202) | Out-Null
    Wait-Until { [ThoRemixTrayProbe]::IsWindowVisible($desktop.Handle) } 'Tray left-click did not restore desktop.'
    $menu = Open-TrayMenu $tray
    Save-Window $menu.window 'tray-menu.png'
    $menuItems = $menu.items
    $pause = @($menuItems | Where-Object { $_.text -eq 'Tạm dừng lịch' })
    if ($pause.Count -ne 1 -or ([bool]($pause[0].state -band 3) -eq $enabledBefore)) {
        throw 'Pause menu availability does not match the campaign enabled state.'
    }
    Click-MenuItem $menu 'Lịch chạy…'
    Start-Sleep -Milliseconds 400
    Save-Window $desktop 'tray-schedule.png'
    $menu = Open-TrayMenu $tray
    Click-MenuItem $menu 'Thoát Thỏ Remix'
    if (-not $owner.WaitForExit(10000)) { throw 'Tray exit did not stop the desktop.' }
    Wait-Until { @(Get-Process -Name ThoRemix -ErrorAction SilentlyContinue).Count -eq 0 } 'Old launcher remains.'
    Start-Process -FilePath (Join-Path $Root 'ThoRemix.exe') -WindowStyle Hidden
    Wait-Until { @([ThoRemixTrayProbe]::Windows() | Where-Object { $_.Class -eq 'TkTopLevel' -and $_.Title -eq 'Thỏ Remix — Toolkit' }).Count -eq 1 } 'Restart failed.'
    $desktop = Get-Desktop
    Start-Sleep -Milliseconds 700
    $tray = Get-Tray $desktop
    [ThoRemixTrayProbe]::PostMessage($desktop.Handle, 0x10, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
    Wait-Until { -not [ThoRemixTrayProbe]::IsWindowVisible($desktop.Handle) } 'Final close did not hide.'
    $iconRect = New-Object ThoRemixTrayProbe+RECT
    $iconStatus = [ThoRemixTrayProbe]::IconRect($tray.Handle, [ref]$iconRect)
    if ($iconStatus -eq 1) {
        [ThoRemixTrayProbe]::Click($iconRect)
        Start-Sleep -Milliseconds 300
        $overflow = [ThoRemixTrayProbe]::Windows() | Where-Object { $_.Class -eq 'NotifyIconOverflowWindow' -and $_.Visible }
        if ($overflow) { Save-Window $overflow 'tray-icons.png' }
    }
    if ((Get-FileHash -LiteralPath (Join-Path $Root 'config/settings.json')).Hash -ne $configBefore) { throw 'Verification changed campaign settings.' }
    @{observed_at=(Get-Date).ToUniversalTime().ToString('o'); shell_icon_registered=$true;
      close_hides=$true; second_launch_restores_same_instance=$true; tray_click_restores=$true;
      native_menu_items=$menuItems; menu_exit_verified=$true; restart_verified=$true;
      final_state='hidden_in_tray'; process_id=$desktop.Process; campaign_settings_unchanged=$true} |
      ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidence 'tray.json') -Encoding utf8
    Write-Output (Join-Path $evidence 'tray.json')
} finally { [ThoRemixTrayProbe]::SetCursorPos($originalCursor.X, $originalCursor.Y) | Out-Null }
