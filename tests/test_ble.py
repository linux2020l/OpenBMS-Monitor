import asyncio
from types import SimpleNamespace as NS

import pytest

from jkbms_widget.ble import (
    JK_CHAR_UUID,
    JK_SERVICE_UUID,
    JkBleError,
    select_characteristics,
    send_request,
)
from jkbms_widget.commands import REQUEST_CELL_INFO, ForbiddenCommandError

OTHER_UUID = "00002a00-0000-1000-8000-00805f9b34fb"


def char(handle, props, uuid=JK_CHAR_UUID):
    return NS(uuid=uuid, handle=handle, properties=props, descriptors=[])


def service(chars, uuid=JK_SERVICE_UUID):
    return NS(uuid=uuid, handle=1, characteristics=chars)


def test_new_module_with_two_ffe1_characteristics():
    w = char(0x03, ["write-without-response", "write"])
    n = char(0x05, ["notify"])
    services = [service([char(0x10, ["read"], OTHER_UUID)], OTHER_UUID), service([w, n])]
    assert select_characteristics(services) == (w, n)


def test_old_module_with_single_ffe1():
    c = char(0x12, ["read", "write-without-response", "write", "notify"])
    assert select_characteristics([service([c])]) == (c, c)


def test_missing_service_raises():
    with pytest.raises(JkBleError):
        select_characteristics([service([], OTHER_UUID)])


class FakeClient:
    def __init__(self):
        self.writes = []

    async def write_gatt_char(self, char, data, response):
        self.writes.append((char, data, response))


def test_send_request_writes_allowed_frame_without_response():
    client, w = FakeClient(), char(0x03, ["write-without-response"])
    asyncio.run(send_request(client, w, REQUEST_CELL_INFO))
    assert client.writes == [(w, REQUEST_CELL_INFO, False)]


def test_send_request_never_writes_forbidden_frame():
    client, w = FakeClient(), char(0x03, ["write"])
    write_frame = bytes.fromhex("AA5590EB1D0401000000") + bytes(9) + b"\x00"
    with pytest.raises(ForbiddenCommandError):
        asyncio.run(send_request(client, w, write_frame))
    assert client.writes == []
