"""Smoke tests for the Qt UI (offscreen, no window appears)."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton  # noqa: E402

from jkbms_widget import strings  # noqa: E402
from jkbms_widget.app import MODE_TASKBAR, MODE_WIDGET, Controller, Monitor  # noqa: E402
from jkbms_widget.capture import read_capture  # noqa: E402
from jkbms_widget.drivers.jk.parser import CellInfo, Decoder, DeviceInfo  # noqa: E402
from jkbms_widget.settings import Settings  # noqa: E402
from jkbms_widget.sources import DataSource  # noqa: E402
from jkbms_widget.ui.alarms import AlarmDialog  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "jk02_32s_b1a8s20p_windows.txt"


class FakeSource(DataSource):
    def __init__(self):
        super().__init__()
        self.is_running = False

    @property
    def running(self):
        return self.is_running

    def start(self):
        self.is_running = True

    def stop(self, wait_s=0.0):
        self.is_running = False


@pytest.fixture(scope="module")
def app():
    from jkbms_widget.ui import theme

    app = QApplication.instance() or QApplication([])
    theme.apply_style(app)  # same style as the real app
    return app


@pytest.fixture
def cells():
    dec = Decoder()
    return [o for e in read_capture(FIXTURE) if e.direction == "RX"
            for o in dec.feed(e.data) if isinstance(o, CellInfo)]


def make_controller(tmp_path=None, **settings):
    path = None if tmp_path is None else tmp_path / "settings.json"
    ctl = Controller(Settings(address="AA:BB", **settings), settings_path=path)
    src = FakeSource()
    ctl.set_source(src)
    return ctl, src


def test_compact_and_dashboard_show_live_values(app, cells):
    ctl, src = make_controller(display_mode=MODE_WIDGET)
    src.status.emit("replay", "fixture")
    for c in cells:
        src.cell_info.emit(c)  # same thread -> delivered immediately

    snap = ctl.snapshot()
    assert not snap.stale and snap.state == "Idle"
    assert "100" in ctl.compact.soc.text()
    assert "13.5" in ctl.compact.voltage.text()

    ctl.expand()
    assert ctl.dashboard.isVisible() and not ctl.compact.isVisible()
    assert "Очікування" in ctl.dashboard.rows["Режим роботи:"].text()
    assert ctl.dashboard.health_title.text() == "Акумулятор в нормі"
    ctl.collapse()
    assert ctl.compact.isVisible() and not ctl.dashboard.isVisible()


def test_disconnect_marks_data_stale_and_toggle_works(app, cells):
    ctl, src = make_controller()
    src.status.emit("connected", "C8:47:80:00:00:00")  # Windows gave no BLE name
    src.device_info.emit(DeviceInfo("JK_B1A8S20P", "11A", "11.53", "LFP 3.8kWh"))
    src.cell_info.emit(cells[0])
    assert not ctl.snapshot().stale
    # Name from the device-info frame (not the MAC) - now shown in the tooltip,
    # the line itself shows the time left.
    assert "LFP 3.8kWh" in ctl.compact.status.toolTip()
    assert "C8:47" not in ctl.compact.status.toolTip()

    assert src.running
    ctl.toggle_connection()  # running -> stop
    assert not src.running
    src.status.emit("stopped", "")
    assert ctl.snapshot().stale
    ctl.toggle_connection()  # stopped -> start
    assert src.running


def test_taskbar_mode_is_default_and_autostart_never_opens_dashboard(app):
    ctl = Controller(Settings(address="AA:BB", expanded=True))  # dashboard was open on exit
    ctl.set_source(FakeSource())
    assert ctl.settings.display_mode == MODE_TASKBAR
    ctl.start(autostart=True)
    assert not ctl.dashboard.isVisible() and not ctl.compact.isVisible()
    assert ctl.strip.wanted


def test_manual_start_restores_open_dashboard(app):
    ctl = Controller(Settings(address="AA:BB", expanded=True, display_mode=MODE_WIDGET))
    ctl.set_source(FakeSource())
    ctl.start()
    assert ctl.dashboard.isVisible()


def test_history_is_reloaded_per_bms_after_restart(app, tmp_path):
    import time

    db = tmp_path / "history.sqlite"
    start = time.time() - 3600  # an hour ago: well inside the 7-day window
    start -= start % 10
    ctl = Controller(Settings(address="AA:BB"), history_path=db)
    ctl.set_source(FakeSource())
    for k in range(30):
        ctl.history.add(start + k, 80, -2.0)  # buckets 0,10 closed -> SQLite; 20 open
    ctl.shutdown()  # stores the open bucket too

    same = Controller(Settings(address="AA:BB"), history_path=db)
    assert [p.time for p in same.history.series(7 * 24 * 3600, time.time())] == \
        [start, start + 10, start + 20]
    other = Controller(Settings(address="CC:DD"), history_path=db)
    assert other.history.series(7 * 24 * 3600, time.time()) == []
    same.shutdown()
    other.shutdown()


def test_display_mode_switch_and_settings_saved(app, tmp_path):
    ctl, _ = make_controller(tmp_path, display_mode=MODE_WIDGET)
    ctl.start()
    assert ctl.compact.isVisible() and not ctl.strip.wanted
    ctl.set_display_mode(MODE_TASKBAR)  # this PC has a horizontal taskbar
    assert ctl.strip.wanted and not ctl.compact.isVisible()
    assert Settings.load(tmp_path / "settings.json").display_mode == MODE_TASKBAR
    ctl.set_display_mode(MODE_WIDGET)
    assert ctl.compact.isVisible() and not ctl.strip.wanted


def test_menu_builds_and_shutdown_saves_positions(app, tmp_path):
    ctl, src = make_controller(tmp_path)
    ctl.start()
    ctl.populate_menu()
    texts = [a.text() for a in ctl.menu.actions()]
    assert "Вихід" in texts and "Відключитися" in texts
    ctl.compact.move(123, 456)
    ctl.shutdown()
    saved = Settings.load(tmp_path / "settings.json")
    # Offscreen (tests): virtual-screen positions must never overwrite real ones.
    assert saved.compact_pos is None
    assert not src.running


NEIGHBOUR = ("C8:47:80:7A:DC:B3", "LFP-4kWh", -70)
OURS = ("C8:47:80:1A:F9:9E", "LFP 3.8kWh", -88)


def _picker(monkeypatch, current, results):
    from jkbms_widget.ble import ScanResult
    from jkbms_widget.ui import picker

    monkeypatch.setattr(picker._Scanner, "start", lambda self: None)  # no real BLE scan
    dlg = picker.BmsPickerDialog(current, "LFP 3.8kWh" if current else "")
    dlg._on_results([ScanResult(a, n, r, "jk") for a, n, r in results])
    return dlg


def test_picker_never_preselects_a_foreign_bms(app, monkeypatch):
    dlg = _picker(monkeypatch, None, [NEIGHBOUR, OURS])
    assert dlg.list.count() == 2
    assert dlg.list.currentItem() is None and not dlg.select_btn.isEnabled()


def test_picker_puts_saved_bms_first_and_selects_it(app, monkeypatch):
    dlg = _picker(monkeypatch, OURS[0], [NEIGHBOUR, OURS])
    assert dlg.list.currentRow() == 0
    assert dlg.list.currentItem().data(0x0100).address == OURS[0]  # Qt.UserRole


def test_picker_keeps_saved_bms_listed_when_not_advertising(app, monkeypatch):
    dlg = _picker(monkeypatch, OURS[0], [NEIGHBOUR])
    assert dlg.list.count() == 2
    assert "не видно" in dlg.list.item(0).text()
    assert dlg.list.currentItem().data(0x0100).address == OURS[0]


def test_settings_dialog_applies_changes(app, tmp_path):
    from jkbms_widget.ui.settings_dialog import SettingsDialog

    ctl, _ = make_controller(tmp_path)
    s = ctl.settings
    dlg = SettingsDialog(s, autostart_on=False, autostart_available=False)
    dlg.threshold_changed.connect(ctl.set_idle_threshold)
    dlg.mode_changed.connect(ctl.set_display_mode)
    dlg.threshold.setValue(2.5)
    assert s.idle_threshold == 2.5 and ctl.tracker.idle_threshold == 2.5
    dlg.mode_buttons["taskbar"].setChecked(True)
    assert s.display_mode == "taskbar"
    assert not dlg.autostart.isEnabled()  # dev run, not the .exe
    assert Settings.load(tmp_path / "settings.json").idle_threshold == 2.5


def test_gear_buttons_request_settings(app):
    ctl, _ = make_controller()
    hits = []
    ctl.open_settings = lambda: hits.append(1)  # don't open a modal dialog in tests
    ctl.compact.settings_requested.disconnect()
    ctl.dashboard.settings_requested.disconnect()
    ctl.compact.settings_requested.connect(ctl.open_settings)
    ctl.dashboard.settings_requested.connect(ctl.open_settings)
    ctl.compact.settings_requested.emit()
    ctl.dashboard.settings_requested.emit()
    assert hits == [1, 1]


def test_picker_focus_never_selects_a_foreign_bms(app, monkeypatch):
    from jkbms_widget.ble import ScanResult
    from jkbms_widget.ui import picker

    monkeypatch.setattr(picker._Scanner, "start", lambda self: None)  # no real BLE scan
    dlg = picker.BmsPickerDialog(None, "")
    dlg._on_results([ScanResult("C8:47:80:7A:DC:B3", "LFP-4kWh", -70, "jk"),
                     ScanResult("C8:47:80:1A:F9:9E", "LFP 3.8kWh", -88, "jk")])
    dlg.show()
    dlg.list.setFocus()  # Qt makes row 0 "current" on focus - must not count as a choice
    app.processEvents()
    assert not dlg.select_btn.isEnabled()
    dlg._accept()
    assert dlg.selected is None
    dlg.list.item(1).setSelected(True)  # explicit click
    dlg._accept()
    assert dlg.selected.address == "C8:47:80:1A:F9:9E"


def test_maximized_window_dims_widget_and_corner_strip_only(app, monkeypatch):
    from jkbms_widget import win_taskbar

    ctl, _ = make_controller()
    monkeypatch.setattr(win_taskbar, "foreground_is_maximized", lambda own: True)
    ctl.update_dimming()
    # The strip on the taskbar never overlaps a maximized window: stays opaque.
    assert ctl.compact.windowOpacity() < 0.5 and ctl.strip.windowOpacity() == 1.0
    ctl.strip.in_corner = True  # moved over the screen during a full-screen app
    ctl.update_dimming()
    assert ctl.strip.windowOpacity() < 0.5
    monkeypatch.setattr(win_taskbar, "foreground_is_maximized", lambda own: False)
    ctl.update_dimming()
    assert ctl.compact.windowOpacity() == 1.0 and ctl.strip.windowOpacity() == 1.0
    ctl.settings.dim_when_maximized = False
    monkeypatch.setattr(win_taskbar, "foreground_is_maximized", lambda own: True)
    ctl.update_dimming()
    assert ctl.compact.windowOpacity() == 1.0  # setting off: never dims


def test_widget_shows_time_left_instead_of_name(app, cells):
    import dataclasses

    ctl, src = make_controller(display_mode=MODE_WIDGET)
    src.status.emit("connected", "")
    src.device_info.emit(DeviceInfo("JK_B1A8S20P", "11A", "11.53", "LFP 3.8kWh"))
    for _ in range(5):
        src.cell_info.emit(dataclasses.replace(cells[0], current=-25.0))
    assert ctl.compact.status.text().endswith("до розряду")
    assert "LFP 3.8kWh" in ctl.compact.status.toolTip()


def test_updater_skips_unchanged_values():
    from jkbms_widget.ui.widgets import Updater

    calls = []
    upd = Updater()
    for v in ("a", "a", "b", "b", "a"):
        upd("k", v, calls.append)
    assert calls == ["a", "b", "a"]


def test_alarm_dialog_lists_alarms_in_ukrainian(app):
    dlg = AlarmDialog(("fully_charged", "cell_undervoltage"), stale=False)  # keep a reference
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    assert "Батарея повністю заряджена" in texts
    assert "Низька напруга комірки" in texts
    dlg_empty = AlarmDialog((), stale=False)
    assert "Активних аварій немає" in [w.text() for w in dlg_empty.findChildren(QLabel)]


def test_restart_command_keeps_options_but_drops_one_shot_flags():
    from jkbms_widget.app import restart_command

    exe = r"C:\Apps\JkBmsWidget\JkBmsWidget.exe"
    assert restart_command(True, exe, [exe, "--autostart"], []) == (exe, [])
    assert restart_command(True, exe, [exe, "--exit-after", "8", "widget"], []) == (exe, ["widget"])
    py = r"C:\venv\python.exe"
    orig = [py, "-m", "jkbms_widget", "widget", "--replay", "f.txt", "--exit-after", "5"]
    assert restart_command(False, py, ["ignored"], orig) == (py, ["-m", "jkbms_widget", "widget",
                                                                 "--replay", "f.txt"])


def test_scale_change_restarts_and_same_scale_does_not(app, monkeypatch):
    ctl, _ = make_controller(ui_scale=1.0)
    quits = []
    monkeypatch.setattr(ctl, "quit", lambda: quits.append(1))
    ctl.set_scale(1.0)  # unchanged: nothing to do
    assert not ctl.restart_pending and quits == []
    ctl.set_scale(1.25)
    assert ctl.restart_pending and quits == [1]
    assert ctl.settings.ui_scale == 1.25


def test_dashboard_cells_tab_and_energy_rows(app, cells):
    ctl, src = make_controller(display_mode=MODE_WIDGET)
    src.status.emit("replay", "fixture")
    for c in cells:
        src.cell_info.emit(c)
    ctl.expand()
    d = ctl.dashboard
    d.refresh_chart(force=True)
    texts = [lbl.text() for lbl in d.energy_rows.values()]
    assert all("kWh" in t for t in texts)
    assert d.pages.currentWidget() is d.chart and d.chart_controls.isVisibleTo(d)
    d._set_tab(1)
    assert d.pages.currentWidget() is d.cells and not d.chart_controls.isVisibleTo(d)
    assert d.cells.cell is not None and len(d.cells.cell.cell_voltages) == 4
    d.cells.grab()  # paints without errors
    d._set_tab(0)


def test_notifications_go_through_the_controller(app, cells, monkeypatch):
    import dataclasses

    ctl, src = make_controller(display_mode=MODE_WIDGET, low_soc_threshold=20)
    shown = []
    monkeypatch.setattr(ctl, "_toast", lambda event, snap: shown.append(event.kind))
    src.status.emit("connected", "AA:BB")
    src.cell_info.emit(dataclasses.replace(cells[0], soc=15))
    assert shown == ["low_soc"]
    ctl.settings.notify_enabled = False
    ctl.notifier.low_soc = 50  # would fire again if enabled
    src.cell_info.emit(dataclasses.replace(cells[0], soc=40))
    assert shown == ["low_soc"]


def test_two_bms_each_with_own_views_and_dashboard_switch(app, cells, monkeypatch):
    import dataclasses

    from jkbms_widget.ble import ScanResult

    settings = Settings(address="AA:01", bms_name="Main",
                        extra_devices=[{"address": "AA:02", "name": "Second"}],
                        display_mode=MODE_TASKBAR)
    ctl = Controller(settings)
    notes = []
    monkeypatch.setattr(ctl, "_notify", notes.append)  # no modal box without a tray
    assert [m.address for m in ctl.monitors] == ["AA:01", "AA:02"]
    sources = [FakeSource(), FakeSource()]
    for m, s in zip(ctl.monitors, sources):
        m.set_source(s)
        s.status.emit("replay", "fixture")
    sources[0].cell_info.emit(dataclasses.replace(cells[0], soc=80))
    sources[1].cell_info.emit(dataclasses.replace(cells[0], soc=30))
    first, second = ctl.monitors
    assert first.strip.snap.cell.soc == 80 and second.strip.snap.cell.soc == 30
    ctl.apply_display_mode()
    assert (first.strip.slot, second.strip.slot) == (0, 1)

    ctl.expand(second)  # click on the second strip
    assert ctl.active == 1 and ctl.dashboard.history is second.history
    assert ctl.dashboard.selector.isVisibleTo(ctl.dashboard)
    assert ctl.dashboard.ring.soc == 30
    ctl.set_active(0)
    assert ctl.dashboard.history is first.history

    # Add a third BMS through the picker, then remove the second one.
    monkeypatch.setattr(ctl, "_pick", lambda current: ScanResult("AA:03", "Third", -60, "jk"))
    monkeypatch.setattr(Monitor, "make_ble_source", lambda self: FakeSource())
    ctl.add_bms()
    assert [m.address for m in ctl.monitors] == ["AA:01", "AA:02", "AA:03"]
    assert [d.address for d in settings.devices()] == ["AA:01", "AA:02", "AA:03"]
    ctl.add_bms()  # the same BMS again: refused
    assert len(ctl.monitors) == 3 and notes == [strings.BMS_ALREADY]
    ctl.remove_bms(1)
    assert [m.address for m in ctl.monitors] == ["AA:01", "AA:03"]
    assert [d.name for d in settings.devices()] == ["Main", "Third"]
    assert ctl.monitors[1].strip.slot == 1  # moved into the free slot
    ctl.remove_bms(0)
    ctl.remove_bms(0)  # the last BMS can't be removed
    assert len(ctl.monitors) == 1
    ctl.shutdown()


def test_strip_slots_sit_side_by_side():
    from jkbms_widget.ui.taskbar_strip import SLOT_GAP, STRIP_WIDTH, TaskbarStrip
    from jkbms_widget.win_taskbar import TaskbarInfo

    info = TaskbarInfo(0, 1392, 2560, 1440, 3, 2340, False)
    s = TaskbarStrip()
    assert s._effective_offset(info) is None  # first strip: default place
    s.slot = 1
    default = s._effective_offset(info) - (STRIP_WIDTH + SLOT_GAP)
    s.offset = 100
    assert s._effective_offset(info) == 100 + STRIP_WIDTH + SLOT_GAP
    assert default > 0


def test_hidden_bms_keeps_recording_and_strips_are_numbered(app, cells):
    import dataclasses

    from jkbms_widget.ui.settings_dialog import SettingsDialog

    settings = Settings(address="AA:01", bms_name="Main", display_mode=MODE_TASKBAR,
                        extra_devices=[{"address": "AA:02", "name": "Second"},
                                       {"address": "AA:03", "name": "Third"}])
    ctl = Controller(settings)
    sources = [FakeSource() for _ in ctl.monitors]
    for m, s in zip(ctl.monitors, sources):
        m.set_source(s)
        s.status.emit("replay", "x")
    ctl.apply_display_mode()
    assert [m.strip.number for m in ctl.monitors] == [1, 2, 3]
    assert [m.compact.number.text() for m in ctl.monitors] == ["1", "2", "3"]

    ctl.set_visible(1, False)  # the eye in the settings list / "Hide from the taskbar"
    first, second, third = ctl.monitors
    assert not second.strip.wanted and first.strip.wanted and third.strip.wanted
    assert (first.strip.slot, third.strip.slot) == (0, 1)  # no gap for the hidden one
    assert third.strip.number == 3  # numbers stay those of the list
    assert settings.devices()[1].visible is False
    sources[1].cell_info.emit(dataclasses.replace(cells[0], soc=42))
    assert second.cell.soc == 42  # hidden, but still connected and recording
    assert second.history.open_bucket() is not None

    ctl.show_menu(QPoint(0, 0), third)  # right-click on the third strip
    ctl.menu.close()
    ctl._menu_monitor = third
    ctl.populate_menu()
    texts = [a.text() for a in ctl.menu.actions()]
    assert texts[0] == "3. Third" and strings.MENU_HIDE_BMS in texts
    assert strings.MENU_REMOVE_BMS in texts

    dlg = SettingsDialog(settings, False, False, devices=ctl.device_rows())
    flips = []
    dlg.visibility_changed.connect(lambda i, on: flips.append((i, on)))
    eye = dlg.devices.itemWidget(dlg.devices.item(1)).findChild(QToolButton)
    assert not eye.isChecked()
    eye.click()
    assert flips == [(1, True)]
    ctl.shutdown()


def test_dashboard_selector_switches_and_hides_from_its_menu(app):
    settings = Settings(address="AA:01", bms_name="Main",
                        extra_devices=[{"address": "AA:02", "name": "Second"}])
    ctl = Controller(settings)
    for m in ctl.monitors:
        m.set_source(FakeSource())
    sel = ctl.dashboard.selector
    assert sel.text().startswith("1. Main")
    sel._fill()
    rows = [a.defaultWidget() for a in sel.menu_.actions()]
    assert len(rows) == 2
    rows[1].findChild(QToolButton).click()  # eye of the second BMS: hide it
    assert ctl.monitors[1].visible is False and settings.devices()[1].visible is False
    rows[1].findChild(QPushButton).click()  # its name: show it in the dashboard
    assert ctl.active == 1 and sel.text().startswith("2. Second")
    ctl.shutdown()


def test_selector_second_click_closes_instead_of_reopening(app):
    import time

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from jkbms_widget.ui.bms_selector import BmsSelector

    sel = BmsSelector()
    sel.set_items(["Main", "Second"], [True, True], 0)
    opened = []
    sel._open = lambda: opened.append(1)
    sel.clicked.disconnect()
    sel.clicked.connect(lambda: sel._open())
    sel.resize(160, 30)
    sel._hidden_at = time.monotonic()  # the menu was just closed by this press
    QTest.mouseClick(sel, Qt.LeftButton)
    assert opened == []
    sel._hidden_at = time.monotonic() - 1.0  # a later, ordinary click opens it
    QTest.mouseClick(sel, Qt.LeftButton)
    assert opened == [1]


def test_low_soc_threshold_colours_views_and_balancing_row(app, cells):
    import dataclasses

    from jkbms_widget.ui import theme

    ctl, src = make_controller(display_mode=MODE_WIDGET, low_soc_threshold=60)
    monkey = []
    ctl._toast = lambda event, snap: monkey.append(event.kind)
    src.status.emit("replay", "fixture")
    src.cell_info.emit(dataclasses.replace(cells[0], soc=55, balancing=False))
    snap = ctl.snapshot()
    assert snap.is_low and snap.low_soc == 60
    assert theme.RED in ctl.compact.soc.text()  # widget SOC turns red at the threshold
    assert strings.LOW_SOC_STATE.format(t=60) in ctl.strip.icon_tooltip()
    ctl.expand()
    assert ctl.dashboard.rows[strings.ROW_BALANCING].text() == strings.NO_VALUE
    src.cell_info.emit(dataclasses.replace(cells[0], soc=55, balancing=True))
    assert ctl.dashboard.rows[strings.ROW_BALANCING].text() == strings.BALANCING_ACTIVE
    ctl.set_low_soc(50)
    assert not ctl.snapshot().is_low and theme.RED not in ctl.compact.soc.text()
