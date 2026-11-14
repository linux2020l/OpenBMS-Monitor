import pytest

from jkbms_widget.history_store import RETENTION_S, HistoryStore
from jkbms_widget.state import History, HistoryPoint
from jkbms_widget.ui.chart import _decimate

OURS, OTHER = "C8:47:80:1A:F9:9E", "C8:47:80:7A:DC:B3"


def test_store_keeps_series_per_bms_and_prunes_after_a_week():
    store = HistoryStore(":memory:")
    now = 1_000_000.0
    store.add(OURS, HistoryPoint(now - 10, 90, -5.0))
    store.add(OURS.lower(), HistoryPoint(now, 89, -5.5))  # MAC case does not matter
    store.add(OTHER, HistoryPoint(now, 50, 1.0))
    store.add(OURS, HistoryPoint(now - RETENTION_S - 60, 100, 0.0))  # too old

    assert [p.soc for p in store.load(OURS, 0)] == [100, 90, 89]
    assert store.prune(now) == 1
    assert [p.soc for p in store.load(OURS, 0)] == [90, 89]
    assert [p.soc for p in store.load(OTHER, 0)] == [50]


def test_history_reports_closed_buckets_for_persistence():
    closed = []
    h = History(bucket_s=10, on_bucket_closed=closed.append)
    for k in range(25):
        h.add(1000.0 + k, soc=80, current=-2.0)
    assert [p.time for p in closed] == [1000, 1010]  # bucket 1020 still open
    assert h.open_bucket().time == 1020


def test_week_of_history_survives_restart(tmp_path):
    db = tmp_path / "history.sqlite"
    store = HistoryStore(db)
    h = History(bucket_s=10, on_bucket_closed=lambda p: store.add(OURS, p))
    start = 2_000_000.0
    for k in range(0, 3600, 2):  # one hour, a sample every 2 s
        h.add(start + k, soc=100 - k / 360, current=-3.0)
    store.add(OURS, h.open_bucket())
    store.close()

    reopened = HistoryStore(db)
    h2 = History(bucket_s=10)
    h2.extend(reopened.load(OURS, 0), now=start + 3600)
    pts = h2.series(7 * 24 * 3600, start + 3600)
    assert len(pts) == 360 and pts[0].time == start


def test_voltage_is_stored_and_old_databases_are_upgraded(tmp_path):
    import sqlite3

    db = tmp_path / "old.sqlite"
    old = sqlite3.connect(db)  # first-version schema, no voltage column
    old.execute("CREATE TABLE samples (bms TEXT NOT NULL, t REAL NOT NULL, soc REAL NOT NULL,"
                " current REAL NOT NULL, PRIMARY KEY (bms, t)) WITHOUT ROWID")
    old.execute("INSERT INTO samples VALUES (?, 1.0, 90, -5)", (OURS,))
    old.commit()
    old.close()

    store = HistoryStore(db)
    store.add(OURS, HistoryPoint(11.0, 89, -5.0, 13.2))
    pts = store.load(OURS, 0)
    assert pts[0].voltage is None and pts[0].power is None  # old point
    assert pts[1].voltage == 13.2 and pts[1].power == pytest.approx(-66.0)


def test_history_averages_voltage_per_bucket():
    h = History(bucket_s=10)
    h.add(0.0, 90, -5.0, 13.0)
    h.add(5.0, 90, -5.0, 13.2)
    assert h.open_bucket().voltage == pytest.approx(13.1)


def test_decimate_limits_points_per_pixel():
    pts = [HistoryPoint(float(t), 50.0, float(t % 7)) for t in range(60_480)]  # 7 days
    out = _decimate(pts, 800)
    assert len(out) <= 1600
    assert out[0].time == 0.0
    assert _decimate(pts[:100], 800) == pts[:100]  # small series untouched
