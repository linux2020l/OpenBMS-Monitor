from pathlib import Path

from jkbms_widget.capture import parse_line, read_capture
from jkbms_widget.replay import iter_chunks

FIXTURE = Path(__file__).parent / "fixtures" / "jk02_32s_b1a8s20p_windows.txt"


def test_replay_yields_all_rx_chunks_in_order_with_timing():
    delays = []
    chunks = list(iter_chunks(FIXTURE, speed=2.0, sleep=delays.append))
    rx = [e for e in read_capture(FIXTURE) if e.direction == "RX"]
    assert chunks == [e.data for e in rx]
    total = rx[-1].time - rx[0].time
    assert abs(sum(delays) - total / 2) < 1e-6  # speed 2 = half the time


def test_replay_loop_repeats():
    gen = iter_chunks(FIXTURE, speed=0, loop=True)
    n = sum(1 for e in read_capture(FIXTURE) if e.direction == "RX")
    first = [next(gen) for _ in range(n)]
    second = [next(gen) for _ in range(n)]
    assert first == second


def test_parse_line_handles_padded_and_unpadded_length():
    assert parse_line("    1.000 RX h=0x0011 len= 3 AA BB CC").data == b"\xaa\xbb\xcc"
    assert parse_line("    1.000 TX h=0x0011 len=128 " + "00 " * 128).direction == "TX"
    assert parse_line("# comment") is None
