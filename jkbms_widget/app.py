"""Widget application: data source -> Controller -> views.

Views: floating compact widget OR taskbar strip (display mode), the
expandable dashboard, and the tray icon with the shared menu.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QPoint, QProcess, QRect, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from . import autostart, strings, win_taskbar
from . import drivers
from .model import CellInfo, DeviceInfo
from .notifications import ALARM, FULL, LOST, LOW_SOC, Notifier
from .settings import Device, Settings, app_dir
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


class Monitor(QObject):
    """One BMS: its data source, derived state, history and its own small
    views (floating widget + taskbar strip). The Controller owns a list of
    them (several BMS at once, owner's request 2026-11-15)."""

    def __init__(self, ctl: "Controller", device: Device | None) -> None:
        super().__init__()
        self.ctl = ctl
        self.device = device  # None until the first BMS is picked
        s = ctl.settings
        self.source: DataSource | None = None
        self.tracker = StateTracker(s.idle_threshold)
        self.notifier = Notifier(s.low_soc_threshold)
        self.history = History(on_bucket_closed=self._store_point)
        self.cell: CellInfo | None = None
        self.last_cell_at = 0.0
        self.status, self.status_detail = "stopped", ""
        self.device_name = device.name if device else ""
        self.compact = CompactWindow()
        self.strip = TaskbarStrip()
        self.strip.offset = s.taskbar_offset
        self.strip.fullscreen_behavior = s.fullscreen_behavior

    @property
    def address(self) -> str | None:
        return self.device.address if self.device else None

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

    # ----- history (10 s buckets, one SQLite series per BMS address) ----------------
    def _store_point(self, point) -> None:
        store = self.ctl.store
        if store is None or not self.address:
            return
        try:
            store.add(self.address, point)
        except sqlite3.Error:
            log.exception("cannot store history point")

    def load_history(self) -> None:
        store = self.ctl.store
        if store is None or not self.address:
            return
        now = time.time()
        try:
            self.history.extend(store.load(self.address, now - RETENTION_S), now)
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

        self.dashboard = DashboardWindow(self.mon.history)
        self.dashboard.settings_requested.connect(self.open_settings)
        self.dashboard.alarms_requested.connect(lambda: self.show_alarms())
        self.dashboard.toggle_connection.connect(self.toggle_connection)
        self.dashboard.quit_requested.connect(self.quit)
        self.dashboard.collapse_requested.connect(self.collapse)
        self.dashboard.context_menu.connect(self.show_menu)
        self.dashboard.monitor_selected.connect(self.set_active)
        self.dashboard.visibility_toggled.connect(self.set_visible)
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

    # ----- monitors -------------------------------------------------------------
    def _new_monitor(self, device: Device | None) -> Monitor:
        m = Monitor(self, device)
        m.load_history()
        m.compact.alarms_requested.connect(lambda m=m: self.show_alarms(m))
        m.compact.expand_requested.connect(lambda m=m: self.expand(m))
        m.compact.context_menu.connect(lambda pos, m=m: self.show_menu(pos, m))
        m.compact.settings_requested.connect(self.open_settings)
        m.strip.clicked.connect(lambda m=m: self.toggle_dashboard(m))
        m.strip.alarms_clicked.connect(lambda m=m: self.show_alarms(m))
        m.strip.context_menu.connect(lambda pos, m=m: self.show_menu(pos, m))
        m.strip.offset_changed.connect(self._on_strip_moved)
        return m

    @property
    def mon(self) -> Monitor:
        return self.monitors[min(self.active, len(self.monitors) - 1)]

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
        if not 0 <= index < len(self.monitors) or index == self.active:
            return
        self.active = index
        self.dashboard.set_history(self.mon.history)
        self._update_dashboard_list()
        self.render()

    def _update_dashboard_list(self) -> None:
        names = [m.device_name or m.address or strings.BMS_NOT_SET for m in self.monitors]
        self.dashboard.set_monitors(names, self.active, [m.visible for m in self.monitors])

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
        for m in self.monitors:
            snap = m.snapshot()
            snaps.append(snap)
            if self.settings.notify_enabled and not self.replay:
                for event in m.notifier.update(snap, mono):
                    self._toast(event, snap)
            m.compact.update_view(snap)
            m.strip.update_view(snap)
            if m is self.mon and self.dashboard.isVisible():
                self.dashboard.update_view(snap)
        self._update_tray(snaps)

    def _update_tray(self, snaps: list[Snapshot]) -> None:
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
        for snap in snaps:
            name = snap.device_name or strings.APP_TITLE
            c = snap.cell
            if c is None or snap.stale:
                lines.append(f"{name}: {strings.STATUS_TEXT.get(snap.status, snap.status)}")
            elif len(snaps) == 1:
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
        several = len(self.monitors) > 1
        slot = 0
        for i, m in enumerate(self.monitors):
            # Numbers match the settings list (owner: several strips must be numbered).
            number = i + 1 if several else None
            m.strip.set_number(number)
            m.compact.set_number(number)
            m.strip.slot = slot  # visible strips side by side, the main BMS next to the tray
            m.strip.set_wanted(taskbar and m.visible)
            m.compact.setVisible(not hide_widgets and m.visible)
            slot += m.visible

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

    def expand(self, monitor: Monitor | None = None) -> None:
        if monitor is not None:
            self.set_active(self.monitors.index(monitor))
        if not self.dashboard.property("placed"):
            screen = QGuiApplication.primaryScreen().availableGeometry()
            geo = self.dashboard.frameGeometry()
            geo.moveCenter(screen.center())
            self.dashboard.move(geo.topLeft())
            self.dashboard.setProperty("placed", True)
        for m in self.monitors:
            m.compact.hide()
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()
        self.render()

    def collapse(self) -> None:
        self.dashboard.hide()
        self.apply_display_mode()

    def toggle_dashboard(self, monitor: Monitor | None = None) -> None:
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
        for m in self.monitors:
            m.strip.offset = offset
            m.strip.reposition()
        self.save_settings()

    @staticmethod
    def _on_screen(rect: QRect) -> bool:
        return QGuiApplication.screenAt(rect.center()) is not None

    def _restore_positions(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        y = screen.top() + 24
        for m in self.monitors:
            w = m.compact
            w.adjustSize()
            pos = m.device.compact_pos if m.device else self.settings.compact_pos
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
        if self.dashboard.property("placed"):
            g = self.dashboard.geometry()
            self.settings.dashboard_geometry = [g.x(), g.y(), g.width(), g.height()]
        self.settings.expanded = self.dashboard.isVisible()

    # ----- menu (tray, widgets, strips and dashboard share it) ------------------
    def show_menu(self, pos: QPoint, monitor: Monitor | None = None) -> None:
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
        if target is not None and target in self.monitors and target.device is not None:
            index = self.monitors.index(target)
            title = add(f"{index + 1}. {target.device_name or target.address}", lambda: None,
                        enabled=False)
            title.setFont(QFont(theme.FONT_FAMILY, 9, QFont.Bold))
            add(strings.MENU_HIDE_BMS, lambda i=index: self.set_visible(i, False))
            add(strings.MENU_REMOVE_BMS, lambda i=index: self.remove_bms(i),
                enabled=len(self.monitors) > 1 and not self.replay)
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
        if len(self.monitors) > 1:  # show / hide each BMS (also brings hidden ones back)
            shown = QMenu(strings.MENU_SHOWN_BMS, m)
            for i, mon in enumerate(self.monitors):
                add(f"{i + 1}. {mon.device_name or mon.address}",
                    lambda i=i, mon=mon: self.set_visible(i, not mon.visible),
                    checked=mon.visible, menu=shown)
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
                rows.append((m.device_name or m.device.name or "—",
                             f"{brand} · {m.device.address}", m.device.visible))
        return rows

    def set_visible(self, index: int, visible: bool) -> None:
        """Show / hide one BMS's strip and widget; its data keeps being recorded."""
        if not 0 <= index < len(self.monitors) or self.monitors[index].device is None:
            return
        self.monitors[index].device.visible = visible
        self.save_devices()
        self.apply_display_mode()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, autostart.is_enabled(), autostart.available(),
                             replay=self.replay, devices=self.device_rows())

        def refresh() -> None:
            dlg.set_devices(self.device_rows())

        def change(index: int) -> None:
            self.set_active(index)
            self.pick_bms()
            refresh()

        def mode(m: str) -> None:
            self.set_display_mode(m)
            dlg.set_mode(self.settings.display_mode)  # may have fallen back to widget

        dlg.add_requested.connect(lambda: (self.add_bms(), refresh()))
        dlg.change_requested.connect(change)
        dlg.remove_requested.connect(lambda i: (self.remove_bms(i), refresh()))
        dlg.visibility_changed.connect(self.set_visible)
        dlg.mode_changed.connect(mode)
        dlg.scale_changed.connect(lambda s: self.set_scale(s, restart=False))
        dlg.language_changed.connect(self.set_language)
        dlg.threshold_changed.connect(self.set_idle_threshold)
        dlg.fullscreen_changed.connect(self.set_fullscreen_behavior)
        dlg.dim_changed.connect(self.set_dim_when_maximized)
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
        for m in self.monitors:
            m.tracker.idle_threshold = value
        self.save_settings()
        self.render()

    def update_dimming(self) -> None:
        own = {native_hwnd(w) for w in QApplication.topLevelWidgets() if w.isVisible()}
        dim = self.settings.dim_when_maximized and win_taskbar.foreground_is_maximized(own)
        # A maximized window ends above the taskbar, so a strip on the taskbar
        # never covers it: only dim strips in their corner position (owner's
        # report 2026-11-14: the strip greyed out for no reason).
        wanted: dict[QWidget, bool] = {}
        for m in self.monitors:
            wanted[m.compact] = dim
            wanted[m.strip] = dim and m.strip.in_corner
        if wanted != self._dimmed:
            self._dimmed = wanted
            for window, state in wanted.items():
                set_dimmed(window, state)

    def set_dim_when_maximized(self, enabled: bool) -> None:
        self.settings.dim_when_maximized = enabled
        self.save_settings()
        self.update_dimming()

    def set_fullscreen_behavior(self, behavior: str) -> None:
        self.settings.fullscreen_behavior = behavior
        for m in self.monitors:
            m.strip.fullscreen_behavior = behavior
            m.strip.reposition()
        self.save_settings()

    def set_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError:
            log.exception("autostart change failed")

    # ----- user actions -----------------------------------------------------------
    def show_alarms(self, monitor: Monitor | None = None) -> None:
        snap = (monitor or self.mon).snapshot()
        alarms = snap.cell.alarms if snap.cell else ()
        parent = self.dashboard if self.dashboard.isVisible() else None
        AlarmDialog(alarms, snap.stale and snap.cell is not None, parent).exec()

    def toggle_connection(self) -> None:
        """Connect / disconnect the BMS shown in the dashboard."""
        m = self.mon
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

    def pick_bms(self) -> None:
        """Choose (or replace) the BMS of the active monitor."""
        if self.replay:
            return
        m = self.mon
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
        if changed:
            log.info("BMS selected: %s %r (%s)", r.address, r.name, r.driver_id)
            m.save_history()  # keep the old BMS's open bucket
            m.reset_state()
        old_pos = m.device.compact_pos if m.device else self.settings.compact_pos
        # Unknown device picked via "show all": try the default driver.
        m.device = Device(r.address, r.name, drivers.get(r.driver_id).id, None, old_pos)
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
        m = self.monitors.pop(index)
        log.info("BMS removed: %s", m.address)
        m.save_history()
        if m.source is not None:
            m.source.stop(wait_s=3.0)
        m.close_views()
        self._dimmed.clear()
        if self.active >= len(self.monitors) or self.active == index:
            self.active = 0
        self.dashboard.set_history(self.mon.history)
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
        default = Path(docs) / "JK BMS Monitor" / f"history-{name}-{datetime.now():%Y%m%d-%H%M}.csv"
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

    def toggle_autostart(self) -> None:
        self.set_autostart(not autostart.is_enabled())

    def set_notify(self, enabled: bool) -> None:
        self.settings.notify_enabled = enabled
        self.save_settings()

    def set_low_soc(self, percent: int) -> None:
        self.settings.low_soc_threshold = percent
        for m in self.monitors:
            m.notifier.low_soc = percent
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
            icon = QSystemTrayIcon.Information if event.kind == FULL else QSystemTrayIcon.Warning
            self.tray.showMessage(snap.device_name or strings.APP_TITLE, text, icon, 10000)

    def _notify(self, text: str) -> None:
        if self.tray is not None:
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
        for m in self.monitors:
            m.save_history()

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
