"""Read and write raw BLE capture logs (the `dump` output format).

Format, one event per line ('#' lines are comments):
    <seconds since start> <TX|RX> h=0x<handle> len=<n> <hex bytes>
Example:
       2.712 RX h=0x0011 len= 23 22 00 00 ...
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CaptureEvent:
    time: float  # seconds since capture start
    direction: str  # "TX" (to BMS) or "RX" (notification from BMS)
    handle: int
    data: bytes


def format_event(event: CaptureEvent) -> str:
    return (
        f"{event.time:9.3f} {event.direction} h=0x{event.handle:04X} "
        f"len={len(event.data):3d} {event.data.hex(' ').upper()}"
    )


def parse_line(line: str) -> CaptureEvent | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split()
    # parts: time, dir, "h=0x....", "len=", maybe "n" (when padded), hex...
    time, direction, handle = float(parts[0]), parts[1], int(parts[2][2:], 16)
    rest = " ".join(parts[3:])  # "len= 23 22 00 ..." or "len=128 55 AA ..."
    length_text, _, hex_text = rest.partition("=")[2].strip().partition(" ")
    data = bytes.fromhex(hex_text)
    if len(data) != int(length_text):
        raise ValueError(f"length mismatch in capture line: {line[:60]}...")
    return CaptureEvent(time, direction, handle, data)


def read_capture(path: str | Path) -> list[CaptureEvent]:
    with open(path, encoding="utf-8") as f:
        return [e for e in map(parse_line, f) if e is not None]
