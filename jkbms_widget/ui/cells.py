"""Cells tab of the dashboard: one bar per cell voltage.

The bar scale always spans at least SCALE_WINDOW_V around the average
voltage (owner's report 2026-11-15: scaling between the lowest and highest
cell made the bars jump with every millivolt). A real imbalance still shows;
exact values are printed above the bars. Lowest cell blue, highest amber,
the rest green - colours only from EVEN_SPREAD_V of spread, so they do not
flicker on noise.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QWidget

from .. import strings
from ..model import CellInfo
from . import theme

EVEN_SPREAD_V = 0.010  # below 10 mV all cells count as equal (no colours)
SCALE_WINDOW_V = 0.100  # the scale spans at least 100 mV
MIN_BAR, MAX_BAR = 0.15, 0.95  # height shares at the ends of the scale


def bar_shares(voltages: tuple[float, ...]) -> list[float]:
    """Bar heights as 0..1 shares (pure, tested).

    Equal cells sit at mid height; 1 mV moves a bar by under 1 % of its range
    unless the spread is already larger than SCALE_WINDOW_V.
    """
    if not voltages:
        return []
    lo, hi = min(voltages), max(voltages)
    mid = sum(voltages) / len(voltages)
    half = max(SCALE_WINDOW_V, (hi - lo) * 1.2) / 2
    lo_s, hi_s = min(lo, mid - half), max(hi, mid + half)
    return [MIN_BAR + (MAX_BAR - MIN_BAR) * (v - lo_s) / (hi_s - lo_s) for v in voltages]


class CellsView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cell: CellInfo | None = None
        self.stale = True
        self.setMinimumHeight(190)

    def set_cell(self, cell: CellInfo | None, stale: bool) -> None:
        if (cell, stale) != (self.cell, self.stale):
            self.cell, self.stale = cell, stale
            if self.isVisible():
                self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        small = QFont(theme.FONT_FAMILY, 8)
        normal = QFont(theme.FONT_FAMILY, 9)
        muted, text = QColor(theme.MUTED), QColor(theme.MUTED if self.stale else theme.TEXT)
        cell = self.cell
        if cell is None or not cell.cell_voltages:
            p.setPen(muted)
            p.setFont(normal)
            p.drawText(self.rect(), Qt.AlignCenter, strings.CELLS_NO_DATA)
            return

        v = cell.cell_voltages
        lo, hi = min(v), max(v)
        imin, imax = v.index(lo) + 1, v.index(hi) + 1
        fm = QFontMetricsF(normal)

        # Top line: spread / average / min / max, balancing on the right.
        p.setFont(normal)
        p.setPen(text)
        summary = strings.CELLS_SUMMARY.format(delta=(hi - lo) * 1000, avg=sum(v) / len(v),
                                               imin=imin, imax=imax)
        p.drawText(QRectF(0, 0, self.width(), fm.height()), Qt.AlignLeft | Qt.AlignVCenter, summary)
        if cell.balancing:
            p.setPen(QColor(theme.AMBER))
            p.drawText(QRectF(0, 0, self.width(), fm.height()), Qt.AlignRight | Qt.AlignVCenter,
                       strings.CELLS_BALANCING)

        # Bottom line: temperatures.
        temps = [f"T{n} {t:.1f} °C" for n, t in enumerate(cell.temperatures, 1)]
        if cell.mosfet_temperature is not None:
            temps.append(f"MOS {cell.mosfet_temperature:.1f} °C")
        p.setPen(muted)
        p.drawText(QRectF(0, self.height() - fm.height(), self.width(), fm.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, "   ·   ".join(temps))

        # Bars.
        top = fm.height() + 8 + QFontMetricsF(small).height() + 2  # room for value labels
        bottom = self.height() - fm.height() - 8 - QFontMetricsF(small).height() - 2
        area_h = max(10.0, bottom - top)
        n = len(v)
        slot = self.width() / n
        bar_w = min(56.0, slot * 0.62)
        even = hi - lo < EVEN_SPREAD_V
        p.setFont(small)
        sfm = QFontMetricsF(small)
        for i, (volts, share) in enumerate(zip(v, bar_shares(v))):
            if self.stale:
                color = QColor(theme.GREY)
            elif not even and i + 1 == imin:
                color = QColor(theme.BLUE)
            elif not even and i + 1 == imax:
                color = QColor(theme.AMBER)
            else:
                color = QColor(theme.GREEN)
            cx = slot * i + slot / 2
            h = area_h * share
            bar = QRectF(cx - bar_w / 2, bottom - h, bar_w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.TRACK))
            p.drawRoundedRect(QRectF(bar.left(), top, bar_w, area_h), 4, 4)
            p.setBrush(color)
            p.drawRoundedRect(bar, 4, 4)
            p.setPen(text)
            label = f"{volts:.3f}"
            p.drawText(QRectF(cx - slot / 2, bar.top() - sfm.height() - 2, slot, sfm.height()),
                       Qt.AlignCenter, label)
            p.setPen(muted)
            p.drawText(QRectF(cx - slot / 2, bottom + 2, slot, sfm.height()), Qt.AlignCenter,
                       f"#{i + 1}")
