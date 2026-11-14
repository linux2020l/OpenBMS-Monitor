"""Connect to the BMS, log every raw notification as hex, print decoded data.

The raw log (format: see capture.py) is the source of truth; decoding on
the console is only for live checking. Raw logs can be turned into test
fixtures with tools/make_fixture.py.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from bleak import BleakClient, BleakScanner

from .ble import describe_gatt, scan, select_characteristics, send_request
from .capture import CaptureEvent, format_event
from .commands import REQUEST_CELL_INFO, REQUEST_DEVICE_INFO
from .parser import CellInfo, Decoder, Variant
from .replay import describe

CELL_INFO_RETRY_S = 5.0  # re-send 0x96 until the first cell-info frame (as esphome does)
MAX_CELL_INFO_RETRIES = 3


async def _pick_address() -> str | None:
    print("No --address given, scanning for JK BMS (8 s)...")
    candidates = [r for r in await scan() if r.looks_like_jk]
    if len(candidates) == 1:
        c = candidates[0]
        print(f"Found {c.name!r} at {c.address} (RSSI {c.rssi} dBm)")
        return c.address
    if not candidates:
        print("No JK-looking device found. Run `scan` and pass --address.")
    else:
        print("Several JK-looking devices found, pass one with --address:")
        for c in candidates:
            print(f"  {c.address}  {c.rssi:4d} dBm  {c.name}")
    return None


async def run_dump(
    address: str | None, seconds: float, log_dir: Path, variant: Variant | None = None
) -> int:
    if address is None:
        address = await _pick_address()
        if address is None:
            return 2

    print(f"Looking for {address}...")
    device = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if device is None:
        print(
            "Device not found. Is the BMS in range and the JK phone app "
            "disconnected? (Only one BLE connection at a time.)"
        )
        return 1

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"dump-{datetime.now():%Y%m%d-%H%M%S}.txt"
    stats: Counter[str] = Counter()
    decoder = Decoder(variant)
    got_cell_info = False
    disconnected = asyncio.Event()
    t0 = time.monotonic()

    with log_path.open("w", encoding="utf-8") as log:

        def log_line(direction: str, handle: int, data: bytes) -> None:
            event = CaptureEvent(time.monotonic() - t0, direction, handle, data)
            log.write(format_event(event) + "\n")

        def comment(text: str) -> None:
            print(text)
            log.write(f"# {text}\n")

        # Called by bleak on the event loop for every BLE notification.
        def on_notify(char, data: bytearray) -> None:
            nonlocal got_cell_info
            data = bytes(data)
            log_line("RX", char.handle, data)  # log first, decode second
            stats["notifications"] += 1
            stats["bytes"] += len(data)
            for obj in decoder.feed(data):
                print(f"  {time.monotonic() - t0:6.1f}s {describe(obj)}")
                if isinstance(obj, CellInfo):
                    got_cell_info = True

        comment(f"jkbms_widget dump {datetime.now().isoformat(timespec='seconds')}")
        comment(f"device {device.address} name={device.name!r} bleak={version('bleak')}")

        async with BleakClient(
            device, disconnected_callback=lambda _c: disconnected.set()
        ) as client:
            comment("connected; GATT table:")
            for line in describe_gatt(client.services):
                comment(line)

            write_char, notify_char = select_characteristics(client.services)
            comment(f"write char handle=0x{write_char.handle:04X}, notify char handle=0x{notify_char.handle:04X}")
            await client.start_notify(notify_char, on_notify)

            async def request(frame: bytes, label: str) -> None:
                sent = await send_request(client, write_char, frame)
                log_line("TX", write_char.handle, sent)
                print(f"  {time.monotonic() - t0:7.1f}s sent {label} request")

            await request(REQUEST_DEVICE_INFO, "device info (0x97)")
            await asyncio.sleep(1.0)
            await request(REQUEST_CELL_INFO, "cell info (0x96)")

            print(f"Logging for {seconds:.0f} s (Ctrl+C to stop early)...")
            deadline = time.monotonic() + seconds
            next_retry = time.monotonic() + CELL_INFO_RETRY_S
            retries = 0
            while time.monotonic() < deadline and not disconnected.is_set():
                try:
                    await asyncio.wait_for(disconnected.wait(), timeout=1.0)
                except TimeoutError:
                    pass
                log.flush()
                if (
                    not got_cell_info
                    and retries < MAX_CELL_INFO_RETRIES
                    and time.monotonic() >= next_retry
                ):
                    retries += 1
                    await request(REQUEST_CELL_INFO, f"cell info (0x96), retry {retries}")
                    next_retry = time.monotonic() + CELL_INFO_RETRY_S

            if disconnected.is_set():
                comment("BMS disconnected")
            else:
                try:
                    await client.stop_notify(notify_char)
                except Exception:  # best effort; we disconnect anyway
                    pass

        s = decoder.assembler.stats
        comment(
            f"summary: {dict(stats)}, frames ok={s.frames_ok} crc_errors={s.crc_errors} "
            f"dropped={s.dropped_chunks} aborted={s.aborted_frames}"
        )

    print(f"Log saved to {log_path.resolve()}")
    if not got_cell_info:
        print("WARNING: no cell-info frame was decoded.")
    return 0
