"""JBD / Jiabaida / Xiaoxiang BMS over BLE - capture only (decoder to come).

Protocol facts (read 2026-11-15, identical in both sources):
syssi/esphome-jbd-bms `components/jbd_bms_ble` and patman15/aiobmsble
`aiobmsble/bms/jbd_bms.py`.

GATT: service 0xFF00, notify 0xFF01, write 0xFF02. Polled.
Request: DD A5 <register> <len=0> <CRC16 BE = 0x10000 - sum(register, len)> 77
Read registers used here (pure reads, no state change):
    0x03 basic info (voltage, current, capacity, SOC, protection bits, temps)
    0x04 cell voltages
    0x05 hardware version / model string
NOT used, on purpose: DD 5A ... (writes: MOSFET, capacity, balancer, factory
mode) and FF AA ... (password / app-key authentication).
"""

from __future__ import annotations

from fnmatch import fnmatchcase

from .base import BmsDriver, Request, uuid16


def _read_request(register: int) -> bytes:
    # Private: register reads only (0xA5), length always 0.
    body = bytes([register, 0x00])
    crc = (0x10000 - sum(body)) & 0xFFFF
    return bytes([0xDD, 0xA5]) + body + crc.to_bytes(2, "big") + b"\x77"


REQUEST_BASIC_INFO = _read_request(0x03)  # DD A5 03 00 FF FD 77
REQUEST_CELL_INFO = _read_request(0x04)  # DD A5 04 00 FF FC 77
REQUEST_HARDWARE = _read_request(0x05)  # DD A5 05 00 FF FB 77

# BLE name patterns from aiobmsble's JBD matcher (JBD boards are mostly
# recognised by name; uppercase here, compared case-insensitively).
NAME_PATTERNS = ("12???BL*", "24???BL*", "@KSM:*", "J-?????Y*", "JBD-*", "LSG-*", "N-?????BL*",
                 "OGR-*", "SBL-*", "SJ-???-*", "SX1*", "SX60*", "TITAN-*", "TZ-H*")


class JbdDriver(BmsDriver):
    id = "jbd"
    name = "JBD / Xiaoxiang"
    service_uuid = uuid16(0xFF00)
    notify_uuid = uuid16(0xFF01)
    write_uuid = uuid16(0xFF02)
    connect_requests = (Request(REQUEST_HARDWARE, "hardware version (0x05)", delay_after_s=0.5),)
    poll_requests = (
        Request(REQUEST_BASIC_INFO, "basic info (0x03)", delay_after_s=0.5),
        Request(REQUEST_CELL_INFO, "cell voltages (0x04)"),
    )
    poll_interval_s = 2.0
    allowed_frames = frozenset({REQUEST_BASIC_INFO, REQUEST_CELL_INFO, REQUEST_HARDWARE})
    capture_only = True
    source = "esphome-jbd-bms + aiobmsble"

    def matches(self, name: str, service_uuids: list[str]) -> bool:
        n = name.upper()
        return any(fnmatchcase(n, p) for p in NAME_PATTERNS) or self.service_uuid in service_uuids


DRIVER = JbdDriver()
