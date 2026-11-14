"""Brand-independent battery data model.

Every BMS driver (drivers/<brand>/) turns its frames into these objects;
everything above the drivers (state, history, UI) only knows this model.
Pure Python, no BLE/GUI imports.

Fields a BMS does not report are None (or empty), and the UI shows "—".
Alarms are brand-independent codes (strings below); each driver maps its own
bits/flags to them. UI texts for the codes live in strings.ALARM_TEXT.
"""

from __future__ import annotations

from dataclasses import dataclass

# |I| below this (A) counts as Idle. 1.0 A so that the inverter's standby
# draw (~0.4-0.8 A on the owner's system) shows as Idle. User-configurable.
DEFAULT_IDLE_THRESHOLD = 1.0

# Known alarm codes. Add new ones here AND to strings.ALARM_TEXT /
# strings_en.ALARM_TEXT (tests check that every code has a text).
ALARM_CODES = (
    "balance_wire_resistance",
    "mosfet_overtemperature",
    "cell_count_mismatch",
    "current_sensor_fault",
    "fully_charged",
    "pack_overvoltage",
    "charge_overcurrent",
    "charge_short_circuit",
    "charge_overtemperature",
    "charge_undertemperature",
    "coprocessor_error",
    "cell_undervoltage",
    "pack_undervoltage",
    "discharge_overcurrent",
    "discharge_short_circuit",
    "discharge_overtemperature",
    "charge_mosfet_fault",
    "discharge_mosfet_fault",
    "gps_disconnected",
    "password_change_required",
    "discharge_on_failed",
    "battery_overtemperature",
    "temperature_sensor_fault",
    "parallel_module_fault",
    "short_circuit_release_failed",
    "discharge_overcurrent_2",
    "discharge_overcurrent_3",
    "discharge_undertemperature",
    "gps_remote_lock",
)

# Status information, not faults: shown blue, never as a red alarm.
INFORMATIONAL_ALARMS = frozenset({"fully_charged"})


@dataclass(frozen=True)
class DeviceInfo:
    model: str
    hardware_version: str = ""
    software_version: str = ""
    name: str = ""


@dataclass(frozen=True)
class CellInfo:
    """One live reading of the battery (name kept from the JK cell-info frame)."""

    cell_voltages: tuple[float, ...]  # V, only the cells that are present
    pack_voltage: float  # V
    current: float  # A, positive = charging, negative = discharging
    soc: int  # %
    remaining_capacity: float | None = None  # Ah
    nominal_capacity: float | None = None  # Ah
    cycle_count: int | None = None
    soh: int | None = None  # %
    temperatures: tuple[float, ...] = ()  # degC, battery/NTC sensors
    mosfet_temperature: float | None = None  # degC
    charging_enabled: bool | None = None  # charge MOSFET on
    discharging_enabled: bool | None = None  # discharge MOSFET on
    balancing: bool | None = None
    balance_current: float | None = None  # A
    alarms: tuple[str, ...] = ()  # active alarm codes (ALARM_CODES or "<brand>_bit_N")
    raw_alarms: int = 0  # brand-specific bitmask, for logs/diagnostics only

    @property
    def power(self) -> float:
        """W, same sign convention as current."""
        return self.pack_voltage * self.current

    @property
    def cell_min(self) -> float:
        return min(self.cell_voltages, default=0.0)

    @property
    def cell_max(self) -> float:
        return max(self.cell_voltages, default=0.0)

    @property
    def max_temperature(self) -> float | None:
        """Hottest battery sensor (falls back to the MOSFET sensor)."""
        if self.temperatures:
            return max(self.temperatures)
        return self.mosfet_temperature

    def summary(self, idle_threshold: float = DEFAULT_IDLE_THRESHOLD) -> str:
        """One-line text for console output (dump / replay)."""
        alarms = ", ".join(self.alarms) or "none"
        return (
            f"SOC {self.soc:3d}%  {self.pack_voltage:6.3f} V  {self.current:+8.3f} A  "
            f"{self.power:+8.1f} W  {battery_state(self.current, idle_threshold):11s}  "
            f"cells {self.cell_min:.3f}-{self.cell_max:.3f} V  alarms: {alarms}"
        )


def battery_state(current: float, idle_threshold: float = DEFAULT_IDLE_THRESHOLD) -> str:
    """'Charging', 'Discharging' or 'Idle' (|I| below threshold)."""
    if abs(current) < idle_threshold:
        return "Idle"
    return "Charging" if current > 0 else "Discharging"


def describe(obj: DeviceInfo | CellInfo) -> str:
    """One console line for a decoded object."""
    if isinstance(obj, DeviceInfo):
        return (
            f"device: {obj.model} HW {obj.hardware_version} SW {obj.software_version} "
            f"name {obj.name!r}"
        )
    return obj.summary()
