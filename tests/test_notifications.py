from jkbms_widget.model import CellInfo
from jkbms_widget.notifications import ALARM, FULL, LOST, LOW_SOC, Notifier
from jkbms_widget.state import CHARGING, DISCHARGING, IDLE, Snapshot


def snap(soc=50, state=IDLE, alarms=(), stale=False, status="connected"):
    cell = CellInfo(cell_voltages=(3.3,) * 4, pack_voltage=13.2, current=0.0, soc=soc,
                    alarms=alarms)
    return Snapshot(cell=cell, state=state, stale=stale, status=status)


def kinds(events):
    return [e.kind for e in events]


def test_low_soc_fires_once_and_rearms_after_recharge():
    n = Notifier(low_soc=20)
    assert kinds(n.update(snap(21, DISCHARGING), 0)) == []
    assert kinds(n.update(snap(20, DISCHARGING), 1)) == [LOW_SOC]
    assert kinds(n.update(snap(19, DISCHARGING), 2)) == []  # no spam
    assert kinds(n.update(snap(24, CHARGING), 3)) == []  # not re-armed yet (< 25)
    assert kinds(n.update(snap(20, DISCHARGING), 4)) == []
    n.update(snap(25, CHARGING), 5)  # re-armed
    assert kinds(n.update(snap(18, DISCHARGING), 6)) == [LOW_SOC]


def test_new_faults_only_and_info_alarms_ignored():
    n = Notifier()
    assert kinds(n.update(snap(alarms=("fully_charged",)), 0)) == []
    ev = n.update(snap(alarms=("cell_undervoltage",)), 1)
    assert kinds(ev) == [ALARM] and ev[0].alarms == ("cell_undervoltage",)
    assert n.update(snap(alarms=("cell_undervoltage",)), 2) == []  # still the same
    ev = n.update(snap(alarms=("cell_undervoltage", "charge_overtemperature")), 3)
    assert ev[0].alarms == ("charge_overtemperature",)
    n.update(snap(), 4)  # cleared
    assert kinds(n.update(snap(alarms=("cell_undervoltage",)), 5)) == [ALARM]


def test_lost_after_a_minute_of_reconnecting_but_not_after_manual_disconnect():
    n = Notifier()
    n.update(snap(), 0)
    assert n.update(snap(stale=True, status="lost"), 30) == []
    assert kinds(n.update(snap(stale=True, status="connecting"), 61)) == [LOST]
    assert n.update(snap(stale=True, status="lost"), 120) == []  # once
    n.update(snap(), 130)  # back
    assert n.update(snap(stale=True, status="stopped"), 300) == []  # user disconnected


def test_no_lost_notification_before_the_first_data():
    n = Notifier()
    assert n.update(Snapshot(cell=None, status="connecting"), 500) == []


def test_full_charge_only_when_reached_while_charging():
    n = Notifier()
    assert n.update(snap(100, IDLE), 0) == []  # app started with a full battery
    n.update(snap(96, DISCHARGING), 1)  # re-armed
    assert n.update(snap(99, CHARGING), 2) == []
    assert kinds(n.update(snap(100, CHARGING), 3)) == [FULL]
    assert n.update(snap(100, CHARGING), 4) == []
