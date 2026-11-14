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
    assert strings.alarm_text(11) == "Cell undervoltage"
    assert strings.alarm_text(31) == "Unknown alarm (bit 31)"
    assert strings.fmt_time_left_long(3.8, "empty") == "≈ 3.8 h to empty"
    assert strings.fmt_hours(0.5) == "≈ 30 min"
    strings.set_language("uk")
    assert strings.fmt_time_left_long(3.8, "empty") == "≈ 3.8 год до розряду"
    assert strings.alarm_text(11) == "Низька напруга комірки"


@pytest.mark.parametrize(
    "setting, system, expected",
    [("auto", "uk", "uk"), ("auto", "en", "en"), ("auto", "de", "en"), ("auto", None, "en"),
     ("uk", "en", "uk"), ("en", "uk", "en")],
)
def test_auto_language_follows_windows(setting, system, expected):
    assert strings.resolve_language(setting, system) == expected
