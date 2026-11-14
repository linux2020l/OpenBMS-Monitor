"""Decode complete JK02 response frames into plain data objects.

Pure Python, no BLE/GUI imports. Input: a 300-byte, CRC-checked frame from
`frames.FrameAssembler`. Offsets follow syssi/esphome-jk-bms
(`decode_jk02_cell_info_`) and are confirmed on JK_B1A8S20P HW 11A / SW 11.53
for the JK02_32S variant (see CLAUDE.md). JK02_24S offsets are esphome-only
(unverified on real hardware). The old JK04 protocol is not supported.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from enum import Enum

from .frames import FrameAssembler

FRAME_TYPE_SETTINGS = 0x01
FRAME_TYPE_CELL_INFO = 0x02
FRAME_TYPE_DEVICE_INFO = 0x03


class Variant(Enum):
    JK02_24S = "JK02_24S"  # hardware version < 11
    JK02_32S = "JK02_32S"  # hardware version >= 11


# Alarm bitmask names (esphome DEFAULT_ERRORS_JK02). JK02_24S uses bits 0..15.
ALARM_NAMES: dict[int, str] = {
    0: "Wire resistance",
    1: "MOSFET overtemperature",
    2: "Cell count is not equal to settings",
    3: "Current sensor anomaly",
    4: "Battery is fully charged",
    5: "Battery pack overvoltage",
    6: "Charge overcurrent",
    7: "Charge short circuit",
    8: "Charge overtemperature",
    9: "Charge undertemperature",
    10: "Coprocessor communication error",
    11: "Cell undervoltage",
    12: "Battery pack undervoltage",
    13: "Discharge overcurrent",
    14: "Discharge short circuit",
    15: "Discharge overtemperature",
    16: "Charging MOSFET abnormal",
    17: "Discharging MOSFET abnormal",
    18: "GPS disconnected",
    19: "Modify password in time",
    20: "Discharge on failed",
    21: "Battery overtemperature",
    22: "Temperature sensor anomaly",
    23: "PL module anomaly",
    24: "SCP release failed",
    25: "Discharge OCP II",
    26: "Discharge OCP III",
    27: "Discharge undertemperature",
    28: "GPS remote lock",
}

# Bits that are status information, not faults (UI should not show them red).
INFORMATIONAL_ALARM_BITS = frozenset({4})

# |I| below this (A) counts as Idle. 1.0 A so that the inverter's standby
# draw (~0.4-0.8 A on the owner's system) shows as Idle. User-configurable.
DEFAULT_IDLE_THRESHOLD = 1.0


@dataclass(frozen=True)
class DeviceInfo:
    model: str
    hardware_version: str
    software_version: str
    name: str


@dataclass(frozen=True)
class CellInfo:
    cell_voltages: tuple[float, ...]  # V, only the cells that are present
    pack_voltage: float  # V
    current: float  # A, positive = charging, negative = discharging
    soc: int  # %
    remaining_capacity: float  # Ah
    nominal_capacity: float  # Ah
    cycle_count: int
    soh: int  # %
    temperature_1: float  # degC
    temperature_2: float  # degC
    mosfet_temperature: float  # degC
    alarm_bits: int  # raw bitmask
    charging_enabled: bool  # charge MOSFET on
    discharging_enabled: bool  # discharge MOSFET on
    balancing: bool
    balance_current: float  # A
    counter: int  # frame counter (byte 5), wraps at 255
    alarms: tuple[int, ...] = field(default=())  # active bit numbers

    @property
    def power(self) -> float:
        """W, same sign convention as current (computed like esphome)."""
        return self.pack_voltage * self.current

    @property
    def cell_min(self) -> float:
        return min(self.cell_voltages, default=0.0)

    @property
    def cell_max(self) -> float:
        return max(self.cell_voltages, default=0.0)

    def alarm_names(self) -> list[str]:
        return [ALARM_NAMES.get(bit, f"Unknown alarm (bit {bit})") for bit in self.alarms]

    def summary(self, idle_threshold: float = DEFAULT_IDLE_THRESHOLD) -> str:
        """One-line text for console output (dump / replay)."""
        alarms = ", ".join(self.alarm_names()) or "none"
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


def guess_variant(hardware_version: str) -> Variant:
    """JK02_32S for HW >= 11 (e.g. '11A', '11.XW'), JK02_24S otherwise."""
    match = re.match(r"\s*(\d+)", hardware_version)
    major = int(match.group(1)) if match else 0
    return Variant.JK02_32S if major >= 11 else Variant.JK02_24S


def _ascii(frame: bytes, offset: int, size: int) -> str:
    raw = frame[offset:offset + size].split(b"\x00", 1)[0]
    return raw.decode("ascii", errors="replace").strip()


def parse_device_info(frame: bytes) -> DeviceInfo:
    return DeviceInfo(
        model=_ascii(frame, 6, 16),
        hardware_version=_ascii(frame, 22, 8),
        software_version=_ascii(frame, 30, 8),
        name=_ascii(frame, 46, 16),
    )


def parse_cell_info(frame: bytes, variant: Variant) -> CellInfo:
    def u8(o): return frame[o]
    def u16(o): return struct.unpack_from("<H", frame, o)[0]
    def i16(o): return struct.unpack_from("<h", frame, o)[0]
    def u32(o): return struct.unpack_from("<I", frame, o)[0]
    def i32(o): return struct.unpack_from("<i", frame, o)[0]

    is_32s = variant is Variant.JK02_32S
    max_cells = 32 if is_32s else 24
    o = 32 if is_32s else 0  # shift of all fields after the cell block

    # Bitmask of connected cells (bit i = cell i). Confirmed for 32S at 70.
    cell_mask = u32(70 if is_32s else 54)
    voltages = [u16(6 + 2 * i) / 1000 for i in range(max_cells)]
    if cell_mask:
        cells = tuple(v for i, v in enumerate(voltages) if cell_mask >> i & 1)
    else:  # fallback (as esphome): all non-zero voltages
        cells = tuple(v for v in voltages if v > 0)

    if is_32s:
        alarm_bits, alarm_width = u32(134 + o), 32
        mosfet_temp = i16(112 + o) / 10
    else:
        alarm_bits, alarm_width = u16(136), 16
        mosfet_temp = i16(134) / 10

    return CellInfo(
        cell_voltages=cells,
        pack_voltage=u32(118 + o) / 1000,
        current=i32(126 + o) / 1000,
        soc=u8(141 + o),
        remaining_capacity=u32(142 + o) / 1000,
        nominal_capacity=u32(146 + o) / 1000,
        cycle_count=u32(150 + o),
        soh=u8(158 + o),
        temperature_1=i16(130 + o) / 10,
        temperature_2=i16(132 + o) / 10,
        mosfet_temperature=mosfet_temp,
        alarm_bits=alarm_bits,
        alarms=tuple(b for b in range(alarm_width) if alarm_bits >> b & 1),
        charging_enabled=bool(u8(166 + o)),
        discharging_enabled=bool(u8(167 + o)),
        balancing=u8(140 + o) != 0,
        balance_current=i16(138 + o) / 1000,
        counter=u8(5),
    )


def parse_frame(frame: bytes, variant: Variant) -> DeviceInfo | CellInfo | None:
    """Decode a valid frame. Returns None for types we don't use (settings)."""
    ftype = frame[4]
    if ftype == FRAME_TYPE_DEVICE_INFO:
        return parse_device_info(frame)
    if ftype == FRAME_TYPE_CELL_INFO:
        return parse_cell_info(frame, variant)
    return None


class Decoder:
    """Notification chunks in -> DeviceInfo / CellInfo objects out.

    The protocol variant is taken from the device-info frame (HW version)
    unless `variant` is forced. Cell-info frames that arrive before the
    variant is known are skipped (counted in `skipped_cell_frames`), because
    decoding them with the wrong offset table would show wrong numbers.
    """

    def __init__(self, variant: Variant | None = None) -> None:
        self.forced_variant = variant
        self.variant = variant
        self.device_info: DeviceInfo | None = None
        self.assembler = FrameAssembler()
        self.skipped_cell_frames = 0

    def feed(self, chunk: bytes | bytearray) -> list[DeviceInfo | CellInfo]:
        out: list[DeviceInfo | CellInfo] = []
        for frame in self.assembler.feed(chunk):
            ftype = frame[4]
            if ftype == FRAME_TYPE_DEVICE_INFO:
                info = parse_device_info(frame)
                self.device_info = info
                if self.forced_variant is None:
                    self.variant = guess_variant(info.hardware_version)
                out.append(info)
            elif ftype == FRAME_TYPE_CELL_INFO:
                if self.variant is None:
                    self.skipped_cell_frames += 1
                else:
                    out.append(parse_cell_info(frame, self.variant))
        return out
