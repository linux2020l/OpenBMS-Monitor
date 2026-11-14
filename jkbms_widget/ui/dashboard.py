"""Expanded dashboard window, laid out like docs/ui-mockup.png."""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import strings
from ..state import History, Snapshot
from . import icons, theme
from .compact import STATE_COLORS, alarm_button_style, icon_button, value_html
from .chart import CHARGE_COLOR, DISCHARGE_COLOR, ZERO_COLOR, HistoryChart
from .widgets import DragMover, SocRing, StatusDot, Updater, rounded_corners

CHART_REFRESH_S = 5.0  # history has 10 s buckets; redrawing more often is wasted work


def card() -> QFrame:
    f = QFrame()
    f.setProperty("card", True)
    return f


def muted(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("muted", True)
    return lbl


class Tile(QFrame):
    """Icon + big value + caption (current, power, voltage, temperature)."""

    def __init__(self, icon_name: str, color: str, caption: str) -> None:
        super().__init__()
        self.setProperty("card", True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 10, 14, 10)
        lay.setSpacing(16)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, color, 30))
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.value = QLabel()
        col.addWidget(self.value)
        col.addWidget(muted(caption))
        lay.addLayout(col, 1)

    def set_value(self, number: str, unit: str, stale: bool) -> None:
        html = value_html(number, unit, 18, theme.MUTED if stale else theme.TEXT)
        if html != self.value.text():
            self.value.setText(html)


class DashboardWindow(QWidget):
    collapse_requested = Signal()
    alarms_requested = Signal()
    settings_requested = Signal()
    toggle_connection = Signal()
    quit_requested = Signal()
    context_menu = Signal(QPoint)

    def __init__(self, history: History) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        rounded_corners(self)
        self.setWindowTitle(strings.APP_TITLE)
        self.history = history
        self.span_s = strings.CHART_RANGES[0][1]
        self.upd = Updater()
        self._chart_at = -1e9  # monotonic time of the last chart refresh
        self.resize(1000, 640)

        root = QFrame(objectName="root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 10, 18, 18)
        lay.setSpacing(14)

        lay.addWidget(self._build_title_bar())

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addLayout(self._build_left(), 3)
        body.addLayout(self._build_tiles(), 3)
        body.addWidget(self._build_status_panel(), 4)
        lay.addLayout(body, 3)
        lay.addWidget(self._build_chart(), 2)

        self._snap = Snapshot(cell=None)
        self.update_view(self._snap)

    # ----- layout -----------------------------------------------------------
    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(4, 0, 0, 0)
        h.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(icons.pixmap("battery", theme.GREEN, 30))
        h.addWidget(logo)
        title = QLabel(strings.APP_TITLE)
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        h.addWidget(title)
        sep = QFrame()
        sep.setFixedSize(1, 24)
        sep.setStyleSheet(f"background: {theme.CARD_BORDER};")
        h.addSpacing(8)
        h.addWidget(sep)
        h.addSpacing(8)
        bt = QLabel()
        bt.setPixmap(icons.pixmap("bluetooth", theme.BLUE, 22))
        h.addWidget(bt)
        self.status_text = QLabel()
        self.status_text.setStyleSheet("font-size: 12pt;")  # size hint uses the right font
        h.addWidget(self.status_text)
        self.status_dot = StatusDot(10)
        h.addWidget(self.status_dot)
        h.addStretch(1)

        self.connect_btn = QPushButton()
        self.connect_btn.setStyleSheet(f"color: {theme.MUTED};")
        self.connect_btn.setCursor(Qt.PointingHandCursor)
        self.connect_btn.clicked.connect(self.toggle_connection)
        h.addWidget(self.connect_btn)
        for name, tip, signal in (
            ("gear", strings.TIP_SETTINGS, self.settings_requested),
            ("collapse", strings.TIP_COLLAPSE, self.collapse_requested),
            ("close", strings.TIP_CLOSE, self.quit_requested),
        ):
            b = icon_button(name, theme.TEXT, 20, tip)
            b.clicked.connect(signal)
            h.addWidget(b)
        DragMover(self).attach(bar)
        return bar

    def _build_left(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(14)
        ring_card = card()
        rl = QVBoxLayout(ring_card)
        rl.setContentsMargins(12, 12, 12, 12)
        self.ring = SocRing()
        rl.addWidget(self.ring)
        col.addWidget(ring_card, 1)

        left_card = card()
        ll = QHBoxLayout(left_card)
        ll.setContentsMargins(18, 10, 18, 10)
        ll.setSpacing(14)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("clock", theme.GREEN, 30))
        ll.addWidget(ic)
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        self.time_left = QLabel()
        self.time_left_kind = muted()
        tcol.addWidget(self.time_left)
        tcol.addWidget(self.time_left_kind)
        ll.addLayout(tcol, 1)
        col.addWidget(left_card)
        return col

    def _build_tiles(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(14)
        self.tile_current = Tile("bolt", theme.BLUE, strings.TILE_CURRENT)
        self.tile_power = Tile("pulse", theme.PURPLE, strings.TILE_POWER)
        self.tile_voltage = Tile("volt", theme.GREEN, strings.TILE_VOLTAGE)
        self.tile_temp = Tile("thermo", theme.RED, strings.TILE_TEMPERATURE)
        for t in (self.tile_current, self.tile_power, self.tile_voltage, self.tile_temp):
            col.addWidget(t, 1)
        return col

    def _build_status_panel(self) -> QFrame:
        panel = card()
        v = QVBoxLayout(panel)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(14)
        self.health_icon = QToolButton()
        self.health_icon.setIconSize(QSize(44, 44))
        self.health_icon.clicked.connect(self.alarms_requested)
        head.addWidget(self.health_icon)
        hcol = QVBoxLayout()
        hcol.setSpacing(2)
        self.health_title = QLabel()
        self.health_title.setStyleSheet("font-size: 15pt; font-weight: 600;")
        self.health_sub = muted()
        self.health_sub.setWordWrap(True)
        hcol.addWidget(self.health_title)
        hcol.addWidget(self.health_sub)
        head.addLayout(hcol, 1)
        v.addLayout(head)

        line = QFrame(objectName="line")
        v.addWidget(line)

        grid = QGridLayout()
        grid.setVerticalSpacing(12)
        self.rows: dict[str, QLabel] = {}
        for r, key in enumerate(
            (strings.ROW_MODE, strings.ROW_TIME_LEFT, strings.ROW_CELLS,
             strings.ROW_BALANCING, strings.ROW_MOSFETS)
        ):
            grid.addWidget(muted(key), r, 0)
            val = QLabel()
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setStyleSheet("font-size: 11pt;")
            grid.addWidget(val, r, 1)
            self.rows[key] = val
        r = len(self.rows)
        grid.addWidget(muted(strings.ROW_ALARMS), r, 0)
        self.alarm_btn = QToolButton()
        self.alarm_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.alarm_btn.setToolTip(strings.TIP_ALARMS)
        self.alarm_btn.clicked.connect(self.alarms_requested)
        grid.addWidget(self.alarm_btn, r, 1, Qt.AlignRight)
        v.addLayout(grid)
        v.addStretch(1)
        return panel

    def _build_chart(self) -> QFrame:
        box = card()
        v = QVBoxLayout(box)
        v.setContentsMargins(18, 12, 18, 12)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("chart", theme.BLUE, 22))
        head.addWidget(ic)
        t = QLabel(strings.CHART_TITLE)
        t.setStyleSheet("font-size: 12pt;")
        head.addWidget(t)
        head.addStretch(1)
        # Both panels use the same colour meaning (SOC in pastel shades).
        for text, color in ((strings.LEGEND_CHARGE, CHARGE_COLOR),
                            (strings.LEGEND_DISCHARGE, DISCHARGE_COLOR),
                            (strings.LEGEND_IDLE, ZERO_COLOR)):
            dot = StatusDot(10)
            dot.set_color(color)
            head.addWidget(dot)
            head.addWidget(QLabel(text))
            head.addSpacing(10)
        group = QButtonGroup(self)
        for text, span in strings.CHART_RANGES:
            b = QPushButton(text)
            b.setProperty("range", True)
            b.setCheckable(True)
            b.setChecked(span == self.span_s)
            b.clicked.connect(lambda _=False, s=span: self._set_span(s))
            group.addButton(b)
            head.addWidget(b)
        v.addLayout(head)
        self.chart = HistoryChart()
        v.addWidget(self.chart, 1)
        return box

    def _set_span(self, span_s: float) -> None:
        self.span_s = span_s
        self.refresh_chart(force=True)

    # ----- updates ----------------------------------------------------------
    def refresh_chart(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._chart_at < CHART_REFRESH_S:
            return
        self._chart_at = now
        self.chart.set_data(
            self.history.series(self.span_s, time.time()), self.span_s, strings.CHART_EMPTY
        )

    def showEvent(self, event) -> None:
        self.refresh_chart(force=True)
        super().showEvent(event)

    def update_view(self, snap: Snapshot) -> None:
        # Every setter goes through self.upd, so unchanged values cost nothing.
        upd = self.upd
        self._snap = snap
        cell, stale = snap.cell, snap.stale
        status_color = theme.STATUS_COLORS.get(snap.status, theme.GREY)
        upd("status", strings.STATUS_TEXT.get(snap.status, snap.status), self.status_text.setText)
        upd("status_style", status_color, lambda c: self.status_text.setStyleSheet(
            f"color: {c}; font-size: 12pt;"))
        upd("status_tip", snap.status_detail, self.status_text.setToolTip)
        self.status_dot.set_color(status_color)
        connected = snap.status in ("connecting", "connected", "lost", "replay")
        upd("connect", strings.MENU_DISCONNECT if connected else strings.MENU_CONNECT,
            self.connect_btn.setText)

        self.ring.set_value(None if cell is None else cell.soc, stale)
        alarm_button_style(self.alarm_btn, snap, 18, upd, none_text=strings.ALARMS_NONE)

        if cell is None:
            for t, unit in ((self.tile_current, "A"), (self.tile_power, "W"),
                            (self.tile_voltage, "V"), (self.tile_temp, "°C")):
                t.set_value(strings.NO_VALUE, unit, True)
            upd("time_left", value_html(strings.NO_VALUE, "", 18, theme.MUTED), self.time_left.setText)
            upd("time_kind", "", self.time_left_kind.setText)
            for key, lbl in self.rows.items():
                upd(f"row{key}", strings.NO_VALUE, lbl.setText)
            self._set_health("check", theme.GREY, strings.HEALTH_NO_DATA, strings.HEALTH_NO_DATA_SUB)
            self.refresh_chart()
            return

        self.tile_current.set_value(strings.fmt_current(cell.current), "A", stale)
        self.tile_power.set_value(*strings.fmt_power(cell.power), stale)
        self.tile_voltage.set_value(strings.fmt_voltage(cell.pack_voltage), "V", stale)
        temp = max(cell.temperature_1, cell.temperature_2)
        self.tile_temp.set_value(f"{temp:.0f}", "°C", stale)
        upd("temp_tip", strings.TEMP_TOOLTIP.format(
            t1=cell.temperature_1, t2=cell.temperature_2, mos=cell.mosfet_temperature),
            self.tile_temp.setToolTip)

        upd("time_left", value_html(strings.fmt_hours(snap.hours_left), "", 18,
                                    theme.MUTED if stale else theme.TEXT), self.time_left.setText)
        upd("time_kind", strings.TIME_LEFT_KIND[snap.left_kind], self.time_left_kind.setText)

        mode = self.rows[strings.ROW_MODE]
        state_color = theme.MUTED if stale else STATE_COLORS.get(snap.state, theme.TEXT)
        upd(f"row{strings.ROW_MODE}", strings.STATE_NAMES[snap.state], mode.setText)
        upd("mode_style", state_color,
            lambda c: mode.setStyleSheet(f"font-size: 11pt; color: {c};"))
        upd(f"row{strings.ROW_TIME_LEFT}", strings.fmt_hours(snap.hours_left),
            self.rows[strings.ROW_TIME_LEFT].setText)
        delta_mv = (cell.cell_max - cell.cell_min) * 1000
        cells_lbl = self.rows[strings.ROW_CELLS]
        upd(f"row{strings.ROW_CELLS}", f"{cell.cell_min:.3f} – {cell.cell_max:.3f} V",
            cells_lbl.setText)
        upd("cells_tip",
            "\n".join(f"#{n}: {v:.3f} V" for n, v in enumerate(cell.cell_voltages, 1))
            + f"\nΔ {delta_mv:.0f} mV", cells_lbl.setToolTip)
        upd(f"row{strings.ROW_BALANCING}", strings.YES if cell.balancing else strings.NO,
            self.rows[strings.ROW_BALANCING].setText)
        upd(f"row{strings.ROW_MOSFETS}",
            f"{strings.ON if cell.charging_enabled else strings.OFF} / "
            f"{strings.ON if cell.discharging_enabled else strings.OFF}",
            self.rows[strings.ROW_MOSFETS].setText)

        faults = snap.fault_alarms
        if stale:
            self._set_health("warning", theme.GREY, strings.HEALTH_STALE, strings.HEALTH_STALE_SUB)
        elif faults:
            names = ", ".join(strings.alarm_text(b) for b in faults[:2])
            self._set_health("warning", theme.RED, strings.HEALTH_ALARM.format(n=len(faults)), names)
        else:
            self._set_health("check", theme.GREEN, strings.HEALTH_OK, strings.HEALTH_OK_SUB)
        self.refresh_chart()

    def _set_health(self, icon_name: str, color: str, title: str, sub: str) -> None:
        upd = self.upd
        upd("health_icon", (icon_name, color),
            lambda v: self.health_icon.setIcon(icons.icon(v[0], v[1], 44)))
        upd("health_title", title, self.health_title.setText)
        upd("health_style", color, lambda c: self.health_title.setStyleSheet(
            f"font-size: 15pt; font-weight: 600; color: {c};"))
        upd("health_sub", sub, self.health_sub.setText)

    def contextMenuEvent(self, event) -> None:
        self.context_menu.emit(event.globalPos())
