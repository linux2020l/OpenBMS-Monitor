import asyncio
from types import SimpleNamespace as NS

import pytest

from jkbms_widget import drivers
from jkbms_widget.ble import BmsBleError, select_characteristics, send_request
from jkbms_widget.drivers import ForbiddenCommandError
from jkbms_widget.drivers.jk import DRIVER as JK
from jkbms_widget.drivers.jk.commands import ALLOWED_FRAMES, REQUEST_CELL_INFO

OTHER_UUID = "00002a00-0000-1000-8000-00805f9b34fb"


def char(handle, props, uuid=JK.notify_uuid):
    return NS(uuid=uuid, handle=handle, properties=props, descriptors=[])


def service(chars, uuid=JK.service_uuid):
    return NS(uuid=uuid, handle=1, characteristics=chars)


def test_new_module_with_two_ffe1_characteristics():
    w = char(0x03, ["write-without-response", "write"])
    n = char(0x05, ["notify"])
    services = [service([char(0x10, ["read"], OTHER_UUID)], OTHER_UUID), service([w, n])]
    assert select_characteristics(services, JK) == (w, n)


def test_old_module_with_single_ffe1():
    c = char(0x12, ["read", "write-without-response", "write", "notify"])
    assert select_characteristics([service([c])], JK) == (c, c)


def test_missing_service_raises():
    with pytest.raises(BmsBleError):
        select_characteristics([service([], OTHER_UUID)], JK)


class FakeClient:
    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, char, data, response):
        self.writes.append((char, data, response))


def test_send_request_writes_allowed_frame_without_response():
    client, w = FakeClient(), char(0x03, ["write-without-response"])
    asyncio.run(send_request(client, w, REQUEST_CELL_INFO, JK))
    assert client.writes == [(w, REQUEST_CELL_INFO, False)]


def test_send_request_never_writes_forbidden_frame():
    client, w = FakeClient(), char(0x03, ["write"])
    write_frame = bytes.fromhex("AA5590EB1D0401000000") + bytes(9) + b"\x00"
    with pytest.raises(ForbiddenCommandError):
        asyncio.run(send_request(client, w, write_frame, JK))
    assert client.writes == []


# ----- read-only rules every driver must follow --------------------------------
@pytest.mark.parametrize("driver", drivers.DRIVERS, ids=lambda d: d.id)
def test_driver_sends_only_allowlisted_frames(driver):
    sent = {r.frame for r in driver.connect_requests + driver.poll_requests}
    assert sent, "a driver must request data"
    assert sent <= driver.allowed_frames
    assert all(isinstance(f, bytes) for f in driver.allowed_frames)


def test_jk_allowlist_is_exactly_the_two_read_requests():
    assert JK.allowed_frames == ALLOWED_FRAMES
    assert {f[4] for f in ALLOWED_FRAMES} == {0x96, 0x97}  # cell info, device info only


def test_registry_lookup_and_detection():
    assert drivers.get("jk") is JK
    assert drivers.get(None) is JK and drivers.get("nope") is JK  # old settings files
    assert drivers.detect("LFP-4kWh", [JK.service_uuid.upper()]) is JK
    assert drivers.detect("JK_B2A8S20P", []) is JK
    assert drivers.detect("Phone", [OTHER_UUID]) is None
