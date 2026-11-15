"""Dashboard title-bar BMS selector with an eye per BMS.

A plain QComboBox closes its popup on any click, so an eye toggle inside
it is impossible. This is a button with a menu of row widgets instead:
clicking a name shows that BMS (menu closes), clicking the eye shows /
hides its taskbar strip or widget (menu stays open). Owner's request
2026-11-15.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QToolButton, QWidget, QWidgetAction

from .. import strings
from . import icons, theme


def eye_icon(visible: bool):
    return icons.icon("eye" if visible else "eye_off", theme.TEXT if visible else theme.MUTED, 20)


class BmsSelector(QToolButton):
    selected = Signal(int)
    visibility_toggled = Signal(int, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # No setMenu(): Qt's own menu indicator left a stray pixel. The menu is
        # opened by hand and the chevron is painted here, so it can rotate.
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setToolTip(strings.DASH_SELECT_TIP)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("bmsSelector")
        self.setStyleSheet(
            f"QToolButton#bmsSelector {{ background: {theme.CARD}; border: 1px solid {theme.CARD_BORDER};"
            f" border-radius: 6px; padding: 4px 26px 4px 10px; color: {theme.TEXT}; }}"
            f"QToolButton#bmsSelector:hover {{ border-color: {theme.GREY}; }}")
        self.menu_ = QMenu(self)
        self.menu_.aboutToShow.connect(self._fill)
        self.menu_.aboutToShow.connect(lambda: self._turn(180.0))
        self.menu_.aboutToHide.connect(self._on_hide)
        self._hidden_at = 0.0  # monotonic time the menu last closed
        self.clicked.connect(self._open)
        self._angle = 0.0  # chevron rotation: 0 = down (closed), 180 = up (open)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_angle)
        self.names: list[str] = []
        self.visible: list[bool] = []
        self.active = 0

    def set_items(self, names: list[str], visible: list[bool], active: int) -> None:
        self.names, self.visible, self.active = list(names), list(visible), active
        if names:
            self.setText(f"{active + 1}. {names[active]}")

    def _fill(self) -> None:
        self.menu_.clear()
        for i, name in enumerate(self.names):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(6, 2, 6, 2)
            pick = QPushButton(f"{i + 1}. {name}")
            pick.setFlat(True)
            pick.setCursor(Qt.PointingHandCursor)
            weight = "600" if i == self.active else "400"
            pick.setStyleSheet(f"text-align: left; padding: 6px 8px; font-weight: {weight};"
                               f" color: {theme.TEXT}; border: none;")
            pick.clicked.connect(lambda _=False, i=i: self._pick(i))
            h.addWidget(pick, 1)
            eye = QToolButton()
            eye.setCheckable(True)
            eye.setChecked(self.visible[i])
            eye.setIcon(eye_icon(self.visible[i]))
            eye.setIconSize(QSize(20, 20))
            eye.setToolTip(strings.TIP_EYE)
            eye.toggled.connect(lambda on, i=i, b=eye: self._eye(i, on, b))
            h.addWidget(eye)
            action = QWidgetAction(self.menu_)
            action.setDefaultWidget(row)
            self.menu_.addAction(action)

    def _open(self) -> None:
        self.menu_.popup(self.mapToGlobal(QPoint(0, self.height() + 2)))

    def _on_hide(self) -> None:
        self._hidden_at = time.monotonic()
        self._turn(0.0)

    # A press on this button while the menu is open first closes the menu
    # (Qt closes popups on any outside press) and is then replayed to the
    # button, whose click would reopen it at once. Swallow that press, so a
    # second click closes the menu like a normal drop-down.
    REOPEN_GUARD_S = 0.25

    def mousePressEvent(self, event) -> None:
        if time.monotonic() - self._hidden_at < self.REOPEN_GUARD_S:
            event.accept()
            return
        super().mousePressEvent(event)

    def _turn(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._angle)
        self._anim.setEndValue(target)
        self._anim.start()

    def _set_angle(self, value) -> None:
        self._angle = float(value)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(self.width() - 15, self.height() / 2)
        p.rotate(self._angle)
        chevron = QPainterPath()
        chevron.moveTo(QPointF(-4, -2))
        chevron.lineTo(QPointF(0, 2))
        chevron.lineTo(QPointF(4, -2))
        p.setPen(QPen(QColor(theme.MUTED), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(chevron)

    def _pick(self, index: int) -> None:
        self.menu_.close()
        self.selected.emit(index)

    def _eye(self, index: int, on: bool, button: QToolButton) -> None:
        button.setIcon(eye_icon(on))  # the menu stays open
        self.visible[index] = on
        self.visibility_toggled.emit(index, on)
