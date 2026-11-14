"""Smoke tests for the Qt UI (offscreen, no window appears)."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from jkbms_widget.app import MODE_TASKBAR, MODE_WIDGET, Controller  # noqa: E402
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
