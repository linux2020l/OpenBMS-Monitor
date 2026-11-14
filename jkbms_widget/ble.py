"""BLE transport for the JK BMS, built on bleak (WinRT backend on Windows).

This module only moves bytes. It knows nothing about frame contents.

SAFETY: `send_request()` is the ONLY function in the project that writes to
the BMS, and it passes every payload through `commands.ensure_read_only()`.
Do not call `client.write_gatt_char()` anywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass

from bleak import BleakClient, BleakScanner

from .commands import ensure_read_only

# Full 128-bit forms of the 16-bit UUIDs 0xFFE0 / 0xFFE1 (bleak reports these).
JK_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
JK_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"


class JkBleError(RuntimeError):
    """The connected device does not look like a JK BMS."""


@dataclass
class ScanResult:
    address: str
    name: str
    rssi: int
    looks_like_jk: bool


async def scan(timeout: float = 8.0) -> list[ScanResult]:
    """Scan for BLE devices; JK candidates first, then by signal strength."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        uuids = [u.lower() for u in adv.service_uuids]
        looks_like_jk = JK_SERVICE_UUID in uuids or name.upper().startswith("JK")
        results.append(ScanResult(device.address, name, adv.rssi, looks_like_jk))
    results.sort(key=lambda r: (not r.looks_like_jk, -r.rssi))
    return results


def select_characteristics(services):
    """Pick (write_char, notify_char) inside service 0xFFE0.

    Newer JK BLE modules have TWO characteristics with the same UUID 0xFFE1
    (one for write, one for notify); older ones have a single FFE1 that does
    both. Looking them up by UUID alone is ambiguous, so we choose by
    properties. Works with bleak's service collection (any iterable of
    services with .uuid/.characteristics, which keeps it unit-testable).
    """
    service = next((s for s in services if s.uuid.lower() == JK_SERVICE_UUID), None)
    if service is None:
        raise JkBleError("GATT service 0xFFE0 not found - is this a JK BMS?")

    chars = [c for c in service.characteristics if c.uuid.lower() == JK_CHAR_UUID]
    if not chars:  # unexpected layout: fall back to anything in the service
        chars = list(service.characteristics)

    notify = next((c for c in chars if "notify" in c.properties), None)
    write = next(
        (c for c in chars if "write-without-response" in c.properties), None
    ) or next((c for c in chars if "write" in c.properties), None)

    if notify is None or write is None:
        raise JkBleError("No suitable write/notify characteristic in service 0xFFE0")
    return write, notify


async def send_request(client: BleakClient, write_char, frame: bytes) -> bytes:
    """Write one allowlisted read request to the BMS. Returns the bytes sent."""
    payload = ensure_read_only(frame)  # SAFETY GATE: raises on anything else
    # esphome uses write-without-response; use it whenever the char supports it.
    response = "write-without-response" not in write_char.properties
    await client.write_gatt_char(write_char, payload, response=response)
    return payload


def describe_gatt(services) -> list[str]:
    """Human-readable GATT table (services, characteristics, descriptors)."""
    lines = []
    for s in services:
        lines.append(f"service {s.uuid} handle=0x{s.handle:04X}")
        for c in s.characteristics:
            props = ",".join(c.properties)
            lines.append(f"  char {c.uuid} handle=0x{c.handle:04X} props={props}")
            for d in c.descriptors:
                lines.append(f"    desc {d.uuid} handle=0x{d.handle:04X}")
    return lines
