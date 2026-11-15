import re

import pytest

from jkbms_widget import strings, strings_en

# Same in every language, so strings_en.py does not repeat them.
NEUTRAL = {"TIME_KINDS", "NO_VALUE"}


@pytest.fixture(autouse=True)
def back_to_ukrainian():
    yield
    strings.set_language("uk")  # other tests expect the Ukrainian texts


def _placeholders(value) -> list:
    if isinstance(value, str):
        return sorted(re.findall(r"\{(\w+)", value))
    if isinstance(value, dict):
        return [(k, _placeholders(v)) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))]
    if isinstance(value, (list, tuple)):
        return [_placeholders(v) for v in value]
    return []


def test_every_text_has_an_english_version_of_the_same_shape():
    uk_names = set(strings._UK) - NEUTRAL
    en_names = {n for n in vars(strings_en) if n.isupper()}
    assert uk_names - en_names == set(), "missing in strings_en.py"
    assert en_names - uk_names == set(), "unknown names in strings_en.py"
    for name in uk_names:
        uk, en = strings._UK[name], getattr(strings_en, name)
        assert type(uk) is type(en), name
        if isinstance(uk, dict):
            assert uk.keys() == en.keys(), name
        if isinstance(uk, list):  # (key, label) options or (label, seconds) ranges
            def keys(items):
                return [a if isinstance(b, str) else b for a, b in items]

            assert keys(uk) == keys(en), name
        assert _placeholders(uk) == _placeholders(en), name


def test_set_language_switches_texts_and_formatters():
    strings.set_language("en")
    assert strings.language == "en"
    assert strings.STATE_NAMES["Discharging"] == "Discharging"
    assert strings.alarm_text("cell_undervoltage") == "Cell undervoltage"
    assert strings.alarm_text("jk_bit_31") == "Unknown alarm (jk_bit_31)"
    assert strings.fmt_time_left_long(3.8, "empty") == "≈ 3.8 h to empty"
    assert strings.fmt_hours(0.5) == "≈ 30 min"
    strings.set_language("uk")
    assert strings.fmt_time_left_long(3.8, "empty") == "≈ 3.8 год до розряду"
    assert strings.alarm_text("cell_undervoltage") == "Низька напруга комірки"


def test_every_alarm_code_has_a_text_in_every_language():
    from jkbms_widget.model import ALARM_CODES

    for lang in strings.LANGUAGES:
        strings.set_language(lang)
        missing = [c for c in ALARM_CODES if c not in strings.ALARM_TEXT]
        assert missing == [], lang


@pytest.mark.parametrize(
    "setting, system, expected",
    [("auto", "uk", "uk"), ("auto", "en", "en"), ("auto", "de", "en"), ("auto", None, "en"),
     ("uk", "en", "uk"), ("en", "uk", "en")],
)
def test_auto_language_follows_windows(setting, system, expected):
    assert strings.resolve_language(setting, system) == expected


def test_energy_and_duration_formatters():
    assert strings.fmt_energy(0.35) == "350 Wh"
    assert strings.fmt_energy(-0.0424) == "-42 Wh"
    assert strings.fmt_energy(1.254) == "1.25 kWh"
    assert strings.fmt_duration(45 * 60) == "45 хв"
    assert strings.fmt_duration(2 * 3600 + 5 * 60) == "2 год 05 хв"
    assert strings.fmt_duration(3 * 86400 + 4 * 3600) == "3 дн 4 год"
    strings.set_language("en")
    try:
        assert strings.fmt_duration(2 * 3600 + 5 * 60) == "2 h 05 min"
    finally:
        strings.set_language("uk")
