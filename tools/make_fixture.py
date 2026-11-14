"""Turn a raw JK `dump` log into a sanitized test fixture.

Usage (from the project folder):
    python tools/make_fixture.py logs/dump-XXXX.txt tests/fixtures/NAME.txt --cell-frames 12

What it does:
* keeps all events from the start up to N complete cell-info frames,
  keeping the original chunking (prefix bytes included) and timing;
* overwrites private ASCII fields in every device-info frame (BLE passcode,
  serial number, setup passcode) and recomputes the frame checksum
  (drivers/jk/privacy.py);
* drops the '#' header lines (they contain the MAC address).

Captures recorded in the app ("Record diagnostics") are already sanitized.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jkbms_widget.capture import format_event, read_capture  # noqa: E402
from jkbms_widget.drivers.jk.privacy import PRIVATE_FIELDS, sanitize  # noqa: E402,F401


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
