"""Data sources for the UI: live BLE or a replayed capture.

Each source runs in its own background thread and talks to the GUI only
through Qt signals. A signal emitted from another thread is delivered to
GUI objects via the Qt event loop (queued connection), so slots always run
on the GUI thread and never touch BLE state directly.

bleak runs on a private asyncio loop in the BLE thread, never on the Qt
main thread (Qt initializes COM as STA there, which breaks WinRT).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import drivers
from .drivers import BmsDriver
from .model import CellInfo, DeviceInfo

log = logging.getLogger("jkbms_widget.ble")

RECONNECT_DELAY_S = 5.0  # wait between connection attempts
DATA_TIMEOUT_S = 10.0  # no notification for this long = connection is dead


class DataSource(QObject):
    """Common signals. status codes: see strings.STATUS_TEXT."""

    status = Signal(str, str)  # (code, detail)
    device_info = Signal(object)  # DeviceInfo
    cell_info = Signal(object)  # CellInfo

    can_disconnect = True

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=type(self).__name__, daemon=True)
        self._thread.start()

    def stop(self, wait_s: float = 0.0) -> None:
        """Ask the thread to finish; optionally wait (used on app exit)."""
        self._stop.set()
        if wait_s and self._thread is not None:
            self._thread.join(wait_s)

    def _emit(self, obj: DeviceInfo | CellInfo) -> None:
        if isinstance(obj, DeviceInfo):
            self.device_info.emit(obj)
        else:
            self.cell_info.emit(obj)

    def _run(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class ReplaySource(DataSource):
    """Plays a capture file in an endless loop (mock BMS)."""

    def __init__(self, path: str | Path, speed: float = 1.0, driver: BmsDriver | None = None,
                 options: dict | None = None):
        super().__init__()
        self.path, self.speed = Path(path), speed
        self.driver = driver or drivers.DEFAULT_DRIVER
        self.options = options or {}

    def _run(self) -> None:
        from .replay import iter_chunks

        self.status.emit("replay", self.path.name)
        decoder = self.driver.new_decoder(**self.options)
        # Interruptible sleep: wakes up immediately when stop() is called.
        for chunk in iter_chunks(self.path, self.speed or 1.0, loop=True, sleep=self._stop.wait):
            if self._stop.is_set():
                break
            for obj in decoder.feed(chunk):
                self._emit(obj)
        self.status.emit("stopped", "")


class BleSource(DataSource):
    """Connects to the BMS, streams data, reconnects when the link drops."""

    def __init__(self, address: str, driver: BmsDriver | None = None,
                 options: dict | None = None):
        super().__init__()
        self.address = address
        self.driver = driver or drivers.DEFAULT_DRIVER
        self.options = options or {}  # driver options, e.g. JK {"variant": "JK02_32S"}

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        while not self._stop.is_set():
            try:
                await self._session()
            except Exception as exc:  # any BLE failure -> show it, retry later
                if not self._stop.is_set():
                    log.warning("BLE session ended: %s: %s", type(exc).__name__, exc)
                    self.status.emit("lost", f"{type(exc).__name__}: {exc}")
            # Wait before the next attempt, but react quickly to stop().
            deadline = time.monotonic() + RECONNECT_DELAY_S
            while not self._stop.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.2)
        self.status.emit("stopped", "")

    async def _session(self) -> None:
        from bleak import BleakClient, BleakScanner

        from .ble import select_characteristics, send_request

        drv = self.driver
        self.status.emit("connecting", self.address)
        device = await BleakScanner.find_device_by_address(self.address, timeout=10.0)
        if device is None:
            raise ConnectionError("BMS not found (out of range or phone app connected?)")
        if self._stop.is_set():
            return

        decoder = drv.new_decoder(**self.options)
        disconnected = asyncio.Event()
        last_rx = time.monotonic()
        got_cell_info = False

        def on_notify(_char, data: bytearray) -> None:
            nonlocal last_rx, got_cell_info
            last_rx = time.monotonic()
            for obj in decoder.feed(data):
                got_cell_info |= isinstance(obj, CellInfo)
                self._emit(obj)

        async with BleakClient(
            device, disconnected_callback=lambda _c: disconnected.set()
        ) as client:
            write_char, notify_char = select_characteristics(client.services, drv)
            await client.start_notify(notify_char, on_notify)
            self.status.emit("connected", device.name or self.address)

            for req in drv.connect_requests:
                await send_request(client, write_char, req.frame, drv)
                if req.delay_after_s:
                    await asyncio.sleep(req.delay_after_s)
            next_poll = time.monotonic() + drv.poll_interval_s
            last_rx = time.monotonic()

            while not self._stop.is_set() and not disconnected.is_set():
                await asyncio.sleep(0.2)
                now = time.monotonic()
                polling = drv.poll_requests and not (drv.poll_until_data and got_cell_info)
                if polling and now >= next_poll:
                    for req in drv.poll_requests:
                        await send_request(client, write_char, req.frame, drv)
                        if req.delay_after_s:
                            await asyncio.sleep(req.delay_after_s)
                    next_poll = now + drv.poll_interval_s
                if now - last_rx > DATA_TIMEOUT_S:
                    raise TimeoutError(f"no data for {DATA_TIMEOUT_S:.0f} s")
            # Leaving the `async with` block disconnects from the BMS.

        if disconnected.is_set() and not self._stop.is_set():
            raise ConnectionError("BMS closed the connection")
