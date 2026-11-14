"""Decode complete JK02 response frames into the common model.

Pure Python, no BLE/GUI imports. Input: a 300-byte, CRC-checked frame from
`frames.FrameAssembler`. Offsets follow syssi/esphome-jk-bms
(`decode_jk02_cell_info_`) and are confirmed on JK_B1A8S20P HW 11A / SW 11.53
and JK-B2A8S20P HW 19H / SW 19.34 for the JK02_32S variant (see CLAUDE.md).
JK02_24S offsets are esphome-only (unverified on real hardware). The old
JK04 protocol is not supported.
"""

from __future__ import annotations

import re
import struct
from enum import Enum

from ...model import CellInfo, DeviceInfo
from .frames import FrameAssembler

FRAME_TYPE_SETTINGS = 0x01
FRAME_TYPE_CELL_INFO = 0x02
FRAME_TYPE_DEVICE_INFO = 0x03


class Variant(Enum):
    JK02_24S = "JK02_24S"  # hardware version < 11
    JK02_32S = "JK02_32S"  # hardware version >= 11


# JK alarm bit -> common alarm code (esphome DEFAULT_ERRORS_JK02; JK02_24S
# uses bits 0..15). Bit 4 "fully charged" is informational, not a fault.
ALARM_BITS: dict[int, str] = {
    0: "balance_wire_resistance",
    1: "mosfet_overtemperature",
    2: "cell_count_mismatch",
    3: "current_sensor_fault",
    4: "fully_charged",
    5: "pack_overvoltage",
    6: "charge_overcurrent",
    7: "charge_short_circuit",
    8: "charge_overtemperature",
    9: "charge_undertemperature",
    10: "coprocessor_error",
    11: "cell_undervoltage",
    12: "pack_undervoltage",
    13: "discharge_overcurrent",
    14: "discharge_short_circuit",
    15: "discharge_overtemperature",
    16: "charge_mosfet_fault",
    17: "discharge_mosfet_fault",
    18: "gps_disconnected",
    19: "password_change_required",
    20: "discharge_on_failed",
    21: "battery_overtemperature",
    22: "temperature_sensor_fault",
    23: "parallel_module_fault",
    24: "short_circuit_release_failed",
    25: "discharge_overcurrent_2",
    26: "discharge_overcurrent_3",
    27: "discharge_undertemperature",
    28: "gps_remote_lock",
}


def alarm_codes(bits: int, width: int) -> tuple[str, ...]:
    """Active bits -> common codes; unknown bits become 'jk_bit_N'."""
    return tuple(ALARM_BITS.get(b, f"jk_bit_{b}") for b in range(width) if bits >> b & 1)


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
        temperatures=(i16(130 + o) / 10, i16(132 + o) / 10),
        mosfet_temperature=mosfet_temp,
        raw_alarms=alarm_bits,
        alarms=alarm_codes(alarm_bits, alarm_width),
        charging_enabled=bool(u8(166 + o)),
        discharging_enabled=bool(u8(167 + o)),
        balancing=u8(140 + o) != 0,
        balance_current=i16(138 + o) / 1000,
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

    def __init__(self, variant: Variant | str | None = None) -> None:
        if isinstance(variant, str):
            variant = Variant(variant)  # from settings / command line
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

    def stats_text(self) -> str:
        s = self.assembler.stats
        return (f"{s.frames_ok} frames OK, {s.crc_errors} CRC errors, "
                f"{s.dropped_chunks} dropped chunks, {s.aborted_frames} aborted, "
                f"{self.skipped_cell_frames} skipped")
