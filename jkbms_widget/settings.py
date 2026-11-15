"""User settings and app data files (JSON in %APPDATA%\\JkBmsWidget).

Pure Python, no Qt. A missing or corrupt file never stops the app: we
fall back to defaults and overwrite it on the next save.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .model import DEFAULT_IDLE_THRESHOLD

APP_DIR_NAME = "JkBmsWidget"


def app_dir() -> Path:
    """%APPDATA%\\JkBmsWidget (created on demand)."""
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Device:
    """One monitored BMS."""

    address: str
    name: str = ""
    driver: str = "jk"
    variant: str | None = None  # JK only
    compact_pos: list[int] | None = None  # its floating widget, [x, y]
    visible: bool = True  # own strip / widget shown (data is recorded either way)


_DEVICE_KEYS = {f.name for f in fields(Device)}


@dataclass
class Settings:
    # The first (main) BMS keeps its original top-level fields, so settings
    # files from before multi-BMS support load unchanged; further BMS are
    # in `extra_devices` (owner's request 2026-11-15: several BMS at once).
    address: str | None = None  # BMS MAC address
    bms_name: str = ""  # last known BLE name, for display
    driver: str = "jk"  # BMS family (drivers.DRIVERS ids); old files = JK
    variant: str | None = None  # JK only: force "JK02_24S"/"JK02_32S"; None = auto
    idle_threshold: float = DEFAULT_IDLE_THRESHOLD
    ui_scale: float = 1.0  # applied at startup (QT_SCALE_FACTOR)
    compact_pos: list[int] | None = None  # [x, y]
    dashboard_geometry: list[int] | None = None  # [x, y, w, h]
    expanded: bool = False  # dashboard was open on exit
    compact_hidden: bool = False  # floating widget hidden (tray only)
    display_mode: str = "taskbar"  # "taskbar" (strip on taskbar, default) or "widget"
    taskbar_offset: int | None = None  # strip: logical px from taskbar right edge
    fullscreen_behavior: str = "hide"  # strip during full-screen apps: "hide" / "corner"
    dim_when_maximized: bool = True  # widget/strip see-through + click-through then
    language: str = "auto"  # "auto" (Windows display language), "uk" or "en"
    notify_enabled: bool = True  # Windows notifications (low SOC, alarms, lost, full)
    low_soc_threshold: int = 20  # %, "low battery" notification
    bms_visible: bool = True  # main BMS: strip / widget shown
    extra_devices: list[dict] = field(default_factory=list)  # Device dicts, 2nd BMS on
    extra: dict = field(default_factory=dict)  # forward compatibility

    # ----- devices --------------------------------------------------------------
    def devices(self) -> list[Device]:
        """All monitored BMS, the main one first (empty before the first pick)."""
        out = []
        if self.address:
            out.append(Device(self.address, self.bms_name, self.driver, self.variant,
                              self.compact_pos, self.bms_visible))
        for d in self.extra_devices:
            out.append(Device(**{k: v for k, v in d.items() if k in _DEVICE_KEYS}))
        return out

    def set_devices(self, devices: list[Device]) -> None:
        """Store the list back (the first one becomes the main BMS)."""
        if devices:
            main = devices[0]
            self.address, self.bms_name, self.driver = main.address, main.name, main.driver
            self.variant, self.compact_pos = main.variant, main.compact_pos
            self.bms_visible = main.visible
        else:
            self.address, self.bms_name = None, ""
        self.extra_devices = [asdict(d) for d in devices[1:]]

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            # utf-8-sig: also accept a BOM (Notepad / PowerShell 5.1 add one).
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in data.items() if k in known})
        s._sanitize()
        return s

    def _sanitize(self) -> None:
        # Hand-edited or old files: keep values in a usable range.
        try:
            self.idle_threshold = min(max(float(self.idle_threshold), 0.0), 100.0)
        except (TypeError, ValueError):
            self.idle_threshold = DEFAULT_IDLE_THRESHOLD
        try:
            self.ui_scale = min(max(float(self.ui_scale), 0.75), 3.0)
        except (TypeError, ValueError):
            self.ui_scale = 1.0
        if self.variant not in (None, "JK02_24S", "JK02_32S"):
            self.variant = None
        from . import drivers  # local import: keeps settings importable on its own

        if self.driver not in {d.id for d in drivers.DRIVERS}:
            self.driver = drivers.DEFAULT_DRIVER.id
        if self.display_mode not in ("widget", "taskbar"):
            self.display_mode = "taskbar"
        try:
            self.low_soc_threshold = min(max(int(self.low_soc_threshold), 5), 100)
        except (TypeError, ValueError):
            self.low_soc_threshold = 20
        self.notify_enabled = bool(self.notify_enabled)
        if self.language not in ("auto", "uk", "en"):
            self.language = "auto"
        if self.fullscreen_behavior not in ("hide", "corner"):
            self.fullscreen_behavior = "hide"
        if not isinstance(self.taskbar_offset, int):
            self.taskbar_offset = None
        if not (isinstance(self.compact_pos, list) and len(self.compact_pos) == 2):
            self.compact_pos = None
        if not (isinstance(self.dashboard_geometry, list) and len(self.dashboard_geometry) == 4):
            self.dashboard_geometry = None
        # Extra BMS: keep only well-formed entries, no duplicates of the main one.
        known_drivers = {d.id for d in drivers.DRIVERS}
        seen = {(self.address or "").upper()}
        clean = []
        for d in self.extra_devices if isinstance(self.extra_devices, list) else []:
            if not (isinstance(d, dict) and isinstance(d.get("address"), str)):
                continue
            entry = {k: v for k, v in d.items() if k in _DEVICE_KEYS}
            entry["address"] = entry["address"].upper()
            if entry["address"] in seen:
                continue
            seen.add(entry["address"])
            if entry.get("driver") not in known_drivers:
                entry["driver"] = drivers.DEFAULT_DRIVER.id
            pos = entry.get("compact_pos")
            if not (isinstance(pos, list) and len(pos) == 2):
                entry["compact_pos"] = None
            entry["visible"] = bool(entry.get("visible", True))
            clean.append(entry)
        self.extra_devices = clean

    def save(self, path: Path) -> None:
        # Write to a temp file first so a crash never leaves a half-written file.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
