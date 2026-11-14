import struct
from pathlib import Path

import pytest

from jkbms_widget.capture import read_capture
from jkbms_widget.commands import checksum
from jkbms_widget.frames import FrameAssembler
from jkbms_widget.parser import (
    CellInfo,
    Decoder,
    DeviceInfo,
    Variant,
    battery_state,
    guess_variant,
)

FIXTURE = Path(__file__).parent / "fixtures" / "jk02_32s_b1a8s20p_windows.txt"


@pytest.fixture(scope="module")
def decoded():
    dec = Decoder()
    out = [obj for e in read_capture(FIXTURE) if e.direction == "RX" for obj in dec.feed(e.data)]
    return dec, out


def test_device_info_and_variant(decoded):
    dec, out = decoded
    info = out[0]
    assert isinstance(info, DeviceInfo)
    assert info.model == "JK_B1A8S20P"
    assert info.hardware_version == "11A"
    assert info.software_version == "11.53"
    assert info.name == "LFP 3.8kWh"
    assert dec.variant is Variant.JK02_32S
    assert dec.skipped_cell_frames == 0


def test_first_cell_info_matches_values_seen_in_jk_app(decoded):
    _, out = decoded
    cell = next(o for o in out if isinstance(o, CellInfo))
    assert cell.cell_voltages == (3.393, 3.391, 3.391, 3.390)
    assert cell.pack_voltage == pytest.approx(13.566)
    assert cell.current == pytest.approx(-0.413)
    assert cell.power == pytest.approx(-5.6028, abs=1e-3)
    assert cell.soc == 100
    assert cell.remaining_capacity == pytest.approx(297.252)
    assert cell.nominal_capacity == pytest.approx(297.439)
    assert cell.cycle_count == 75
    assert cell.soh == 98
    assert cell.temperature_1 == pytest.approx(11.8)
    assert cell.temperature_2 == pytest.approx(12.6)
    assert cell.mosfet_temperature == pytest.approx(14.8)
    assert cell.alarm_bits == 0 and cell.alarms == ()
    assert cell.charging_enabled and cell.discharging_enabled
    assert not cell.balancing


def test_all_cell_frames_are_plausible(decoded):
    _, out = decoded
    cells = [o for o in out if isinstance(o, CellInfo)]
    assert len(cells) == 12
    for c in cells:
        assert len(c.cell_voltages) == 4
        assert 2.5 < c.cell_min <= c.cell_max < 3.65
        assert c.pack_voltage == pytest.approx(sum(c.cell_voltages), abs=0.05)
        assert 0 <= c.soc <= 100


FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.txt"))
PRIVATE_FIELDS = [(62, 16), (86, 16), (118, 16)]  # passcode, serial, setup passcode


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_device_info_fixture_is_sanitized(path):
    # Checked structurally, so the test itself never contains real secrets.
    asm = FrameAssembler()
    frames = [f for e in read_capture(path) if e.direction == "RX" for f in asm.feed(e.data) if f[4] == 3]
    assert frames
    for frame in frames:
        for offset, size in PRIVATE_FIELDS:
            assert set(frame[offset:offset + size]) <= {ord("0"), 0}, (offset, path.name)


FIXTURE_HW19 = Path(__file__).parent / "fixtures" / "jk02_32s_b2a8s20p_hw19.txt"


def test_newer_b2a8s20p_hw19_decodes_with_the_32s_layout():
    """JK-B2A8S20P HW 19H / SW 19.34 ("LFP-4kWh", captured 2026-11-14).

    Same frame layout as HW 11A. Differences seen on Windows: frames arrive
    as 128 + 128 + 44 bytes without the BCD length prefix, and the BLE
    module also sends stray 'AT\\r\\n' notifications (dropped).
    """
    dec = Decoder()
    out = [obj for e in read_capture(FIXTURE_HW19) if e.direction == "RX" for obj in dec.feed(e.data)]
    info = out[0]
    assert (info.model, info.hardware_version, info.software_version, info.name) == (
        "JK-B2A8S20P", "19H", "19.34", "LFP-4kWh")
    assert dec.variant is Variant.JK02_32S
    cells = [o for o in out if isinstance(o, CellInfo)]
    assert len(cells) == 12 and dec.assembler.stats.crc_errors == 0
    c = cells[-1]
    assert len(c.cell_voltages) == 4 and 3.40 <= c.cell_min <= c.cell_max <= 3.41
    assert c.pack_voltage == pytest.approx(13.62, abs=0.01)
    assert c.nominal_capacity == pytest.approx(314.0)
    assert c.soc == 100 and c.soh == 100 and c.cycle_count == 0
    assert c.temperature_1 == pytest.approx(22.7, abs=1.0)
    assert c.mosfet_temperature == pytest.approx(25.1, abs=1.0)
    assert c.alarms == ()


def first_cell_frame() -> bytes:
    asm = FrameAssembler()
    events = read_capture(FIXTURE)
    return next(f for e in events if e.direction == "RX" for f in asm.feed(e.data) if f[4] == 2)


def test_cell_frames_before_device_info_are_skipped():
    dec = Decoder()  # no forced variant, no device info seen yet
    assert dec.feed(first_cell_frame()) == []
    assert dec.skipped_cell_frames == 1


def test_forced_variant_decodes_without_device_info():
    dec = Decoder(variant=Variant.JK02_32S)
    out = dec.feed(first_cell_frame())
    assert len(out) == 1 and isinstance(out[0], CellInfo)


def test_alarm_bits_are_decoded_to_names():
    # Take a real cell frame, set alarm bits 4 and 11 (32S: u32 at 134+32), fix CRC.
    frame = bytearray(first_cell_frame())
    struct.pack_into("<I", frame, 134 + 32, (1 << 4) | (1 << 11))
    frame[-1] = checksum(frame[:-1])
    (cell,) = Decoder(variant=Variant.JK02_32S).feed(bytes(frame))
    assert cell.alarms == (4, 11)
    assert cell.alarm_names() == ["Battery is fully charged", "Cell undervoltage"]


@pytest.mark.parametrize(
    "hw, variant",
    [("11A", Variant.JK02_32S), ("11.XW", Variant.JK02_32S), ("15A", Variant.JK02_32S),
     ("10.XW", Variant.JK02_24S), ("8.0", Variant.JK02_24S), ("", Variant.JK02_24S)],
)
def test_guess_variant(hw, variant):
    assert guess_variant(hw) is variant


@pytest.mark.parametrize(
    "current, state",
    [(0.0, "Idle"), (0.49, "Idle"), (-0.49, "Idle"), (0.5, "Charging"),
     (12.0, "Charging"), (-0.5, "Discharging"), (-24.5, "Discharging")],
)
def test_battery_state(current, state):
    assert battery_state(current, 0.5) == state
