"""Small always-on-top frameless widget (floating display mode)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import strings, win_taskbar
from ..state import CHARGING, DISCHARGING, Snapshot
from . import icons, theme
from .widgets import DragMover, Updater, native_hwnd, rounded_corners

STATE_COLORS = {CHARGING: theme.GREEN, DISCHARGING: theme.AMBER}


def value_html(number: str, unit: str, size_pt: int, color: str = theme.TEXT) -> str:
    gap = "" if unit == "%" else " "
    return (
        f"<span style='font-size:{size_pt}pt; font-weight:600; color:{color}'>{number}</span>"
        f"<span style='font-size:{max(7, size_pt - 4)}pt; color:{theme.MUTED}'>{gap}{unit}</span>"
    )


def icon_button(name: str, color: str, size: int, tip: str) -> QToolButton:
    b = QToolButton()
    b.setIcon(icons.icon(name, color, size))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def alarm_button_style(
    button: QToolButton, snap: Snapshot, size: int, upd: Updater, none_text: str = ""
) -> None:
    """Shared look of the alarm indicator (compact + dashboard)."""
    cell = snap.cell
    faults = snap.fault_alarms
    if cell is None:
        name, color, text = "check", theme.GREY, ""
    elif faults:
        name, color, text = "warning", theme.RED, str(len(faults))
    elif cell.alarms:
        name, color, text = "info", theme.BLUE, none_text
    else:
        name, color, text = "check", theme.GREEN, none_text
    if snap.stale and cell is not None and not faults:
        color = theme.GREY
    upd("alarm_icon", (name, color), lambda v: button.setIcon(icons.icon(v[0], v[1], size)))
    upd("alarm_text", text, button.setText)
    upd("alarm_style", color, lambda c: button.setStyleSheet(f"color: {c}; font-weight: 600;"))


class CompactWindow(QWidget):
    expand_requested = Signal()
    alarms_requested = Signal()
    settings_requested = Signal()
    context_menu = Signal(QPoint)

    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.on_desktop = False  # pinned to the desktop instead of always on top
        rounded_corners(self)
        self.setWindowTitle(strings.APP_TITLE)
        self.upd = Updater()

        root = QFrame(objectName="root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        lay = QHBoxLayout(root)
        lay.setContentsMargins(14, 8, 8, 8)
        lay.setSpacing(12)

        # Left: status dot + SOC, battery state below.
        left = QVBoxLayout()
        left.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.soc = QLabel()
        # BMS number when several are shown (same as in the settings list).
        self.number = QLabel()
        self.number.setProperty("muted", True)
        self.number.setStyleSheet("font-size: 9pt; font-weight: 600;")
        self.number.hide()
        top.addWidget(self.number, 0, Qt.AlignVCenter)
        top.addWidget(self.soc)
        left.addLayout(top)
        self.state = QLabel()
        left.addWidget(self.state)
        lay.addLayout(left)

        line = QFrame()
        line.setFixedWidth(1)
        line.setStyleSheet(f"background: {theme.CARD_BORDER};")
        lay.addWidget(line)

        # Right: V / A / W, then status text + buttons.
        right = QVBoxLayout()
        right.setSpacing(2)
        values = QHBoxLayout()
        values.setSpacing(14)
        self.voltage, self.current, self.power = QLabel(), QLabel(), QLabel()
        for w in (self.voltage, self.current, self.power):
            values.addWidget(w)
        values.addStretch(1)
        right.addLayout(values)

        bottom = QHBoxLayout()
        bottom.setSpacing(2)
        self.status = QLabel()
        self.status.setProperty("muted", True)
        bottom.addWidget(self.status, 1)
        self.alarm_btn = QToolButton()
        self.alarm_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.alarm_btn.setIconSize(QSize(18, 18))
        self.alarm_btn.setToolTip(strings.TIP_ALARMS)
        self.alarm_btn.setCursor(Qt.PointingHandCursor)
        self.alarm_btn.clicked.connect(self.alarms_requested)
        bottom.addWidget(self.alarm_btn)
        gear = icon_button("gear", theme.MUTED, 16, strings.TIP_SETTINGS)
        gear.clicked.connect(self.settings_requested)
        bottom.addWidget(gear)
        expand = icon_button("expand", theme.MUTED, 16, strings.TIP_EXPAND)
        expand.clicked.connect(self.expand_requested)
        bottom.addWidget(expand)
        right.addLayout(bottom)
        lay.addLayout(right, 1)

        DragMover(self).attach(root)
        self.setMinimumWidth(380)
        self.update_view(Snapshot(cell=None))

    def set_on_desktop(self, on: bool) -> None:
        """Always on top (default) or pinned to the desktop under other windows."""
        if on == self.on_desktop:
            return
        self.on_desktop = on
        shown = self.isVisible()
        flags = Qt.Tool | Qt.FramelessWindowHint
        self.setWindowFlags(flags if on else flags | Qt.WindowStaysOnTopHint)
        if shown:  # setWindowFlags hides the window
            self.show()
        elif self.testAttribute(Qt.WA_WState_Created):
            win_taskbar.pin_to_desktop(native_hwnd(self), on)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # The native window may be new after setWindowFlags: corners and owner again.
        rounded_corners(self)
        win_taskbar.pin_to_desktop(native_hwnd(self), self.on_desktop)
        if self.on_desktop:
            # showEvent comes before Windows shows the window (which puts it on
            # top): send it down again once it is really visible.
            QTimer.singleShot(0, lambda: win_taskbar.pin_to_desktop(native_hwnd(self),
                                                                    self.on_desktop))

    def nativeEvent(self, event_type, message):
        # Pinned to the desktop: never let Windows raise it above other apps
        # (on show, on click, after the dashboard is collapsed).
        if self.on_desktop and bytes(event_type) == b"windows_generic_MSG":
            win_taskbar.keep_at_bottom(int(message))
        return super().nativeEvent(event_type, message)

    def set_number(self, number: int | str | None) -> None:
        self.number.setText("" if number is None else str(number))
        self.number.setVisible(number is not None)

    def update_view(self, snap: Snapshot) -> None:
        upd = self.upd
        cell = snap.cell
        # No status dot (owner's request 2026-11-15): the status text below says it,
        # and the SOC tooltip names the connection state.
        upd("soc_tip", strings.STATUS_TEXT.get(snap.status, snap.status), self.soc.setToolTip)

        main = theme.MUTED if snap.stale else theme.TEXT
        if cell is None:
            upd("soc", value_html(strings.NO_VALUE, "%", 20, main), self.soc.setText)
            upd("v", value_html(strings.NO_VALUE, "V", 12, main), self.voltage.setText)
            upd("a", value_html(strings.NO_VALUE, "A", 12, main), self.current.setText)
            upd("w", value_html(strings.NO_VALUE, "W", 12, main), self.power.setText)
            upd("state", "", self.state.setText)
        else:
            soc_color = theme.MUTED if snap.stale else theme.soc_color(cell.soc, snap.low_soc)
            upd("soc", value_html(f"{cell.soc}", "%", 20, soc_color), self.soc.setText)
            upd("v", value_html(strings.fmt_voltage(cell.pack_voltage), "V", 12, main),
                self.voltage.setText)
            upd("a", value_html(strings.fmt_current(cell.current), "A", 12, main),
                self.current.setText)
            upd("w", value_html(*strings.fmt_power(cell.power), 12, main), self.power.setText)
            color = theme.MUTED if snap.stale else STATE_COLORS.get(snap.state, theme.MUTED)
            upd("state", strings.STATE_NAMES[snap.state], self.state.setText)
            upd("state_style", color,
                lambda c: self.state.setStyleSheet(f"color: {c}; font-size: 9pt;"))

        status = strings.STATUS_TEXT.get(snap.status, snap.status)
        name = snap.device_name or snap.status_detail
        live = snap.status in ("connected", "replay") and not snap.stale
        # Owner's choice: time to empty/full here; the BMS name moves to the tooltip.
        time_text = strings.fmt_time_left_long(snap.hours_left, snap.left_kind) if live else ""
        if time_text:
            text, tip = time_text, f"{name}\n{status}" if name else status
        elif snap.status == "connected":
            text, tip = name, status  # current ≈ 0: no estimate, show the name
        else:
            text, tip = status, snap.status_detail
        if snap.partial:  # bank: some of its BMS are not in the sums
            text = strings.BANK_PARTIAL_SHORT.format(n=len(snap.offline), total=snap.members)
            tip = strings.partial_note(snap)
        elif snap.missing:
            text = strings.BANK_NO_DATA_SHORT
            tip = strings.BANK_NO_DATA_SUB.format(names=", ".join(snap.missing))
        upd("status", text, self.status.setText)
        upd("status_tip", tip, self.status.setToolTip)
        upd("status_style", theme.AMBER if snap.partial else (theme.RED if snap.missing else ""),
            lambda c: self.status.setStyleSheet(f"color: {c};" if c else ""))
        alarm_button_style(self.alarm_btn, snap, 18, upd)

    def contextMenuEvent(self, event) -> None:
        # The controller builds the menu (same one as in the tray).
        self.context_menu.emit(event.globalPos())
