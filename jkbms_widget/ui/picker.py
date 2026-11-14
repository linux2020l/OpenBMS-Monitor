"""Dialog to find and choose the BMS (first run, or menu "Вибрати BMS…")."""

from __future__ import annotations

import asyncio
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .. import strings, win_taskbar
from ..ble import ScanResult, scan
from .widgets import native_hwnd


class _Scanner(QObject):
    """Runs one BLE scan on a worker thread; reports back via signals."""

    done = Signal(list)
    failed = Signal(str)

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="ble-scan").start()

    def _run(self) -> None:
        try:
            self.done.emit(asyncio.run(scan(8.0)))
        except Exception as exc:  # adapter off, etc.
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class BmsPickerDialog(QDialog):
    """Lists JK BMS devices. Safety: nothing is preselected except the saved
    BMS, because several JK BMS may be in range (neighbours) and the strongest
    signal is not necessarily ours."""

    def __init__(
        self,
        current_address: str | None = None,
        current_name: str = "",
        scan_delay_ms: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.PICK_TITLE)
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        win_taskbar.dark_title_bar(native_hwnd(self))
        self.setMinimumSize(460, 380)
        self.selected: ScanResult | None = None
        self.current_address = (current_address or "").upper()
        self.current_name = current_name
        self.results: list[ScanResult] = []

        lay = QVBoxLayout(self)
        hint = QLabel(strings.PICK_HINT)
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        lay.addWidget(hint)
        self.status = QLabel()
        lay.addWidget(self.status)
        self.list = QListWidget()
        self.list.setMinimumHeight(200)  # room for ~3 devices even if the hint wraps tall
        self.list.itemDoubleClicked.connect(lambda _i: self._accept())
        self.list.itemSelectionChanged.connect(self._update_buttons)
        lay.addWidget(self.list, 1)
        self.show_all = QCheckBox(strings.PICK_SHOW_ALL)
        self.show_all.toggled.connect(lambda _c: self._fill())
        lay.addWidget(self.show_all)

        line = QFrame(objectName="line")
        lay.addWidget(line)
        buttons = QHBoxLayout()
        self.rescan_btn = QPushButton(strings.PICK_RESCAN)
        self.rescan_btn.clicked.connect(self.start_scan)
        buttons.addWidget(self.rescan_btn)
        buttons.addStretch(1)
        cancel = QPushButton(strings.PICK_CANCEL)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        cancel.setProperty("secondary", True)
        self.rescan_btn.setProperty("secondary", True)
        self.select_btn = QPushButton(strings.PICK_SELECT)
        self.select_btn.setProperty("primary", True)
        self.select_btn.clicked.connect(self._accept)
        buttons.addWidget(self.select_btn)
        lay.addLayout(buttons)

        self.scanner = _Scanner(self)
        self.scanner.done.connect(self._on_results)
        self.scanner.failed.connect(self._on_error)
        self._fill()
        # After a disconnect the BMS needs a moment before it advertises again.
        self.status.setText(strings.PICK_SCANNING)
        self.rescan_btn.setEnabled(False)
        QTimer.singleShot(scan_delay_ms, self.start_scan)

    def start_scan(self) -> None:
        self.status.setText(strings.PICK_SCANNING)
        self.rescan_btn.setEnabled(False)
        self.scanner.start()

    def _on_results(self, results: list) -> None:
        self.results = results
        self.rescan_btn.setEnabled(True)
        self._fill()

    def _on_error(self, err: str) -> None:
        self.rescan_btn.setEnabled(True)
        self.status.setText(strings.PICK_ERROR.format(err=err))

    def _fill(self) -> None:
        self.list.clear()
        shown = [r for r in self.results if r.looks_like_jk or self.show_all.isChecked()]
        saved = next((r for r in self.results if r.address.upper() == self.current_address), None)
        if self.current_address:
            # The saved BMS always comes first, even if it is not advertising
            # right now (e.g. still connected to the phone).
            if saved is None:
                saved = ScanResult(self.current_address, self.current_name, 0, True)
                detail = strings.PICK_NOT_SEEN
            else:
                detail = f"{saved.rssi} dBm"
            shown = [saved] + [r for r in shown if r is not saved]
        for r in shown:
            name = r.name or "—"
            is_saved = r is saved
            label = f"{name}  {strings.PICK_SAVED_MARK}" if is_saved else name
            rssi = detail if is_saved else f"{r.rssi} dBm"
            item = QListWidgetItem(f"{label}\n{r.address}   {rssi}")
            item.setData(Qt.UserRole, r)
            self.list.addItem(item)
            if is_saved:
                self.list.setCurrentItem(item)  # the only automatic selection
        jk = sum(1 for r in self.results if r.looks_like_jk)
        if self.results or not self.current_address:
            self.status.setText(strings.PICK_FOUND.format(n=jk) if jk else strings.PICK_NONE)
        self._update_buttons()

    # Use the *selection*, not the "current" item: when the list gets focus Qt
    # makes the first row current (without selecting it), which would quietly
    # pick the strongest signal - possibly a neighbour's BMS.
    def _update_buttons(self) -> None:
        self.select_btn.setEnabled(bool(self.list.selectedItems()))

    def _accept(self) -> None:
        items = self.list.selectedItems()
        if items:
            self.selected = items[0].data(Qt.UserRole)
            self.accept()
