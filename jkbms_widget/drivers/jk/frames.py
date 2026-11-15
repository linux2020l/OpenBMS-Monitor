"""Reassemble JK BMS response frames from BLE notification chunks.

Pure Python, no BLE/GUI imports (portable logic, see CLAUDE.md).

A response frame is 300 bytes:
    [0..3]  55 AA EB 90   header
    [4]     frame type    0x01 settings, 0x02 cell info, 0x03 device info
    [5]     counter
    ...
    [299]   checksum      sum(bytes[0..298]) & 0xFF
It arrives split over several notifications. How it is split depends on
the negotiated MTU:

* Small MTU (ESP32 / esphome): 20-byte chunks, plain data.
* Large MTU (Windows, seen on our BMS): 128 + 23 + 128 + 23 bytes. Each
  notification SHORTER than the first chunk of the frame carries one extra
  leading byte = number of following bytes in BCD (0x22 before 22 bytes).
  Full-size chunks have no prefix.

Prefix rule used here: strip the first byte of a continuation chunk only if
the chunk is shorter than the frame's first chunk AND that byte equals the
BCD-encoded remaining length. The CRC check catches any wrong guess.

Newer BLE modules (JK-B2A8S20P HW 19H) also send stray "AT\r\n"
notifications, and sometimes glue one IN FRONT of a frame start: a
128-byte chunk "41 54 0D 0A 55 AA EB 90 05 ..." (seen 2026-11-15 on a
device-info and the logbook frame). That prefix is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from .commands import REQUEST_HEADER, checksum  # acks echo the request header

RESPONSE_HEADER = bytes([0x55, 0xAA, 0xEB, 0x90])
FRAME_SIZE = 300
AT_PREFIX = b"AT\r\n"


def is_valid_frame(frame: bytes) -> bool:
    return (
        len(frame) == FRAME_SIZE
        and frame[:4] == RESPONSE_HEADER
        and checksum(frame[:FRAME_SIZE - 1]) == frame[FRAME_SIZE - 1]
    )


def _bcd(n: int) -> int | None:
    """Encode 0..99 as BCD (22 -> 0x22). None if out of range."""
    return (n // 10) << 4 | (n % 10) if 0 <= n <= 99 else None


def _strip_length_prefix(chunk: bytes, full_chunk_size: int) -> bytes:
    if len(chunk) >= 2 and len(chunk) < full_chunk_size and chunk[0] == _bcd(len(chunk) - 1):
        return chunk[1:]
    return chunk


@dataclass
class AssemblerStats:
    frames_ok: int = 0
    crc_errors: int = 0
    dropped_chunks: int = 0  # acks / stray data outside a frame
    aborted_frames: int = 0  # new header arrived before the frame was complete


class FrameAssembler:
    """Feed raw notification payloads in; get complete, CRC-valid frames out."""

    def __init__(self) -> None:
        self._buf: bytearray | None = None
        self._first_chunk_size = 0
        self.stats = AssemblerStats()

    def reset(self) -> None:
        """Forget any partial frame (call after a reconnect)."""
        self._buf = None

    def feed(self, chunk: bytes | bytearray) -> list[bytes]:
        chunk = bytes(chunk)
        size = len(chunk)  # the prefix rule compares with the chunk as sent
        if chunk[:8] == AT_PREFIX + RESPONSE_HEADER:
            chunk = chunk[4:]
        if chunk[:4] == RESPONSE_HEADER:
            if self._buf is not None:
                self.stats.aborted_frames += 1
            self._buf = bytearray(chunk)
            self._first_chunk_size = size
        elif self._buf is None:
            self.stats.dropped_chunks += 1  # e.g. a 20-byte command ack
            return []
        else:
            data = _strip_length_prefix(chunk, self._first_chunk_size)
            if data[:4] == REQUEST_HEADER:
                # An ack in the middle of a frame: ignore it, keep the frame.
                self.stats.dropped_chunks += 1
                return []
            self._buf += data

        if len(self._buf) < FRAME_SIZE:
            return []

        # Some firmware sends longer frames; only the first 300 bytes are
        # covered by the checksum, the rest is ignored (same as esphome).
        frame = bytes(self._buf[:FRAME_SIZE])
        self._buf = None
        if is_valid_frame(frame):
            self.stats.frames_ok += 1
            return [frame]
        self.stats.crc_errors += 1
        return []
