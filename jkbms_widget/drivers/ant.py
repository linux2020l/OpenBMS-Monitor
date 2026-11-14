"""ANT BMS (new "ANT-BLE" protocol) over BLE - capture only (decoder to come).

Protocol facts (read 2026-11-15, identical in both sources):
syssi/esphome-ant-bms `components/ant_bms_ble` and patman15/aiobmsble
`aiobmsble/bms/ant_bms.py`.

GATT: service 0xFFE0, one characteristic 0xFFE1 for notify and write - the
same UUIDs as JK, so ANT is recognised by its name ("ANT-BLE...") only.
Polled. Request: 7E A1 <function> <address LE> <length> <CRC16/MODBUS LE over
bytes 1..> AA 55. Reads used here (no state change):
    function 0x01 status (cells, temps, voltage, current, SOC, MOSFETs)
    function 0x02 at 0x026C, 0x20 bytes: device info (HW / SW version)
NOT used: function 0x23 (password) and 0x51 (register write).
"""

from __future__ import annotations

from .base import BmsDriver, Request, crc16_modbus, uuid16


def _read_request(function: int, address: int, length: int) -> bytes:
    # Private: only the two read functions below are ever built.
    assert function in (0x01, 0x02)
    body = bytes([0xA1, function]) + address.to_bytes(2, "little") + bytes([length])
    return b"\x7e" + body + crc16_modbus(body).to_bytes(2, "little") + b"\xaa\x55"


REQUEST_STATUS = _read_request(0x01, 0x0000, 0xBE)  # 7E A1 01 00 00 BE 18 55 AA 55
REQUEST_DEVICE_INFO = _read_request(0x02, 0x026C, 0x20)  # 7E A1 02 6C 02 20 58 C4 AA 55


class AntDriver(BmsDriver):
    id = "ant"
    name = "ANT BMS"
    service_uuid = uuid16(0xFFE0)
    notify_uuid = uuid16(0xFFE1)
    write_uuid = uuid16(0xFFE1)
    connect_requests = (Request(REQUEST_DEVICE_INFO, "device info (0x02)", delay_after_s=0.5),)
    poll_requests = (Request(REQUEST_STATUS, "status (0x01)"),)
    poll_interval_s = 2.0
    allowed_frames = frozenset({REQUEST_STATUS, REQUEST_DEVICE_INFO})
    capture_only = True
    source = "esphome-ant-bms + aiobmsble"

    def matches(self, name: str, service_uuids: list[str]) -> bool:
        n = name.upper()
        return n.startswith("ANT") and "BLE" in n  # "ANT-BLE24...", "ANT_BLE3..."


DRIVER = AntDriver()
