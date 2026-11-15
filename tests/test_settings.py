import json

from jkbms_widget.settings import Settings
from jkbms_widget.state import History


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(address="C8:47:80:1A:F9:9E", bms_name="LFP 3.8kWh",
                 compact_pos=[100, 200], dashboard_geometry=[1, 2, 900, 600], ui_scale=1.25)
    s.save(path)
    loaded = Settings.load(path)
    assert loaded == s


def test_missing_or_corrupt_settings_give_defaults(tmp_path):
    assert Settings.load(tmp_path / "nope.json") == Settings()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert Settings.load(bad) == Settings()
    bad.write_text("[1, 2]", encoding="utf-8")
    assert Settings.load(bad) == Settings()


def test_settings_file_with_bom_is_read(tmp_path):
    path = tmp_path / "s.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"address": "C8:47:80:1A:F9:9E"}).encode())
    assert Settings.load(path).address == "C8:47:80:1A:F9:9E"


def test_settings_sanitizes_and_ignores_unknown_keys(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({
        "address": "AA", "idle_threshold": -5, "ui_scale": 10, "variant": "JK99",
        "compact_pos": [1], "unknown_key": 1,
    }), encoding="utf-8")
    s = Settings.load(path)
    assert s.address == "AA"
    assert s.idle_threshold == 0.0 and s.ui_scale == 3.0
    assert s.variant is None and s.compact_pos is None


def test_history_json_roundtrip_drops_old_points():
    h = History(bucket_s=10)
    for k in range(30):
        h.add(1000.0 + k, soc=90, current=-2.0)
    restored = History(bucket_s=10, max_age_s=100)
    restored.load_json(h.to_json(), now=1040.0)
    assert [p.time for p in restored.series(3600, 1040.0)] == [1000, 1010, 1020]
    # Older than max_age: dropped.
    late = History(bucket_s=10, max_age_s=100)
    late.load_json(h.to_json(), now=1115.0)
    assert [p.time for p in late.series(3600, 1115.0)] == [1020]


def test_history_ignores_bad_json():
    h = History()
    h.load_json("garbage", now=0)
    h.load_json('{"points": [[1, 2]]}', now=0)
    assert h.series(3600, 0) == []


def test_notification_settings_are_sanitized(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"low_soc_threshold": 300, "notify_enabled": 0}), encoding="utf-8")
    s = Settings.load(path)
    assert s.low_soc_threshold == 100 and s.notify_enabled is False
    assert Settings().low_soc_threshold == 20 and Settings().notify_enabled is True


def test_devices_main_plus_extras_round_trip(tmp_path):
    from jkbms_widget.settings import Device

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "address": "C8:47:80:1A:F9:9E", "bms_name": "LFP 3.8kWh",
        "extra_devices": [{"address": "c8:47:80:7a:dc:b3", "name": "LFP-4kWh", "bogus": 1},
                          {"address": "C8:47:80:1A:F9:9E"},  # duplicate of the main one
                          {"name": "no address"}, "junk"],
    }), encoding="utf-8")
    s = Settings.load(path)
    devs = s.devices()
    assert [d.address for d in devs] == ["C8:47:80:1A:F9:9E", "C8:47:80:7A:DC:B3"]
    assert devs[1].name == "LFP-4kWh" and devs[1].driver == "jk"
    # Removing the main BMS promotes the next one.
    s.set_devices(devs[1:])
    assert s.address == "C8:47:80:7A:DC:B3" and s.extra_devices == []
    s.set_devices([])
    assert s.address is None and s.devices() == []
    s.set_devices([Device("AA:01", "A"), Device("AA:02", "B")])
    assert [d.name for d in s.devices()] == ["A", "B"]
