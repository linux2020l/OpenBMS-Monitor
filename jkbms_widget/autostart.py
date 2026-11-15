"""Start with Windows via the per-user Run registry key (exe build only).

HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\OpenBmsMonitor =
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
VALUE_NAME = "OpenBmsMonitor"
LEGACY_VALUE_NAME = "JkBmsWidget"  # before the rename (v0.8.0)
AUTOSTART_FLAG = "--autostart"


def available() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def _exe() -> str:
    return f'"{sys.executable}"'


def command() -> str:
    return f"{_exe()} {AUTOSTART_FLAG}"


def _read(name: str = VALUE_NAME) -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, name)[0]
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
    """Fix entries written by older builds: the value from before the rename
    (JkBmsWidget) becomes ours, and an exe registered without --autostart
    gets the flag."""
    if not available():
        return
    if _read(LEGACY_VALUE_NAME) is not None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, LEGACY_VALUE_NAME)
            except FileNotFoundError:
                pass
        set_enabled(True)  # it was on before the rename: keep it on
    elif is_enabled() and _read() != command():
        set_enabled(True)
