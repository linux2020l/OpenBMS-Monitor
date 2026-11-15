"""Compact data strip shown over the Windows taskbar (taskbar display mode).

A frameless, always-on-top tool window placed left of the tray. It follows
the taskbar (position/size/DPI) and can be dragged left/right along it.
While a full-screen app or game is active it either hides or moves to the
bottom-right corner of the screen (setting `fullscreen_behavior`).

Left: battery icon (fill = SOC, bolt while charging, red badge on faults).
Clicking the icon opens the alarm list when there are faults, otherwise the
dashboard; clicking anywhere else opens the dashboard.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter
from PySide6.QtWidgets import QToolTip, QWidget

from .. import strings
from .. import win_taskbar as wt
from ..state import CHARGING, DISCHARGING, Snapshot
from . import icons, theme
from .widgets import native_hwnd

log = logging.getLogger(__name__)

STRIP_WIDTH = 236  # logical px
DRAG_THRESHOLD = 4  # px of movement before a press becomes a drag
CORNER_MARGIN = 12  # logical px from the screen edges in "corner" mode
CORNER_HEIGHT = 42
SLOT_GAP = 6  # px between strips when several BMS are shown
NUMBER_WIDTH = 10  # px left of the battery icon for the BMS number
ICON_RECT = QRectF(8, 0, 30, 16)  # battery icon; y is centred at paint time


class TaskbarStrip(QWidget):
    clicked = Signal()  # left click without dragging (outside the icon / no faults)
    alarms_clicked = Signal()  # click on the battery icon while faults are active
    context_menu = Signal(QPoint)  # right click, global position
    offset_changed = Signal(int)  # user dragged the strip (logical px)

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        # Must stay translucent: it sits on top of the taskbar's own background.
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowTitle(strings.APP_TITLE)
        self.snap = Snapshot(cell=None)
        self.offset: int | None = None  # group offset; None = right next to the tray
        self.slot = 0  # position in the group (several BMS: one strip each, right to left)
        self.number: int | str | None = None  # BMS number / bank letter left of the icon
        self.wanted = False  # taskbar mode is on
        self.fullscreen_behavior = "hide"  # or "corner"
        self.light = False
        self.in_corner = False
        self._fullscreen = False
        self._hover = False
        self._press: QPoint | None = None
        self._press_offset = 0
        self._dragging = False
        self._info: wt.TaskbarInfo | None = None

        # Follow the taskbar and win back the topmost position twice a second.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.reposition)

    # ----- public -----------------------------------------------------------
    def set_wanted(self, wanted: bool) -> None:
        self.wanted = wanted
        if wanted:
            self.timer.start(500)
            self.reposition()
        else:
            self.timer.stop()
            self.hide()

    def update_view(self, snap: Snapshot) -> None:
        if snap != self.snap:
            self.snap = snap
            self.update()

    # ----- placement --------------------------------------------------------
    def _dpr(self) -> float:
        return QGuiApplication.primaryScreen().devicePixelRatio()

    def _corner_geometry(self) -> tuple[int, int, int, int]:
        screen = QGuiApplication.primaryScreen().geometry()  # full screen, not work area
        return (screen.right() - STRIP_WIDTH - CORNER_MARGIN + 1,
                screen.bottom() - CORNER_HEIGHT - CORNER_MARGIN + 1
                - self.slot * (CORNER_HEIGHT + SLOT_GAP),  # several BMS: stacked upwards
                STRIP_WIDTH, CORNER_HEIGHT)

    def _effective_offset(self, info: wt.TaskbarInfo | None) -> int | None:
        """This strip's offset from the taskbar edge: group offset + its slot."""
        base = self.offset
        if base is None:
            if not self.slot:
                return None  # first strip, default place: strip_geometry decides
            base = wt.default_offset(info, self._dpr()) if info else wt.FALLBACK_OFFSET
        return base + self.slot * (STRIP_WIDTH + SLOT_GAP)

    def reposition(self) -> None:
        if not self.wanted:
            return
        if self._dragging:
            return
        fullscreen = wt.fullscreen_app_active()
        if fullscreen != self._fullscreen:
            self._fullscreen = fullscreen
            log.info("full-screen %s (foreground %s)", "on" if fullscreen else "off",
                     wt.foreground_class() or "?")
        if fullscreen:
            if self.fullscreen_behavior != "corner":
                self.hide()  # a game/video is full-screen: get out of the way
                return
            geo, corner = self._corner_geometry(), True
        else:
            info = wt.taskbar_info()
            self._info = info
            geo = None if info is None else wt.strip_geometry(info, self._dpr(), STRIP_WIDTH,
                                                       self._effective_offset(info))
            corner = False
            if geo is None:
                self.hide()  # vertical / auto-hide taskbar: not supported
                return
            self.light = wt.taskbar_uses_light_theme()
        if corner != self.in_corner:
            self.in_corner = corner
            self.update()
        if tuple(self.geometry().getRect()) != geo:
            self.setGeometry(*geo)
        if not self.isVisible():
            self.show()
            # Windows may place a new tool window on its first show; put it
            # where it belongs right away (owner saw new strips overlap).
            if tuple(self.geometry().getRect()) != geo:
                self.setGeometry(*geo)
        wt.keep_on_top(native_hwnd(self))

    # ----- painting ---------------------------------------------------------
    def set_number(self, number: int | str | None) -> None:
        if number != self.number:
            self.number = number
            self.update()

    def _icon_rect(self) -> QRectF:
        r = QRectF(ICON_RECT)
        r.moveTop(self.height() / 2 - r.height() / 2)
        if self.number is not None:
            r.translate(NUMBER_WIDTH, 0)  # room for the BMS number
        return r

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        light = self.light and not self.in_corner
        if self.in_corner:
            # Over a game/video: solid dark card so the text stays readable.
            p.setPen(QColor(theme.CARD_BORDER))
            p.setBrush(QColor(16, 19, 26, 235))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        else:
            # Alpha 1 instead of 0: fully transparent pixels would be click-through.
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(128, 128, 128, 40 if self._hover else 1))
            p.drawRoundedRect(r, 6, 6)

        snap, cell = self.snap, self.snap.cell
        text = QColor("#1f2328" if light else theme.TEXT)
        muted = QColor("#5b6472" if light else theme.MUTED)
        if snap.stale:
            text = muted
        h = r.height()

        # BMS number when several are shown (same as in the settings list).
        if self.number is not None:
            p.setFont(QFont(theme.FONT_FAMILY, 8, QFont.Bold))
            # Amber letter: a BMS of this bank has no fresh data (details in the tooltip).
            p.setPen(QColor(theme.AMBER) if snap.partial
                     else (QColor(theme.RED) if snap.missing else muted))
            p.drawText(QRectF(2, 0, NUMBER_WIDTH, h), Qt.AlignCenter, str(self.number))

        # Battery icon (replaces the old status dot and the right-hand check).
        icon_rect = self._icon_rect()
        outline = muted.name() if (snap.stale or cell is None) else text.name()
        fill = theme.GREY if snap.stale else (theme.soc_color(cell.soc, snap.low_soc) if cell else theme.GREY)
        icons.paint_battery(
            p, icon_rect,
            soc=None if cell is None else cell.soc,
            fill=fill, outline=outline,
            charging=bool(cell) and not snap.stale and snap.state == CHARGING,
            fault=bool(snap.fault_alarms),
        )
        x = icon_rect.right() + 8

        big = QFont(theme.FONT_FAMILY, 13, QFont.Bold)
        p.setFont(big)
        soc_text = f"{cell.soc}%" if cell else f"{strings.NO_VALUE}%"
        soc_color = QColor(theme.soc_color(cell.soc, snap.low_soc)) if cell and not snap.stale else text
        p.setPen(soc_color)
        fm = QFontMetricsF(big)
        p.drawText(QPointF(x, h / 2 + fm.capHeight() / 2), soc_text)
        x += fm.horizontalAdvance(soc_text) + 10

        small = QFont(theme.FONT_FAMILY, 8)
        p.setFont(small)
        fs = QFontMetricsF(small)
        if cell:
            line1 = f"{strings.fmt_voltage(cell.pack_voltage)} V   {strings.fmt_current(cell.current)} A"
            power, unit = strings.fmt_power(cell.power)
            # Time to empty / full instead of the state word; charge vs discharge
            # is visible through the bolt and the colour of this line.
            tail = (strings.fmt_time_left_short(snap.hours_left, snap.left_kind)
                    or strings.STATE_NAMES[snap.state])
            line2 = f"{power} {unit}   {tail}"
        else:
            line1 = strings.STATUS_TEXT.get(snap.status, snap.status)
            line2 = ""
        p.setPen(text)
        p.drawText(QPointF(x, h / 2 - 2), line1)
        state_color = {CHARGING: theme.GREEN, DISCHARGING: theme.AMBER}.get(snap.state)
        p.setPen(QColor(state_color) if (state_color and not snap.stale and cell) else muted)
        p.drawText(QPointF(x, h / 2 + fs.ascent() + 1), line2)

    def icon_tooltip(self) -> str:
        snap = self.snap
        if snap.fault_alarms:
            text = "\n".join(strings.alarm_text(b) for b in snap.fault_alarms)
        elif snap.cell is None or snap.status not in ("connected", "replay"):
            text = strings.STATUS_TEXT.get(snap.status, snap.status)
        else:
            text = strings.NO_ALARMS
        if snap.partial:
            text = (strings.BANK_PARTIAL.format(n=len(snap.offline), total=snap.members) + "\n"
                    + strings.partial_note(snap) + "\n" + text)
        elif snap.missing:
            text = (strings.BANK_NO_DATA + "\n"
                    + strings.BANK_NO_DATA_SUB.format(names=", ".join(snap.missing)))
        if snap.is_low:
            text = strings.LOW_SOC_STATE.format(t=snap.low_soc) + "\n" + text
        # Several strips side by side: say which BMS this one is.
        return f"{snap.device_name}\n{text}" if snap.device_name else text

    # ----- mouse ------------------------------------------------------------
    def enterEvent(self, _e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._press_local = e.position()
            info = self._info
            eff = self._effective_offset(info)
            self._press_offset = (
                eff if eff is not None
                else (wt.default_offset(info, self._dpr()) if info else wt.FALLBACK_OFFSET)
            )
            self._dragging = False

    def mouseMoveEvent(self, e) -> None:
        if self._press is None:
            # Hover: show alarm/status details over the battery icon.
            if self._icon_rect().adjusted(-4, -8, 8, 8).contains(e.position()):
                QToolTip.showText(e.globalPosition().toPoint(), self.icon_tooltip(), self)
            return
        if self._info is None or self.in_corner:
            return  # no dragging in the full-screen corner
        dx = e.globalPosition().toPoint().x() - self._press.x()
        if not self._dragging and abs(dx) < DRAG_THRESHOLD:
            return
        self._dragging = True
        new_offset = self._press_offset - dx  # moving right = closer to the edge
        geo = wt.strip_geometry(self._info, self._dpr(), STRIP_WIDTH, new_offset)
        if geo:
            self.setGeometry(*geo)
            eff = int(self._info.right / self._dpr()) - (geo[0] + geo[2])
            self.offset = eff - self.slot * (STRIP_WIDTH + SLOT_GAP)  # group offset

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton or self._press is None:
            return
        if self._dragging:
            self.offset_changed.emit(int(self.offset))
        elif self.snap.fault_alarms and self._icon_rect().adjusted(-4, -8, 8, 8).contains(
                self._press_local):
            self.alarms_clicked.emit()
        else:
            self.clicked.emit()
        self._press, self._dragging = None, False

    def contextMenuEvent(self, e) -> None:
        self.context_menu.emit(e.globalPos())
