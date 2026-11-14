"""Start with Windows via the per-user Run registry key (exe build only).

HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\JkBmsWidget =
    "<exe path>" --autostart
Per-user, no admin rights needed, visible and removable in Task Manager >
Startup apps. `--autostart` tells the app it was started by Windows, so it
shows only the compact widget / taskbar strip, never the big dashboard.
Only offered for the frozen .exe: a dev setup (python + venv + working
directory) cannot be started reliably from that key.
"""

from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "JkBmsWidget"
AUTOSTART_FLAG = "--autostart"


def available() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def _exe() -> str:
    return f'"{sys.executable}"'


def command() -> str:
    return f"{_exe()} {AUTOSTART_FLAG}"


def _read() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)[0]
    except OSError:
        return None


def is_enabled() -> bool:
    value = _read()
    return value is not None and value.startswith(_exe())


def set_enabled(enabled: bool) -> None:
    if not available():
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def upgrade_entry() -> None:
    """Older builds registered the exe without --autostart: fix it in place."""
    if available() and is_enabled() and _read() != command():
        set_enabled(True)
