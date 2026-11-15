import pytest

from jkbms_widget.model import CellInfo
from jkbms_widget.state import (
    CHARGING,
    DISCHARGING,
    IDLE,
    History,
    StateTracker,
    time_left,
)


def feed(tracker, currents, start=0.0, step=0.55):
    states = []
    for k, i in enumerate(currents):
        states.append(tracker.update(i, start + k * step))
    return states


def test_inverter_standby_stays_idle():
    # Real pattern from the capture: 0 / -0.41 / -0.62 / -0.83 A.
    t = StateTracker(idle_threshold=1.0)
    states = feed(t, [0, -0.413, -0.827, -0.620, -0.413, 0, -0.827, -0.620] * 5)
    assert set(states) == {IDLE}


def test_real_discharge_is_detected_after_averaging():
    t = StateTracker(idle_threshold=1.0)
    assert feed(t, [-25.0] * 10)[-1] == DISCHARGING


def test_hysteresis_prevents_flicker_near_threshold():
    t = StateTracker(idle_threshold=1.0, hysteresis=0.3, state_window_s=0.1)
    assert t.update(-1.2, 0) == DISCHARGING
    assert t.update(-0.9, 1) == DISCHARGING  # between 0.7 and 1.0: stays
    assert t.update(-0.6, 2) == IDLE  # below 0.7: back to idle
    assert t.update(-0.9, 3) == IDLE  # needs 1.0 to leave idle again


def test_direct_switch_charging_to_discharging():
    t = StateTracker(idle_threshold=1.0, state_window_s=0.1)
    assert t.update(5.0, 0) == CHARGING
    assert t.update(-5.0, 1) == DISCHARGING


def cell(remaining=297.25, nominal=297.44):
    return CellInfo(
        cell_voltages=(3.39,) * 4, pack_voltage=13.56, current=0.0, soc=100,
        remaining_capacity=remaining, nominal_capacity=nominal, cycle_count=75,
        soh=98, temperatures=(12.0, 12.0), mosfet_temperature=15.0,
        charging_enabled=True, discharging_enabled=True,
        balancing=False, balance_current=0.0,
    )


def test_time_left():
    assert time_left(cell(), -0.6) == (pytest.approx(297.25 / 0.6), "empty")
    assert time_left(cell(remaining=100), 10.0) == (pytest.approx(19.744), "full")
    assert time_left(cell(), 0.05) == (None, None)
    # A BMS that does not report capacity: no estimate instead of a crash.
    assert time_left(cell(remaining=None, nominal=None), -5.0) == (None, None)


def test_minimal_reading_from_a_simple_bms():
    from jkbms_widget.state import Snapshot

    c = CellInfo(cell_voltages=(3.3, 3.31), pack_voltage=6.61, current=-2.0, soc=50,
                 alarms=("fully_charged", "cell_undervoltage"))
    assert c.max_temperature is None and c.power == pytest.approx(-13.22)
    assert Snapshot(cell=c).fault_alarms == ("cell_undervoltage",)  # info is not a fault


def test_history_buckets_and_span():
    h = History(bucket_s=10)
    for k in range(60):  # 60 s of data, 1 sample/s, current = k
        h.add(1000.0 + k, soc=50, current=float(k))
    pts = h.series(span_s=3600, now=1059.0)
    assert [p.time for p in pts] == [1000, 1010, 1020, 1030, 1040, 1050]
    assert pts[0].current == pytest.approx(4.5)  # mean of 0..9
    # span 20 s at t=1059: closed bucket 1040 (19 s old) + open bucket 1050
    assert [p.time for p in h.series(span_s=20, now=1059.0)] == [1040, 1050]


def test_energy_counters_integrate_buckets():
    from jkbms_widget.state import HistoryPoint, energy_kwh

    pts = [HistoryPoint(t, 50, 36.0, 13.0) for t in range(0, 3600, 10)]  # 1 h, +36 A
    pts += [HistoryPoint(3600 + t, 50, -10.0, None) for t in range(0, 1800, 10)]  # old: no V
    charged, discharged = energy_kwh(pts, since=0)
    assert charged == pytest.approx(13.0 * 36 / 1000)  # 0.468 kWh
    assert discharged == pytest.approx(13.0 * 10 * 0.5 / 1000)  # nearest voltage used
    assert energy_kwh(pts, since=3600)[0] == 0.0  # only the discharge half
    assert energy_kwh([], since=0) == (0.0, 0.0)


def test_local_midnight():
    from datetime import datetime

    from jkbms_widget.state import local_midnight

    t = datetime(2026, 11, 15, 13, 45, 10).timestamp()
    assert local_midnight(t) == datetime(2026, 11, 15).timestamp()


def test_formatters():
    from jkbms_widget.strings import alarm_text, fmt_current, fmt_hours, fmt_power

    assert fmt_power(-5.6028) == ("-5.6", "W")
    assert fmt_power(-1570.0) == ("-1.57", "kW")
    assert fmt_current(-0.413) == "-0.41" and fmt_current(-24.53) == "-24.5"
    assert fmt_hours(None) == "—"
    assert fmt_hours(0.5) == "≈ 30 хв"
    assert fmt_hours(3.8) == "≈ 3.8 год"
    assert fmt_hours(495) == "≈ 21 дн"
    assert alarm_text("cell_undervoltage") == "Низька напруга комірки"
    assert alarm_text("jk_bit_31") == "Невідома аварія (jk_bit_31)"


def test_time_left_texts():
    from jkbms_widget.strings import fmt_time_left_long, fmt_time_left_short

    assert fmt_time_left_short(3.8, "empty") == "≈ 3.8 год"  # no arrow: colour shows it
    assert fmt_time_left_short(0.5, "full") == "≈ 30 хв"
    assert fmt_time_left_short(None, None) == ""
    assert fmt_time_left_long(3.8, "empty") == "≈ 3.8 год до розряду"
    assert fmt_time_left_long(2.0, "full") == "≈ 2.0 год до повного заряду"


def test_history_drops_old_points():
    h = History(bucket_s=10, max_age_s=100)
    h.add(0.0, 50, 1.0)
    h.add(10.0, 50, 1.0)
    h.add(500.0, 50, 1.0)
    assert [p.time for p in h.series(10_000, 500.0)] == [500.0]


def test_history_csv_rows():
    from jkbms_widget.state import CSV_HEADER, HistoryPoint, history_csv

    text = history_csv([HistoryPoint(1_763_200_000.0, 76.0, -4.25, 13.21),
                        HistoryPoint(1_763_200_010.0, 76.0, 1.5, None)])
    lines = text.strip().split("\n")
    assert lines[0] == CSV_HEADER
    assert lines[1].endswith(",1763200000,76,-4.250,13.210,-56.1")
    assert lines[2].endswith(",1763200010,76,1.500,,")  # old point: no voltage


def test_cell_bars_stay_steady_on_millivolt_noise():
    from jkbms_widget.ui.cells import MAX_BAR, MIN_BAR, bar_shares

    assert bar_shares(()) == []
    assert bar_shares((3.3, 3.3)) == pytest.approx([0.55, 0.55])  # equal cells: mid height
    a = bar_shares((3.301, 3.302, 3.302, 3.303))
    b = bar_shares((3.302, 3.302, 3.301, 3.303))  # noise swaps which cell is lowest
    assert max(abs(x - y) for x, y in zip(a, b)) < 0.02  # bars barely move
    big = bar_shares((3.20, 3.30, 3.40))  # real 200 mV imbalance still spans the scale
    assert big[0] < MIN_BAR + 0.1 and big[2] > MAX_BAR - 0.1


def test_energy_between_counts_partial_buckets():
    from jkbms_widget.state import HistoryPoint, energy_between

    pts = [HistoryPoint(t, 50, 36.0, 10.0) for t in range(0, 3600, 10)]  # 360 W, 1 h
    assert energy_between(pts, 0, 3600) == pytest.approx((0.36, 0.0))
    # Half an hour, starting and ending mid-bucket: still exactly half.
    assert energy_between(pts, 905, 2705)[0] == pytest.approx(0.18)
    assert energy_between(pts, 2705, 905)[0] == pytest.approx(0.18)  # either drag direction
    assert energy_between(pts, 3600, 7200) == (0.0, 0.0)  # after the data
    mixed = pts[:180] + [HistoryPoint(1800 + t, 50, -18.0, 10.0) for t in range(0, 1800, 10)]
    charged, discharged = energy_between(mixed, 0, 3600)
    assert charged == pytest.approx(0.18) and discharged == pytest.approx(0.09)
