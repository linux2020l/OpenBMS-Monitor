from datetime import datetime

import pytest

from PySide6.QtGui import QColor

from jkbms_widget.ui import chart
from jkbms_widget.ui.chart import _nice_ceiling, current_tick_step, time_step, time_ticks


@pytest.mark.parametrize(
    "current, soc_color, line_color",
    [(5.0, chart.SOC_CHARGE_COLOR, chart.CHARGE_COLOR),
     (-5.0, chart.SOC_DISCHARGE_COLOR, chart.DISCHARGE_COLOR),
     (0.0, chart.SOC_IDLE_COLOR, chart.ZERO_COLOR)],
)
def test_soc_line_uses_lighter_pastel_of_the_current_colour(current, soc_color, line_color):
    assert chart._soc_color(current) == soc_color
    assert chart._direction_color(current) == line_color
    soc, line = QColor(soc_color), QColor(line_color)
    assert soc.lightness() > line.lightness()
    assert soc.hsvSaturation() < line.hsvSaturation() or current == 0.0


def test_chart_idle_follows_the_threshold():
    # A bank's summed current is rarely exactly 0: +0.4 A is still idle at 1 A.
    assert chart._direction_color(0.4, 1.0) == chart.ZERO_COLOR
    assert chart._soc_color(-0.9, 1.0) == chart.SOC_IDLE_COLOR
    assert chart._direction_color(1.0, 1.0) == chart.CHARGE_COLOR
    assert chart._soc_color(-1.2, 1.0) == chart.SOC_DISCHARGE_COLOR


@pytest.mark.parametrize(
    "max_abs_current, limit",
    [(0.0, 10), (0.6, 10), (10.0, 10), (10.1, 20), (57.1, 60), (99.9, 100), (123.0, 130), (250.0, 250)],
)
def test_current_axis_scales_in_10_amp_steps(max_abs_current, limit):
    assert _nice_ceiling(max_abs_current) == limit


@pytest.mark.parametrize("limit, step", [(10, 10), (40, 10), (60, 20), (130, 50), (250, 100)])
def test_current_grid_has_at_most_four_intervals(limit, step):
    assert current_tick_step(limit) == step
    assert limit / step <= 4


@pytest.mark.parametrize(
    "span_s, step",
    [(3600, 600), (6 * 3600, 3600), (24 * 3600, 10800), (7 * 24 * 3600, 86400)],
)
def test_time_step_for_ranges_on_a_900px_chart(span_s, step):
    assert time_step(span_s, 900) == step


def test_time_ticks_fall_on_round_local_times():
    t0 = datetime(2026, 11, 14, 21, 23, 17).timestamp()
    ticks = time_ticks(t0, t0 + 3600, 600)
    labels = [datetime.fromtimestamp(t).strftime("%H:%M") for t in ticks]
    assert labels == ["21:30", "21:40", "21:50", "22:00", "22:10", "22:20"]
    days = time_ticks(t0, t0 + 3 * 86400, 86400)
    assert all(datetime.fromtimestamp(t).strftime("%H:%M") == "00:00" for t in days)


def test_range_summary_gives_energy_net_and_soc_change():
    from jkbms_widget.state import HistoryPoint

    pts = [HistoryPoint(t, 50 + t / 360, 20.0, 13.0) for t in range(0, 3600, 10)]
    info = chart.range_summary(pts, 1800, 0)
    assert info["t0"] == 0 and info["t1"] == 1800
    assert info["charged"] == pytest.approx(13.0 * 20 * 0.5 / 1000)
    assert info["discharged"] == 0.0 and info["net"] == pytest.approx(info["charged"])
    assert info["soc0"] == 50 and info["soc1"] == pytest.approx(50 + 1790 / 360)
    assert chart.range_summary(pts, 5000, 6000) is None
    assert chart.range_summary([], 0, 10) is None


def test_fill_runs_merge_flicker_and_stop_at_gaps():
    G, A, I = "green", "amber", "grey"
    xs = [float(10 * k) for k in range(8)]  # 10 px apart
    # Long runs stay separate; a gap (None) is never filled across.
    assert chart.fill_runs([G, G, A, A, None, I, I], xs) == [(G, 0, 2), (A, 2, 4), (I, 5, 7)]
    # Runs narrower than min_px take the previous colour, then merge.
    xs = [float(k) for k in range(8)]  # 1 px apart
    assert chart.fill_runs([G, G, G, A, G, G, G], xs, min_px=3) == [(G, 0, 7)]
    assert chart.fill_runs([G, G, G, A, A, A, A], xs, min_px=3) == [(G, 0, 3), (A, 3, 7)]
    assert chart.fill_runs([], []) == []


def test_smooth_averages_neighbours_within_the_window():
    xs = [0.0, 1.0, 2.0, 3.0, 10.0]
    assert chart.smooth(xs, [1, -1, 1, -1, 5], 2.0) == [0.0, 1 / 3, -1 / 3, 0.0, 5.0]
    assert chart.smooth([], [], 12) == []

