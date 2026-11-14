"""Turn a raw `dump` log into a sanitized test fixture.

Usage (from the project folder):
    python tools/make_fixture.py logs/dump-XXXX.txt tests/fixtures/NAME.txt --cell-frames 12

What it does:
* keeps all events from the start up to N complete cell-info frames,
  keeping the original chunking (prefix bytes included) and timing;
* overwrites private ASCII fields in every device-info frame (BLE passcode,
  serial number, setup passcode) and recomputes the frame checksum;
* drops the '#' header lines (they contain the MAC address).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jkbms_widget.capture import CaptureEvent, format_event, read_capture  # noqa: E402
from jkbms_widget.frames import FRAME_SIZE, RESPONSE_HEADER, _strip_length_prefix, checksum  # noqa: E402

# (offset, size) of private fields in the device-info frame (type 0x03),
# found by inspecting real frames from JK_B1A8S20P HW 11A / SW 11.53 and
# JK-B2A8S20P HW 19H / SW 19.34. Each field is scrubbed up to its first NUL.
PRIVATE_FIELDS = [
    (62, 16),  # BLE connect passcode
    (86, 16),  # serial number (11 chars on HW 11A, 15 on HW 19H)
    (118, 16),  # setup passcode
]


def _scrub(frame: bytearray) -> None:
    for offset, size in PRIVATE_FIELDS:
        old = frame[offset:offset + size]
        used = len(old.split(b"\x00", 1)[0])  # keep the original length/NUL padding
        frame[offset:offset + used] = b"0" * used
    frame[FRAME_SIZE - 1] = checksum(frame[:FRAME_SIZE - 1])


def sanitize(events: list[CaptureEvent], cell_frames: int) -> list[CaptureEvent]:
    out = list(events)
    i, seen_cell = 0, 0
    while i < len(out):
        e = out[i]
        if e.direction != "RX" or e.data[:4] != RESPONSE_HEADER:
            i += 1
            continue
        ftype = e.data[4]
        if ftype == 0x02:
            seen_cell += 1
            if seen_cell > cell_frames:
                return out[:i]
        # Collect this frame's chunks: (index, prefix_len, payload).
        parts = [(i, 0, e.data)]
        size, j = len(e.data), i + 1
        while size < FRAME_SIZE and j < len(out):
            if out[j].direction == "RX":
                data = _strip_length_prefix(out[j].data, len(e.data))
                parts.append((j, len(out[j].data) - len(data), data))
                size += len(data)
            j += 1
        if ftype == 0x03 and size >= FRAME_SIZE:
            frame = bytearray(b"".join(p for _, _, p in parts))
            _scrub(frame)
            pos = 0
            for idx, prefix_len, payload in parts:
                new = out[idx].data[:prefix_len] + bytes(frame[pos:pos + len(payload)])
                out[idx] = CaptureEvent(out[idx].time, "RX", out[idx].handle, new)
                pos += len(payload)
        i = j
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--cell-frames", type=int, default=12)
    ap.add_argument("--note", default="JK_B1A8S20P HW 11A SW 11.53, Windows 11, bleak 1.1.1")
    args = ap.parse_args()

    events = sanitize(read_capture(args.src), args.cell_frames)
    with open(args.dst, "w", encoding="utf-8") as f:
        f.write(f"# Sanitized capture: {args.note}\n")
        f.write("# Device-info passcodes/serial overwritten with '0', CRC recomputed.\n")
        for e in events:
            f.write(format_event(e) + "\n")
    print(f"wrote {len(events)} events to {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
