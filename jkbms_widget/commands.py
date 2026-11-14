"""Read-only request frames for the JK BMS BLE protocol (JK02 / JK04).

SAFETY RULE: this module is the single source of bytes that may ever be
written to the BMS. It deliberately exposes NO generic frame builder:
only two pre-built, constant read requests exist, and `ensure_read_only()`
must be called by the BLE layer on every write.

Why a whole-frame allowlist instead of a command-byte check: in this
protocol the "command" byte of a write is actually a register address
(e.g. charge switch, thresholds), and the value/length bytes carry the new
setting. A frame that starts with an allowed command byte but has non-zero
length/value bytes is not something we have ever verified to be harmless,
so we accept only the exact 20-byte frames below.

Request frame layout (20 bytes), verified against syssi/esphome-jk-bms
(`jk_bms_ble.cpp`, `build_frame()`):

    [0..3]   AA 55 90 EB      request header
    [4]      command          0x96 = cell info, 0x97 = device info
    [5]      length           0 for read requests
    [6..9]   value, uint32 LE 0 for read requests
    [10..18] zero padding
    [19]     checksum         sum(bytes[0..18]) & 0xFF
"""

from enum import IntEnum

REQUEST_HEADER = bytes([0xAA, 0x55, 0x90, 0xEB])
REQUEST_FRAME_LENGTH = 20


class Command(IntEnum):
    """The only commands this application is allowed to send."""

    CELL_INFO = 0x96  # start streaming cell info frames (type 0x02)
    DEVICE_INFO = 0x97  # request one device info frame (type 0x03)


class ForbiddenCommandError(RuntimeError):
    """Raised when something tries to write a non-allowlisted frame."""


def checksum(data: bytes) -> int:
    """8-bit additive checksum used by JK frames: sum of bytes, modulo 256."""
    return sum(data) & 0xFF


def _build_read_request(command: Command) -> bytes:
    # Private on purpose: takes only a Command, always zero length/value.
    body = REQUEST_HEADER + bytes([command, 0x00]) + bytes(4) + bytes(9)
    assert len(body) == REQUEST_FRAME_LENGTH - 1
    return body + bytes([checksum(body)])


REQUEST_DEVICE_INFO: bytes = _build_read_request(Command.DEVICE_INFO)
REQUEST_CELL_INFO: bytes = _build_read_request(Command.CELL_INFO)

ALLOWED_FRAMES: frozenset[bytes] = frozenset({REQUEST_DEVICE_INFO, REQUEST_CELL_INFO})


def ensure_read_only(frame: bytes | bytearray) -> bytes:
    """Return `frame` as bytes if it is an allowlisted read request, else raise.

    The BLE layer must pass every outgoing payload through this function
    immediately before writing it to the characteristic.
    """
    frame = bytes(frame)
    if frame not in ALLOWED_FRAMES:
        raise ForbiddenCommandError(
            f"Refusing to send non-read-only frame to BMS: {frame.hex(' ')}"
        )
    return frame
