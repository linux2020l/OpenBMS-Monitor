from pathlib import Path

import pytest

from jkbms_widget.capture import read_capture
from jkbms_widget.commands import checksum
from jkbms_widget.frames import FRAME_SIZE, FrameAssembler, is_valid_frame

FIXTURE = Path(__file__).parent / "fixtures" / "jk02_32s_b1a8s20p_windows.txt"


def rx_chunks():
    return [e.data for e in read_capture(FIXTURE) if e.direction == "RX"]


def assemble(chunks):
    asm = FrameAssembler()
    frames = [f for c in chunks for f in asm.feed(c)]
    return frames, asm.stats


@pytest.fixture(scope="module")
def real_frames():
    frames, stats = assemble(rx_chunks())
    assert stats.crc_errors == 0
    return frames


def test_real_capture_reassembles_with_valid_crc(real_frames):
    types = [f[4] for f in real_frames]
    assert types.count(0x02) == 12
    assert types.count(0x03) == 2
    assert types.count(0x01) == 1
    assert all(len(f) == FRAME_SIZE and is_valid_frame(f) for f in real_frames)


def test_acks_between_frames_are_dropped():
    _, stats = assemble(rx_chunks())
    assert stats.dropped_chunks == 2  # one ack per request (0x97, 0x96)


def _split(frame, size):
    return [frame[i:i + size] for i in range(0, len(frame), size)]


def test_small_mtu_chunking_without_prefix(real_frames):
    # Same frames as an ESP32/Android with MTU 23 would deliver them.
    chunks = [c for f in real_frames for c in _split(f, 20)]
    frames, stats = assemble(chunks)
    assert frames == real_frames
    assert stats.crc_errors == 0


def test_full_size_chunk_starting_with_bcd_like_byte_is_not_stripped():
    # 20-byte continuation chunk whose first byte (0x19) equals BCD(19):
    # must NOT be treated as a prefix, because it is not shorter than chunk 1.
    body = bytearray(FRAME_SIZE)
    body[0:6] = bytes.fromhex("55AAEB900200")
    body[20] = 0x19
    body[-1] = checksum(body[:-1])
    frames, stats = assemble(_split(bytes(body), 20))
    assert frames == [bytes(body)]


def test_ack_in_the_middle_of_a_frame_is_ignored(real_frames):
    frame = real_frames[-1]
    ack = bytes.fromhex("20AA5590EBC80101") + bytes(12) + b"\x44"
    frames, stats = assemble([frame[:128], ack, frame[128:]])
    assert frames == [frame]
    assert stats.dropped_chunks == 1


def test_corrupted_frame_is_rejected_and_next_one_still_works(real_frames):
    bad = bytearray(real_frames[-1])
    bad[150] ^= 0xFF
    frames, stats = assemble(_split(bytes(bad), 20) + _split(real_frames[-1], 20))
    assert frames == [real_frames[-1]]
    assert stats.crc_errors == 1


def test_new_header_aborts_incomplete_frame(real_frames):
    frame = real_frames[-1]
    frames, stats = assemble([frame[:100], frame[:128], frame[128:]])
    assert frames == [frame]
    assert stats.aborted_frames == 1


def test_garbage_before_first_header_is_dropped(real_frames):
    frames, stats = assemble([b"\x01\x02\x03", real_frames[0]])
    assert frames == [real_frames[0]]
    assert stats.dropped_chunks == 1
