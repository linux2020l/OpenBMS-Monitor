"""Replay a captured BLE log as if it came from a live BMS (no hardware).

Used by the `replay` CLI command now, and as a mock data source for the UI
in milestone 4.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path

from .capture import read_capture
from .drivers import BmsDriver
from .model import describe


def iter_chunks(
    path: str | Path,
    speed: float = 1.0,
    loop: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[bytes]:
    """Yield RX notification payloads with the original timing.

    speed: 1.0 = real time, 2.0 = twice as fast, 0 = no delays.
    loop: start over at the end (endless mock data).
    """
    events = [e for e in read_capture(path) if e.direction == "RX"]
    if not events:
        return
    while True:
        prev = events[0].time
        for e in events:
            if speed > 0:
                sleep(max(0.0, (e.time - prev) / speed))
            prev = e.time
            yield e.data
        if not loop:
            return


def run_replay(path: str | Path, speed: float, loop: bool, driver: BmsDriver,
               options: dict | None = None) -> int:
    decoder = driver.new_decoder(**(options or {}))
    for chunk in iter_chunks(path, speed, loop):
        for obj in decoder.feed(chunk):
            print(describe(obj))
    print(f"done: {decoder.stats_text()}")
    return 0
