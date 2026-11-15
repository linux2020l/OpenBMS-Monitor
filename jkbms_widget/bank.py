"""Banks: several BMS shown as one battery, wired in parallel or in series.

Pure Python, no Qt (unit-tested). Owner's choices 2026-11-15:
* parallel (step D2): several banks, one strip per bank, a member that is
  offline is left out of the sums (the views warn about it), low-SOC / full
  notifications come from the bank, alarms and lost links from each BMS;
* series: voltages add up, the current is common, SOC is the weakest
  pack's; an offline member counts with its last known voltage for a
  while, then the bank shows "no data";
* every bank has a letter the user picks, like a drive letter.
"""

from __future__ import annotations

from string import ascii_uppercase

from .model import CellInfo

PARALLEL, SERIES = "parallel", "series"
KINDS = (PARALLEL, SERIES)
LETTERS = tuple(ascii_uppercase)  # banks are lettered, BMS numbered: never a clash


def free_letter(used) -> str:
    """First letter not taken by another bank."""
    taken = set(used)
    return next((ch for ch in LETTERS if ch not in taken), "Z")


def _all_known(values) -> bool:
    return all(v is not None for v in values)


def combine_cells(cells: list[CellInfo], kind: str = PARALLEL) -> CellInfo | None:
    """One reading for the whole bank.

    Parallel: same voltage (average), currents and Ah add up, SOC weighted
    by capacity (remaining / nominal summed, so a big pack counts more; plain
    average if a BMS does not report its capacity).
    Series: voltages add up, the current is common (average of the
    readings), Ah and SOC are those of the weakest pack: the string stops
    when its emptiest pack is empty.
    """
    if not cells:
        return None
    n = len(cells)
    remaining = [c.remaining_capacity for c in cells]
    nominal = [c.nominal_capacity for c in cells]
    if kind == SERIES:
        voltage = sum(c.pack_voltage for c in cells)
        current = sum(c.current for c in cells) / n
        soc = min(c.soc for c in cells)
        rem = min(remaining) if _all_known(remaining) else None
        nom = min(nominal) if _all_known(nominal) else None
    else:
        voltage = sum(c.pack_voltage for c in cells) / n
        current = sum(c.current for c in cells)
        rem = sum(remaining) if _all_known(remaining) else None
        nom = sum(nominal) if _all_known(nominal) else None
        if rem is not None and nom:
            soc = round(min(100.0, max(0.0, 100.0 * rem / nom)))
        else:
            soc = round(sum(c.soc for c in cells) / n)
    soh = [c.soh for c in cells]
    mos_t = [c.mosfet_temperature for c in cells if c.mosfet_temperature is not None]
    charge = [c.charging_enabled for c in cells]
    discharge = [c.discharging_enabled for c in cells]
    balancing = [c.balancing for c in cells]
    alarms: list[str] = []
    for c in cells:  # union, first-seen order
        alarms += [a for a in c.alarms if a not in alarms]
    return CellInfo(
        cell_voltages=tuple(v for c in cells for v in c.cell_voltages),
        pack_voltage=voltage,
        current=current,
        soc=soc,
        remaining_capacity=rem,
        nominal_capacity=nom,
        cycle_count=None,  # per pack only; a sum would mean nothing
        soh=min(soh) if _all_known(soh) else None,
        temperatures=tuple(t for c in cells for t in c.temperatures),
        mosfet_temperature=max(mos_t) if mos_t else None,
        # A MOSFET is "on" for the bank only if it is on in every pack.
        charging_enabled=all(charge) if _all_known(charge) else None,
        discharging_enabled=all(discharge) if _all_known(discharge) else None,
        balancing=True if any(balancing) else (False if _all_known(balancing) else None),
        balance_current=None,
        alarms=tuple(alarms),
    )


EXCHANGE_MIN_A = 0.5  # A; below this packs are not shown as working against each other


def exchange_current(currents: list[float]) -> float:
    """Current flowing from one pack into another inside a parallel bank, A (>= 0).

    The bank's sum is what goes to / comes from the inverter or charger.
    When some packs charge while others discharge, the smaller of "flowing
    in" and "flowing out" circulates between packs and cancels in the sum
    (owner's report 2026-11-15). Example: +5 A and -5 A -> sum 0, exchange 5.
    """
    charging = sum(i for i in currents if i > 0)
    discharging = -sum(i for i in currents if i < 0)
    return min(charging, discharging)
