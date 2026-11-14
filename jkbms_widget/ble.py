"""BLE transport for any supported BMS, built on bleak (WinRT backend on Windows).

This module only moves bytes. It knows nothing about frame contents; the
BMS-specific parts (UUIDs, requests, allowlist) come from a driver.

SAFETY: `send_request()` is the ONLY function in the project that writes to
a BMS, and it passes every payload through `driver.ensure_read_only()`
(the driver's whole-frame allowlist). Do not call `client.write_gatt_char()`
anywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass

from bleak import BleakClient, BleakScanner

from . import drivers
from .drivers import BmsDriver


class BmsBleError(RuntimeError):
    """The connected device does not look like the expected BMS."""


@dataclass
class ScanResult:
    address: str
    name: str
    rssi: int
    driver_id: str | None  # recognised BMS family, None = unknown device

    @property
    def looks_like_bms(self) -> bool:
        return self.driver_id is not None


async def scan(timeout: float = 8.0) -> list[ScanResult]:
    """Scan for BLE devices; recognised BMS first, then by signal strength."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        driver = drivers.detect(name, list(adv.service_uuids))
        results.append(ScanResult(device.address, name, adv.rssi,
                                  None if driver is None else driver.id))
    results.sort(key=lambda r: (not r.looks_like_bms, -r.rssi))
    return results


def select_characteristics(services, driver: BmsDriver):
    """Pick (write_char, notify_char) inside the driver's GATT service.

    Some modules have TWO characteristics with the same UUID (JK: one FFE1
    for write, one for notify), others a single one that does both. Looking
    them up by UUID alone is ambiguous, so we choose by properties. Works
    with bleak's service collection (any iterable of services with
    .uuid/.characteristics, which keeps it unit-testable).
    """
    service = next((s for s in services if s.uuid.lower() == driver.service_uuid), None)
    if service is None:
        raise BmsBleError(f"GATT service {driver.service_uuid} not found - is this a {driver.name}?")
    chars = list(service.characteristics)

    def pick(uuid: str, wanted: tuple[str, ...]):
        named = [c for c in chars if c.uuid.lower() == uuid] or chars  # unexpected layout
        for prop in wanted:  # in order of preference
            found = next((c for c in named if prop in c.properties), None)
            if found is not None:
                return found
        return None

    notify = pick(driver.notify_uuid, ("notify", "indicate"))
    write = pick(driver.write_uuid, ("write-without-response", "write"))
    if notify is None or write is None:
        raise BmsBleError(f"No suitable write/notify characteristic for {driver.name}")
    return write, notify


async def send_request(client: BleakClient, write_char, frame: bytes, driver: BmsDriver) -> bytes:
    """Write one allowlisted read request to the BMS. Returns the bytes sent."""
    payload = driver.ensure_read_only(frame)  # SAFETY GATE: raises on anything else
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
