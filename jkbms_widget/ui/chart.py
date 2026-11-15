"""History chart for the dashboard (owner's design, 2026-11-14).

Two panels sharing one time axis, each on its own darker rounded
background so they read as separate charts:
* top: SOC 0-100 %, grid every 25 %, line in PASTEL green while charging,
  pastel amber while discharging, light grey at ~0 A (owner's request:
  lighter than the current colours);
* bottom: |current| 0..N A in 10 A steps, coloured by direction
  (green = charging, amber = discharging, grey = ~0).
Time ticks fall on round clock times (every 5/10 min ... 1 day).
Hovering shows a crosshair and a tooltip with time, SOC, current,
voltage and power of the nearest 10-second bucket.
Dragging with the left mouse button picks a time range (owner's request
2026-11-15): it is shaded across both panels and a box shows the energy
that went in / out of the battery in it (`state.energy_between`), the net
and the SOC change. A click without dragging clears it.
"""

from __future__ import annotations

import bisect
import math
import time
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .. import strings
from ..state import HistoryPoint, energy_between
from . import theme

CHARGE_COLOR = theme.GREEN  # current panel
DISCHARGE_COLOR = theme.AMBER
ZERO_COLOR = theme.GREY
SOC_CHARGE_COLOR = "#a8e6c1"  # SOC panel: pastel versions of the above
SOC_DISCHARGE_COLOR = "#f6d98f"
SOC_IDLE_COLOR = "#d6dae2"
PANEL_BG = "#12151c"  # a bit darker than the card behind the chart
PANEL_PAD = 6.0  # px the panel background extends around the plot area
# Default idle threshold, A. The dashboard sets the user's threshold (settings,
# same as the Idle state): a bank's summed current is rarely exactly 0, so a
# tiny fixed value coloured idle banks as charging / discharging (owner's report).
ZERO_CURRENT = 0.05

SELECT_COLOR = theme.BLUE
DRAG_MIN_PX = 4  # shorter drags count as a click (clears the selection)

CURRENT_AXIS_STEP = 10.0  # A; owner's request: currents can exceed 100 A
TIME_STEPS = (60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400)


# ----- pure helpers (unit-tested) ---------------------------------------------
def _nice_ceiling(x: float) -> float:
    """Current axis limit: |I| max rounded up to a multiple of 10 A (min 10 A)."""
    return max(1.0, math.ceil(x / CURRENT_AXIS_STEP)) * CURRENT_AXIS_STEP


def current_tick_step(limit: float) -> float:
    """Grid step for the current axis: multiples of 10 A, at most 4 intervals."""
    for step in (10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if limit / step <= 4:
            return float(step)
    return limit / 4


def time_step(span_s: float, width_px: float, min_px: float = 90) -> int:
    """Round tick interval so that labels are at least `min_px` apart."""
    max_ticks = max(2, int(width_px / min_px))
    for step in TIME_STEPS:
        if span_s / step <= max_ticks:
            return step
    return TIME_STEPS[-1]


def time_ticks(t0: float, t1: float, step: int) -> list[float]:
    """Tick times aligned to local clock (e.g. 21:30, 21:40 ... or midnight)."""
    offset = datetime.fromtimestamp(t0).astimezone().utcoffset().total_seconds()
    first = math.ceil((t0 + offset) / step) * step - offset
    ticks, t = [], first
    while t <= t1:
        ticks.append(t)
        t += step
    return ticks


def _decimate(points: list[HistoryPoint], width_px: int) -> list[HistoryPoint]:
    """At most ~2 points per pixel column (a week has 60k buckets).

    Groups of neighbouring points are averaged; this keeps the shape and
    makes painting a 7-day chart as cheap as a 1-hour one.
    """
    limit = max(2, width_px * 2)
    if len(points) <= limit:
        return points
    step = math.ceil(len(points) / limit)
    out = []
    for i in range(0, len(points), step):
        chunk = points[i:i + step]
        n = len(chunk)
        volts = [p.voltage for p in chunk if p.voltage is not None]
        out.append(HistoryPoint(
            chunk[0].time, sum(p.soc for p in chunk) / n, sum(p.current for p in chunk) / n,
            sum(volts) / len(volts) if volts else None))
    return out


def _direction_color(current: float, idle: float = ZERO_CURRENT) -> str:
    """|current| below `idle` (A) counts as idle (grey)."""
    if current >= idle:
        return CHARGE_COLOR
    if current <= -idle:
        return DISCHARGE_COLOR
    return ZERO_COLOR


def _soc_color(current: float, idle: float = ZERO_CURRENT) -> str:
    if current >= idle:
        return SOC_CHARGE_COLOR
    if current <= -idle:
        return SOC_DISCHARGE_COLOR
    return SOC_IDLE_COLOR


def range_summary(points: list[HistoryPoint], t0: float, t1: float,
                  bucket_s: float = 10.0) -> dict | None:
    """Energy and SOC change between t0 and t1 (selection box contents).

    `points` must be sorted by time. None if no bucket overlaps the range.
    """
    if t1 < t0:
        t0, t1 = t1, t0
    times = [p.time for p in points]
    inside = points[bisect.bisect_left(times, t0 - bucket_s):bisect.bisect_left(times, t1)]
    inside = [p for p in inside if p.time + bucket_s > t0]
    if not inside:
        return None
    charged, discharged = energy_between(inside, t0, t1, bucket_s)
    return {"t0": t0, "t1": t1, "charged": charged, "discharged": discharged,
            "net": charged - discharged, "soc0": inside[0].soc, "soc1": inside[-1].soc}


# ----- widget -------------------------------------------------------------------
class HistoryChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.points: list[HistoryPoint] = []
        self._times: list[float] = []
        self.span_s = 3600.0
        self.idle_threshold = ZERO_CURRENT  # A; set from the settings by the dashboard
        self.empty_text = ""
        self._now = time.time()
        self._hover_x: float | None = None
        self.bucket_s = 10.0  # history bucket length, for the energy of a range
        # Selected range as unix times (stays put while new data scrolls in).
        self.selection: tuple[float, float] | None = None
        self._drag_x: float | None = None  # press position while dragging
        self._summary_key = None
        self._summary: dict | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setMinimumHeight(190)

    def set_data(self, points: list[HistoryPoint], span_s: float, empty_text: str,
                 bucket_s: float = 10.0) -> None:
        self.points, self.span_s, self.empty_text = points, span_s, empty_text
        self.bucket_s = bucket_s
        self._times = [p.time for p in points]
        self._now = time.time()
        self.update()

    # ----- geometry ---------------------------------------------------------
    def _panels(self) -> tuple[QRectF, QRectF]:
        # gap > 2 * PANEL_PAD leaves a strip of the card between the panels.
        left, right, top, bottom, gap = 50.0, 14.0, 8.0, 26.0, 24.0
        w = self.width() - left - right
        h = self.height() - top - bottom - gap
        soc = QRectF(left, top, w, h * 0.55)
        cur = QRectF(left, soc.bottom() + gap, w, h * 0.45)
        return soc, cur

    def _x_of(self, t: float, plot: QRectF) -> float:
        t0 = self._now - self.span_s
        return plot.left() + (t - t0) / self.span_s * plot.width()

    def _t_of(self, x: float, plot: QRectF) -> float:
        """Inverse of `_x_of`, clamped to the plot."""
        x = min(max(x, plot.left()), plot.right())
        return self._now - self.span_s + (x - plot.left()) / plot.width() * self.span_s

    def clear_selection(self) -> None:
        self.selection = None
        self._drag_x = None
        self.update()

    def selection_summary(self) -> dict | None:
        """`range_summary` of the selection, clipped to the shown span (cached)."""
        if self.selection is None:
            return None
        t0 = max(min(self.selection), self._now - self.span_s)
        t1 = min(max(self.selection), self._now)
        if t1 <= t0:
            return None
        key = (t0, t1, id(self.points), len(self.points), self.bucket_s)
        if key != self._summary_key:
            self._summary_key = key
            self._summary = range_summary(self.points, t0, t1, self.bucket_s)
        return self._summary

    def _max_gap(self, plot: QRectF) -> float:
        # A gap much longer than the point spacing (app off, BMS out of range)
        # is drawn as a break, not as a straight line across it.
        return max(60.0, self.span_s / max(1.0, plot.width()) * 3)

    # ----- painting ---------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont(theme.FONT_FAMILY, 8)
        p.setFont(font)
        fm = QFontMetricsF(font)
        soc_rect, cur_rect = self._panels()
        t0, t1 = self._now - self.span_s, self._now
        grid = QPen(QColor(theme.TRACK), 1)
        label = QColor(theme.MUTED)

        # Separate rounded backgrounds for the two panels.
        p.setPen(QPen(QColor(theme.CARD_BORDER), 1))
        p.setBrush(QColor(PANEL_BG))
        for r in (soc_rect, cur_rect):
            p.drawRoundedRect(r.adjusted(-PANEL_PAD, -PANEL_PAD, PANEL_PAD, PANEL_PAD), 6, 6)
        p.setBrush(Qt.NoBrush)
        label_gap = PANEL_PAD + 5  # axis labels sit left of the panel background

        # Time grid + labels (shared by both panels).
        step = time_step(self.span_s, soc_rect.width())
        if step >= 86400:
            fmt = "%d.%m"
        elif self.span_s > 86400:
            fmt = "%d.%m %H:%M"
        else:
            fmt = "%H:%M"
        for t in time_ticks(t0, t1, step):
            x = self._x_of(t, soc_rect)
            p.setPen(grid)
            p.drawLine(QPointF(x, soc_rect.top()), QPointF(x, soc_rect.bottom()))
            p.drawLine(QPointF(x, cur_rect.top()), QPointF(x, cur_rect.bottom()))
            text = datetime.fromtimestamp(t).strftime(fmt)
            w = fm.horizontalAdvance(text)
            p.setPen(label)
            p.drawText(QPointF(min(max(x - w / 2, 0), self.width() - w), self.height() - 5), text)

        # SOC grid every 25 %.
        for pct in (0, 25, 50, 75, 100):
            y = soc_rect.bottom() - pct / 100 * soc_rect.height()
            p.setPen(grid)
            p.drawLine(QPointF(soc_rect.left(), y), QPointF(soc_rect.right(), y))
            p.setPen(label)
            text = f"{pct}%"
            p.drawText(QPointF(soc_rect.left() - fm.horizontalAdvance(text) - label_gap,
                               y + fm.ascent() / 2 - 1), text)

        # Current grid in 10 A multiples.
        limit = _nice_ceiling(max([abs(pt.current) for pt in self.points] + [0.0]))
        cstep = current_tick_step(limit)
        k = 0
        while k * cstep <= limit + 1e-9:
            amps = k * cstep
            y = cur_rect.bottom() - amps / limit * cur_rect.height()
            p.setPen(grid)
            p.drawLine(QPointF(cur_rect.left(), y), QPointF(cur_rect.right(), y))
            p.setPen(label)
            text = f"{amps:.0f} A"
            p.drawText(QPointF(cur_rect.left() - fm.horizontalAdvance(text) - label_gap,
                               y + fm.ascent() / 2 - 1), text)
            k += 1

        if len(self.points) < 2:
            p.setPen(label)
            p.drawText(soc_rect.united(cur_rect), Qt.AlignCenter, self.empty_text)
            return

        pts = _decimate(self.points, int(soc_rect.width()))
        max_gap = self._max_gap(soc_rect)
        p.save()
        p.setClipRect(soc_rect.united(cur_rect).adjusted(-2, -2, 2, 2))

        def soc_y(pt):
            return soc_rect.bottom() - pt.soc / 100 * soc_rect.height()

        def cur_y(pt):
            return cur_rect.bottom() - min(abs(pt.current), limit) / limit * cur_rect.height()

        # Both lines: one path per colour, each segment coloured by the
        # direction of the current at its end; no segment across a gap.
        idle = self.idle_threshold
        self._draw_segments(p, pts, max_gap, soc_rect, soc_y, lambda i: _soc_color(i, idle), 1.8)
        self._draw_segments(p, pts, max_gap, cur_rect, cur_y,
                            lambda i: _direction_color(i, idle), 2.0)
        p.restore()

        if self.selection is not None:
            self._paint_selection(p, fm, soc_rect, cur_rect)
        else:
            self._paint_hover(p, fm, soc_rect, cur_rect, soc_y, cur_y)

    def _paint_selection(self, p, fm, soc_rect, cur_rect) -> None:
        t0, t1 = sorted(self.selection)
        x0 = max(self._x_of(t0, soc_rect), soc_rect.left())
        x1 = min(self._x_of(t1, soc_rect), soc_rect.right())
        if x1 <= x0:
            return  # scrolled out of the shown span
        # Shaded band across both panels, solid edges.
        band = QColor(SELECT_COLOR)
        band.setAlpha(45)
        top, bottom = soc_rect.top(), cur_rect.bottom()
        p.setPen(Qt.NoPen)
        p.setBrush(band)
        p.drawRect(QRectF(x0, top, x1 - x0, bottom - top))
        p.setPen(QPen(QColor(SELECT_COLOR), 1))
        for x in (x0, x1):
            p.drawLine(QPointF(x, top), QPointF(x, bottom))

        info = self.selection_summary()
        if info is None:
            return
        # One pixel is ~4 s on the 1 h range, ~26 s on 6 h: seconds only on 1 h.
        fmt = ("%d.%m %H:%M" if self.span_s > 86400 else
               "%H:%M:%S" if self.span_s <= 3600 else "%H:%M")
        start = datetime.fromtimestamp(info["t0"]).strftime(fmt)
        end = datetime.fromtimestamp(info["t1"]).strftime(fmt)
        net = info["net"]
        sign = "+" if net > 0 else ""
        rows = [
            (f"{start} – {end}  ·  {strings.fmt_duration(info['t1'] - info['t0'])}", theme.MUTED),
            (f"{strings.SEL_CHARGED}   {strings.fmt_energy(info['charged'])}", CHARGE_COLOR),
            (f"{strings.SEL_DISCHARGED}   {strings.fmt_energy(info['discharged'])}",
             DISCHARGE_COLOR),
            (f"{strings.SEL_NET}   {sign}{strings.fmt_energy(net)}", theme.TEXT),
            (f"SOC   {info['soc0']:.0f} → {info['soc1']:.0f} %", SOC_IDLE_COLOR),
        ]
        if self._drag_x is None:
            rows.append((strings.SEL_CLEAR, theme.MUTED))
        self._paint_box(p, fm, rows, (x0 + x1) / 2, soc_rect, centered=True)

    def _paint_box(self, p, fm, rows, x, plot, centered=False) -> None:
        """Rounded tooltip box at the top of `plot`, next to / centred on x."""
        pad, line_h = 8.0, fm.height() + 2
        w = max(fm.horizontalAdvance(text) for text, _ in rows) + 2 * pad
        h = line_h * len(rows) + 2 * pad - 2
        if centered:
            bx = min(max(x - w / 2, plot.left()), plot.right() - w)
        else:
            bx = x + 12 if x + 12 + w <= plot.right() else x - 12 - w
        by = plot.top() + 4
        p.setPen(QPen(QColor(theme.CARD_BORDER), 1))
        p.setBrush(QColor(16, 19, 26, 240))
        p.drawRoundedRect(QRectF(bx, by, w, h), 6, 6)
        for n, (text, c) in enumerate(rows):
            p.setPen(QColor(c))
            p.drawText(QPointF(bx + pad, by + pad + fm.ascent() + n * line_h), text)

    def _draw_segments(self, p, pts, max_gap, rect, y_of, color_of, width) -> None:
        paths: dict[str, QPainterPath] = {}
        for a, b in zip(pts, pts[1:]):
            if b.time - a.time > max_gap:
                continue
            seg = paths.setdefault(color_of(b.current), QPainterPath())
            seg.moveTo(QPointF(self._x_of(a.time, rect), y_of(a)))
            seg.lineTo(QPointF(self._x_of(b.time, rect), y_of(b)))
        p.setBrush(Qt.NoBrush)
        for color, seg in paths.items():
            p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(seg)

    def _nearest(self, t: float) -> HistoryPoint | None:
        if not self._times:
            return None
        i = bisect.bisect_left(self._times, t)
        candidates = [j for j in (i - 1, i) if 0 <= j < len(self._times)]
        j = min(candidates, key=lambda k: abs(self._times[k] - t))
        return self.points[j]

    def _paint_hover(self, p, fm, soc_rect, cur_rect, soc_y, cur_y) -> None:
        x = self._hover_x
        if x is None or not (soc_rect.left() <= x <= soc_rect.right()):
            return
        t0 = self._now - self.span_s
        t = t0 + (x - soc_rect.left()) / soc_rect.width() * self.span_s
        pt = self._nearest(t)
        if pt is None or abs(pt.time - t) > self._max_gap(soc_rect):
            return  # cursor over a gap: nothing to show
        px = self._x_of(pt.time, soc_rect)

        # Crosshair across both panels + markers on the lines.
        p.setPen(QPen(QColor(theme.MUTED), 1, Qt.DashLine))
        p.drawLine(QPointF(px, soc_rect.top()), QPointF(px, cur_rect.bottom()))
        color = _direction_color(pt.current, self.idle_threshold)
        soc_color = _soc_color(pt.current, self.idle_threshold)
        for y, c in ((soc_y(pt), soc_color), (cur_y(pt), color)):
            p.setPen(QPen(QColor(theme.BG), 2))
            p.setBrush(QColor(c))
            p.drawEllipse(QPointF(px, y), 4, 4)

        # Tooltip box.
        fmt = "%d.%m %H:%M:%S" if self.span_s > 86400 else "%H:%M:%S"
        direction = (strings.TIP_CHARGE if color == CHARGE_COLOR else
                     strings.TIP_DISCHARGE if color == DISCHARGE_COLOR else "")
        power = pt.power
        rows = [
            (datetime.fromtimestamp(pt.time).strftime(fmt), theme.MUTED),
            (f"SOC   {pt.soc:.0f} %", soc_color),
            (f"{strings.TIP_CURRENT}   {abs(pt.current):.1f} A  {direction}".rstrip(), color),
            (f"{strings.TIP_VOLTAGE}   " +
             (f"{pt.voltage:.2f} V" if pt.voltage is not None else strings.NO_VALUE), theme.TEXT),
            (f"{strings.TIP_POWER}   " +
             (f"{abs(power):.0f} W" if power is not None else strings.NO_VALUE), theme.TEXT),
            (strings.SEL_HINT, theme.MUTED),
        ]
        self._paint_box(p, fm, rows, px, soc_rect)

    # ----- mouse ------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self._drag_x = event.position().x()
        self.selection = None
        self.update()

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        self._hover_x = x
        if self._drag_x is not None and abs(x - self._drag_x) >= DRAG_MIN_PX:
            plot = self._panels()[0]
            self.selection = (self._t_of(self._drag_x, plot), self._t_of(x, plot))
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._drag_x is None:
            return super().mouseReleaseEvent(event)
        x = event.position().x()
        if abs(x - self._drag_x) < DRAG_MIN_PX:
            self.selection = None  # a plain click clears
        else:
            plot = self._panels()[0]
            self.selection = (self._t_of(self._drag_x, plot), self._t_of(x, plot))
        self._drag_x = None
        self.update()

    def leaveEvent(self, _event) -> None:
        self._hover_x = None
        self.update()
