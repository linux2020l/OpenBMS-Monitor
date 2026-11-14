"""Derived values for the UI: stable battery state, time left, history.

Pure Python, no Qt imports (unit-tested, portable).
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass

from .model import DEFAULT_IDLE_THRESHOLD, INFORMATIONAL_ALARMS, CellInfo

IDLE, CHARGING, DISCHARGING = "Idle", "Charging", "Discharging"


class StateTracker:
    """Charging / Discharging / Idle without flicker.

    The BMS reports current in ~0.2 A steps and a standby inverter makes it
    jump around. So the state is decided from a short moving average with
    hysteresis: leave Idle at |avg| >= threshold, return to Idle only at
    |avg| < threshold - hysteresis. A longer average is kept for the
    time-left estimate.
    """

    def __init__(
        self,
        idle_threshold: float = DEFAULT_IDLE_THRESHOLD,
        hysteresis: float = 0.3,
        state_window_s: float = 5.0,
        estimate_window_s: float = 60.0,
    ) -> None:
        self.idle_threshold = idle_threshold
        self.hysteresis = hysteresis
        self.state_window_s = state_window_s
        self.estimate_window_s = estimate_window_s
        self._samples: deque[tuple[float, float]] = deque()  # (t, current)
        self.state = IDLE
        self.state_current = 0.0  # short average, A
        self.estimate_current = 0.0  # long average, A

    def _avg(self, now: float, window: float) -> float:
        values = [i for t, i in self._samples if now - t <= window]
        return sum(values) / len(values) if values else 0.0

    def update(self, current: float, now: float) -> str:
        self._samples.append((now, current))
        while self._samples and now - self._samples[0][0] > self.estimate_window_s:
            self._samples.popleft()
        avg = self._avg(now, self.state_window_s)
        self.state_current = avg
        self.estimate_current = self._avg(now, self.estimate_window_s)

        on = self.idle_threshold
        off = max(0.0, self.idle_threshold - self.hysteresis)
        if self.state == IDLE:
            if avg >= on:
                self.state = CHARGING
            elif avg <= -on:
                self.state = DISCHARGING
        elif self.state == CHARGING:
            if avg <= -on:
                self.state = DISCHARGING
            elif avg < off:
                self.state = IDLE
        else:  # DISCHARGING
            if avg >= on:
                self.state = CHARGING
            elif avg > -off:
                self.state = IDLE
        return self.state


@dataclass(frozen=True)
class Snapshot:
    """Everything the UI needs to draw one update."""

    cell: CellInfo | None  # None until the first cell-info frame
    state: str = IDLE
    hours_left: float | None = None
    left_kind: str | None = None  # 'empty' / 'full' / None
    stale: bool = True  # no fresh data (disconnected or timed out)
    status: str = "stopped"  # connection status code
    status_detail: str = ""
    device_name: str = ""  # BLE name from the device-info frame

    @property
    def fault_alarms(self) -> tuple[str, ...]:
        """Active alarm codes that are real faults (not e.g. 'fully_charged')."""
        if self.cell is None:
            return ()
        return tuple(a for a in self.cell.alarms if a not in INFORMATIONAL_ALARMS)


MIN_ESTIMATE_CURRENT = 0.1  # A; below this "time left" is not shown


def time_left(cell: CellInfo, avg_current: float) -> tuple[float | None, str | None]:
    """(hours, kind) where kind is 'empty' or 'full'; (None, None) if ~0 A
    or the BMS does not report its capacity."""
    if cell.remaining_capacity is None:
        return None, None
    if avg_current <= -MIN_ESTIMATE_CURRENT:
        return cell.remaining_capacity / -avg_current, "empty"
    if avg_current >= MIN_ESTIMATE_CURRENT and cell.nominal_capacity is not None:
        missing = max(0.0, cell.nominal_capacity - cell.remaining_capacity)
        return missing / avg_current, "full"
    return None, None


@dataclass(frozen=True)
class HistoryPoint:
    time: float  # unix time, s (bucket start)
    soc: float  # %
    current: float  # A, bucket average (positive = charging)
    voltage: float | None = None  # V, bucket average; None for old points

    @property
    def power(self) -> float | None:
        return None if self.voltage is None else self.voltage * self.current


def local_midnight(now: float) -> float:
    """Unix time of today's 00:00 local time."""
    from datetime import datetime

    return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0,
                                               microsecond=0).timestamp()


def energy_kwh(points: list[HistoryPoint], since: float,
               bucket_s: float = 10.0) -> tuple[float, float]:
    """(charged, discharged) kWh in history buckets starting at or after `since`.

    Each point is one bucket average, so its energy is V * I * bucket_s.
    Gaps (app not running) simply add nothing. Old points stored without
    voltage use the nearest known voltage (pack voltage changes slowly).
    """
    charged = discharged = 0.0  # Wh
    last_v = next((p.voltage for p in points if p.voltage is not None), None)
    for p in points:
        if p.voltage is not None:
            last_v = p.voltage
        if p.time < since or last_v is None:
            continue
        wh = last_v * p.current * bucket_s / 3600
        if wh > 0:
            charged += wh
        else:
            discharged -= wh
    return charged / 1000, discharged / 1000


CSV_HEADER = "time,unix_time,soc_percent,current_a,voltage_v,power_w"


def history_csv(points: list[HistoryPoint]) -> str:
    """History as CSV: comma-separated, dot decimals, local ISO time.

    One row per 10 s bucket; current/power positive = charging. Old points
    stored without voltage have empty voltage/power cells.
    """
    from datetime import datetime

    rows = [CSV_HEADER]
    for p in points:
        stamp = datetime.fromtimestamp(p.time).isoformat(timespec="seconds")
        volts = "" if p.voltage is None else f"{p.voltage:.3f}"
        watts = "" if p.power is None else f"{p.power:.1f}"
        rows.append(f"{stamp},{p.time:.0f},{p.soc:.0f},{p.current:.3f},{volts},{watts}")
    return "\n".join(rows) + "\n"


class History:
    """SOC/current/voltage history in fixed buckets (default 10 s, 7 days)."""

    def __init__(
        self,
        bucket_s: float = 10.0,
        max_age_s: float = 7 * 24 * 3600,
        on_bucket_closed=None,
    ) -> None:
        self.bucket_s = bucket_s
        self.max_age_s = max_age_s
        # Called with each finished bucket (HistoryPoint) - used to persist it.
        self.on_bucket_closed = on_bucket_closed
        self._points: deque[HistoryPoint] = deque()
        self._bucket_start: float | None = None
        self._soc = 0.0
        self._sum_i = 0.0
        self._sum_v = 0.0
        self._n = 0
        self._n_v = 0

    def _current_bucket(self) -> HistoryPoint | None:
        if self._bucket_start is None or self._n == 0:
            return None
        voltage = self._sum_v / self._n_v if self._n_v else None
        return HistoryPoint(self._bucket_start, self._soc, self._sum_i / self._n, voltage)

    def add(self, now: float, soc: float, current: float, voltage: float | None = None) -> None:
        start = now - now % self.bucket_s
        if self._bucket_start is not None and start != self._bucket_start:
            point = self._current_bucket()
            if point is not None:
                self._points.append(point)
                if self.on_bucket_closed is not None:
                    self.on_bucket_closed(point)
            self._sum_i, self._n, self._sum_v, self._n_v = 0.0, 0, 0.0, 0
        self._bucket_start = start
        self._soc = soc
        self._sum_i += current
        self._n += 1
        if voltage is not None:
            self._sum_v += voltage
            self._n_v += 1
        while self._points and now - self._points[0].time > self.max_age_s:
            self._points.popleft()

    def clear(self) -> None:
        """Forget everything (another BMS was selected)."""
        self._points.clear()
        self._bucket_start, self._sum_i, self._n = None, 0.0, 0
        self._sum_v, self._n_v = 0.0, 0

    def open_bucket(self) -> HistoryPoint | None:
        """The bucket still being filled (saved separately on exit)."""
        return self._current_bucket()

    def extend(self, points: list[HistoryPoint], now: float) -> None:
        """Add stored points (e.g. loaded from SQLite), keeping time order."""
        fresh = [p for p in points if 0 <= now - p.time <= self.max_age_s]
        self._points = deque(sorted(list(self._points) + fresh, key=lambda p: p.time))

    def to_json(self) -> str:
        """Closed buckets plus the open one, as compact JSON rows."""
        pts = list(self._points)
        current = self._current_bucket()
        if current is not None:
            pts.append(current)
        rows = [[round(p.time, 1), round(p.soc, 1), round(p.current, 3)] for p in pts]
        return json.dumps({"bucket_s": self.bucket_s, "points": rows}, separators=(",", ":"))

    def load_json(self, text: str, now: float) -> None:
        """Restore saved points (older than max_age_s are dropped). Bad data is ignored."""
        try:
            rows = json.loads(text)["points"]
            points = [HistoryPoint(float(t), float(s), float(i)) for t, s, i in rows]
        except (ValueError, KeyError, TypeError):
            return
        self.extend(points, now)

    def series(self, span_s: float, now: float) -> list[HistoryPoint]:
        """Points from the last `span_s` seconds, including the open bucket."""
        out = [p for p in self._points if now - p.time <= span_s]
        current = self._current_bucket()
        if current is not None:
            out.append(current)
        return out
