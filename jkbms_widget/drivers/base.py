"""What a BMS driver must provide. Pure Python, no BLE/GUI imports.

A driver describes one BMS family (brand/protocol):
* how to recognise it in a BLE scan (`matches`);
* which GATT service/characteristics carry its data;
* which request frames it sends on connect and while polling;
* its READ-ONLY ALLOWLIST: the exact frames that may ever be written;
* a decoder that turns notification chunks into model.DeviceInfo/CellInfo.

SAFETY (hard project rule): a driver lists every frame it may send as a
constant in `allowed_frames`. There is no generic frame builder for other
code to use. `ble.send_request()` - the only write path in the app -
calls `driver.ensure_read_only()` on every payload. Never add a frame that
changes a BMS setting, not even behind a flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..model import CellInfo, DeviceInfo


class ForbiddenCommandError(RuntimeError):
    """Raised when something tries to write a non-allowlisted frame."""


def uuid16(short: int) -> str:
    """Full 128-bit form of a 16-bit BLE UUID, as bleak reports it."""
    return f"0000{short:04x}-0000-1000-8000-00805f9b34fb"


def crc16_modbus(data: bytes) -> int:
    """CRC-16/MODBUS (init 0xFFFF, reflected poly 0xA001), used by Daly and ANT."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class RawDecoder:
    """Decoder for capture-only drivers: decodes nothing, counts traffic.

    Used until a brand has a real decoder (written from community captures).
    """

    def __init__(self) -> None:
        self.notifications = 0
        self.bytes = 0

    def feed(self, chunk: bytes | bytearray) -> list[DeviceInfo | CellInfo]:
        self.notifications += 1
        self.bytes += len(chunk)
        return []

    def stats_text(self) -> str:
        return f"{self.notifications} notifications, {self.bytes} bytes (not decoded yet)"


@dataclass(frozen=True)
class Request:
    frame: bytes
    label: str  # for logs, e.g. "device info (0x97)"
    delay_after_s: float = 0.0


class Decoder(Protocol):
    def feed(self, chunk: bytes | bytearray) -> list[DeviceInfo | CellInfo]: ...

    def stats_text(self) -> str: ...


class BmsDriver:
    """Base class; one subclass (one instance) per BMS family."""

    id: str = ""  # stored in settings, e.g. "jk"
    name: str = ""  # shown to the user, e.g. "JK BMS"
    service_uuid: str = ""
    notify_uuid: str = ""
    write_uuid: str = ""
    connect_requests: tuple[Request, ...] = ()
    poll_requests: tuple[Request, ...] = ()
    poll_interval_s: float = 5.0
    # True: poll only until the first cell reading (the BMS then streams by
    # itself, like JK); False: poll for as long as the connection lasts.
    poll_until_data: bool = False
    allowed_frames: frozenset[bytes] = frozenset()
    # True: requests are known, decoding is not written yet - the driver can
    # only record diagnostics (it cannot be the monitored BMS).
    capture_only: bool = False
    source: str = ""  # where the protocol facts come from (shown in captures)

    def matches(self, name: str, service_uuids: list[str]) -> bool:
        raise NotImplementedError

    def new_decoder(self, **options) -> Decoder:
        return RawDecoder()

    def sanitize_events(self, events: list) -> list:
        """Remove private data (serials, passcodes) from captured events."""
        return events

    def ensure_read_only(self, frame: bytes | bytearray) -> bytes:
        """Return `frame` as bytes if this driver allowlists it, else raise."""
        frame = bytes(frame)
        if frame not in self.allowed_frames:
            raise ForbiddenCommandError(
                f"Refusing to send non-read-only frame to {self.name}: {frame.hex(' ')}"
            )
        return frame
