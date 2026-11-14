"""Settings window (gear button). Every change is applied immediately."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from .. import strings
from ..settings import Settings
from . import theme
from .compact import icon_button
from .widgets import DragMover, rounded_corners

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("section", True)
    return lbl


def _note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("muted", True)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("font-size: 9pt;")
    return lbl


class SettingsDialog(QDialog):
    pick_requested = Signal()
    mode_changed = Signal(str)  # "widget" / "taskbar"
    scale_changed = Signal(float)
    language_changed = Signal(str)  # "auto" / "uk" / "en"
    threshold_changed = Signal(float)
    fullscreen_changed = Signal(str)  # "hide" / "corner"
    dim_changed = Signal(bool)
    autostart_changed = Signal(bool)
    open_folder = Signal()

    def __init__(self, settings: Settings, autostart_on: bool, autostart_available: bool,
                 replay: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.SETTINGS_TITLE)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        rounded_corners(self)
        self.setMinimumWidth(440)

        root = QFrame(objectName="root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 12, 20, 18)
        lay.setSpacing(10)

        # Header (draggable) with a close button.
        header = QFrame()
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        title = QLabel(strings.SETTINGS_TITLE)
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        h.addWidget(title)
        h.addStretch(1)
        close = icon_button("close", theme.TEXT, 18, strings.CLOSE)
        close.clicked.connect(self.accept)
        h.addWidget(close)
        lay.addWidget(header)
        DragMover(self).attach(header)

        # --- BMS --------------------------------------------------------------
        lay.addWidget(_section(strings.SECTION_BMS))
        bms_row = QHBoxLayout()
        bms_col = QVBoxLayout()
        bms_col.setSpacing(0)
        self.bms_name = QLabel()
        self.bms_name.setStyleSheet("font-size: 11pt; font-weight: 600;")
        self.bms_addr = QLabel()
        self.bms_addr.setProperty("muted", True)
        bms_col.addWidget(self.bms_name)
        bms_col.addWidget(self.bms_addr)
        bms_row.addLayout(bms_col, 1)
        change = QPushButton(strings.BMS_CHANGE)
        change.setProperty("secondary", True)
        change.setEnabled(not replay)
        change.clicked.connect(self.pick_requested)
        bms_row.addWidget(change)
        lay.addLayout(bms_row)
        if replay:
            lay.addWidget(_note(strings.REPLAY_NOTE))
        self.set_bms(settings.bms_name, settings.address)
        lay.addWidget(QFrame(objectName="line"))

        # --- Display ----------------------------------------------------------
        lay.addWidget(_section(strings.SECTION_DISPLAY))
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QRadioButton] = {}
        for mode, text in (("widget", strings.MODE_WIDGET), ("taskbar", strings.MODE_TASKBAR)):
            rb = QRadioButton(text)
            self.mode_group.addButton(rb)
            self.mode_buttons[mode] = rb
            rb.toggled.connect(lambda on, m=mode: on and self.mode_changed.emit(m))
            lay.addWidget(rb)
        self.set_mode(settings.display_mode)

        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        # Row 0: full-screen behaviour of the strip; row 1: scale; row 2: language.
        grid.addWidget(QLabel(strings.FULLSCREEN_LABEL), 0, 0)
        self.fullscreen = QComboBox()
        for key, text in strings.FULLSCREEN_OPTIONS:
            self.fullscreen.addItem(text, key)
        self.fullscreen.setCurrentIndex(max(0, self.fullscreen.findData(settings.fullscreen_behavior)))
        self.fullscreen.currentIndexChanged.connect(
            lambda i: self.fullscreen_changed.emit(self.fullscreen.itemData(i)))
        grid.addWidget(self.fullscreen, 0, 1, Qt.AlignRight)
        grid.addWidget(QLabel(strings.SCALE_LABEL), 1, 0)
        self.scale = QComboBox()
        for s in SCALES:
            self.scale.addItem(f"{s * 100:.0f}%", s)
        nearest = min(range(len(SCALES)), key=lambda i: abs(SCALES[i] - settings.ui_scale))
        self.scale.setCurrentIndex(nearest)
        self.scale.currentIndexChanged.connect(
            lambda i: self.scale_changed.emit(self.scale.itemData(i)))
        grid.addWidget(self.scale, 1, 1, Qt.AlignRight)
        grid.addWidget(QLabel(strings.LANGUAGE_LABEL), 2, 0)
        self.language = QComboBox()
        for key, text in strings.LANGUAGE_OPTIONS:
            self.language.addItem(text, key)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.language)))
        self.language.currentIndexChanged.connect(
            lambda i: self.language_changed.emit(self.language.itemData(i)))
        grid.addWidget(self.language, 2, 1, Qt.AlignRight)
        lay.addLayout(grid)
        lay.addWidget(_note(strings.SCALE_NOTE))
        self.dim = QCheckBox(strings.DIM_LABEL)
        self.dim.setChecked(settings.dim_when_maximized)
        self.dim.toggled.connect(self.dim_changed)
        lay.addWidget(self.dim)
        lay.addWidget(_note(strings.DIM_NOTE))
        lay.addWidget(QFrame(objectName="line"))

        # --- Battery ----------------------------------------------------------
        lay.addWidget(_section(strings.SECTION_BATTERY))
        row = QHBoxLayout()
        row.addWidget(QLabel(strings.IDLE_LABEL), 1)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.1, 50.0)
        self.threshold.setSingleStep(0.1)
        self.threshold.setDecimals(1)
        self.threshold.setSuffix(" A")
        # Arrow buttons are hidden by the stylesheet (width 0). Don't use
        # setButtonSymbols(NoButtons): with a stylesheet Qt then shrinks the
        # text field to 1 px. Mouse wheel and Up/Down keys change the value.
        self.threshold.setMinimumWidth(90)
        self.threshold.setValue(settings.idle_threshold)
        self.threshold.valueChanged.connect(self.threshold_changed)
        row.addWidget(self.threshold)
        lay.addLayout(row)
        lay.addWidget(_note(strings.IDLE_NOTE))
        lay.addWidget(QFrame(objectName="line"))

        # --- System -----------------------------------------------------------
        lay.addWidget(_section(strings.SECTION_SYSTEM))
        self.autostart = QCheckBox(strings.MENU_AUTOSTART)
        self.autostart.setChecked(autostart_on)
        self.autostart.setEnabled(autostart_available)
        if not autostart_available:
            self.autostart.setToolTip(strings.TIP_AUTOSTART_DEV)
        self.autostart.toggled.connect(self.autostart_changed)
        lay.addWidget(self.autostart)
        if not autostart_available:
            lay.addWidget(_note(strings.TIP_AUTOSTART_DEV))
        folder = QPushButton(strings.MENU_SETTINGS_FOLDER)
        folder.setProperty("secondary", True)
        folder.clicked.connect(self.open_folder)
        lay.addWidget(folder, 0, Qt.AlignLeft)

        lay.addSpacing(6)
        done = QPushButton(strings.SETTINGS_DONE)
        done.setProperty("primary", True)
        done.clicked.connect(self.accept)
        lay.addWidget(done, 0, Qt.AlignRight)

    def set_bms(self, name: str, address: str | None) -> None:
        self.bms_name.setText(name or (strings.BMS_NOT_SET if not address else "—"))
        self.bms_addr.setText(address or "")

    def set_mode(self, mode: str) -> None:
        """Reflect the effective mode (the controller may refuse 'taskbar')."""
        rb = self.mode_buttons.get(mode)
        if rb is not None and not rb.isChecked():
            rb.blockSignals(True)
            rb.setChecked(True)
            rb.blockSignals(False)
