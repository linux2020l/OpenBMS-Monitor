"""Create / change a parallel bank: its name and which BMS belong to it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QGridLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from .. import strings
from ..bank import KINDS, LETTERS, PARALLEL
from . import theme
from .compact import icon_button
from .widgets import DragMover, rounded_corners

MIN_MEMBERS = 2  # a "bank" of one BMS is just that BMS


class BankDialog(QDialog):
    def __init__(self, name: str, candidates: list[tuple[str, str, bool]], letter: str = "A",
                 taken: list[str] | tuple = (), kind: str = PARALLEL, parent=None) -> None:
        """candidates: (address, label, checked) of BMS that may join;
        letter: this bank's letter, taken: letters of the other banks."""
        super().__init__(parent)
        self.setWindowTitle(strings.BANK_EDITOR_TITLE)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        rounded_corners(self)
        self.setMinimumWidth(420)

        root = QFrame(objectName="root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 12, 20, 18)
        lay.setSpacing(10)

        header = QFrame()
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        title = QLabel(strings.BANK_EDITOR_TITLE)
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        h.addWidget(title)
        h.addStretch(1)
        close = icon_button("close", theme.TEXT, 18, strings.CLOSE)
        close.clicked.connect(self.reject)
        h.addWidget(close)
        lay.addWidget(header)
        DragMover(self).attach(header)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.addWidget(QLabel(strings.BANK_LETTER_LABEL), 0, 0)
        grid.addWidget(QLabel(strings.BANK_NAME_LABEL), 0, 1)
        # Like a drive letter: any letter no other bank uses.
        self.letter_box = QComboBox()
        self.letter_box.setMinimumWidth(72)
        for ch in LETTERS:
            if ch not in taken:
                self.letter_box.addItem(ch, ch)
        self.letter_box.setCurrentIndex(max(0, self.letter_box.findData(letter)))
        self.letter_box.currentIndexChanged.connect(self._update_placeholder)
        grid.addWidget(self.letter_box, 1, 0)
        self.name_edit = QLineEdit(name)
        self.name_edit.setMaxLength(40)
        grid.addWidget(self.name_edit, 1, 1)
        lay.addLayout(grid)
        self._update_placeholder()

        lay.addWidget(QLabel(strings.BANK_KIND_LABEL))
        kinds = QHBoxLayout()
        self.kind_group = QButtonGroup(self)
        self.kind_buttons: dict[str, QRadioButton] = {}
        for k in KINDS:
            rb = QRadioButton(strings.BANK_KIND_NAMES[k])
            rb.setToolTip(strings.BANK_KIND_TIPS[k])
            rb.setChecked(k == kind)
            self.kind_group.addButton(rb)
            self.kind_buttons[k] = rb
            kinds.addWidget(rb)
        kinds.addStretch(1)
        lay.addLayout(kinds)
        self.kind_note = QLabel()
        self.kind_note.setProperty("muted", True)
        self.kind_note.setWordWrap(True)
        self.kind_note.setStyleSheet("font-size: 9pt;")
        lay.addWidget(self.kind_note)
        self.kind_group.buttonToggled.connect(lambda *_: self._update_kind_note())
        self._update_kind_note()

        lay.addWidget(QLabel(strings.BANK_MEMBERS_LABEL))
        self.list = QListWidget()
        for address, label, checked in candidates:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, address)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self.list.addItem(item)
        self.list.itemChanged.connect(self._update)
        lay.addWidget(self.list, 1)
        note = QLabel(strings.BANK_EDITOR_NOTE)
        note.setProperty("muted", True)
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 9pt;")
        lay.addWidget(note)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(strings.PICK_CANCEL)
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(strings.BANK_SAVE)
        self.ok.setProperty("primary", True)
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self._update()

    def members(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out

    def name(self) -> str:
        return self.name_edit.text().strip()

    def letter(self) -> str:
        return self.letter_box.currentData()

    def kind(self) -> str:
        return next((k for k, rb in self.kind_buttons.items() if rb.isChecked()), PARALLEL)

    def _update_placeholder(self, *_args) -> None:
        # Empty name = "Bank <letter>", shown as a hint.
        self.name_edit.setPlaceholderText(strings.BANK_DEFAULT_NAME.format(label=self.letter()))

    def _update_kind_note(self) -> None:
        self.kind_note.setText(strings.BANK_KIND_TIPS[self.kind()])

    def _update(self, *_args) -> None:
        self.ok.setEnabled(len(self.members()) >= MIN_MEMBERS)
