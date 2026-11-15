"""Cells tab of the dashboard: one bar per cell voltage.

The bar scale always spans at least SCALE_WINDOW_V around the average
voltage (owner's report 2026-11-15: scaling between the lowest and highest
cell made the bars jump with every millivolt). A real imbalance still shows;
exact values are printed above the bars. Lowest cell blue, highest amber,
the rest green - colours only from EVEN_SPREAD_V of spread, so they do not
flicker on noise.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
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
        self.packs: tuple[tuple[str, CellInfo], ...] = ()
        self.continuous = False
        self.stale = True
        self.setMinimumHeight(190)

    def set_cell(self, cell: CellInfo | None, stale: bool,
                 packs: tuple[tuple[str, CellInfo], ...] = (), continuous: bool = False) -> None:
        """packs: a bank's members (name, reading); each is drawn as its own group.
        continuous: series bank, cells are numbered 1..N across the packs (one
        string) and the top line also shows the spread of all cells."""
        packs = tuple(packs)
        key = (cell, stale, packs, continuous)
        if key != (self.cell, self.stale, self.packs, self.continuous):
            self.cell, self.stale, self.packs, self.continuous = key
            if self.isVisible():
                self.update()

    def groups(self) -> list[tuple[str, CellInfo]]:
        """What to draw: one group per pack of a bank, else the single BMS.

        Owner's report 2026-11-15: a bank's cells must read 1234 1234 with a
        spread per pack, not 12345678 (packs in parallel, not in series).
        """
        if len(self.packs) > 1:
            return [(name, c) for name, c in self.packs if c.cell_voltages]
        return [("", self.cell)] if self.cell is not None and self.cell.cell_voltages else []

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        small = QFont(theme.FONT_FAMILY, 8)
        normal = QFont(theme.FONT_FAMILY, 9)
        bold = QFont(theme.FONT_FAMILY, 9, QFont.Bold)
        muted, text = QColor(theme.MUTED), QColor(theme.MUTED if self.stale else theme.TEXT)
        groups = self.groups()
        if not groups:
            p.setPen(muted)
            p.setFont(normal)
            p.drawText(self.rect(), Qt.AlignCenter, strings.CELLS_NO_DATA)
            return

        fm, sfm = QFontMetricsF(normal), QFontMetricsF(small)
        several = len(groups) > 1
        overall = several and self.continuous  # series: spread of the whole string on top
        head_lines = (2 if several else 1) + overall  # [all cells] + pack name + its summary
        top = head_lines * fm.height() + 8 + sfm.height() + 2  # room for value labels
        bottom = self.height() - fm.height() - 8 - sfm.height() - 2
        area_h = max(10.0, bottom - top)
        # One scale for all packs, so bar heights compare across packs too.
        all_v = tuple(v for _, c in groups for v in c.cell_voltages)
        shares = bar_shares(all_v)
        y0 = 0.0
        if overall:
            lo, hi = min(all_v), max(all_v)
            p.setFont(normal)
            p.setPen(text)
            p.drawText(QRectF(0, 0, self.width(), fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       strings.CELLS_ALL + "  " + strings.CELLS_SUMMARY.format(
                           delta=(hi - lo) * 1000, avg=sum(all_v) / len(all_v),
                           imin=all_v.index(lo) + 1, imax=all_v.index(hi) + 1))
            y0 = fm.height()
        gap = 22.0 if several else 0.0
        slot = (self.width() - gap * (len(groups) - 1)) / len(all_v)
        bar_w = min(56.0, slot * 0.62)
        x, k = 0.0, 0
        for g, (name, cell) in enumerate(groups):
            v = cell.cell_voltages
            n = len(v)
            w = slot * n
            lo, hi = min(v), max(v)
            imin, imax = v.index(lo) + 1, v.index(hi) + 1
            summary = strings.CELLS_SUMMARY.format(delta=(hi - lo) * 1000, avg=sum(v) / n,
                                                   imin=imin, imax=imax)
            first = k + 1 if self.continuous else 1  # number of this pack's first cell
            imin, imax = imin + first - 1, imax + first - 1
            summary = strings.CELLS_SUMMARY.format(delta=(hi - lo) * 1000, avg=sum(v) / n,
                                                   imin=imin, imax=imax)
            line = QRectF(x, y0, w, fm.height())
            if several:
                p.setFont(bold)
                p.setPen(text)
                p.drawText(line, Qt.AlignLeft | Qt.AlignVCenter,
                           QFontMetricsF(bold).elidedText(name, Qt.ElideRight, w * 0.6))
                line = QRectF(x, y0 + fm.height(), w, fm.height())
            p.setFont(normal)
            p.setPen(text)
            p.drawText(line, Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(summary, Qt.ElideRight, w))
            if cell.balancing:
                p.setPen(QColor(theme.AMBER))
                p.drawText(QRectF(x, y0, w, fm.height()), Qt.AlignRight | Qt.AlignVCenter,
                           strings.CELLS_BALANCING)

            # Bottom line: this pack's temperatures.
            temps = [f"T{t_n} {t:.1f} °C" for t_n, t in enumerate(cell.temperatures, 1)]
            if cell.mosfet_temperature is not None:
                temps.append(f"MOS {cell.mosfet_temperature:.1f} °C")
            p.setPen(muted)
            p.drawText(QRectF(x, self.height() - fm.height(), w, fm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText("   ·   ".join(temps), Qt.ElideRight, w))

            # Bars, numbered from 1 in every pack; lowest / highest of this pack coloured.
            even = hi - lo < EVEN_SPREAD_V
            p.setFont(small)
            for i, (volts, share) in enumerate(zip(v, shares[k:k + n])):
                if self.stale:
                    color = QColor(theme.GREY)
                elif not even and i + first == imin:
                    color = QColor(theme.BLUE)
                elif not even and i + first == imax:
                    color = QColor(theme.AMBER)
                else:
                    color = QColor(theme.GREEN)
                cx = x + slot * i + slot / 2
                h = area_h * share
                bar = QRectF(cx - bar_w / 2, bottom - h, bar_w, h)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.TRACK))
                p.drawRoundedRect(QRectF(bar.left(), top, bar_w, area_h), 4, 4)
                p.setBrush(color)
                p.drawRoundedRect(bar, 4, 4)
                p.setPen(text)
                p.drawText(QRectF(cx - slot / 2, bar.top() - sfm.height() - 2, slot, sfm.height()),
                           Qt.AlignCenter, f"{volts:.3f}")
                p.setPen(muted)
                p.drawText(QRectF(cx - slot / 2, bottom + 2, slot, sfm.height()), Qt.AlignCenter,
                           f"#{i + first}")
            if g < len(groups) - 1:  # divider between packs
                p.setPen(QColor(theme.CARD_BORDER))
                sep = x + w + gap / 2
                p.drawLine(QPointF(sep, top - sfm.height()), QPointF(sep, bottom + sfm.height()))
            x += w + gap
            k += n
