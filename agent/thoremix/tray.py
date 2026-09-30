"""Windows notification-area adapter. Callbacks only enqueue Tk-thread commands."""
from __future__ import annotations

import ctypes
import hashlib
import os
import threading
from ctypes import wintypes


def rabbit_icon():
    from PIL import Image, ImageDraw

    image = Image.new('RGBA', (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((1, 1, 62, 62), radius=15, fill='#6550bb')
    draw.ellipse((20, 7, 29, 37), fill='white')
    draw.ellipse((35, 7, 44, 37), fill='white')
    draw.ellipse((15, 25, 49, 55), fill='white')
    draw.ellipse((24, 37, 28, 42), fill='#17243a')
    draw.ellipse((36, 37, 40, 42), fill='#17243a')
    draw.ellipse((30, 44, 34, 47), fill='#e693af')
    return image


class DesktopTray:
    def __init__(self, commands):
        import pystray

        self.commands = commands
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.schedule_enabled = False
        self.busy = False
        self._state = None

        def action(command):
            return lambda icon, item: self.commands.put(command)

        self.icon = pystray.Icon('ThoRemix', rabbit_icon(), 'Thỏ Remix', pystray.Menu(
            pystray.MenuItem('Mở Thỏ Remix', action('show'), default=True),
            pystray.MenuItem('Lịch chạy…', action('schedule')),
            pystray.MenuItem('Tạm dừng lịch', action('pause'),
                            enabled=lambda item: self.schedule_enabled),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Thoát Thỏ Remix', action('quit')),
        ))
        self.thread = threading.Thread(target=self._run, name='ThoRemixTray', daemon=True)

    @property
    def available(self):
        return self.ready.is_set() and self.thread.is_alive()

    def start(self):
        self.thread.start()

    def _run(self):
        def setup(icon):
            try:
                if not self.stopping.is_set():
                    icon.visible = True
                    self.ready.set()
                    self.commands.put('tray_ready')
            except Exception:
                self.commands.put('tray_unavailable')
                icon.stop()

        try:
            # The Win32 backend permits its message loop on a dedicated thread.
            self.icon.run(setup=setup)
        except Exception:
            self.commands.put('tray_unavailable')
        finally:
            self.ready.clear()
            if not self.stopping.is_set():
                self.commands.put('tray_unavailable')

    def update(self, *, enabled, active):
        state = (bool(enabled), bool(active))
        if state == self._state or not self.available:
            return
        self.schedule_enabled, self.busy = state
        self.icon.title = 'Thỏ Remix · ' + ('Đang xử lý' if active else
                                          ('Lịch đã bật' if enabled else 'Lịch tạm dừng'))
        self.icon.update_menu()
        self._state = state

    def stop(self):
        self.stopping.set()
        self.ready.clear()
        self.icon.stop()
        if self.thread.is_alive():
            self.thread.join(timeout=2)


def instance_names(namespace=None):
    """Keep legacy identity; private instances get deterministic distinct names."""
    if namespace is None:
        suffix = ""
    elif not isinstance(namespace, str) or not namespace:
        raise ValueError("INVALID_DESKTOP_NAMESPACE")
    else:
        suffix = "-" + hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:24]
    return (r"Local\ThoRemixDesktop" + suffix, r"Local\ThoRemixDesktopActivate" + suffix)


class DesktopInstance:
    """One desktop per Windows session, with a kernel event to reopen a hidden one."""
    MUTEX = 'Local\\ThoRemixDesktop'
    ACTIVATE = 'Local\\ThoRemixDesktopActivate'

    def __init__(self, *, namespace=None):
        if namespace is not None:
            self.MUTEX, self.ACTIVATE = instance_names(namespace)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True) if os.name == 'nt' else None
        self.mutex = self.event = None
        self.primary = True
        if not self.kernel:
            return
        k = self.kernel
        k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateEventW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateMutexW.restype = wintypes.HANDLE
        k.SetEvent.argtypes = [wintypes.HANDLE]
        k.SetEvent.restype = wintypes.BOOL
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        # Create the event before the mutex so even a simultaneous second launch is retained.
        self.event = k.CreateEventW(None, False, False, self.ACTIVATE)
        if not self.event:
            raise ctypes.WinError(ctypes.get_last_error())
        self.mutex = k.CreateMutexW(None, False, self.MUTEX)
        error = ctypes.get_last_error()
        if not self.mutex:
            self.close()
            raise ctypes.WinError(error)
        self.primary = error != 183
        if not self.primary and not k.SetEvent(self.event):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def activation_pending(self):
        return bool(self.event and self.kernel.WaitForSingleObject(self.event, 0) == 0)

    def close(self):
        for name in ('mutex', 'event'):
            handle = getattr(self, name)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)


