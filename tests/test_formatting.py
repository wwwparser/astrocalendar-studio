"""Формат строк календаря — то, что читает человек, ломаться не должно."""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal.core import Event                                    # noqa: E402
from astrocal.fmt import (angle_deg, date_time_msk, distance_km,   # noqa: E402
                          magnitude, phase_fraction, ru_constellation)

LINE = re.compile(r"^▪️\d{2} [а-яё]+, \d{2}:\d{2} — .+$")


def test_magnitude_always_signed_with_comma():
    assert magnitude(-4.7) == "V=-4,7m"
    assert magnitude(0.6) == "V=+0,6m"
    assert magnitude(10.55) == "V=+10,6m"


def test_phase_sign_encodes_waxing():
    assert phase_fraction(0.21, waxing=False) == "Ф=-0,21"
    assert phase_fraction(0.12, waxing=True) == "Ф=+0,12"


def test_phase_never_prints_full_unity():
    # 1,00 в календарях не пишут — полная фаза обозначается как 0,99
    assert phase_fraction(1.0, waxing=True) == "Ф=+0,99"


@pytest.mark.parametrize("deg, expected", [
    (2.34, "2.3°"),
    (0.41, "0°25′"),
    (0.135, "0°8′"),
    (0.996, "1.0°"),      # 60′ округляются в градусы, а не в «0°60′»
    (0.005, "18″"),       # меньше минуты — в секундах, а не «0°0′»
])
def test_angle_formatting(deg, expected):
    assert angle_deg(deg) == expected


def test_date_uses_russian_genitive_month():
    assert date_time_msk(dt.datetime(2026, 9, 7, 0, 30)) == "07 сентября, 00:30"


def test_distance_has_no_thousands_separator():
    assert distance_km(368228.4) == "368228"


def test_constellation_translated():
    assert ru_constellation("Tau") == "Телец"
    assert ru_constellation("Cet") == "Кит"
    # неизвестное сокращение возвращается как есть, а не падает
    assert ru_constellation("Xyz") == "Xyz"


def test_event_line_matches_calendar_format():
    event = Event(when=dt.datetime(2026, 9, 7, 0, 30, 12),
                  text="Проверочное событие", category="test")
    assert LINE.match(event.line()), event.line()


def test_hour_precision_rounds_to_nearest_hour():
    event = Event(when=dt.datetime(2026, 9, 7, 10, 44),
                  text="x", category="test", precision="hour")
    assert event.display_time.hour == 11
    assert event.display_time.minute == 0

# ------------------------------------------------------------------ числа


def test_number_uses_a_comma():
    from astrocal.fmt import number
    assert number(12.8) == "12,8"
    assert number(1.234, 2) == "1,23"
    assert number(3.9, 1, sign=True) == "+3,9"


def test_number_does_not_touch_the_rest_of_the_sentence():
    """Замена точки на запятую во всей строке ломает «а.е.» и «Макс.»."""
    from astrocal.fmt import number
    assert f"Макс. длительность: {number(0.6)} с" == "Макс. длительность: 0,6 с"
    assert f"{number(1.1, 2)} а.е." == "1,10 а.е."
