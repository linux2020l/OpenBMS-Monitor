from jkbms_widget.bank import SERIES, combine_cells, free_letter
from jkbms_widget.model import CellInfo
from jkbms_widget.settings import BankConfig, Settings, clean_banks


def pack(v=13.4, i=0.0, soc=50, rem=150.0, nom=300.0, **kw):
    return CellInfo(cell_voltages=(3.35,) * 4, pack_voltage=v, current=i, soc=soc,
                    remaining_capacity=rem, nominal_capacity=nom, **kw)


def test_labels_are_letters():
    assert free_letter([]) == "A" and free_letter(["A", "C"]) == "B"


def test_parallel_packs_add_currents_and_weight_soc_by_capacity():
    big = pack(v=13.40, i=-20.0, soc=90, rem=270.0, nom=300.0)
    small = pack(v=13.30, i=-5.0, soc=10, rem=10.0, nom=100.0)
    bank = combine_cells([big, small])
    assert bank.current == -25.0
    assert abs(bank.pack_voltage - 13.35) < 1e-9
    assert bank.remaining_capacity == 280.0 and bank.nominal_capacity == 400.0
    assert bank.soc == 70  # 280 / 400, not the plain average 50
    assert len(bank.cell_voltages) == 8


def test_soc_falls_back_to_average_without_capacity():
    bank = combine_cells([pack(soc=80, rem=None), pack(soc=40)])
    assert bank.soc == 60 and bank.remaining_capacity is None


def test_flags_and_alarms_of_a_bank():
    a = pack(charging_enabled=True, discharging_enabled=True, balancing=False,
             alarms=("cell_undervoltage",), temperatures=(20.0, 21.0), mosfet_temperature=30.0)
    b = pack(charging_enabled=False, discharging_enabled=True, balancing=True,
             alarms=("cell_undervoltage", "fully_charged"), temperatures=(25.0,))
    bank = combine_cells([a, b])
    assert bank.charging_enabled is False  # off in one pack = off for the bank
    assert bank.discharging_enabled is True
    assert bank.balancing is True
    assert bank.alarms == ("cell_undervoltage", "fully_charged")
    assert bank.max_temperature == 25.0 and bank.mosfet_temperature == 30.0
    assert combine_cells([]) is None


def test_clean_banks_keeps_only_valid_groups():
    banks = clean_banks([
        {"id": "a", "name": "Home", "members": ["aa:01", "AA:02", "aa:01"]},
        {"id": "b", "members": ["AA:02", "AA:03"]},  # AA:02 is already in bank a
        {"id": "a", "members": ["AA:04", "AA:05"]},  # duplicate id
        {"members": ["AA:06", "AA:07"]},  # no id
        "junk",
    ])
    assert banks == [{"id": "a", "name": "Home", "members": ["AA:01", "AA:02"],
                      "visible": True, "compact_pos": None, "kind": "parallel", "letter": "A"}]


def test_banks_round_trip_through_the_settings_file(tmp_path):
    s = Settings(address="AA:01", extra_devices=[{"address": "AA:02"}])
    s.set_banks([BankConfig("x1", "Home", ["AA:01", "AA:02"], visible=False)])
    path = tmp_path / "settings.json"
    s.save(path)
    loaded = Settings.load(path).bank_configs()
    assert loaded == [BankConfig("x1", "Home", ["AA:01", "AA:02"], False, None, "A")]


def test_exchange_between_packs_does_not_cancel():
    from jkbms_widget.bank import exchange_current

    assert exchange_current([5.0, -5.0]) == 5.0  # one pack charges the other, sum 0
    assert exchange_current([8.0, -3.0]) == 3.0  # 5 A from the charger, 3 A circulating
    assert exchange_current([-4.0, -6.0]) == 0.0  # both discharge: nothing circulates
    assert exchange_current([]) == 0.0


def test_series_packs_add_voltages_and_follow_the_weakest():
    a = pack(v=13.4, i=-10.2, soc=80, rem=240.0, nom=300.0)
    b = pack(v=13.2, i=-9.8, soc=35, rem=105.0, nom=300.0)
    bank = combine_cells([a, b], SERIES)
    assert abs(bank.pack_voltage - 26.6) < 1e-9
    assert abs(bank.current + 10.0) < 1e-9  # one string: the common current
    assert bank.soc == 35 and bank.remaining_capacity == 105.0
    assert bank.nominal_capacity == 300.0
