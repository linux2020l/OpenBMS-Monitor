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

    def matches(self, name: str, service_uuids: list[str]) -> bool:
        raise NotImplementedError

    def new_decoder(self, **options) -> Decoder:
        raise NotImplementedError

    def ensure_read_only(self, frame: bytes | bytearray) -> bytes:
        """Return `frame` as bytes if this driver allowlists it, else raise."""
        frame = bytes(frame)
        if frame not in self.allowed_frames:
            raise ForbiddenCommandError(
                f"Refusing to send non-read-only frame to {self.name}: {frame.hex(' ')}"
            )
        return frame
