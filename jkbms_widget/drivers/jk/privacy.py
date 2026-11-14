"""Remove private data from JK captures before they are shared.

The device-info frame (type 0x03) carries the BLE connect passcode, the
serial number and the setup passcode as ASCII. They are overwritten with
'0' (keeping their length and NUL padding) and the frame CRC is
recomputed, so the capture still decodes. The original chunking (incl.
the Windows length-prefix bytes) and timing are kept.
"""

from __future__ import annotations

from ...capture import CaptureEvent
from .frames import FRAME_SIZE, RESPONSE_HEADER, _strip_length_prefix, checksum

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


def sanitize(events: list[CaptureEvent], cell_frames: int | None = None) -> list[CaptureEvent]:
    """Scrub every device-info frame; optionally keep only `cell_frames`
    cell-info frames (fixtures stay small)."""
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
            if cell_frames is not None and seen_cell > cell_frames:
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
