"""When to show a Windows notification. Pure Python, no Qt (unit-tested).

`Notifier.update(snapshot, now)` is called about once a second and returns
the events to show. Each condition fires once and re-arms only after it
clearly cleared, so a value hovering around a threshold never spams:
* low SOC: at or below the threshold; again only after SOC rose to
  threshold + REARM_MARGIN (owner's default 20 %);
* BMS alarm: a fault code that was not active before (info codes like
  "fully_charged" are not faults);
* connection lost: still not reconnected after LOST_AFTER_S while the app
  keeps trying (a manual disconnect is not "lost");
* fully charged: SOC reached 100 % while charging; not when the app starts
  with an already full battery.
"""

from __future__ import annotations

from dataclasses import dataclass

from .state import CHARGING, Snapshot

LOW_SOC, ALARM, LOST, FULL = "low_soc", "alarm", "lost", "full"
REARM_MARGIN = 5  # % above the low-SOC threshold before it can fire again
FULL_REARM_SOC = 97  # % below which "fully charged" can fire again
LOST_AFTER_S = 60.0
RECONNECTING = ("connecting", "lost")  # statuses while the app keeps trying


@dataclass(frozen=True)
class Event:
    kind: str  # LOW_SOC / ALARM / LOST / FULL
    soc: int | None = None
    alarms: tuple[str, ...] = ()


class Notifier:
    def __init__(self, low_soc: int = 20) -> None:
        self.low_soc = low_soc
        self._low_armed = True
        self._full_armed: bool | None = None  # None until the first reading
        self._active_faults: set[str] = set()
        self._last_live: float | None = None  # monotonic time of the last fresh data
        self._lost_sent = False

    def update(self, snap: Snapshot, now: float) -> list[Event]:
        events: list[Event] = []
        cell = snap.cell
        if cell is not None and not snap.stale:
            self._last_live, self._lost_sent = now, False
            soc = cell.soc
            if soc <= self.low_soc and self._low_armed:
                events.append(Event(LOW_SOC, soc=soc))
                self._low_armed = False
            elif soc >= self.low_soc + REARM_MARGIN:
                self._low_armed = True

            if self._full_armed is None:
                self._full_armed = soc < 100  # started full: nothing to report
            if soc >= 100 and self._full_armed and snap.state == CHARGING:
                events.append(Event(FULL, soc=soc))
                self._full_armed = False
            elif soc <= FULL_REARM_SOC:
                self._full_armed = True

            faults = set(snap.fault_alarms)
            new = tuple(a for a in snap.fault_alarms if a not in self._active_faults)
            if new:
                events.append(Event(ALARM, alarms=new))
            self._active_faults = faults
        elif (self._last_live is not None and not self._lost_sent
              and snap.status in RECONNECTING and now - self._last_live >= LOST_AFTER_S):
            events.append(Event(LOST))
            self._lost_sent = True
        return events
