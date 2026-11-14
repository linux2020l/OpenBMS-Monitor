"""'Record diagnostics' dialog: a 60 s read-only capture of any BMS, saved
as a sanitized file the user can share (GitHub issue / community chat).

The controller disconnects from the monitored BMS while this dialog is open
(a connected BMS does not advertise, and only one connection is possible).
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .. import diagnostics, drivers, strings, win_taskbar
from ..ble import ScanResult
from .picker import _Scanner
from .widgets import native_hwnd

DIAG_SECONDS = 60


def captures_folder() -> Path:
    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())
    return Path(docs) / "JK BMS Monitor"


class _Recorder(QObject):
    """Runs diagnostics.record() on a worker thread."""

    progress = Signal(float, int)
    finished = Signal(object)  # diagnostics.Recording

    def __init__(self, address: str, driver, name: str = "", parent=None) -> None:
        super().__init__(parent)
        self.address, self.driver, self.name = address, driver, name
        self.stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="ble-diagnostics").start()

    def _run(self) -> None:
        rec = asyncio.run(diagnostics.record(self.address, self.driver, DIAG_SECONDS, self.stop,
                                             progress=lambda s, n: self.progress.emit(s, n),
                                             name=self.name))
        self.finished.emit(rec)


class DiagnosticsDialog(QDialog):
    def __init__(self, scan_delay_ms: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.DIAG_TITLE)
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        win_taskbar.dark_title_bar(native_hwnd(self))
        self.setMinimumSize(500, 520)
        self.results: list[ScanResult] = []
        self.recorder: _Recorder | None = None
        self.saved: Path | None = None

        lay = QVBoxLayout(self)
        intro = QLabel(strings.DIAG_INTRO)
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        lay.addWidget(intro)

        self.list = QListWidget()
        self.list.setMinimumHeight(170)
        self.list.itemSelectionChanged.connect(self._on_select)
        lay.addWidget(self.list, 1)
        self.show_all = QCheckBox(strings.PICK_SHOW_ALL)
        self.show_all.toggled.connect(lambda _c: self._fill())
        lay.addWidget(self.show_all)

        row = QHBoxLayout()
        row.addWidget(QLabel(strings.DIAG_BRAND))
        self.brand = QComboBox()
        for d in drivers.DRIVERS:
            self.brand.addItem(d.name, d.id)
        row.addWidget(self.brand, 1)
        lay.addLayout(row)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, DIAG_SECONDS)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        lay.addWidget(self.bar)

        lay.addWidget(QFrame(objectName="line"))
        buttons = QHBoxLayout()
        self.rescan_btn = QPushButton(strings.PICK_RESCAN)
        self.rescan_btn.setProperty("secondary", True)
        self.rescan_btn.clicked.connect(self.start_scan)
        buttons.addWidget(self.rescan_btn)
        self.folder_btn = QPushButton(strings.DIAG_OPEN_FOLDER)
        self.folder_btn.setProperty("secondary", True)
        self.folder_btn.clicked.connect(self.open_folder)
        buttons.addWidget(self.folder_btn)
        buttons.addStretch(1)
        self.close_btn = QPushButton(strings.CLOSE)
        self.close_btn.setProperty("secondary", True)
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        self.start_btn = QPushButton(strings.DIAG_START)
        self.start_btn.setProperty("primary", True)
        self.start_btn.clicked.connect(self._start_or_stop)
        buttons.addWidget(self.start_btn)
        lay.addLayout(buttons)

        self.scanner = _Scanner(self)
        self.scanner.done.connect(self._on_results)
        self.scanner.failed.connect(lambda err: self._scan_done(strings.PICK_ERROR.format(err=err)))
        self._update_buttons()
        QTimer.singleShot(scan_delay_ms, self.start_scan)

    # ----- scanning / choosing ----------------------------------------------
    def start_scan(self) -> None:
        self.status.setText(strings.PICK_SCANNING)
        self.rescan_btn.setEnabled(False)
        self.scanner.start()

    def _scan_done(self, text: str) -> None:
        self.rescan_btn.setEnabled(self.recorder is None)
        self.status.setText(text)

    def _on_results(self, results: list) -> None:
        self.results = results
        found = sum(1 for r in results if r.looks_like_bms)
        self._scan_done(strings.PICK_FOUND.format(n=found) if found else strings.PICK_NONE)
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        for r in self.results:
            if not (r.looks_like_bms or self.show_all.isChecked()):
                continue
            brand = drivers.get(r.driver_id).name if r.driver_id else strings.BRAND_UNKNOWN
            item = QListWidgetItem(f"{r.name or '—'}\n{brand} · {r.address}   {r.rssi} dBm")
            item.setData(Qt.UserRole, r)
            self.list.addItem(item)
        self._update_buttons()

    def _selected(self) -> ScanResult | None:
        items = self.list.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _on_select(self) -> None:
        r = self._selected()
        if r is not None and r.driver_id:
            self.brand.setCurrentIndex(max(0, self.brand.findData(r.driver_id)))
        self._update_buttons()

    def _update_buttons(self) -> None:
        busy = self.recorder is not None
        self.start_btn.setText(strings.DIAG_STOP if busy else strings.DIAG_START)
        self.start_btn.setEnabled(busy or self._selected() is not None)
        for w in (self.list, self.brand, self.show_all, self.close_btn):
            w.setEnabled(not busy)
        self.folder_btn.setVisible(self.saved is not None)

    # ----- recording -----------------------------------------------------------
    def _start_or_stop(self) -> None:
        if self.recorder is not None:
            self.recorder.stop.set()  # finished() follows with what was recorded
            return
        r = self._selected()
        if r is None:
            return
        driver = drivers.get(self.brand.currentData())
        self.saved = None
        self.recorder = _Recorder(r.address, driver, r.name, self)
        self.recorder.progress.connect(self._on_progress)
        self.recorder.finished.connect(self._on_finished)
        self.bar.setValue(0)
        self.status.setText(strings.DIAG_CONNECTING)
        self.rescan_btn.setEnabled(False)
        self._update_buttons()
        self.recorder.start()

    def _on_progress(self, seconds: float, notifications: int) -> None:
        self.bar.setValue(min(DIAG_SECONDS, int(seconds)))
        self.status.setText(strings.DIAG_PROGRESS.format(s=int(seconds), total=DIAG_SECONDS,
                                                        n=notifications))

    def _on_finished(self, rec) -> None:
        self.recorder = None
        self.bar.setValue(DIAG_SECONDS)
        lines = []
        if rec.rx_count == 0:
            lines.append(strings.DIAG_NO_DATA)
        if rec.error:
            lines.append(strings.DIAG_ERROR.format(err=rec.error))
        # Even without data the GATT table helps (it shows which brand it is).
        if rec.rx_count or rec.gatt:
            try:
                self.saved = diagnostics.save(rec, captures_folder())
                lines.append(strings.DIAG_SAVED.format(path=self.saved, n=rec.rx_count))
            except OSError as exc:
                lines.append(strings.DIAG_ERROR.format(err=exc))
        text = "\n".join(lines)
        self.status.setText(text)
        self.rescan_btn.setEnabled(True)
        self._update_buttons()

    def open_folder(self) -> None:
        folder = captures_folder()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def reject(self) -> None:
        if self.recorder is not None:  # never close mid-recording (BLE thread runs)
            return
        super().reject()
