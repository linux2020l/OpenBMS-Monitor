"""Widget application: data source -> Controller -> views.

Views: floating compact widget OR taskbar strip (display mode), the
expandable dashboard, and the tray icon with the shared menu.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import sqlite3
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QPoint, QProcess, QRect, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from . import autostart, strings, updates, win_taskbar
from . import drivers
from .bank import SERIES, combine_cells, free_letter
from .model import CellInfo, DeviceInfo
from .notifications import ALARM, FULL, LOST, LOW_SOC, Notifier
from .settings import DOCUMENTS_DIR_NAME, BankConfig, Device, Settings, app_dir
from .sources import BleSource, DataSource, ReplaySource
from .history_store import RETENTION_S, HistoryStore
from .state import History, Snapshot, StateTracker, time_left
from .ui import icons, theme
from .ui.alarms import AlarmDialog
from .ui.compact import CompactWindow
from .ui.dashboard import DashboardWindow
from .ui.diagnostics_dialog import DiagnosticsDialog
from .ui.picker import BmsPickerDialog
from .ui.settings_dialog import SCALES, SettingsDialog
from .ui.taskbar_strip import STRIP_WIDTH, TaskbarStrip
from .ui.widgets import native_hwnd, set_dimmed

log = logging.getLogger("jkbms_widget")

STALE_AFTER_S = 5.0  # no cell-info frame for this long -> show values as stale
LIVE_STATUSES = ("connected", "replay")
HISTORY_PRUNE_MS = 60 * 60 * 1000  # drop points older than 7 days once an hour
MODE_WIDGET, MODE_TASKBAR = "widget", "taskbar"
ONE_SHOT_FLAGS = {"--autostart": 0, "--exit-after": 1}  # flag -> number of values
# Owner's choice (D2): a bank reports low charge / full itself; alarms and
# lost links come from each of its BMS (the bank's alarms are their union).
BANK_EVENTS = frozenset({LOW_SOC, FULL})
MEMBER_EVENTS = frozenset({ALARM, LOST})
SERIES_GRACE_S = 60.0  # series bank: an offline pack's last voltage is used this long


def restart_command(frozen: bool, executable: str, argv: list[str],
                    orig_argv: list[str]) -> tuple[str, list[str]]:
    """(program, args) that start this app again with the same options.

    Drops one-shot flags: a restart is not a Windows autostart and must not
    exit by itself. Dev runs (python -m jkbms_widget ...) are restarted with
    the original interpreter options, the frozen exe with its own args.
    """
    args = list(argv[1:]) if frozen else list(orig_argv[1:])
    out, skip = [], 0
    for a in args:
        if skip:
            skip -= 1
        elif a in ONE_SHOT_FLAGS:
            skip = ONE_SHOT_FLAGS[a]
        else:
            out.append(a)
    return executable, out


class UpdateChecker(QObject):
    """Runs updates.fetch_latest in a background thread (it blocks on the
    network) and hands the result to the GUI thread through a signal."""

    finished = Signal(object, bool)  # Release | None, asked by the user

    def __init__(self, fetch=updates.fetch_latest) -> None:
        super().__init__()
        self.fetch = fetch
        self.busy = False

    def check(self, manual: bool = False) -> None:
        if self.busy:
            return
        self.busy = True
        import threading

        def run() -> None:
            release = self.fetch()
            self.busy = False
            self.finished.emit(release, manual)  # queued to the GUI thread

        threading.Thread(target=run, name="update-check", daemon=True).start()


class View(QObject):
    """Something shown as one battery: a BMS (Monitor) or a parallel bank
    (Bank). Each has its own state, history, notifications, floating widget
    and taskbar strip."""

    source: DataSource | None = None

    def __init__(self, ctl: "Controller") -> None:
        super().__init__()
        self.ctl = ctl
        s = ctl.settings
        self.tracker = StateTracker(s.idle_threshold)
        self.notifier = Notifier(s.low_soc_threshold)
        self.history = History(on_bucket_closed=self._store_point)
        self.compact = CompactWindow()
        self.compact.set_on_desktop(s.widgets_on_desktop)
        self.strip = TaskbarStrip()
        self.strip.offset = s.taskbar_offset
        self.strip.fullscreen_behavior = s.fullscreen_behavior

    @property
    def history_key(self) -> str | None:
        """Name of this view's series in the history database."""
        raise NotImplementedError

    # ----- history (10 s buckets, one SQLite series per BMS / bank) ---------------
    def _store_point(self, point) -> None:
        store = self.ctl.store
        if store is None or not self.history_key:
            return
        try:
            store.add(self.history_key, point)
        except sqlite3.Error:
            log.exception("cannot store history point")

    def load_history(self) -> None:
        store = self.ctl.store
        if store is None or not self.history_key:
            return
        now = time.time()
        try:
            self.history.extend(store.load(self.history_key, now - RETENTION_S), now)
        except sqlite3.Error:
            log.exception("cannot load history")

    def save_history(self) -> None:
        """Store the bucket still being filled (on exit / BMS switch)."""
        point = self.history.open_bucket()
        if point is not None:
            self._store_point(point)

    def close_views(self) -> None:
        self.strip.set_wanted(False)
        for w in (self.compact, self.strip):
            w.hide()
            w.deleteLater()


class Monitor(View):
    """One BMS: its data source, derived state, history and its own small
    views (floating widget + taskbar strip). The Controller owns a list of
    them (several BMS at once, owner's request 2026-11-15)."""

    def __init__(self, ctl: "Controller", device: Device | None) -> None:
        super().__init__(ctl)
        self.device = device  # None until the first BMS is picked
        self.source: DataSource | None = None
        self.cell: CellInfo | None = None
        self.last_cell_at = 0.0
        self.status, self.status_detail = "stopped", ""
        self.device_name = device.name if device else ""

    @property
    def address(self) -> str | None:
        return self.device.address if self.device else None

    @property
    def history_key(self) -> str | None:
        return self.address

    @property
    def visible(self) -> bool:
        """Own strip / widget shown (hidden BMS still record their history)."""
        return self.device.visible if self.device else True

    def reset_state(self) -> None:
        """Another BMS now uses this slot: forget the old one's data."""
        self.history.clear()
        self.cell = None
        self.tracker = StateTracker(self.ctl.settings.idle_threshold)
        self.notifier = Notifier(self.ctl.settings.low_soc_threshold)

    # ----- source -------------------------------------------------------------
    def make_ble_source(self) -> BleSource:
        d = self.device
        options = self.ctl.options_override
        if options is None:  # command line (--variant) wins, else the device's own setting
            options = {"variant": d.variant} if d.variant else {}
        return BleSource(d.address, drivers.get(d.driver), options)

    def set_source(self, source: DataSource) -> None:
        old = self.source
        if old is not None:
            for sig, slot in ((old.status, self.on_status), (old.cell_info, self.on_cell),
                              (old.device_info, self.on_device_info)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            old.stop(wait_s=3.0)
        self.source = source
        source.status.connect(self.on_status)
        source.cell_info.connect(self.on_cell)
        source.device_info.connect(self.on_device_info)
        source.start()

    @property
    def running(self) -> bool:
        return self.source is not None and self.source.running

    # ----- data ---------------------------------------------------------------
    def on_status(self, code: str, detail: str) -> None:
        if (code, detail) != (self.status, self.status_detail):
            log.info("status %s %s %s", self.address, code, detail)
        self.status, self.status_detail = code, detail
        self.ctl.render()

    def on_device_info(self, info: DeviceInfo) -> None:
        # More reliable than the BLE advertisement name, which Windows
        # does not always report (then only the MAC address is known).
        name = info.name or info.model
        if name != self.device_name:
            log.info("device %s HW %s SW %s name %r", info.model, info.hardware_version,
                     info.software_version, info.name)
        self.device_name = name
        if not self.ctl.replay and self.device is not None and self.device.name != name:
            self.device.name = name
            self.ctl.save_devices()
        self.ctl.render()

    def on_cell(self, cell: CellInfo) -> None:
        mono = time.monotonic()
        self.tracker.update(cell.current, mono)
        self.history.add(time.time(), cell.soc, cell.current, cell.pack_voltage)
        self.cell, self.last_cell_at = cell, mono
        bank = self.ctl.bank_of(self)
        if bank is not None:
            bank.feed()
        self.ctl.render()

    def snapshot(self) -> Snapshot:
        cell = self.cell
        stale = (
            cell is None
            or self.status not in LIVE_STATUSES
            or time.monotonic() - self.last_cell_at > STALE_AFTER_S
        )
        hours, kind = (None, None)
        if cell is not None and not stale:
            hours, kind = time_left(cell, self.tracker.estimate_current)
        return Snapshot(
            cell=cell, state=self.tracker.state, hours_left=hours, left_kind=kind,
            stale=stale, status=self.status, status_detail=self.status_detail,
            device_name=self.device_name, low_soc=self.ctl.settings.low_soc_threshold,
        )



class Bank(View):
    """Several BMS wired in parallel, shown as one battery (step D2).

    Values come from the members with fresh data (bank.combine_cells);
    members without data are left out and listed in Snapshot.offline, so
    the views can warn. The bank keeps its own state, history and strip."""

    address = None

    def __init__(self, ctl: "Controller", config: BankConfig) -> None:
        super().__init__(ctl)
        self.config = config
        self.created = time.monotonic()  # series: grace for packs not connected yet

    @property
    def history_key(self) -> str:
        return f"bank:{self.config.id}"

    @property
    def device_name(self) -> str:
        return self.config.name or strings.BANK_DEFAULT_NAME.format(label=self.ctl.label(self))

    @property
    def visible(self) -> bool:
        return self.config.visible

    @property
    def members(self) -> list[Monitor]:
        wanted = set(self.config.members)
        return [m for m in self.ctl.monitors if m.address and m.address.upper() in wanted]

    @property
    def running(self) -> bool:
        return any(m.running for m in self.members)

    def _member_snaps(self) -> list[tuple[Monitor, Snapshot]]:
        return [(m, m.snapshot()) for m in self.members]

    def _combined(self) -> dict:
        """The bank's reading and how complete it is (see Snapshot fields)."""
        now = time.monotonic()
        snaps = self._member_snaps()
        name = {m: s.device_name or m.address for m, s in snaps}
        live = [s for _, s in snaps if not s.stale]
        series = self.config.kind == SERIES
        missing: tuple[str, ...] = ()
        if series:
            # Without a pack the string voltage is unknown: use its last known
            # voltage for a while, then report the bank as having no data
            # (owner's choice 2026-11-15).
            def gone(m: Monitor) -> bool:
                since = m.last_cell_at if m.cell is not None else self.created
                return now - since > SERIES_GRACE_S

            missing = tuple(name[m] for m, s in snaps if s.stale and gone(m))
            complete = all(s.cell is not None for _, s in snaps)
            if live and complete and not missing:
                cell = combine_cells([s.cell for _, s in snaps], SERIES)
                # The current is common: take it from fresh readings only.
                cell = dataclasses.replace(cell, current=sum(s.cell.current for s in live) / len(live))
                stale = False
            else:
                cell = combine_cells([s.cell for _, s in snaps if s.cell is not None], SERIES)
                stale = True
            packs = tuple((name[m], s.cell) for m, s in snaps if s.cell is not None)
        elif live:
            cell, stale = combine_cells([s.cell for s in live]), False
            packs = tuple((name[m], s.cell) for m, s in snaps if not s.stale)
        else:  # nothing fresh: last known values, greyed out
            cell = combine_cells([s.cell for _, s in snaps if s.cell is not None])
            stale = True
            packs = tuple((name[m], s.cell) for m, s in snaps if s.cell is not None)
        if not stale:
            offline = tuple(name[m] for m, s in snaps if s.stale)
            status, detail = live[0].status, ""
        else:
            offline = ()
            trying = [s for _, s in snaps if s.status != "stopped"] or [s for _, s in snaps]
            status, detail = (trying[0].status, trying[0].status_detail) if trying else ("stopped", "")
        return dict(cell=cell, stale=stale, offline=offline, missing=missing, packs=packs,
                    status=status, detail=detail, members=len(snaps))

    @property
    def cell(self) -> CellInfo | None:
        c = self._combined()
        return None if c["stale"] else c["cell"]

    def feed(self) -> None:
        """A member got new data: update the bank's state and history."""
        cell = self.cell
        if cell is None:
            return
        self.tracker.update(cell.current, time.monotonic())
        self.history.add(time.time(), cell.soc, cell.current, cell.pack_voltage)

    def snapshot(self) -> Snapshot:
        c = self._combined()
        cell, stale = c["cell"], c["stale"]
        hours, kind = (None, None)
        if cell is not None and not stale:
            hours, kind = time_left(cell, self.tracker.estimate_current)
        return Snapshot(
            cell=cell, state=self.tracker.state, hours_left=hours, left_kind=kind,
            stale=stale, status=c["status"], status_detail=c["detail"],
            device_name=self.device_name, low_soc=self.ctl.settings.low_soc_threshold,
            members=c["members"], offline=c["offline"], packs=c["packs"],
            series=self.config.kind == SERIES, missing=c["missing"],
        )

class Controller(QObject):
    """Owns the BMS monitors, the shared dashboard, tray and menu."""

    def __init__(
        self,
        settings: Settings,
        settings_path: Path | None = None,
        history_path: Path | None = None,
        replay: bool = False,
        options: dict | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.settings_path = settings_path
        self.history_path = history_path
        self.replay = replay
        self.options_override = options  # driver options from the command line
        self._shut_down = False
        self.restart_pending = False  # run_widget starts a new copy after exit
        self._tray_key = None
        self._open_store()
        self._import_legacy_history()

        self.monitors: list[Monitor] = []
        self.active = 0  # the monitor the dashboard shows
        self.menu = QMenu()
        self.menu.setToolTipsVisible(True)
        self.menu.aboutToShow.connect(self.populate_menu)
        for device in settings.devices() or [None]:
            self.monitors.append(self._new_monitor(device))
        self.banks: list[Bank] = []
        known = {m.address.upper() for m in self.monitors if m.address}
        for config in settings.bank_configs():
            if len(set(config.members) & known) >= 2:  # members removed by hand: skip
                self.banks.append(self._new_bank(config))
        self._sort_banks()

        self.dashboard = DashboardWindow(self.mon.history)
        self.dashboard.set_idle_threshold(settings.idle_threshold)
        self.dashboard.settings_requested.connect(self.open_settings)
        self.dashboard.alarms_requested.connect(lambda: self.show_alarms())
        self.dashboard.toggle_connection.connect(self.toggle_connection)
        self.dashboard.quit_requested.connect(self.quit)
        self.dashboard.collapse_requested.connect(self.collapse)
        self.dashboard.context_menu.connect(self.show_menu)
        self.dashboard.monitor_selected.connect(self.set_active)
        self.dashboard.visibility_toggled.connect(self.set_view_visible)
        self._update_dashboard_list()

        self.tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icons.battery_level_icon(None, theme.GREY))
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(self._on_tray_activated)
            self.tray.show()

        # Re-render once per second so "stale" kicks in even without new data.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.render)
        self.timer.start(1000)
        # While another app's window is maximized / full-screen, the widgets and
        # the corner strips turn see-through and let clicks pass (owner's request).
        self._dimmed: dict[QWidget, bool] = {}  # window -> dimmed now
        self.dim_timer = QTimer(self)
        self.dim_timer.timeout.connect(self.update_dimming)
        self.dim_timer.start(400)
        self.history_timer = QTimer(self)
        self.history_timer.timeout.connect(self.prune_history)
        self.history_timer.start(HISTORY_PRUNE_MS)

        # Update check (step E): once a minute after start, then daily. Only
        # for the real app (settings file), never in replay mode or tests.
        self.update: updates.Release | None = None  # newer release, if any
        self._update_balloon = False  # the last tray balloon was the update one
        self.updater = UpdateChecker()
        self.updater.finished.connect(self._on_update_result)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._auto_update_check)
        if self.settings_path is not None and not self.replay:
            QTimer.singleShot(int(updates.FIRST_CHECK_DELAY_S * 1000), self._auto_update_check)
            self.update_timer.start(int(updates.CHECK_EVERY_S * 1000))
        if self.tray is not None:
            self.tray.messageClicked.connect(self._on_balloon_clicked)

    # ----- monitors -------------------------------------------------------------
    def _wire(self, v: View) -> None:
        v.load_history()
        v.compact.alarms_requested.connect(lambda v=v: self.show_alarms(v))
        v.compact.expand_requested.connect(lambda v=v: self.expand(v))
        v.compact.context_menu.connect(lambda pos, v=v: self.show_menu(pos, v))
        v.compact.settings_requested.connect(self.open_settings)
        v.strip.clicked.connect(lambda v=v: self.toggle_dashboard(v))
        v.strip.alarms_clicked.connect(lambda v=v: self.show_alarms(v))
        v.strip.context_menu.connect(lambda pos, v=v: self.show_menu(pos, v))
        v.strip.offset_changed.connect(self._on_strip_moved)

    def _new_monitor(self, device: Device | None) -> Monitor:
        m = Monitor(self, device)
        self._wire(m)
        return m

    def _new_bank(self, config: BankConfig) -> Bank:
        b = Bank(self, config)
        self._wire(b)
        return b

    def _sort_banks(self) -> None:
        """Banks in letter order, like drives (A next to the tray)."""
        self.banks.sort(key=lambda b: b.config.letter)

    @property
    def views(self) -> list[View]:
        """Everything with its own strip / widget: banks first (the first one
        sits next to the tray), then every BMS."""
        return [*self.banks, *self.monitors]

    def label(self, v: View) -> str:
        """Banks have the user's letter, BMS are numbered as in the settings list."""
        if isinstance(v, Bank):
            return v.config.letter
        return str(self.monitors.index(v) + 1)

    def bank_of(self, m: Monitor) -> Bank | None:
        address = (m.address or "").upper()
        return next((b for b in getattr(self, "banks", ()) if address in b.config.members), None)

    @property
    def mon(self) -> View:
        """The view the dashboard shows (a BMS or a bank)."""
        views = self.views
        return views[min(self.active, len(views) - 1)]

    # Shortcuts to the active monitor (single-BMS code paths and tests).
    compact = property(lambda self: self.mon.compact)
    strip = property(lambda self: self.mon.strip)
    source = property(lambda self: self.mon.source)
    history = property(lambda self: self.mon.history)
    tracker = property(lambda self: self.mon.tracker)
    notifier = property(lambda self: self.mon.notifier)
    cell = property(lambda self: self.mon.cell)
    device_name = property(lambda self: self.mon.device_name)

    def set_source(self, source: DataSource) -> None:
        self.mon.set_source(source)

    def snapshot(self) -> Snapshot:
        return self.mon.snapshot()

    def set_active(self, index: int) -> None:
        if not 0 <= index < len(self.views) or index == self.active:
            return
        self.active = index
        self.dashboard.set_history(self.mon.history)
        self._update_dashboard_list()
        self.render()

    def _update_dashboard_list(self) -> None:
        views = self.views
        names = [v.device_name or v.address or strings.BMS_NOT_SET for v in views]
        self.dashboard.set_monitors(names, self.active, [v.visible for v in views],
                                    [self.label(v) for v in views])

    def _set_active_view(self, view: View | None) -> None:
        """Keep showing `view` after the list changed (else the first one)."""
        views = self.views
        self.active = views.index(view) if view in views else 0
        self.dashboard.set_history(self.mon.history)
        self._update_dashboard_list()

    def save_devices(self) -> None:
        if self.replay:
            return
        self.settings.set_devices([m.device for m in self.monitors if m.device is not None])
        self.save_settings()
        self._update_dashboard_list()

    # ----- startup ----------------------------------------------------------------
    def start(self, autostart: bool = False) -> None:
        """Show the views and connect (or ask which BMS to use).

        autostart: started by Windows at logon - show only the compact
        widgets / taskbar strips, never the big dashboard.
        """
        self._restore_positions()
        self.apply_display_mode()
        if self.settings.expanded and not autostart:
            self.expand()
        if not self.replay:
            for m in self.monitors:
                if m.device is not None and m.source is None:
                    m.set_source(m.make_ble_source())
            if self.monitors[0].device is None:
                QTimer.singleShot(300, self.pick_bms)  # first run: choose a BMS
        self.render()

    # ----- rendering --------------------------------------------------------------
    def render(self) -> None:
        mono = time.monotonic()
        snaps = []
        active = self.mon
        for v in self.views:
            snap = v.snapshot()
            snaps.append(snap)
            if self.settings.notify_enabled and not self.replay:
                if isinstance(v, Bank):
                    kinds = BANK_EVENTS
                else:
                    kinds = MEMBER_EVENTS if self.bank_of(v) is not None else None
                for event in v.notifier.update(snap, mono):
                    if kinds is None or event.kind in kinds:
                        self._toast(event, snap)
            v.compact.update_view(snap)
            v.strip.update_view(snap)
            if v is active and self.dashboard.isVisible():
                self.dashboard.update_view(snap)
        # The tooltip lists banks and BMS outside banks (members are in their bank).
        listed = [s for v, s in zip(self.views, snaps)
                  if isinstance(v, Bank) or self.bank_of(v) is None]
        self._update_tray(snaps, listed)

    def _update_tray(self, snaps: list[Snapshot], listed: list[Snapshot] | None = None) -> None:
        if self.tray is None:
            return
        main = snaps[0]
        cell = main.cell
        faults = any(s.fault_alarms for s in snaps)
        key = (None if cell is None else cell.soc, main.stale, faults, main.low_soc)
        if key != self._tray_key:
            self._tray_key = key
            color = theme.GREY if (main.stale or cell is None) else theme.soc_color(cell.soc, main.low_soc)
            self.tray.setIcon(icons.battery_level_icon(
                None if cell is None else cell.soc, color, faults))
        lines = []
        listed = snaps if listed is None else listed
        for snap in listed:
            name = snap.device_name or strings.APP_TITLE
            c = snap.cell
            if c is None or snap.stale:
                lines.append(f"{name}: {strings.STATUS_TEXT.get(snap.status, snap.status)}")
            elif snap.partial:
                lines.append(f"{name}: {c.soc}% · " + strings.BANK_PARTIAL.format(
                    n=len(snap.offline), total=snap.members))
            elif len(listed) == 1:
                power, unit = strings.fmt_power(c.power)
                lines += [name, f"SOC {c.soc}% · {strings.fmt_voltage(c.pack_voltage)} V",
                          f"{strings.fmt_current(c.current)} A · {power} {unit} · "
                          f"{strings.STATE_NAMES[snap.state]}"]
            else:
                lines.append(f"{name}: {c.soc}% · {strings.fmt_current(c.current)} A")
        self.tray.setToolTip("\n".join(lines)[:127])  # Windows tooltip limit

    # ----- windows ----------------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.settings.display_mode

    def apply_display_mode(self) -> None:
        taskbar = self.mode == MODE_TASKBAR
        hide_widgets = taskbar or self.settings.compact_hidden or self.dashboard.isVisible()
        views = self.views
        several = len(views) > 1
        slot = 0
        for v in views:
            # Numbers match the settings list (owner: several strips must be numbered);
            # banks are lettered.
            number = self.label(v) if several else None
            v.strip.set_number(number)
            v.compact.set_number(number)
            v.strip.slot = slot  # visible strips side by side, the first one next to the tray
            v.strip.set_wanted(taskbar and v.visible)
            v.compact.setVisible(not hide_widgets and v.visible)
            slot += v.visible

    def set_display_mode(self, mode: str) -> None:
        if mode == MODE_TASKBAR and not self._taskbar_supported():
            self._notify(strings.TASKBAR_UNSUPPORTED)
            mode = MODE_WIDGET
        self.settings.display_mode = mode
        if mode == MODE_WIDGET:
            self.settings.compact_hidden = False
        self.save_settings()
        self.apply_display_mode()

    def _taskbar_supported(self) -> bool:
        info = win_taskbar.taskbar_info()
        dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        return info is not None and win_taskbar.strip_geometry(info, dpr, STRIP_WIDTH, None) is not None

    def expand(self, monitor: View | None = None) -> None:
        if monitor is not None:
            self.set_active(self.views.index(monitor))
        if not self.dashboard.property("placed"):
            screen = QGuiApplication.primaryScreen().availableGeometry()
            geo = self.dashboard.frameGeometry()
            geo.moveCenter(screen.center())
            self.dashboard.move(geo.topLeft())
            self.dashboard.setProperty("placed", True)
        for v in self.views:
            v.compact.hide()
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()
        self.render()

    def collapse(self) -> None:
        self.dashboard.hide()
        self.apply_display_mode()

    def toggle_dashboard(self, monitor: View | None = None) -> None:
        if self.dashboard.isVisible() and (monitor is None or monitor is self.mon):
            self.collapse()
        else:
            self.expand(monitor)

    def toggle_widget_hidden(self) -> None:
        self.settings.compact_hidden = not self.settings.compact_hidden
        self.save_settings()
        self.apply_display_mode()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_dashboard()

    def _on_strip_moved(self, offset: int) -> None:
        """One strip was dragged: the whole group moves with it."""
        self.settings.taskbar_offset = offset
        for v in self.views:
            v.strip.offset = offset
            v.strip.reposition()
        self.save_settings()

    @staticmethod
    def _on_screen(rect: QRect) -> bool:
        return QGuiApplication.screenAt(rect.center()) is not None

    def _restore_positions(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        y = screen.top() + 24
        for v in self.views:
            w = v.compact
            w.adjustSize()
            if isinstance(v, Bank):
                pos = v.config.compact_pos
            else:
                pos = v.device.compact_pos if v.device else self.settings.compact_pos
            if pos and self._on_screen(QRect(pos[0], pos[1], w.width(), w.height())):
                w.move(*pos)
            else:  # default: top-right corner of the primary screen, stacked
                w.move(screen.right() - w.width() - 24, y)
            y += w.height() + 12
        geo = self.settings.dashboard_geometry
        if geo and self._on_screen(QRect(*geo)):
            self.dashboard.setGeometry(*geo)
            self.dashboard.setProperty("placed", True)

    def _remember_positions(self) -> None:
        if QGuiApplication.platformName() != "windows":
            return  # offscreen test run: its virtual-screen positions are meaningless
        for m in self.monitors:
            if m.device is not None:
                m.device.compact_pos = [m.compact.x(), m.compact.y()]
        if self.monitors[0].device is None:
            self.settings.compact_pos = [self.compact.x(), self.compact.y()]
        else:
            self.settings.set_devices([m.device for m in self.monitors if m.device])
        for b in self.banks:
            b.config.compact_pos = [b.compact.x(), b.compact.y()]
        self.settings.set_banks([b.config for b in self.banks])
        if self.dashboard.property("placed"):
            g = self.dashboard.geometry()
            self.settings.dashboard_geometry = [g.x(), g.y(), g.width(), g.height()]
        self.settings.expanded = self.dashboard.isVisible()

    # ----- menu (tray, widgets, strips and dashboard share it) ------------------
    def show_menu(self, pos: QPoint, monitor: View | None = None) -> None:
        # Right-click on a strip / widget: the menu starts with that BMS's items.
        self._menu_monitor = monitor
        self.menu.popup(pos)  # aboutToShow fills it

    def populate_menu(self) -> None:
        m = self.menu
        for sub in m.findChildren(QMenu):
            sub.deleteLater()
        m.clear()

        def add(text, slot, checked=None, enabled=True, tip=None, menu=m):
            act = QAction(text, menu)
            if checked is not None:
                act.setCheckable(True)
                act.setChecked(checked)
            act.setEnabled(enabled)
            if tip:
                act.setToolTip(tip)
            act.triggered.connect(lambda _c=False: slot())
            menu.addAction(act)
            return act

        target = getattr(self, "_menu_monitor", None)
        self._menu_monitor = None
        is_bank = isinstance(target, Bank) and target in self.banks
        if is_bank or (target in self.monitors and target.device is not None):
            vi = self.views.index(target)
            title = add(f"{self.label(target)}. {target.device_name or target.address}",
                        lambda: None, enabled=False)
            title.setFont(QFont(theme.FONT_FAMILY, 9, QFont.Bold))
            add(strings.MENU_HIDE_BMS, lambda vi=vi: self.set_view_visible(vi, False))
            if is_bank:
                add(strings.MENU_REMOVE_BANK, lambda b=target: self.remove_bank(self.banks.index(b)),
                    enabled=not self.replay)
            else:
                add(strings.MENU_REMOVE_BMS, lambda i=self.monitors.index(target): self.remove_bms(i),
                    enabled=len(self.monitors) > 1 and not self.replay)
            m.addSeparator()

        if self.update is not None:  # newer release found: offer the download page
            act = add(strings.MENU_UPDATE.format(version=self.update.version), self.open_update_page)
            act.setFont(QFont(theme.FONT_FAMILY, 9, QFont.Bold))
            m.addSeparator()
        add(strings.MENU_SETTINGS, self.open_settings)
        add(strings.MENU_HIDE_DASHBOARD if self.dashboard.isVisible() else strings.MENU_SHOW_DASHBOARD,
            self.toggle_dashboard)
        if self.mode == MODE_WIDGET:
            add(strings.MENU_SHOW_WIDGET if self.settings.compact_hidden else strings.MENU_HIDE_WIDGET,
                self.toggle_widget_hidden)

        modes = QMenu(strings.MENU_DISPLAY_MODE, m)
        group = QActionGroup(modes)
        for mode, text in ((MODE_WIDGET, strings.MODE_WIDGET), (MODE_TASKBAR, strings.MODE_TASKBAR)):
            act = add(text, lambda md=mode: self.set_display_mode(md), checked=self.mode == mode, menu=modes)
            group.addAction(act)
        m.addMenu(modes)
        m.addSeparator()

        running = any(mon.running for mon in self.monitors)
        add(strings.MENU_DISCONNECT if running else strings.MENU_CONNECT, self.toggle_all_connections)
        add(strings.MENU_ADD_BMS if self.monitors[0].device else strings.MENU_PICK_BMS,
            self.add_bms if self.monitors[0].device else self.pick_bms, enabled=not self.replay)
        if len(self.views) > 1:  # show / hide each BMS / bank (also brings hidden ones back)
            shown = QMenu(strings.MENU_SHOWN_BMS, m)
            for vi, v in enumerate(self.views):
                add(f"{self.label(v)}. {v.device_name or v.address}",
                    lambda vi=vi, v=v: self.set_view_visible(vi, not v.visible),
                    checked=v.visible, menu=shown)
            m.addMenu(shown)
        add(strings.MENU_DIAGNOSTICS, self.open_diagnostics, enabled=not self.replay)
        add(strings.MENU_EXPORT_CSV, self.export_csv)

        scales = QMenu(strings.MENU_SCALE, m)
        sgroup = QActionGroup(scales)
        for s in SCALES:
            act = add(f"{s * 100:.0f}%", lambda sc=s: self.set_scale(sc),
                      checked=abs(self.settings.ui_scale - s) < 0.01, menu=scales)
            sgroup.addAction(act)
        m.addMenu(scales)
        add(strings.MENU_AUTOSTART, self.toggle_autostart, checked=autostart.is_enabled(),
            enabled=autostart.available(),
            tip=None if autostart.available() else strings.TIP_AUTOSTART_DEV)
        add(strings.MENU_SETTINGS_FOLDER, self.open_data_folder)
        m.addSeparator()
        add(strings.MENU_EXIT, self.quit)

    def device_rows(self) -> list[tuple[str, str, bool]]:
        """(name, 'brand · address', visible) per configured BMS, for the settings list."""
        rows = []
        for m in self.monitors:
            if m.device is not None:
                brand = drivers.get(m.device.driver).name
                detail = f"{brand} · {m.device.address}"
                bank = self.bank_of(m)
                if bank is not None:
                    detail += " · " + strings.BANK_MEMBER_OF.format(label=self.label(bank))
                rows.append((m.device_name or m.device.name or "—", detail, m.device.visible))
        return rows

    def bank_rows(self) -> list[tuple[str, str, str, bool]]:
        """(letter, name, members text, visible) per bank, for the settings list."""
        rows = []
        for b in self.banks:
            names = ", ".join(m.device_name or m.address for m in b.members)
            detail = strings.BANK_MEMBERS_DETAIL.format(n=len(b.members), names=names)
            rows.append((self.label(b), b.device_name,
                         f"{strings.BANK_KIND_NAMES[b.config.kind]} · {detail}", b.visible))
        return rows

    def set_view_visible(self, index: int, visible: bool) -> None:
        """Selector / menu eye: index into self.views (banks first)."""
        views = self.views
        if not 0 <= index < len(views):
            return
        v = views[index]
        if isinstance(v, Bank):
            v.config.visible = visible
            self.save_banks()
            self.apply_display_mode()
        else:
            self.set_visible(self.monitors.index(v), visible)

    def save_banks(self) -> None:
        if self.replay:
            return
        self.settings.set_banks([b.config for b in self.banks])
        self.save_settings()
        self._update_dashboard_list()

    # ----- banks (several BMS in parallel = one battery) -----------------------------
    def _bank_candidates(self, bank: Bank | None) -> list[tuple[str, str, bool]]:
        """(address, label, checked) of BMS that may join `bank` (not in another bank)."""
        out = []
        for i, m in enumerate(self.monitors):
            if m.address is None:
                continue
            other = self.bank_of(m)
            if other is not None and other is not bank:
                continue
            out.append((m.address.upper(), f"{i + 1}. {m.device_name or m.address}",
                        bank is not None and other is bank))
        return out

    def edit_bank(self, index: int | None = None, parent=None) -> None:
        """Create a bank (index None) or change one: name and member BMS."""
        from .ui.bank_dialog import BankDialog

        if self.replay:
            return
        bank = self.banks[index] if index is not None and 0 <= index < len(self.banks) else None
        candidates = self._bank_candidates(bank)
        if len(candidates) < 2:
            self._notify(strings.BANK_NEED_TWO)
            return
        taken = [b.config.letter for b in self.banks if b is not bank]
        letter = bank.config.letter if bank else free_letter(taken)
        name = bank.config.name if bank else ""
        kind = bank.config.kind if bank else "parallel"
        dlg = BankDialog(name, candidates, letter, taken, kind, parent)
        if dlg.exec() != QDialog.Accepted:
            return
        self.apply_bank(bank, dlg.name(), dlg.members(), dlg.letter(), dlg.kind())

    def apply_bank(self, bank: "Bank | None", name: str, members: list[str],
                   letter: str | None = None, kind: str = "parallel") -> "Bank":
        """Store a new / changed bank (the editor's result; tests call it directly).

        name "" = default name with the letter; letter None = first free one."""
        shown = self.mon
        taken = [b.config.letter for b in self.banks if b is not bank]
        if letter is None or letter in taken:
            letter = bank.config.letter if bank and bank.config.letter not in taken else free_letter(taken)
        if bank is None:
            bank = self._new_bank(BankConfig(uuid.uuid4().hex[:8], name, members,
                                             letter=letter, kind=kind))
            self.banks.append(bank)
            # Owner's choice: one strip per bank; its BMS can be shown again by their eye.
            for m in bank.members:
                m.device.visible = False
            log.info("bank created: %s %s", bank.config.id, members)
        else:
            for m in bank.members:  # BMS taken out of the bank get their own strip back
                if m.address.upper() not in members:
                    m.device.visible = True
            bank.config.name, bank.config.members = name, members
            bank.config.letter, bank.config.kind = letter, kind
            log.info("bank changed: %s %s %s %s", bank.config.id, letter, kind, members)
        self._sort_banks()
        self.save_devices()
        self.save_banks()
        self._set_active_view(shown)
        self._restore_positions()
        self.apply_display_mode()
        self.render()
        return bank

    def remove_bank(self, index: int) -> None:
        """Ungroup a bank: its BMS show their own strips again (its history stays)."""
        if not 0 <= index < len(self.banks):
            return
        shown = self.mon
        b = self.banks.pop(index)
        log.info("bank removed: %s", b.config.id)
        b.save_history()
        for m in b.members:
            m.device.visible = True
        b.close_views()
        self._dimmed.clear()
        self.save_devices()
        self.save_banks()
        self._set_active_view(shown)
        self.apply_display_mode()
        self.render()

    def set_visible(self, index: int, visible: bool) -> None:
        """Show / hide one BMS's strip and widget; its data keeps being recorded."""
        if not 0 <= index < len(self.monitors) or self.monitors[index].device is None:
            return
        self.monitors[index].device.visible = visible
        self.save_devices()
        self.apply_display_mode()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, autostart.is_enabled(), autostart.available(),
                             replay=self.replay, devices=self.device_rows(),
                             banks=self.bank_rows())

        def refresh() -> None:
            dlg.set_devices(self.device_rows())

        def change(index: int) -> None:
            self.set_active(self.views.index(self.monitors[index]))
            self.pick_bms(self.monitors[index])
            refresh()

        def refresh_banks() -> None:
            dlg.set_banks(self.bank_rows())
            refresh()

        def mode(m: str) -> None:
            self.set_display_mode(m)
            dlg.set_mode(self.settings.display_mode)  # may have fallen back to widget

        dlg.add_requested.connect(lambda: (self.add_bms(), refresh()))
        dlg.change_requested.connect(change)
        dlg.remove_requested.connect(lambda i: (self.remove_bms(i), refresh()))
        dlg.visibility_changed.connect(self.set_visible)
        dlg.bank_add_requested.connect(lambda: (self.edit_bank(None, dlg), refresh_banks()))
        dlg.bank_edit_requested.connect(lambda i: (self.edit_bank(i, dlg), refresh_banks()))
        dlg.bank_remove_requested.connect(lambda i: (self.remove_bank(i), refresh_banks()))
        # Banks come first in self.views, so a bank index is also its view index.
        dlg.bank_visibility_changed.connect(self.set_view_visible)
        dlg.mode_changed.connect(mode)
        dlg.scale_changed.connect(lambda s: self.set_scale(s, restart=False))
        dlg.language_changed.connect(self.set_language)
        dlg.threshold_changed.connect(self.set_idle_threshold)
        dlg.fullscreen_changed.connect(self.set_fullscreen_behavior)
        dlg.dim_changed.connect(self.set_dim_when_maximized)
        dlg.desktop_changed.connect(self.set_widgets_on_desktop)
        dlg.updates_changed.connect(self.set_check_updates)
        dlg.update_check_requested.connect(lambda: self.updater.check(manual=True))
        dlg.autostart_changed.connect(self.set_autostart)
        dlg.open_folder.connect(self.open_data_folder)
        dlg.diagnostics_requested.connect(self.open_diagnostics)
        dlg.export_requested.connect(self.export_csv)
        dlg.notify_changed.connect(self.set_notify)
        dlg.low_soc_changed.connect(self.set_low_soc)
        before = (self.settings.ui_scale, self.settings.language)
        dlg.exec()
        # Scale and language need new windows: restart once, when the user is
        # done with the settings (not on every combo box change).
        if (self.settings.ui_scale, self.settings.language) != before:
            self.restart()

    def open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_dir())))

    def set_idle_threshold(self, value: float) -> None:
        self.settings.idle_threshold = value
        for v in self.views:
            v.tracker.idle_threshold = value
        self.dashboard.set_idle_threshold(value)
        self.save_settings()
        self.render()

    def update_dimming(self) -> None:
        own = {native_hwnd(w) for w in QApplication.topLevelWidgets() if w.isVisible()}
        dim = self.settings.dim_when_maximized and win_taskbar.foreground_is_maximized(own)
        # A maximized window ends above the taskbar, so a strip on the taskbar
        # never covers it: only dim strips in their corner position (owner's
        # report 2026-11-14: the strip greyed out for no reason).
        wanted: dict[QWidget, bool] = {}
        for v in self.views:
            # A widget on the desktop is under the maximized window anyway.
            wanted[v.compact] = dim and not self.settings.widgets_on_desktop
            wanted[v.strip] = dim and v.strip.in_corner
        if wanted != self._dimmed:
            self._dimmed = wanted
            for window, state in wanted.items():
                set_dimmed(window, state)

    def set_widgets_on_desktop(self, enabled: bool) -> None:
        """Floating widgets: always on top, or pinned to the desktop."""
        self.settings.widgets_on_desktop = enabled
        self.save_settings()
        self._dimmed.clear()
        for v in self.views:
            set_dimmed(v.compact, False)
            v.compact.set_on_desktop(enabled)
        self.update_dimming()

    def set_dim_when_maximized(self, enabled: bool) -> None:
        self.settings.dim_when_maximized = enabled
        self.save_settings()
        self.update_dimming()

    def set_fullscreen_behavior(self, behavior: str) -> None:
        self.settings.fullscreen_behavior = behavior
        for v in self.views:
            v.strip.fullscreen_behavior = behavior
            v.strip.reposition()
        self.save_settings()

    def set_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError:
            log.exception("autostart change failed")

    # ----- user actions -----------------------------------------------------------
    def show_alarms(self, monitor: View | None = None) -> None:
        snap = (monitor or self.mon).snapshot()
        alarms = snap.cell.alarms if snap.cell else ()
        parent = self.dashboard if self.dashboard.isVisible() else None
        AlarmDialog(alarms, snap.stale and snap.cell is not None, parent).exec()

    def toggle_connection(self) -> None:
        """Connect / disconnect the BMS (or every BMS of the bank) in the dashboard."""
        m = self.mon
        if isinstance(m, Bank):
            members = m.members
            if any(x.running for x in members):
                for x in members:
                    if x.running:
                        x.source.stop()
            else:
                for x in members:
                    if x.source is not None:
                        x.source.start()
                    elif not self.replay:
                        x.set_source(x.make_ble_source())
            return
        if m.source is None:
            self.pick_bms()
        elif m.source.running:
            m.source.stop()  # thread reports "stopped" when the link is closed
        else:
            m.source.start()

    def toggle_all_connections(self) -> None:
        """Menu: disconnect every BMS (frees them for the phone app) or reconnect all."""
        if any(m.running for m in self.monitors):
            for m in self.monitors:
                if m.running:
                    m.source.stop()
        else:
            for m in self.monitors:
                if m.source is not None:
                    m.source.start()
                elif m.device is not None and not self.replay:
                    m.set_source(m.make_ble_source())
            if self.monitors[0].device is None:
                self.pick_bms()

    def _monitored(self, address: str, besides: Monitor | None = None) -> bool:
        return any(m.address and m.address.upper() == address.upper() and m is not besides
                   for m in self.monitors)

    def _pick(self, current: Monitor | None) -> object | None:
        """Run the BMS picker; stops `current`'s link while scanning."""
        was_running = current is not None and current.running
        if was_running:
            current.source.stop(wait_s=3.0)  # a connected BMS does not advertise
        d = current.device if current is not None else None
        dlg = BmsPickerDialog(d.address if d else None, d.name if d else "",
                              d.driver if d else None, scan_delay_ms=2000 if was_running else 0)
        picked = dlg.selected if dlg.exec() == QDialog.Accepted else None
        if picked is None and was_running:
            current.source.start()
        return picked

    def pick_bms(self, m: Monitor | None = None) -> None:
        """Choose (or replace) a BMS (default: the one in the dashboard)."""
        if self.replay:
            return
        if m is None:
            m = self.mon if isinstance(self.mon, Monitor) else self.monitors[0]
        r = self._pick(m)
        if r is None:
            self.render()
            return
        if self._monitored(r.address, besides=m):
            self._notify(strings.BMS_ALREADY)
            if m.source is not None:
                m.source.start()
            return
        changed = r.address != m.address
        bank = self.bank_of(m)
        if changed and bank is not None:  # the new BMS takes the old one's place in its bank
            old = (m.address or "").upper()
            bank.config.members = [r.address.upper() if a == old else a for a in bank.config.members]
            self.save_banks()
        if changed:
            log.info("BMS selected: %s %r (%s)", r.address, r.name, r.driver_id)
            m.save_history()  # keep the old BMS's open bucket
            m.reset_state()
        old_pos = m.device.compact_pos if m.device else self.settings.compact_pos
        old_visible = m.device.visible if m.device else True
        # Unknown device picked via "show all": try the default driver.
        m.device = Device(r.address, r.name, drivers.get(r.driver_id).id, None, old_pos,
                          old_visible)
        m.device_name = r.name
        self.save_devices()
        if changed:
            m.load_history()  # that BMS's own week of history
            if m is self.mon:
                self.dashboard.set_history(m.history)
        m.set_source(m.make_ble_source())
        self.render()

    def add_bms(self) -> None:
        """Monitor one more BMS (its own strip / widget)."""
        if self.replay:
            return
        if self.monitors[0].device is None:
            self.pick_bms()
            return
        r = self._pick(None)
        if r is None:
            return
        if self._monitored(r.address):
            self._notify(strings.BMS_ALREADY)
            return
        log.info("BMS added: %s %r (%s)", r.address, r.name, r.driver_id)
        m = self._new_monitor(Device(r.address, r.name, drivers.get(r.driver_id).id))
        self.monitors.append(m)
        self.save_devices()
        self._restore_positions()
        self.apply_display_mode()
        m.set_source(m.make_ble_source())
        self.render()

    def remove_bms(self, index: int) -> None:
        """Stop monitoring one BMS (its history stays in the database)."""
        if len(self.monitors) < 2 or not 0 <= index < len(self.monitors):
            return
        shown = self.mon
        bank = self.bank_of(self.monitors[index])
        m = self.monitors.pop(index)
        log.info("BMS removed: %s", m.address)
        m.save_history()
        if m.source is not None:
            m.source.stop(wait_s=3.0)
        m.close_views()
        self._dimmed.clear()
        if bank is not None:
            address = (m.address or "").upper()
            bank.config.members = [a for a in bank.config.members if a != address]
            if len(bank.config.members) < 2:  # one BMS left: no bank any more
                self.banks.remove(bank)
                bank.save_history()
                for x in bank.members:
                    x.device.visible = True
                bank.close_views()
            self.save_banks()
        self._set_active_view(shown)
        self.save_devices()
        self.apply_display_mode()
        self.render()

    def export_csv(self) -> None:
        """Save the dashboard BMS's history (up to 7 days, 10 s rows) as CSV."""
        from datetime import datetime

        from PySide6.QtCore import QStandardPaths
        from PySide6.QtWidgets import QFileDialog

        from .state import history_csv

        points = self.history.series(self.history.max_age_s, time.time())
        if not points:
            self._notify(strings.EXPORT_EMPTY)
            return
        docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())
        name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in (self.device_name or "bms"))
        default = Path(docs) / DOCUMENTS_DIR_NAME / f"history-{name}-{datetime.now():%Y%m%d-%H%M}.csv"
        default.parent.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(None, strings.EXPORT_TITLE, str(default), "CSV (*.csv)")
        if not path:
            return
        try:
            Path(path).write_text(history_csv(points), encoding="utf-8")
        except OSError as exc:
            log.exception("CSV export failed")
            self._notify(str(exc))
            return
        log.info("history exported: %s (%d rows)", path, len(points))
        self._notify(strings.EXPORT_DONE.format(path=path, n=len(points)))

    def open_diagnostics(self) -> None:
        """Record a shareable capture of any BMS (community support for new brands)."""
        if self.replay:
            return
        running = [m for m in self.monitors if m.running]
        for m in running:
            m.source.stop(wait_s=3.0)  # a connected BMS neither advertises nor answers
        DiagnosticsDialog(scan_delay_ms=2000 if running else 0).exec()
        for m in running:
            m.source.start()
        self.render()

    def set_scale(self, scale: float, restart: bool = True) -> None:
        """Qt applies a scale factor only at startup, so restart the app."""
        changed = abs(scale - self.settings.ui_scale) > 0.001
        self.settings.ui_scale = scale
        self.save_settings()
        if restart and changed:
            self.restart()

    def set_language(self, lang: str) -> None:
        """Saved now; open_settings restarts the app when the dialog closes."""
        self.settings.language = lang
        self.save_settings()

    def restart(self) -> None:
        """Quit and let run_widget start a fresh copy (about a second)."""
        log.info("restart (scale=%s language=%s)", self.settings.ui_scale, self.settings.language)
        self.restart_pending = True
        self.quit()

    # ----- updates (read-only: tell the user, open the release page) ---------------
    def _auto_update_check(self) -> None:
        if self.settings.check_updates:
            self.updater.check()

    def _on_update_result(self, release, manual: bool) -> None:
        if release is None:
            log.info("update check failed")
            if manual:
                self._notify(strings.UPDATE_FAILED)
            return
        if not updates.is_newer(release.version):
            self.update = None
            if manual:
                self._notify(strings.UPDATE_NONE.format(version=release.version))
            return
        log.info("update available: %s", release.version)
        self.update = release
        if manual or self.settings.update_notified != release.version:
            self.settings.update_notified = release.version  # one balloon per version
            self.save_settings()
            if self.tray is not None:
                self._update_balloon = True
                self.tray.showMessage(strings.APP_TITLE,
                                      strings.UPDATE_AVAILABLE.format(version=release.version),
                                      QSystemTrayIcon.Information, 15000)
            else:
                self._notify(strings.UPDATE_AVAILABLE.format(version=release.version))

    def _on_balloon_clicked(self) -> None:
        if self._update_balloon:
            self.open_update_page()

    def open_update_page(self) -> None:
        url = self.update.url if self.update is not None else updates.RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(url))

    def set_check_updates(self, enabled: bool) -> None:
        self.settings.check_updates = enabled
        self.save_settings()

    def toggle_autostart(self) -> None:
        self.set_autostart(not autostart.is_enabled())

    def set_notify(self, enabled: bool) -> None:
        self.settings.notify_enabled = enabled
        self.save_settings()

    def set_low_soc(self, percent: int) -> None:
        self.settings.low_soc_threshold = percent
        for v in self.views:
            v.notifier.low_soc = percent
        self.save_settings()
        self.render()  # strips / widgets turn red at once

    def _toast(self, event, snap: Snapshot) -> None:
        """Windows notification (tray balloon). Never a modal box: it must not
        block the app while nobody is at the PC."""
        if event.kind == LOW_SOC:
            text = strings.NOTIFY_LOW_SOC.format(soc=event.soc)
        elif event.kind == FULL:
            text = strings.NOTIFY_FULL
        elif event.kind == ALARM:
            text = strings.NOTIFY_ALARM.format(names=", ".join(strings.alarm_text(a) for a in event.alarms))
        elif event.kind == LOST:
            text = strings.NOTIFY_LOST
        else:
            return
        log.info("notification %s %s: %s", snap.device_name, event.kind, text)
        if self.tray is not None:
            self._update_balloon = False
            icon = QSystemTrayIcon.Information if event.kind == FULL else QSystemTrayIcon.Warning
            self.tray.showMessage(snap.device_name or strings.APP_TITLE, text, icon, 10000)

    def _notify(self, text: str) -> None:
        if self.tray is not None:
            self._update_balloon = False
            self.tray.showMessage(strings.APP_TITLE, text)
        else:
            QMessageBox.information(None, strings.APP_TITLE, text)

    # ----- persistence / exit -----------------------------------------------------
    def save_settings(self) -> None:
        if self.settings_path is None:
            return
        try:
            self.settings.save(self.settings_path)
        except OSError:
            log.exception("cannot save settings")

    # History: 10 s buckets are written to SQLite as soon as they close, one
    # series per BMS (MAC), kept for 7 days. In replay mode nothing is stored.
    def _open_store(self) -> None:
        self.store = None
        if self.history_path is None or self.replay:
            return
        try:
            self.store = HistoryStore(self.history_path)
            self.store.prune(time.time())
        except sqlite3.Error:
            log.exception("cannot open history database")
            self.store = None

    def _import_legacy_history(self) -> None:
        """One-time import of the old 24 h history.json (main BMS only)."""
        if self.store is None or not self.settings.address:
            return
        legacy = self.history_path.with_name("history.json")
        if not legacy.exists():
            return
        now = time.time()
        tmp = History()
        try:
            tmp.load_json(legacy.read_text(encoding="utf-8"), now)
            self.store.add_many(self.settings.address, tmp.series(tmp.max_age_s, now))
            legacy.unlink()
        except (OSError, sqlite3.Error):
            log.exception("history.json import failed")

    def save_history(self) -> None:
        for v in self.views:
            v.save_history()

    def prune_history(self) -> None:
        if self.store is not None:
            try:
                self.store.prune(time.time())
            except sqlite3.Error:
                log.exception("history prune failed")

    def shutdown(self) -> None:
        """Save state and disconnect cleanly (idempotent)."""
        if self._shut_down:
            return
        self._shut_down = True
        self._remember_positions()
        self.save_settings()
        self.save_history()
        if self.store is not None:
            self.store.close()
            self.store = None
        for m in self.monitors:
            if m.source is not None:
                m.source.stop()  # ask all at once, then wait for each
        for m in self.monitors:
            if m.source is not None:
                m.source.stop(wait_s=3.0)  # frees the BMS for the phone app
        if self.tray is not None:
            self.tray.hide()
        log.info("exit")

    def quit(self) -> None:
        self.shutdown()
        QApplication.quit()


def setup_logging(path: Path) -> None:
    root = logging.getLogger("jkbms_widget")
    if root.handlers:
        return
    handler = RotatingFileHandler(path, maxBytes=256_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    def excepthook(exc_type, exc, tb):
        root.error("unhandled exception", exc_info=(exc_type, exc, tb))
        if sys.stderr is not None:  # None in the windowed .exe
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook


def run_widget(
    address: str | None = None,
    replay: str | None = None,
    speed: float = 1.0,
    driver_id: str | None = None,
    options: dict | None = None,
    idle_threshold: float | None = None,
    exit_after: float | None = None,
    autostart_launch: bool = False,
) -> int:
    data = app_dir()
    settings_path = data / "settings.json"
    settings = Settings.load(settings_path)
    if address:
        settings.address = address.upper()
        if driver_id:
            settings.driver = driver_id
    if idle_threshold is not None:
        settings.idle_threshold = idle_threshold
    # Scale must be set before QApplication exists.
    own_scale_env = "QT_SCALE_FACTOR" not in os.environ  # not set by the user/tests
    if abs(settings.ui_scale - 1.0) > 0.01 and own_scale_env:
        os.environ["QT_SCALE_FACTOR"] = f"{settings.ui_scale:g}"
    # Language must be set before any window is built (views read strings once).
    system_lang = strings.system_language()
    strings.set_language(strings.resolve_language(settings.language, system_lang))

    app = QApplication.instance() or QApplication(sys.argv)
    setup_logging(data / "widget.log")
    log.info("start (address=%s replay=%s frozen=%s autostart=%s lang=%s/%s)", settings.address,
             bool(replay), getattr(sys, "frozen", False), autostart_launch,
             strings.language, system_lang)

    # One instance only: two copies would fight over the single BLE connection.
    lock = QLockFile(str(data / "widget.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, strings.APP_TITLE, strings.ALREADY_RUNNING)
        return 1

    app.setQuitOnLastWindowClosed(False)  # windows hide/show; exit via menu
    app.setFont(QFont(theme.FONT_FAMILY, 10))
    theme.apply_style(app)  # Fusion + dark palette (consistent, no native hover lag)
    app.setWindowIcon(icons.battery_level_icon(80, theme.GREEN))

    ctl = Controller(settings, settings_path, data / "history.sqlite", replay=bool(replay),
                     options=options or None)
    if replay:
        from .capture import capture_driver_id

        ctl.set_source(ReplaySource(replay, speed, drivers.get(driver_id or capture_driver_id(replay)),
                                    options or {}))
    elif address:
        settings.address = address.upper()
        ctl.save_settings()
    app.aboutToQuit.connect(ctl.shutdown)  # also on Windows logoff/shutdown
    try:
        autostart.upgrade_entry()
    except OSError:
        log.exception("autostart entry upgrade failed")
    ctl.start(autostart=autostart_launch)
    if exit_after:
        QTimer.singleShot(int(exit_after * 1000), ctl.quit)  # diagnostics / tests
    rc = app.exec()
    lock.unlock()  # before the new copy starts, or it would see "already running"
    if ctl.restart_pending:
        if own_scale_env:
            os.environ.pop("QT_SCALE_FACTOR", None)  # the new copy reads the new scale
        program, args = restart_command(bool(getattr(sys, "frozen", False)), sys.executable,
                                        sys.argv, getattr(sys, "orig_argv", sys.argv))
        result = QProcess.startDetached(program, args)
        if not (result[0] if isinstance(result, tuple) else result):
            log.error("restart failed: %s %s", program, args)
    return rc
