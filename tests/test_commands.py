import pytest

from jkbms_widget.commands import (
    ALLOWED_FRAMES,
    REQUEST_CELL_INFO,
    REQUEST_DEVICE_INFO,
    ForbiddenCommandError,
    checksum,
    ensure_read_only,
)

# Reference frames written out by hand (from the project spec / esphome-jk-bms).
DEVICE_INFO_HEX = "AA 55 90 EB 97 00 00 00 00 00 00 00 00 00 00 00 00 00 00 11"
CELL_INFO_HEX = "AA 55 90 EB 96 00 00 00 00 00 00 00 00 00 00 00 00 00 00 10"


def test_request_frames_match_reference_bytes():
    assert REQUEST_DEVICE_INFO == bytes.fromhex(DEVICE_INFO_HEX)
    assert REQUEST_CELL_INFO == bytes.fromhex(CELL_INFO_HEX)


def test_frames_are_20_bytes_with_valid_checksum():
    for frame in ALLOWED_FRAMES:
        assert len(frame) == 20
        assert frame[19] == checksum(frame[:19])


def test_only_two_frames_are_allowed():
    assert ALLOWED_FRAMES == {REQUEST_DEVICE_INFO, REQUEST_CELL_INFO}


def test_allowed_frames_pass_and_bytearray_is_accepted():
    assert ensure_read_only(REQUEST_CELL_INFO) == REQUEST_CELL_INFO
    assert ensure_read_only(bytearray(REQUEST_DEVICE_INFO)) == REQUEST_DEVICE_INFO


def _with_checksum(body: bytes) -> bytes:
    return body + bytes([checksum(body)])


@pytest.mark.parametrize(
    "frame",
    [
        # A register write (address 0x1D, length 4, value 1) with a valid checksum.
        _with_checksum(bytes.fromhex("AA5590EB 1D 04 01000000") + bytes(9)),
        # Allowed command byte but non-zero length/value: still rejected.
        _with_checksum(bytes.fromhex("AA5590EB 96 04 01000000") + bytes(9)),
        # Wrong checksum.
        REQUEST_CELL_INFO[:19] + b"\x00",
        # Truncated / extended / empty.
        REQUEST_CELL_INFO[:19],
        REQUEST_CELL_INFO + b"\x00",
        b"",
    ],
)
def test_everything_else_is_rejected(frame):
    with pytest.raises(ForbiddenCommandError):
        ensure_read_only(frame)
