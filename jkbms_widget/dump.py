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

from . import drivers
from .ble import describe_gatt, scan, select_characteristics, send_request
from .capture import CaptureEvent, format_event
from .drivers import BmsDriver
from .model import CellInfo, describe

MAX_POLL_ROUNDS_BEFORE_DATA = 3  # give up re-requesting if the BMS stays silent


async def _pick_device() -> tuple[str, BmsDriver] | None:
    print("No --address given, scanning for a BMS (8 s)...")
    candidates = [r for r in await scan() if r.looks_like_bms]
    if len(candidates) == 1:
        c = candidates[0]
        print(f"Found {c.name!r} at {c.address} (RSSI {c.rssi} dBm, {c.driver_id})")
        return c.address, drivers.get(c.driver_id)
    if not candidates:
        print("No known BMS found. Run `scan` and pass --address.")
    else:
        print("Several BMS found, pass one with --address:")
        for c in candidates:
            print(f"  {c.address}  {c.rssi:4d} dBm  {c.driver_id:6s} {c.name}")
    return None


async def run_dump(
    address: str | None, seconds: float, log_dir: Path,
    driver: BmsDriver | None = None, options: dict | None = None,
) -> int:
    if address is None:
        picked = await _pick_device()
        if picked is None:
            return 2
        address, detected = picked
        driver = driver or detected
    driver = driver or drivers.DEFAULT_DRIVER

    print(f"Looking for {address}...")
    device = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if device is None:
        print(
            "Device not found. Is the BMS in range and its phone app "
            "disconnected? (Only one BLE connection at a time.)"
        )
        return 1

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"dump-{datetime.now():%Y%m%d-%H%M%S}.txt"
    stats: Counter[str] = Counter()
    decoder = driver.new_decoder(**(options or {}))
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
        comment(f"driver {driver.id}")  # replay/fixtures: which decoder to use

        async with BleakClient(
            device, disconnected_callback=lambda _c: disconnected.set()
        ) as client:
            comment("connected; GATT table:")
            for line in describe_gatt(client.services):
                comment(line)

            write_char, notify_char = select_characteristics(client.services, driver)
            comment(f"write char handle=0x{write_char.handle:04X}, notify char handle=0x{notify_char.handle:04X}")
            await client.start_notify(notify_char, on_notify)

            async def request(req) -> None:
                sent = await send_request(client, write_char, req.frame, driver)
                log_line("TX", write_char.handle, sent)
                print(f"  {time.monotonic() - t0:7.1f}s sent {req.label} request")
                if req.delay_after_s:
                    await asyncio.sleep(req.delay_after_s)

            for req in driver.connect_requests:
                await request(req)

            print(f"Logging for {seconds:.0f} s (Ctrl+C to stop early)...")
            deadline = time.monotonic() + seconds
            next_poll = time.monotonic() + driver.poll_interval_s
            rounds_without_data = 0
            while time.monotonic() < deadline and not disconnected.is_set():
                try:
                    await asyncio.wait_for(disconnected.wait(), timeout=1.0)
                except TimeoutError:
                    pass
                log.flush()
                if got_cell_info and driver.poll_until_data:
                    continue
                if not got_cell_info and rounds_without_data >= MAX_POLL_ROUNDS_BEFORE_DATA:
                    continue
                if driver.poll_requests and time.monotonic() >= next_poll:
                    rounds_without_data += not got_cell_info
                    for req in driver.poll_requests:
                        await request(req)
                    next_poll = time.monotonic() + driver.poll_interval_s

            if disconnected.is_set():
                comment("BMS disconnected")
            else:
                try:
                    await client.stop_notify(notify_char)
                except Exception:  # best effort; we disconnect anyway
                    pass

        comment(f"summary: {dict(stats)}, {decoder.stats_text()}")

    print(f"Log saved to {log_path.resolve()}")
    if not got_cell_info:
        print("WARNING: no cell-info frame was decoded.")
    return 0
