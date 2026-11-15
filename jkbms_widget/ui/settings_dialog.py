"""Settings window (gear button), in tabs. Every change is applied immediately."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
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
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import strings
from ..settings import Settings
from . import icons, theme
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


def _page() -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(4, 12, 4, 4)
    lay.setSpacing(10)
    return page, lay


class SettingsDialog(QDialog):
    """Settings in tabs (owner's choice 2026-11-15: the single page got taller
    than a 1080p screen at 150 %). Every change is applied immediately."""

    add_requested = Signal()
    change_requested = Signal(int)  # index in the BMS list
    remove_requested = Signal(int)
    visibility_changed = Signal(int, bool)  # eye toggle: show this BMS's strip / widget
    bank_add_requested = Signal()
    bank_edit_requested = Signal(int)  # index in the bank list
    bank_remove_requested = Signal(int)
    bank_visibility_changed = Signal(int, bool)
    desktop_changed = Signal(bool)  # floating widgets pinned to the desktop
    updates_changed = Signal(bool)  # daily update check on / off
    update_check_requested = Signal()
    mode_changed = Signal(str)  # "widget" / "taskbar"
    scale_changed = Signal(float)
    language_changed = Signal(str)  # "auto" / "uk" / "en"
    threshold_changed = Signal(float)
    fullscreen_changed = Signal(str)  # "hide" / "corner"
    dim_changed = Signal(bool)
    autostart_changed = Signal(bool)
    open_folder = Signal()
    diagnostics_requested = Signal()
    export_requested = Signal()
    notify_changed = Signal(bool)
    low_soc_changed = Signal(int)

    def __init__(self, settings: Settings, autostart_on: bool, autostart_available: bool,
                 replay: bool = False, devices: list[tuple[str, str, bool]] | None = None,
                 parent=None, banks: list[tuple[str, str, str, bool]] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.SETTINGS_TITLE)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        rounded_corners(self)
        self.setMinimumWidth(480)
        self.replay = replay

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

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        lay.addWidget(self.tabs, 1)

        # --- BMS ----------------------------------------------------------------
        page, p = _page()
        self.devices = QListWidget()
        self.devices.setMinimumHeight(150)
        self.devices.itemSelectionChanged.connect(self._update_buttons)
        p.addWidget(self.devices, 1)
        row = QHBoxLayout()
        self.add_btn = QPushButton(strings.BMS_ADD)
        self.change_btn = QPushButton(strings.BMS_CHANGE)
        self.remove_btn = QPushButton(strings.BMS_REMOVE)
        for b in (self.add_btn, self.change_btn, self.remove_btn):
            b.setProperty("secondary", True)
            row.addWidget(b)
        row.addStretch(1)
        self.add_btn.clicked.connect(self.add_requested)
        self.change_btn.clicked.connect(lambda: self.change_requested.emit(self._row()))
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self._row()))
        p.addLayout(row)
        p.addWidget(_note(strings.REPLAY_NOTE if replay else strings.BMS_LIST_NOTE))
        self.tabs.addTab(page, strings.SETTINGS_TAB_BMS)
        self.set_devices(devices or [])

        # --- Banks (several BMS in parallel = one battery) ------------------------
        page, p = _page()
        self.banks = QListWidget()
        self.banks.setMinimumHeight(150)
        self.banks.itemSelectionChanged.connect(self._update_bank_buttons)
        p.addWidget(self.banks, 1)
        row = QHBoxLayout()
        self.bank_add_btn = QPushButton(strings.BANK_CREATE)
        self.bank_edit_btn = QPushButton(strings.BMS_CHANGE)
        self.bank_remove_btn = QPushButton(strings.BANK_REMOVE)
        for b in (self.bank_add_btn, self.bank_edit_btn, self.bank_remove_btn):
            b.setProperty("secondary", True)
            row.addWidget(b)
        row.addStretch(1)
        self.bank_add_btn.clicked.connect(self.bank_add_requested)
        self.bank_edit_btn.clicked.connect(lambda: self.bank_edit_requested.emit(self._bank_row()))
        self.bank_remove_btn.clicked.connect(
            lambda: self.bank_remove_requested.emit(self._bank_row()))
        p.addLayout(row)
        p.addWidget(_note(strings.BANKS_NOTE))
        self.tabs.addTab(page, strings.SETTINGS_TAB_BANKS)
        self.set_banks(banks or [])

        # --- Display ------------------------------------------------------------
        page, p = _page()
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QRadioButton] = {}
        for mode, text in (("widget", strings.MODE_WIDGET), ("taskbar", strings.MODE_TASKBAR)):
            rb = QRadioButton(text)
            self.mode_group.addButton(rb)
            self.mode_buttons[mode] = rb
            rb.toggled.connect(lambda on, m=mode: on and self.mode_changed.emit(m))
            p.addWidget(rb)
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
        p.addLayout(grid)
        p.addWidget(_note(strings.SCALE_NOTE))
        self.desktop = QCheckBox(strings.DESKTOP_LABEL)
        self.desktop.setChecked(settings.widgets_on_desktop)
        self.desktop.toggled.connect(self.desktop_changed)
        p.addWidget(self.desktop)
        p.addWidget(_note(strings.DESKTOP_NOTE))
        self.dim = QCheckBox(strings.DIM_LABEL)
        self.dim.setChecked(settings.dim_when_maximized)
        self.dim.toggled.connect(self.dim_changed)
        p.addWidget(self.dim)
        p.addWidget(_note(strings.DIM_NOTE))
        p.addStretch(1)
        self.tabs.addTab(page, strings.SETTINGS_TAB_DISPLAY)

        # --- Battery state + notifications ----------------------------------------
        page, p = _page()
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
        p.addLayout(row)
        p.addWidget(_note(strings.IDLE_NOTE))
        p.addWidget(QFrame(objectName="line"))

        self.notify = QCheckBox(strings.NOTIFY_LABEL)
        self.notify.setChecked(settings.notify_enabled)
        self.notify.toggled.connect(self.notify_changed)
        p.addWidget(self.notify)
        p.addWidget(_note(strings.NOTIFY_NOTE))
        low_row = QHBoxLayout()
        low_label = QLabel(strings.LOW_SOC_LABEL)
        low_label.setToolTip(strings.LOW_SOC_TIP)
        low_row.addWidget(low_label, 1)
        self.low_soc = QSpinBox()
        self.low_soc.setRange(5, 100)
        self.low_soc.setToolTip(strings.LOW_SOC_TIP)
        self.low_soc.setSuffix(" %")
        self.low_soc.setMinimumWidth(90)  # see the threshold spin box note above
        self.low_soc.setValue(settings.low_soc_threshold)
        self.low_soc.setEnabled(settings.notify_enabled)
        self.notify.toggled.connect(self.low_soc.setEnabled)
        self.low_soc.valueChanged.connect(self.low_soc_changed)
        low_row.addWidget(self.low_soc)
        p.addLayout(low_row)
        p.addStretch(1)
        self.tabs.addTab(page, strings.SETTINGS_TAB_ALERTS)

        # --- System + data ------------------------------------------------------
        page, p = _page()
        self.autostart = QCheckBox(strings.MENU_AUTOSTART)
        self.autostart.setChecked(autostart_on)
        self.autostart.setEnabled(autostart_available)
        if not autostart_available:
            self.autostart.setToolTip(strings.TIP_AUTOSTART_DEV)
        self.autostart.toggled.connect(self.autostart_changed)
        p.addWidget(self.autostart)
        if not autostart_available:
            p.addWidget(_note(strings.TIP_AUTOSTART_DEV))
        folder = QPushButton(strings.MENU_SETTINGS_FOLDER)
        folder.setProperty("secondary", True)
        folder.clicked.connect(self.open_folder)
        p.addWidget(folder, 0, Qt.AlignLeft)
        p.addWidget(QFrame(objectName="line"))
        # Data tools (also in the right-click menu, which is easy to miss).
        p.addWidget(_section(strings.SECTION_DATA))
        export = QPushButton(strings.MENU_EXPORT_CSV)
        export.setProperty("secondary", True)
        export.clicked.connect(self.export_requested)
        diag = QPushButton(strings.MENU_DIAGNOSTICS)
        diag.setProperty("secondary", True)
        diag.setEnabled(not replay)
        diag.clicked.connect(self.diagnostics_requested)
        tools = QHBoxLayout()
        tools.addWidget(export)
        tools.addWidget(diag)
        tools.addStretch(1)
        p.addLayout(tools)
        p.addWidget(QFrame(objectName="line"))
        p.addWidget(_section(strings.SECTION_UPDATES))
        self.updates = QCheckBox(strings.UPDATE_CHECK_LABEL)
        self.updates.setChecked(settings.check_updates)
        self.updates.toggled.connect(self.updates_changed)
        p.addWidget(self.updates)
        check_now = QPushButton(strings.UPDATE_CHECK_NOW)
        check_now.setProperty("secondary", True)
        check_now.setEnabled(not replay)
        check_now.clicked.connect(self.update_check_requested)
        p.addWidget(check_now, 0, Qt.AlignLeft)
        p.addWidget(_note(strings.UPDATE_CHECK_NOTE))
        p.addStretch(1)
        self.tabs.addTab(page, strings.SETTINGS_TAB_SYSTEM)

        lay.addSpacing(4)
        done = QPushButton(strings.SETTINGS_DONE)
        done.setProperty("primary", True)
        done.clicked.connect(self.accept)
        lay.addWidget(done, 0, Qt.AlignRight)

    # ----- BMS list -------------------------------------------------------------
    def set_devices(self, devices: list[tuple[str, str, bool]]) -> None:
        """(name, detail, visible) per BMS; the first one is the main BMS."""
        row = self._row()
        self.devices.clear()
        several = len(devices) > 1
        for i, (name, detail, visible) in enumerate(devices):
            item = QListWidgetItem()
            self.devices.addItem(item)
            line = QWidget()
            h = QHBoxLayout(line)
            h.setContentsMargins(8, 6, 6, 6)
            text = QLabel(f"{f'{i + 1}. ' if several else ''}{name}"
                          f"{'  ' + strings.BMS_MAIN_MARK if i == 0 and several else ''}\n{detail}")
            text.setAttribute(Qt.WA_TransparentForMouseEvents)  # clicks select the row
            h.addWidget(text, 1)
            eye = QToolButton()
            eye.setIconSize(QSize(22, 22))
            eye.setFixedSize(34, 34)
            eye.setCheckable(True)
            eye.setChecked(visible)
            eye.setToolTip(strings.TIP_EYE)
            eye.setIcon(icons.icon("eye" if visible else "eye_off",
                                   theme.TEXT if visible else theme.MUTED, 20))
            eye.setEnabled(not self.replay)
            eye.toggled.connect(lambda on, i=i, b=eye: self._eye(i, on, b))
            h.addWidget(eye)
            # Explicit height: the size hint is computed before the list's
            # stylesheet padding applies, which clipped the second text line.
            line.setMinimumHeight(54)
            item.setSizeHint(QSize(0, 62))
            self.devices.setItemWidget(item, line)
        if not devices:
            self.devices.addItem(QListWidgetItem(strings.BMS_NOT_SET))
            self.devices.item(0).setFlags(Qt.NoItemFlags)
        elif 0 <= row < len(devices):
            self.devices.setCurrentRow(row)
        self._count = len(devices)
        self._update_buttons()

    # ----- bank list ------------------------------------------------------------
    def set_banks(self, banks: list[tuple[str, str, str, bool]]) -> None:
        """(letter, name, members text, visible) per bank."""
        row = self._bank_row()
        self.banks.clear()
        for i, (label, name, detail, visible) in enumerate(banks):
            item = QListWidgetItem()
            self.banks.addItem(item)
            line = QWidget()
            h = QHBoxLayout(line)
            h.setContentsMargins(8, 6, 6, 6)
            text = QLabel(f"{label}. {name}\n{detail}")
            text.setAttribute(Qt.WA_TransparentForMouseEvents)
            h.addWidget(text, 1)
            eye = QToolButton()
            eye.setIconSize(QSize(22, 22))
            eye.setFixedSize(34, 34)
            eye.setCheckable(True)
            eye.setChecked(visible)
            eye.setToolTip(strings.TIP_EYE_BANK)
            eye.setIcon(icons.icon("eye" if visible else "eye_off",
                                   theme.TEXT if visible else theme.MUTED, 20))
            eye.setEnabled(not self.replay)
            eye.toggled.connect(lambda on, i=i, b=eye: self._bank_eye(i, on, b))
            h.addWidget(eye)
            line.setMinimumHeight(54)
            item.setSizeHint(QSize(0, 62))
            self.banks.setItemWidget(item, line)
        if not banks:
            self.banks.addItem(QListWidgetItem(strings.BANKS_EMPTY))
            self.banks.item(0).setFlags(Qt.NoItemFlags)
        elif 0 <= row < len(banks):
            self.banks.setCurrentRow(row)
        self._bank_count = len(banks)
        self._update_bank_buttons()

    def _bank_eye(self, index: int, on: bool, button: QToolButton) -> None:
        button.setIcon(icons.icon("eye" if on else "eye_off", theme.TEXT if on else theme.MUTED, 20))
        self.bank_visibility_changed.emit(index, on)

    def _bank_row(self) -> int:
        items = self.banks.selectedItems() if hasattr(self, "banks") else []
        return self.banks.row(items[0]) if items else -1

    def _update_bank_buttons(self) -> None:
        selected = self._bank_row() >= 0 and self._bank_count > 0
        self.bank_add_btn.setEnabled(not self.replay)
        self.bank_edit_btn.setEnabled(selected and not self.replay)
        self.bank_remove_btn.setEnabled(selected and not self.replay)

    def _eye(self, index: int, on: bool, button: QToolButton) -> None:
        button.setIcon(icons.icon("eye" if on else "eye_off", theme.TEXT if on else theme.MUTED, 20))
        self.visibility_changed.emit(index, on)

    def _row(self) -> int:
        items = self.devices.selectedItems()
        return self.devices.row(items[0]) if items else -1

    def _update_buttons(self) -> None:
        selected = self._row() >= 0 and self._count > 0
        self.add_btn.setEnabled(not self.replay)
        self.change_btn.setEnabled(selected and not self.replay)
        self.remove_btn.setEnabled(selected and self._count > 1 and not self.replay)

    def set_mode(self, mode: str) -> None:
        """Reflect the effective mode (the controller may refuse 'taskbar')."""
        rb = self.mode_buttons.get(mode)
        if rb is not None and not rb.isChecked():
            rb.blockSignals(True)
            rb.setChecked(True)
            rb.blockSignals(False)
