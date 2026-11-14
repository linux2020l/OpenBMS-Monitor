"""Record a diagnostic capture of any supported BMS (bleak, no Qt).

Used by the in-app "Record diagnostics" dialog (shareable, sanitized file)
and by the `dump` command (raw developer log). The capture format is the
one in capture.py, so recordings replay and turn into test fixtures.

Only the driver's read-only requests are sent (ble.send_request checks
every frame against the driver's allowlist).
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import __version__
from .capture import CaptureEvent, format_event
from .drivers import BmsDriver
from .model import CellInfo, DeviceInfo

MAX_POLL_ROUNDS_BEFORE_DATA = 3  # stop re-requesting if a streaming BMS stays silent


@dataclass
class Recording:
    driver: BmsDriver
    address: str
    name: str
    started: datetime
    gatt: list[str] = field(default_factory=list)
    events: list[CaptureEvent] = field(default_factory=list)
    readings: int = 0  # decoded cell readings (0 for capture-only drivers)
    stats: str = ""
    error: str = ""  # why the capture ended early, if it did

    @property
    def rx_count(self) -> int:
        return sum(1 for e in self.events if e.direction == "RX")


def _bleak_version() -> str:
    try:
        return version("bleak")
    except PackageNotFoundError:
        return "?"


async def record(
    address: str,
    driver: BmsDriver,
    seconds: float,
    stop: threading.Event | None = None,
    progress: Callable[[float, int], None] | None = None,
    on_object: Callable[[float, DeviceInfo | CellInfo], None] | None = None,
    on_request: Callable[[float, str], None] | None = None,
    options: dict | None = None,
    name: str = "",
) -> Recording:
    """Connect, send the driver's requests, log every notification.

    progress(elapsed_s, notifications) is called about once a second;
    on_object / on_request are for live console output (dump).
    Never raises for BLE errors: they end up in Recording.error.
    """
    from bleak import BleakClient, BleakScanner

    from .ble import describe_gatt, select_characteristics, send_request

    rec = Recording(driver, address, name, datetime.now())
    decoder = driver.new_decoder(**(options or {}))
    t0 = time.monotonic()
    stop = stop or threading.Event()

    def elapsed() -> float:
        return time.monotonic() - t0

    try:
        device = await BleakScanner.find_device_by_address(address, timeout=15.0)
        if device is None:
            rec.error = "device not found (out of range, or connected to a phone app?)"
            return rec
        rec.name = device.name or name  # Windows often has no name here: use the scan's
        disconnected = asyncio.Event()
        got_data = False

        def on_notify(char, data: bytearray) -> None:
            nonlocal got_data
            data = bytes(data)
            rec.events.append(CaptureEvent(elapsed(), "RX", char.handle, data))  # log first
            for obj in decoder.feed(data):
                if isinstance(obj, CellInfo):
                    rec.readings += 1
                    got_data = True
                if on_object:
                    on_object(elapsed(), obj)

        async with BleakClient(device, disconnected_callback=lambda _c: disconnected.set()) as client:
            rec.gatt = describe_gatt(client.services)
            write_char, notify_char = select_characteristics(client.services, driver)
            rec.gatt.append(f"write char handle=0x{write_char.handle:04X}, "
                            f"notify char handle=0x{notify_char.handle:04X}")
            await client.start_notify(notify_char, on_notify)

            async def request(req) -> None:
                sent = await send_request(client, write_char, req.frame, driver)
                rec.events.append(CaptureEvent(elapsed(), "TX", write_char.handle, sent))
                if on_request:
                    on_request(elapsed(), req.label)
                if req.delay_after_s:
                    await asyncio.sleep(req.delay_after_s)

            for req in driver.connect_requests:
                await request(req)
            next_poll = time.monotonic() + driver.poll_interval_s
            rounds_without_data = 0
            while elapsed() < seconds and not disconnected.is_set() and not stop.is_set():
                await asyncio.sleep(0.25)
                if progress:
                    progress(elapsed(), rec.rx_count)
                # Streaming BMS (JK) stop being polled once data flows; others
                # are polled all the time. Give up re-requesting a silent one.
                if got_data and driver.poll_until_data:
                    continue
                if driver.poll_until_data and rounds_without_data >= MAX_POLL_ROUNDS_BEFORE_DATA:
                    continue
                if driver.poll_requests and time.monotonic() >= next_poll:
                    rounds_without_data += not got_data
                    for req in driver.poll_requests:
                        await request(req)
                    next_poll = time.monotonic() + driver.poll_interval_s
            if disconnected.is_set():
                rec.error = "BMS closed the connection"
            else:
                try:
                    await client.stop_notify(notify_char)
                except Exception:  # best effort; we disconnect anyway
                    pass
    except Exception as exc:  # BLE failure: keep what was recorded so far
        rec.error = f"{type(exc).__name__}: {exc}"
    finally:
        rec.stats = decoder.stats_text()
    return rec


def header_lines(rec: Recording, include_address: bool) -> list[str]:
    """Comment lines for the capture file. '# driver <id>' must stay one line."""
    lines = [
        f"jkbms_widget capture {rec.started.isoformat(timespec='seconds')}",
        f"app {__version__} bleak={_bleak_version()}",
        f"driver {rec.driver.id}",
        f"brand {rec.driver.name}" + (f" (protocol from {rec.driver.source})" if rec.driver.source else ""),
        (f"device {rec.address} name={rec.name!r}" if include_address
         else f"device name={rec.name!r} (address removed)"),
        "GATT table:",
        *rec.gatt,
    ]
    return lines


def footer_lines(rec: Recording) -> list[str]:
    lines = [f"summary: {rec.rx_count} notifications, {rec.readings} decoded readings, {rec.stats}"]
    if rec.error:
        lines.append(f"ended early: {rec.error}")
    return lines


def to_text(rec: Recording, sanitized: bool = True) -> str:
    """Capture file text. Sanitized: no MAC address, private fields scrubbed
    by the driver (e.g. JK serial number / passcodes)."""
    events = rec.driver.sanitize_events(rec.events) if sanitized else rec.events
    out = [f"# {line}" for line in header_lines(rec, include_address=not sanitized)]
    if sanitized:
        out.append("# Sanitized for sharing: MAC address removed, private fields overwritten.")
    out += [format_event(e) for e in events]
    out += [f"# {line}" for line in footer_lines(rec)]
    return "\n".join(out) + "\n"


def file_name(rec: Recording) -> str:
    return f"bms-capture-{rec.driver.id}-{rec.started:%Y%m%d-%H%M%S}.txt"


def save(rec: Recording, folder: Path, sanitized: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name(rec)
    path.write_text(to_text(rec, sanitized), encoding="utf-8")
    return path
