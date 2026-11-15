"""User settings and app data files (JSON in %APPDATA%\\OpenBmsMonitor).

Pure Python, no Qt. A missing or corrupt file never stops the app: we
fall back to defaults and overwrite it on the next save.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .model import DEFAULT_IDLE_THRESHOLD

APP_DIR_NAME = "OpenBmsMonitor"
LEGACY_APP_DIR_NAME = "JkBmsWidget"  # before the rename to OpenBMS Monitor (v0.8.0)
DOCUMENTS_DIR_NAME = "OpenBMS Monitor"  # Documents\\..., CSV exports and diagnostics


def app_dir() -> Path:
    """%APPDATA%\\OpenBmsMonitor (created on demand; the old folder is moved there)."""
    base = Path(os.environ.get("APPDATA") or str(Path.home()))
    path = base / APP_DIR_NAME
    migrate_legacy_dir(base / LEGACY_APP_DIR_NAME, path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def migrate_legacy_dir(old: Path, new: Path) -> bool:
    """First start after the rename: settings, history and log move to the
    new folder, so nothing is lost. Never overwrites an existing new folder.
    True if something was moved."""
    if new.exists() or not old.is_dir():
        return False
    try:
        old.rename(new)  # same drive: instant, keeps everything
        return True
    except OSError:
        import shutil

        try:  # e.g. a file still locked: copy what can be copied
            shutil.copytree(old, new, ignore=shutil.ignore_patterns("*.lock"))
            return True
        except OSError:
            return False


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
class BankConfig:
    """Several BMS in parallel, shown as one battery (step D2)."""

    id: str  # stable key (history series "bank:<id>")
    name: str = ""
    members: list[str] = field(default_factory=list)  # BMS MAC addresses
    visible: bool = True  # own strip / widget shown
    compact_pos: list[int] | None = None
    letter: str = ""  # A-Z, picked by the user like a drive letter (unique)
    kind: str = "parallel"  # "parallel" / "series"


_BANK_KEYS = {f.name for f in fields(BankConfig)}


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
    widgets_on_desktop: bool = False  # floating widgets pinned to the desktop, not on top
    check_updates: bool = True  # ask GitHub once a day for a newer release
    update_notified: str = ""  # newest version already announced (one balloon per version)
    language: str = "auto"  # "auto" (Windows display language), "uk" or "en"
    notify_enabled: bool = True  # Windows notifications (low SOC, alarms, lost, full)
    low_soc_threshold: int = 20  # %, "low battery" notification
    bms_visible: bool = True  # main BMS: strip / widget shown
    extra_devices: list[dict] = field(default_factory=list)  # Device dicts, 2nd BMS on
    banks: list[dict] = field(default_factory=list)  # BankConfig dicts (parallel banks)
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

    def bank_configs(self) -> list[BankConfig]:
        return [BankConfig(**{k: v for k, v in b.items() if k in _BANK_KEYS}) for b in self.banks]

    def set_banks(self, banks: list[BankConfig]) -> None:
        self.banks = [asdict(b) for b in banks]

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
        self.widgets_on_desktop = bool(self.widgets_on_desktop)
        self.check_updates = bool(self.check_updates)
        if not isinstance(self.update_notified, str):
            self.update_notified = ""
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
        self.banks = clean_banks(self.banks)

    def save(self, path: Path) -> None:
        # Write to a temp file first so a crash never leaves a half-written file.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


def clean_banks(banks) -> list[dict]:
    """Well-formed banks only: unique ids, each BMS in at most one bank,
    at least two members (a "bank" of one BMS is just that BMS), a known
    kind and a unique letter (missing / taken ones get the first free)."""
    from .bank import KINDS, LETTERS, PARALLEL, free_letter

    out, ids, used = [], set(), set()
    for b in banks if isinstance(banks, list) else []:
        if not (isinstance(b, dict) and isinstance(b.get("id"), str) and b["id"]):
            continue
        if b["id"] in ids:
            continue
        members = []
        for a in b.get("members") if isinstance(b.get("members"), list) else []:
            if isinstance(a, str) and a.upper() not in used and a.upper() not in members:
                members.append(a.upper())
        if len(members) < 2:
            continue
        entry = {k: v for k, v in b.items() if k in _BANK_KEYS}
        entry["members"] = members
        entry["name"] = str(entry.get("name") or "")
        entry["visible"] = bool(entry.get("visible", True))
        pos = entry.get("compact_pos")
        if not (isinstance(pos, list) and len(pos) == 2):
            entry["compact_pos"] = None
        if entry.get("kind") not in KINDS:
            entry["kind"] = PARALLEL
        ids.add(b["id"])
        used.update(members)
        out.append(entry)
    letters: set[str] = set()
    for entry in out:
        letter = str(entry.get("letter") or "").upper()
        if letter not in LETTERS or letter in letters:
            letter = ""
        entry["letter"] = letter
        letters.add(letter)
    for entry in out:
        if not entry["letter"]:
            entry["letter"] = free_letter(letters)
            letters.add(entry["letter"])
    return out
