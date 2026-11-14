"""JK (Jikong) BMS over BLE: JK02 protocol (JK-B series, HW >= 11 = 32S).

Modules: commands.py (the read-only allowlist), frames.py (chunks ->
CRC-checked 300-byte frames), parser.py (frames -> model objects).
Protocol notes: CLAUDE.md "JK BLE protocol notes".
"""

from __future__ import annotations

from ..base import BmsDriver, Request, uuid16
from .commands import ALLOWED_FRAMES, REQUEST_CELL_INFO, REQUEST_DEVICE_INFO
from .parser import Decoder, Variant

VARIANTS = tuple(v.value for v in Variant)  # option "variant" (JK02_24S / JK02_32S)


class JkDriver(BmsDriver):
    id = "jk"
    name = "JK BMS"
    service_uuid = uuid16(0xFFE0)
    # Newer modules: two FFE1 characteristics (write + notify); older: one
    # FFE1 for both. ble.select_characteristics picks them by properties.
    notify_uuid = uuid16(0xFFE1)
    write_uuid = uuid16(0xFFE1)
    # 0x97 -> one device-info frame (model, HW version -> protocol variant);
    # 0x96 -> the BMS starts streaming cell-info frames (~every 0.55 s).
    connect_requests = (
        Request(REQUEST_DEVICE_INFO, "device info (0x97)", delay_after_s=1.0),
        Request(REQUEST_CELL_INFO, "cell info (0x96)"),
    )
    # esphome re-sends 0x96 every 5 s until the first cell-info frame.
    poll_requests = (Request(REQUEST_CELL_INFO, "cell info (0x96), retry"),)
    poll_interval_s = 5.0
    poll_until_data = True
    allowed_frames = ALLOWED_FRAMES

    def matches(self, name: str, service_uuids: list[str]) -> bool:
        return self.service_uuid in service_uuids or name.upper().startswith("JK")

    def new_decoder(self, variant: str | None = None, **_options) -> Decoder:
        return Decoder(variant)


DRIVER = JkDriver()
