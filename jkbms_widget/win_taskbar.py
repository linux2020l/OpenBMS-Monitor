"""Windows taskbar geometry and state via Win32 (ctypes). No Qt imports.

Windows 11 has no supported API to put custom content *into* the taskbar
(deskbands were removed). The taskbar mode therefore shows a small
always-on-top window placed over the free part of the taskbar, left of
the notification area (tray), the same approach as tools like TrafficMonitor.

All rectangles here are in PHYSICAL pixels (the process is per-monitor DPI
aware under Qt 6); the caller converts them to Qt logical pixels.
On non-Windows systems every function returns None/False.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3


@dataclass(frozen=True)
class TaskbarInfo:
    left: int
    top: int
    right: int
    bottom: int
    edge: int  # ABE_* constant
    tray_left: int | None  # left x of the notification area, if found
    autohide: bool

    @property
    def horizontal(self) -> bool:
        return self.edge in (ABE_TOP, ABE_BOTTOM)

    @property
    def height(self) -> int:
        return self.bottom - self.top


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _shell32 = ctypes.windll.shell32

    class _APPBARDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uCallbackMessage", wintypes.UINT),
            ("uEdge", wintypes.UINT),
            ("rc", wintypes.RECT),
            ("lParam", wintypes.LPARAM),
        ]

    _ABM_GETSTATE, _ABM_GETTASKBARPOS = 4, 5
    _HWND_TOPMOST = wintypes.HWND(-1)
    _SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    _user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowExW.restype = wintypes.HWND
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.MonitorFromWindow.restype = wintypes.HANDLE
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]


DEFAULT_GAP = 8  # logical px between the strip and the tray
FALLBACK_OFFSET = 320  # logical px from the right edge if the tray is not found


def default_offset(info: TaskbarInfo, dpr: float) -> int:
    """Distance (logical px) from the taskbar's right edge to the strip's right edge."""
    if info.tray_left is not None and info.left < info.tray_left <= info.right:
        return round((info.right - info.tray_left) / dpr) + DEFAULT_GAP
    return FALLBACK_OFFSET


def strip_geometry(
    info: TaskbarInfo, dpr: float, width: int, offset: int | None, margin: int = 3
) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) in Qt logical px for the strip, or None if not placeable.

    Only horizontal, always-visible taskbars on the primary screen are
    supported (vertical or auto-hide taskbars: the strip is not shown).
    Primary screen origin is (0, 0), so physical -> logical is a division.
    """
    if not info.horizontal or info.autohide or dpr <= 0:
        return None
    left, right = info.left / dpr, info.right / dpr
    top, height = info.top / dpr, info.height / dpr
    if offset is None:
        offset = default_offset(info, dpr)
    # Keep the strip fully inside the taskbar.
    offset = max(0, min(int(offset), int(right - left - width)))
    h = int(height - 2 * margin)
    return int(right - offset - width), int(top + margin), width, h


def taskbar_info() -> TaskbarInfo | None:
    """Primary taskbar rectangle, edge, tray position, auto-hide flag."""
    if not IS_WINDOWS:
        return None
    abd = _APPBARDATA(cbSize=ctypes.sizeof(_APPBARDATA))
    if not _shell32.SHAppBarMessage(_ABM_GETTASKBARPOS, ctypes.byref(abd)):
        return None
    state = _shell32.SHAppBarMessage(_ABM_GETSTATE, ctypes.byref(abd))
    tray_left = None
    taskbar = _user32.FindWindowW("Shell_TrayWnd", None)
    if taskbar:
        notify = _user32.FindWindowExW(taskbar, None, "TrayNotifyWnd", None)
        if notify:
            rc = wintypes.RECT()
            if _user32.GetWindowRect(notify, ctypes.byref(rc)):
                tray_left = rc.left
    r = abd.rc
    return TaskbarInfo(r.left, r.top, r.right, r.bottom, abd.uEdge, tray_left, bool(state & 1))


def fullscreen_app_active() -> bool:
    """True while a full-screen app/game or presentation is in the foreground.

    Windows also reports QUNS_BUSY right after "Show desktop" (Win+D, the
    taskbar corner button): the desktop window then has focus and covers the
    whole monitor. So for QUNS_BUSY we also require a real (non-shell)
    foreground window that covers its monitor.
    """
    if not IS_WINDOWS:
        return False
    state = ctypes.c_int()
    if _shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
        return False
    # 2 = QUNS_BUSY (full-screen app), 3 = D3D full-screen, 4 = presentation mode
    if state.value in (3, 4):
        return True
    if state.value == 2:
        hwnd = _user32.GetForegroundWindow()
        return bool(hwnd) and not is_shell_window(hwnd) and _covers_monitor(hwnd)
    return False


def foreground_class() -> str:
    """Window class of the foreground window (for log messages)."""
    if not IS_WINDOWS:
        return ""
    return _class_name(_user32.GetForegroundWindow())


def taskbar_uses_light_theme() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            return winreg.QueryValueEx(key, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False


def native_rounded_corners(hwnd: int, border_color: str | None = None) -> None:
    """Windows 11 rounded corners (and border colour) for a frameless window.

    Lets us drop WA_TranslucentBackground: translucent ("layered") windows
    re-upload the whole window on every repaint, which made hover effects on
    the dashboard buttons slow and unreliable. No effect on Windows 10.
    """
    if not (IS_WINDOWS and hwnd):
        return
    try:
        dwm = ctypes.windll.dwmapi
    except OSError:
        return
    DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
    pref = ctypes.c_int(DWMWCP_ROUND)
    dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                              ctypes.byref(pref), ctypes.sizeof(pref))
    if border_color:
        DWMWA_BORDER_COLOR = 34
        r, g, b = (int(border_color[i:i + 2], 16) for i in (1, 3, 5))
        colorref = ctypes.c_uint(r | g << 8 | b << 16)  # COLORREF is 0x00BBGGRR
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_BORDER_COLOR,
                                  ctypes.byref(colorref), ctypes.sizeof(colorref))


# Shell windows that are "foreground" when the user clicks the desktop,
# taskbar, tray overflow, Start or search - never treated as maximized apps.
_SHELL_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland",
    "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
}


def _class_name(hwnd) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(128)
    _user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def is_shell_window(hwnd) -> bool:
    return _class_name(hwnd) in _SHELL_CLASSES


def foreground_is_maximized(own_hwnds: set[int]) -> bool:
    """True if the active window (not ours, not the shell) is maximized or full-screen."""
    if not IS_WINDOWS:
        return False
    hwnd = _user32.GetForegroundWindow()
    if not hwnd or int(hwnd) in own_hwnds:
        return False
    if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
        return False
    if is_shell_window(hwnd):
        return False
    if _user32.IsZoomed(hwnd):
        return True
    # Borderless full-screen (games, video): window covers its whole monitor.
    return _covers_monitor(hwnd)


def _covers_monitor(hwnd) -> bool:
    rc = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return False
    monitor = _user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if not _user32.GetMonitorInfoW(monitor, ctypes.byref(mi)):
        return False
    m = mi.rcMonitor
    return rc.left <= m.left and rc.top <= m.top and rc.right >= m.right and rc.bottom >= m.bottom


def set_click_through(hwnd: int, enabled: bool) -> None:
    """Let mouse clicks pass through the window (WS_EX_TRANSPARENT).

    Works on layered windows; Qt makes the window layered when its opacity
    is below 1, so call this after setWindowOpacity(<1).
    """
    if not (IS_WINDOWS and hwnd):
        return
    GWL_EXSTYLE, WS_EX_TRANSPARENT = -20, 0x00000020
    style = _user32.GetWindowLongPtrW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    new = style | WS_EX_TRANSPARENT if enabled else style & ~WS_EX_TRANSPARENT
    if new != style:
        _user32.SetWindowLongPtrW(wintypes.HWND(hwnd), GWL_EXSTYLE, new)


def dark_title_bar(hwnd: int) -> None:
    """Dark native title bar for windows that keep the system frame."""
    if not (IS_WINDOWS and hwnd):
        return
    try:
        dwm = ctypes.windll.dwmapi
    except OSError:
        return
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    on = ctypes.c_int(1)
    dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE,
                              ctypes.byref(on), ctypes.sizeof(on))


def keep_on_top(hwnd: int) -> None:
    """Re-assert topmost z-order without moving or activating the window.

    Needed because clicking the taskbar brings it above other topmost windows.
    """
    if IS_WINDOWS and hwnd:
        _user32.SetWindowPos(
            wintypes.HWND(hwnd), _HWND_TOPMOST, 0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
        )
