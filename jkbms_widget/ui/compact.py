"""Small always-on-top frameless widget (floating display mode)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import strings
from ..state import CHARGING, DISCHARGING, Snapshot
from . import icons, theme
from .widgets import DragMover, StatusDot, Updater, rounded_corners

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
        self.dot = StatusDot(10)
        self.soc = QLabel()
        top.addWidget(self.dot, 0, Qt.AlignVCenter)
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

    def update_view(self, snap: Snapshot) -> None:
        upd = self.upd
        cell = snap.cell
        self.dot.set_color(theme.STATUS_COLORS.get(snap.status, theme.GREY))
        upd("dot_tip", strings.STATUS_TEXT.get(snap.status, snap.status), self.dot.setToolTip)

        main = theme.MUTED if snap.stale else theme.TEXT
        if cell is None:
            upd("soc", value_html(strings.NO_VALUE, "%", 20, main), self.soc.setText)
            upd("v", value_html(strings.NO_VALUE, "V", 12, main), self.voltage.setText)
            upd("a", value_html(strings.NO_VALUE, "A", 12, main), self.current.setText)
            upd("w", value_html(strings.NO_VALUE, "W", 12, main), self.power.setText)
            upd("state", "", self.state.setText)
        else:
            soc_color = theme.MUTED if snap.stale else theme.soc_color(cell.soc)
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
        upd("status", text, self.status.setText)
        upd("status_tip", tip, self.status.setToolTip)
        alarm_button_style(self.alarm_btn, snap, 18, upd)

    def contextMenuEvent(self, event) -> None:
        # The controller builds the menu (same one as in the tray).
        self.context_menu.emit(event.globalPos())
