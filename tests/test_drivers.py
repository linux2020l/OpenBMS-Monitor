from datetime import datetime
from pathlib import Path

import pytest

from jkbms_widget import diagnostics, drivers
from jkbms_widget.capture import capture_driver_id, read_capture
from jkbms_widget.drivers import ant, daly, jbd
from jkbms_widget.drivers.jk import DRIVER as JK
from jkbms_widget.model import CellInfo, DeviceInfo

FFE0 = "0000ffe0-0000-1000-8000-00805f9b34fb"
FIXTURE = Path(__file__).parent / "fixtures" / "jk02_32s_b1a8s20p_windows.txt"


def hx(frame: bytes) -> str:
    return frame.hex(" ").upper()


# Frames quoted verbatim in the sources (esphome-jbd-bms, esphome-ant-bms,
# aiobmsble). Our builders must reproduce them byte for byte.
@pytest.mark.parametrize("frame, expected", [
    (jbd.REQUEST_BASIC_INFO, "DD A5 03 00 FF FD 77"),
    (jbd.REQUEST_CELL_INFO, "DD A5 04 00 FF FC 77"),
    (jbd.REQUEST_HARDWARE, "DD A5 05 00 FF FB 77"),
    (ant.REQUEST_STATUS, "7E A1 01 00 00 BE 18 55 AA 55"),
    (ant.REQUEST_DEVICE_INFO, "7E A1 02 6C 02 20 58 C4 AA 55"),
    (daly.REQUEST_D2_MAIN, "D2 03 00 00 00 3E D7 B9"),
    (daly.REQUEST_X81_BLOCK1, "81 03 00 00 00 40 5B FA"),
    (daly.REQUEST_X81_BLOCK2, "81 03 00 41 00 3E 8B CE"),
])
def test_request_frames_match_the_protocol_sources(frame, expected):
    assert hx(frame) == expected


def test_new_drivers_only_send_read_requests():
    # JBD: DD A5 = read register (DD 5A would be a write).
    assert all(f[:2] == b"\xdd\xa5" for f in jbd.DRIVER.allowed_frames)
    # Daly: Modbus function 0x03 = read holding registers (0x06/0x10 write).
    assert all(f[1] == 0x03 for f in daly.DRIVER.allowed_frames)
    # ANT: function 0x01 status / 0x02 read (0x23 password, 0x51 write).
    assert {f[2] for f in ant.DRIVER.allowed_frames} == {0x01, 0x02}
    for d in (jbd.DRIVER, daly.DRIVER, ant.DRIVER):
        assert d.capture_only and not drivers.monitorable(d.id)
    assert drivers.monitorable("jk") and not drivers.monitorable(None)


@pytest.mark.parametrize("name, uuids, expected", [
    ("LFP 3.8kWh", [FFE0], "jk"),  # JK BMS renamed by the owner: found by UUID
    ("JK_B2A8S20P", [], "jk"),
    ("ANT-BLE24ATSB", [FFE0], "ant"),  # same UUID as JK: the name decides
    ("JBD-SP04S028-L4S", [], "jbd"),
    ("SX1234", [], "jbd"),
    ("DL-40D63C2B1234", [], "daly"),
    ("Speaker", ["0000180a-0000-1000-8000-00805f9b34fb"], None),
])
def test_detection(name, uuids, expected):
    d = drivers.detect(name, uuids)
    assert (d.id if d else None) == expected


def recording_from_fixture() -> diagnostics.Recording:
    rec = diagnostics.Recording(JK, "C8:47:80:AA:BB:CC", "LFP 3.8kWh", datetime(2026, 11, 15, 1, 2, 3))
    rec.gatt = ["service 0000ffe0-0000-1000-8000-00805f9b34fb handle=0x000E"]
    rec.events = read_capture(FIXTURE)
    rec.readings, rec.stats = 12, "12 frames OK"
    return rec


def test_shared_capture_hides_the_address_and_replays(tmp_path):
    rec = recording_from_fixture()
    path = diagnostics.save(rec, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert path.name == "bms-capture-jk-20261115-010203.txt"
    assert "C8:47:80:AA:BB:CC" not in text and "address removed" in text
    assert capture_driver_id(path) == "jk"
    dec = drivers.get(capture_driver_id(path)).new_decoder()
    out = [o for e in read_capture(path) if e.direction == "RX" for o in dec.feed(e.data)]
    assert isinstance(out[0], DeviceInfo) and sum(isinstance(o, CellInfo) for o in out) == 12


def test_raw_decoder_counts_traffic_of_capture_only_brands():
    dec = jbd.DRIVER.new_decoder()
    assert dec.feed(b"\xdd\x03\x00\x1b") == [] and dec.feed(b"\x77") == []
    assert dec.stats_text().startswith("2 notifications, 5 bytes")
