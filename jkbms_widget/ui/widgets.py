"""Reusable widgets/helpers: drag mover, Win32 window helpers, SOC ring,
status dot, Updater. The history chart lives in chart.py."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme


class DragMover(QObject):
    """Lets the user drag a frameless window by a widget (event filter).

    Usage: DragMover(window).attach(widget). Clicks on labels inside the
    widget propagate up to it; buttons keep working normally. Uses Qt's
    system move, so Windows handles snapping and multiple monitors.
    """

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window = window

    def attach(self, widget: QWidget) -> None:
        widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            handle = self.window.windowHandle()
            if handle is not None and handle.startSystemMove():
                return True
        return False


def native_hwnd(window: QWidget) -> int:
    """Real Win32 HWND of a window, or 0 when Qt isn't drawing native windows.

    Under QT_QPA_PLATFORM=offscreen (tests, screenshots) winId() is just a
    counter; passing it to Win32 could hit an unrelated window, so all Win32
    calls must go through this.
    """
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "windows":
        return 0
    return int(window.winId())


def rounded_corners(window: QWidget) -> None:
    """Native Windows 11 rounded corners + border for a frameless window."""
    from .. import win_taskbar

    win_taskbar.native_rounded_corners(native_hwnd(window), theme.CARD_BORDER)


DIM_OPACITY = 0.45  # owner's request: see-through while a window is maximized


def set_dimmed(window: QWidget, dimmed: bool) -> None:
    """Semi-transparent + click-through (mouse goes to the window underneath)."""
    from .. import win_taskbar

    hwnd = native_hwnd(window)
    if dimmed:
        window.setWindowOpacity(DIM_OPACITY)  # makes the window layered
        win_taskbar.set_click_through(hwnd, True)
    else:
        win_taskbar.set_click_through(hwnd, False)
        window.setWindowOpacity(1.0)


_MISSING = object()


class Updater:
    """Apply a UI property only when its value changed.

    The views are refreshed several times per second; calling setStyleSheet
    or setIcon each time re-polishes widgets and floods the event queue,
    which made button hover effects lag. Usage: upd("key", value, setter).
    """

    def __init__(self) -> None:
        self._last: dict[str, object] = {}

    def __call__(self, key: str, value, apply) -> None:
        if self._last.get(key, _MISSING) != value:
            self._last[key] = value
            apply(value)


class StatusDot(QWidget):
    def __init__(self, size: int = 10, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(theme.GREY)
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        if QColor(color) != self._color:
            self._color = QColor(color)
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class SocRing(QWidget):
    """Circular SOC gauge like in the mockup."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.soc: float | None = None
        self.stale = True
        self.setMinimumSize(180, 180)

    def set_value(self, soc: float | None, stale: bool) -> None:
        if (soc, stale) != (self.soc, self.stale):
            self.soc, self.stale = soc, stale
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 4
        thick = side * 0.085
        rect = QRectF(
            (self.width() - side) / 2 + thick / 2,
            (self.height() - side) / 2 + thick / 2,
            side - thick,
            side - thick,
        )
        p.setPen(QPen(QColor(theme.TRACK), thick, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 0, 360 * 16)

        soc = self.soc
        color = theme.GREY if (self.stale or soc is None) else theme.soc_color(soc)
        if soc:
            p.setPen(QPen(QColor(color), thick, Qt.SolidLine, Qt.RoundCap))
            # Qt angles: 1/16 degree, 0 = 3 o'clock, positive = counter-clockwise.
            p.drawArc(rect, 90 * 16, -int(min(soc, 100) * 3.6 * 16))

        # Big number + smaller "%" centered, "SOC" below.
        number = "—" if soc is None else f"{soc:.0f}"
        big = QFont(theme.FONT_FAMILY, max(10, int(side * 0.2)), QFont.Bold)
        small = QFont(theme.FONT_FAMILY, max(8, int(side * 0.09)), QFont.DemiBold)
        fm_big, fm_small = QFontMetricsF(big), QFontMetricsF(small)
        pct = "" if soc is None else "%"
        total_w = fm_big.horizontalAdvance(number) + fm_small.horizontalAdvance(pct)
        cx, cy = self.width() / 2, self.height() / 2
        x = cx - total_w / 2
        base = cy + fm_big.ascent() * 0.35
        p.setPen(QColor(theme.MUTED if self.stale else theme.TEXT))
        p.setFont(big)
        p.drawText(QPointF(x, base), number)
        p.setFont(small)
        p.drawText(QPointF(x + fm_big.horizontalAdvance(number) + 2, base), pct)

        label = QFont(theme.FONT_FAMILY, max(7, int(side * 0.065)))
        p.setFont(label)
        p.setPen(QColor(theme.MUTED))
        fm = QFontMetricsF(label)
        p.drawText(QPointF(cx - fm.horizontalAdvance("SOC") / 2, base + fm.height() * 1.4), "SOC")
