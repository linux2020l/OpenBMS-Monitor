"""Popup with the list of active alarms in plain language."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import strings
from ..parser import INFORMATIONAL_ALARM_BITS
from . import icons, theme
from .widgets import DragMover, rounded_corners


class AlarmDialog(QDialog):
    def __init__(self, alarms: tuple[int, ...], stale: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.ALARMS_TITLE)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        rounded_corners(self)
        self.setMinimumWidth(340)

        root = QFrame(objectName="root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        title = QLabel(strings.ALARMS_TITLE)
        title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        lay.addWidget(title)

        if stale:
            note = QLabel(strings.ALARMS_STALE)
            note.setProperty("muted", True)
            note.setWordWrap(True)
            lay.addWidget(note)

        if not alarms:
            row = QHBoxLayout()
            ic = QLabel()
            ic.setPixmap(icons.pixmap("check", theme.GREEN, 20))
            row.addWidget(ic)
            row.addWidget(QLabel(strings.NO_ALARMS), 1)
            lay.addLayout(row)
        for bit in alarms:
            info = bit in INFORMATIONAL_ALARM_BITS
            row = QHBoxLayout()
            ic = QLabel()
            ic.setPixmap(icons.pixmap("info" if info else "warning",
                                      theme.BLUE if info else theme.RED, 20))
            text = QLabel(strings.alarm_text(bit))
            text.setWordWrap(True)
            row.addWidget(ic)
            row.addWidget(text, 1)
            lay.addLayout(row)

        close = QPushButton(strings.CLOSE)
        close.clicked.connect(self.accept)
        close.setProperty("secondary", True)
        lay.addWidget(close, 0, Qt.AlignRight)
        DragMover(self).attach(root)
