"""Daly BMS (and 100Balance, per aiobmsble's README) over BLE - capture only.

Protocol facts (read 2026-11-15): patman15/aiobmsble `aiobmsble/bms/daly_bms.py`.

GATT: service 0xFFF0, notify 0xFFF1, write 0xFFF2. Polled. Two protocol
variants, both Modbus-style "read holding registers" (function 0x03):
    D2 03 <addr BE> <count BE> <CRC16/MODBUS LE>   (answer starts with D2)
    81 03 <addr BE> <count BE> <CRC16/MODBUS LE>   ("X81", answer starts with 51)
A BMS answers only its own variant, so the capture asks both.
Reads used here (all function 0x03, no state change):
    D2 0x0000 x62  main block (cells, temps, voltage, current, SOC, MOSFETs)
    D2 0x003E x9   MOSFET temperature
    81 0x0000 x64  X81 block 1;  81 0x0041 x62  X81 block 2
NOT used: the device-info reads (D2 0x00A9, 81 0x0178) - the X81 one carries
the serial number - and any write function (0x06 / 0x10).
"""

from __future__ import annotations

from .base import BmsDriver, Request, crc16_modbus, uuid16


def _read_registers(device: int, address: int, count: int) -> bytes:
    # Private: function code is fixed to 0x03 (read holding registers).
    body = bytes([device, 0x03]) + address.to_bytes(2, "big") + count.to_bytes(2, "big")
    return body + crc16_modbus(body).to_bytes(2, "little")


REQUEST_D2_MAIN = _read_registers(0xD2, 0x0000, 62)  # D2 03 00 00 00 3E D7 B9
REQUEST_D2_MOS = _read_registers(0xD2, 0x003E, 9)
REQUEST_X81_BLOCK1 = _read_registers(0x81, 0x0000, 64)  # 81 03 00 00 00 40 5B FA
REQUEST_X81_BLOCK2 = _read_registers(0x81, 0x0041, 62)  # 81 03 00 41 00 3E 8B CE


class DalyDriver(BmsDriver):
    id = "daly"
    name = "Daly / 100Balance"
    service_uuid = uuid16(0xFFF0)
    notify_uuid = uuid16(0xFFF1)
    write_uuid = uuid16(0xFFF2)
    poll_requests = (
        Request(REQUEST_D2_MAIN, "D2 main block", delay_after_s=0.5),
        Request(REQUEST_D2_MOS, "D2 MOSFET temperature", delay_after_s=0.5),
        Request(REQUEST_X81_BLOCK1, "X81 block 1", delay_after_s=0.5),
        Request(REQUEST_X81_BLOCK2, "X81 block 2"),
    )
    connect_requests = poll_requests  # no handshake: start with a first round
    poll_interval_s = 3.0
    allowed_frames = frozenset({REQUEST_D2_MAIN, REQUEST_D2_MOS, REQUEST_X81_BLOCK1,
                                REQUEST_X81_BLOCK2})
    capture_only = True
    source = "aiobmsble"

    def matches(self, name: str, service_uuids: list[str]) -> bool:
        return name.upper().startswith("DL-") or self.service_uuid in service_uuids


DRIVER = DalyDriver()
