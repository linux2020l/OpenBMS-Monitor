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
from .settings import Settings, app_dir
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


class Controller(QObject):
    """Receives data on the GUI thread, derives state, updates all views."""

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
        # Driver options: command line wins, else settings (JK: forced protocol variant).
        self.options = options if options is not None else (
            {"variant": settings.variant} if settings.variant else {})
        self.source: DataSource | None = None
        self.tracker = StateTracker(settings.idle_threshold)
        self.notifier = Notifier(settings.low_soc_threshold)
        self.history = History(on_bucket_closed=self._store_point)
        self._open_store()
        self._load_history()
        self.cell: CellInfo | None = None
        self.last_cell_at = 0.0
        self.status, self.status_detail = "stopped", ""
        self.device_name = settings.bms_name
        self._shut_down = False
        self.restart_pending = False  # run_widget starts a new copy after exit
        self._tray_key = None

        self.compact = CompactWindow()
        self.dashboard = DashboardWindow(self.history)
        self.strip = TaskbarStrip()
        self.strip.offset = settings.taskbar_offset
        self.strip.fullscreen_behavior = settings.fullscreen_behavior

        self.menu = QMenu()
        self.menu.setToolTipsVisible(True)
        self.menu.aboutToShow.connect(self.populate_menu)
        self.tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icons.battery_level_icon(None, theme.GREY))
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(self._on_tray_activated)
            self.tray.show()

        self.compact.alarms_requested.connect(self.show_alarms)
        self.compact.expand_requested.connect(self.expand)
        self.compact.context_menu.connect(self.show_menu)
        self.compact.settings_requested.connect(self.open_settings)
        self.dashboard.settings_requested.connect(self.open_settings)
        self.dashboard.alarms_requested.connect(self.show_alarms)
        self.dashboard.toggle_connection.connect(self.toggle_connection)
        self.dashboard.quit_requested.connect(self.quit)
        self.dashboard.collapse_requested.connect(self.collapse)
        self.dashboard.context_menu.connect(self.show_menu)
        self.strip.clicked.connect(self.toggle_dashboard)
        self.strip.alarms_clicked.connect(self.show_alarms)
        self.strip.context_menu.connect(self.show_menu)
        self.strip.offset_changed.connect(self._on_strip_moved)

        # Re-render once per second so "stale" kicks in even without new data.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.render)
        self.timer.start(1000)
        # While another app's window is maximized / full-screen, the widget and
        # the strip turn see-through and let clicks pass (owner's request).
        self._dimmed: dict[QWidget, bool] = {}  # window -> dimmed now
        self.dim_timer = QTimer(self)
        self.dim_timer.timeout.connect(self.update_dimming)
        self.dim_timer.start(400)
        self.history_timer = QTimer(self)
        self.history_timer.timeout.connect(self.prune_history)
        self.history_timer.start(HISTORY_PRUNE_MS)

    # ----- startup / sources ------------------------------------------------
    def start(self, autostart: bool = False) -> None:
        """Show the views and connect (or ask which BMS to use).

        autostart: started by Windows at logon - show only the compact
        widget / taskbar strip, never the big dashboard.
        """
        self._restore_positions()
        self.apply_display_mode()
        if self.settings.expanded and not autostart:
            self.expand()
        if self.source is None and not self.replay:
            if self.settings.address:
                self.set_source(self._make_ble_source())
            else:
                QTimer.singleShot(300, self.pick_bms)  # first run: choose a BMS
        self.render()

    def _make_ble_source(self) -> BleSource:
        return BleSource(self.settings.address, drivers.get(self.settings.driver), self.options)

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

    # ----- data -------------------------------------------------------------
    def on_status(self, code: str, detail: str) -> None:
        if (code, detail) != (self.status, self.status_detail):
            log.info("status %s %s", code, detail)
        self.status, self.status_detail = code, detail
        self.render()

    def on_device_info(self, info: DeviceInfo) -> None:
        # More reliable than the BLE advertisement name, which Windows
        # does not always report (then only the MAC address is known).
        name = info.name or info.model
        if name != self.device_name:
            log.info("device %s HW %s SW %s name %r", info.model, info.hardware_version,
                     info.software_version, info.name)
        self.device_name = name
        if not self.replay and self.settings.bms_name != name:
            self.settings.bms_name = name
            self.save_settings()
        self.render()

    def on_cell(self, cell: CellInfo) -> None:
        mono = time.monotonic()
        self.tracker.update(cell.current, mono)
        self.history.add(time.time(), cell.soc, cell.current, cell.pack_voltage)
        self.cell, self.last_cell_at = cell, mono
        self.render()

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
            device_name=self.device_name,
        )

    def render(self) -> None:
        snap = self.snapshot()
        if self.settings.notify_enabled and not self.replay:
            for event in self.notifier.update(snap, time.monotonic()):
                self._toast(event, snap)
        self.compact.update_view(snap)
        self.strip.update_view(snap)
        if self.dashboard.isVisible():
            self.dashboard.update_view(snap)
        self._update_tray(snap)

    def _update_tray(self, snap: Snapshot) -> None:
        if self.tray is None:
            return
        cell = snap.cell
        key = (None if cell is None else cell.soc, snap.stale, bool(snap.fault_alarms))
        if key != self._tray_key:
            self._tray_key = key
            color = theme.GREY if (snap.stale or cell is None) else theme.soc_color(cell.soc)
            self.tray.setIcon(icons.battery_level_icon(
                None if cell is None else cell.soc, color, bool(snap.fault_alarms)))
        lines = [snap.device_name or strings.APP_TITLE]
        if cell is not None:
            power, unit = strings.fmt_power(cell.power)
            lines.append(f"SOC {cell.soc}% · {strings.fmt_voltage(cell.pack_voltage)} V")
            lines.append(f"{strings.fmt_current(cell.current)} A · {power} {unit} · "
                         f"{strings.STATE_NAMES[snap.state]}")
        if snap.status != "connected":
            lines.append(strings.STATUS_TEXT.get(snap.status, snap.status))
        self.tray.setToolTip("\n".join(lines)[:127])  # Windows tooltip limit

    # ----- windows ----------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.settings.display_mode

    def apply_display_mode(self) -> None:
        taskbar = self.mode == MODE_TASKBAR
        self.strip.set_wanted(taskbar)
        if taskbar or self.settings.compact_hidden or self.dashboard.isVisible():
            self.compact.hide()
        else:
            self.compact.show()

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

    def expand(self) -> None:
        if not self.dashboard.property("placed"):
            screen = QGuiApplication.primaryScreen().availableGeometry()
            geo = self.dashboard.frameGeometry()
            geo.moveCenter(screen.center())
            self.dashboard.move(geo.topLeft())
            self.dashboard.setProperty("placed", True)
        self.compact.hide()
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()
        self.render()

    def collapse(self) -> None:
        self.dashboard.hide()
        self.apply_display_mode()

    def toggle_dashboard(self) -> None:
        self.collapse() if self.dashboard.isVisible() else self.expand()

    def toggle_widget_hidden(self) -> None:
        self.settings.compact_hidden = not self.settings.compact_hidden
        self.save_settings()
        self.apply_display_mode()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_dashboard()

    def _on_strip_moved(self, offset: int) -> None:
        self.settings.taskbar_offset = offset
        self.save_settings()

    @staticmethod
    def _on_screen(rect: QRect) -> bool:
        return QGuiApplication.screenAt(rect.center()) is not None

    def _restore_positions(self) -> None:
        self.compact.adjustSize()
        pos = self.settings.compact_pos
        if pos and self._on_screen(QRect(pos[0], pos[1], self.compact.width(), self.compact.height())):
            self.compact.move(*pos)
        else:  # default: top-right corner of the primary screen
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self.compact.move(screen.right() - self.compact.width() - 24, screen.top() + 24)
        geo = self.settings.dashboard_geometry
        if geo and self._on_screen(QRect(*geo)):
            self.dashboard.setGeometry(*geo)
            self.dashboard.setProperty("placed", True)

    def _remember_positions(self) -> None:
        if QGuiApplication.platformName() != "windows":
            return  # offscreen test run: its virtual-screen positions are meaningless
        self.settings.compact_pos = [self.compact.x(), self.compact.y()]
        if self.dashboard.property("placed"):
            g = self.dashboard.geometry()
            self.settings.dashboard_geometry = [g.x(), g.y(), g.width(), g.height()]
        self.settings.expanded = self.dashboard.isVisible()

    # ----- menu (tray, widget, strip and dashboard share it) ---------------
    def show_menu(self, pos: QPoint) -> None:
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

        running = self.source is not None and self.source.running
        add(strings.MENU_DISCONNECT if running else strings.MENU_CONNECT, self.toggle_connection)
        add(strings.MENU_PICK_BMS, self.pick_bms, enabled=not self.replay)
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

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, autostart.is_enabled(), autostart.available(),
                             replay=self.replay)

        def pick() -> None:
            self.pick_bms()
            dlg.set_bms(self.settings.bms_name, self.settings.address)

        def mode(m: str) -> None:
            self.set_display_mode(m)
            dlg.set_mode(self.settings.display_mode)  # may have fallen back to widget

        dlg.pick_requested.connect(pick)
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
        self.tracker.idle_threshold = value
        self.save_settings()
        self.render()

    def update_dimming(self) -> None:
        own = {native_hwnd(w) for w in QApplication.topLevelWidgets() if w.isVisible()}
        dim = self.settings.dim_when_maximized and win_taskbar.foreground_is_maximized(own)
        # A maximized window ends above the taskbar, so the strip on the
        # taskbar never covers it: only dim the strip in its corner position
        # (owner's report 2026-11-14: the strip greyed out for no reason).
        wanted = {self.compact: dim, self.strip: dim and self.strip.in_corner}
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
        self.strip.fullscreen_behavior = behavior
        self.save_settings()
        self.strip.reposition()

    def set_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError:
            log.exception("autostart change failed")

    # ----- user actions -----------------------------------------------------
    def show_alarms(self) -> None:
        snap = self.snapshot()
        alarms = snap.cell.alarms if snap.cell else ()
        parent = self.dashboard if self.dashboard.isVisible() else None
        AlarmDialog(alarms, snap.stale and snap.cell is not None, parent).exec()

    def toggle_connection(self) -> None:
        if self.source is None:
            self.pick_bms()
        elif self.source.running:
            self.source.stop()  # thread reports "stopped" when the link is closed
        else:
            self.source.start()

    def pick_bms(self) -> None:
        if self.replay:
            return
        was_running = self.source is not None and self.source.running
        if self.source is not None:
            self.source.stop(wait_s=3.0)  # a connected BMS does not advertise
        dlg = BmsPickerDialog(self.settings.address, self.settings.bms_name, self.settings.driver,
                              scan_delay_ms=2000 if was_running else 0)
        if dlg.exec() == QDialog.Accepted and dlg.selected is not None:
            r = dlg.selected
            changed = r.address != self.settings.address
            if changed:
                log.info("BMS selected: %s %r (%s)", r.address, r.name, r.driver_id)
                self.save_history()  # keep the old BMS's open bucket
                self.history.clear()
                self.cell = None
                self.tracker = StateTracker(self.settings.idle_threshold)
                self.notifier = Notifier(self.settings.low_soc_threshold)
            self.settings.address, self.settings.bms_name = r.address, r.name
            # Unknown device picked via "show all": try the default driver.
            self.settings.driver = drivers.get(r.driver_id).id
            self.device_name = r.name
            self.save_settings()
            if changed:
                self._load_history()  # that BMS's own week of history
                self.dashboard.refresh_chart(force=True)
            self.set_source(self._make_ble_source())
        elif self.source is not None and was_running:
            self.source.start()
        self.render()

    def export_csv(self) -> None:
        """Save the current BMS's history (up to 7 days, 10 s rows) as CSV."""
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
        was_running = self.source is not None and self.source.running
        if was_running:
            self.source.stop(wait_s=3.0)  # a connected BMS neither advertises nor answers
        DiagnosticsDialog(scan_delay_ms=2000 if was_running else 0).exec()
        if was_running:
            self.source.start()
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
        self.notifier.low_soc = percent
        self.save_settings()

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
        log.info("notification %s: %s", event.kind, text)
        if self.tray is not None:
            icon = QSystemTrayIcon.Information if event.kind == FULL else QSystemTrayIcon.Warning
            self.tray.showMessage(snap.device_name or strings.APP_TITLE, text, icon, 10000)

    def _notify(self, text: str) -> None:
        if self.tray is not None:
            self.tray.showMessage(strings.APP_TITLE, text)
        else:
            QMessageBox.information(None, strings.APP_TITLE, text)

    # ----- persistence / exit -----------------------------------------------
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

    def _store_point(self, point) -> None:
        if self.store is None or not self.settings.address:
            return
        try:
            self.store.add(self.settings.address, point)
        except sqlite3.Error:
            log.exception("cannot store history point")

    def _load_history(self) -> None:
        """Load the current BMS's last 7 days into the chart buffer."""
        if self.store is None or not self.settings.address:
            return
        now = time.time()
        legacy = self.history_path.with_name("history.json")
        if legacy.exists():  # one-time import of the old 24 h JSON history
            tmp = History()
            try:
                tmp.load_json(legacy.read_text(encoding="utf-8"), now)
                self.store.add_many(self.settings.address, tmp.series(tmp.max_age_s, now))
                legacy.unlink()
            except (OSError, sqlite3.Error):
                log.exception("history.json import failed")
        try:
            self.history.extend(self.store.load(self.settings.address, now - RETENTION_S), now)
        except sqlite3.Error:
            log.exception("cannot load history")

    def save_history(self) -> None:
        """Store the bucket still being filled (called on exit / BMS switch)."""
        point = self.history.open_bucket()
        if point is not None:
            self._store_point(point)

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
        if self.source is not None:
            self.source.stop(wait_s=3.0)  # frees the BMS for the phone app
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
