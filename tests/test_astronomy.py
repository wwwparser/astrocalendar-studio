"""Астрономия сверяется с независимо известными значениями.

Числа в этом файле взяты не из нашего же кода, а из опубликованных источников
(астрономические ежегодники, NASA eclipse catalogue) — иначе тест проверял бы
сам себя. Допуски выбраны так, чтобы ловить реальные ошибки (перепутанный
часовой пояс, геоцентрика вместо топоцентрики, сдвиг на сутки), а не шум
последней цифры.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal.config import MSK                                # noqa: E402
from astrocal.events import eclipses, meteors, moon, planets, seasons   # noqa: E402


def month(year: int, m: int):
    start = dt.datetime(year, m, 1, tzinfo=MSK)
    end = dt.datetime(year + (m == 12), m % 12 + 1, 1, tzinfo=MSK)
    return start, end


def find(events, needle: str):
    hits = [e for e in events if needle.lower() in e.text.lower()]
    assert hits, f"не найдено событие со словами «{needle}»"
    return hits


def test_autumn_equinox_2026():
    # Осеннее равноденствие 2026: 23 сентября 00:05 UTC = 03:05 МСК
    events = seasons.all_events(*month(2026, 9))
    equinox = find(events, "равноденствие")[0]
    assert equinox.when.day == 23
    assert abs(equinox.when.hour * 60 + equinox.when.minute - (3 * 60 + 5)) <= 5


def test_moon_phases_september_2026():
    # Новолуние 11 сентября, полнолуние 26 сентября 2026 (МСК)
    events = moon.phases(*month(2026, 9))
    assert find(events, "новолуние")[0].when.day == 11
    assert find(events, "полнолуние")[0].when.day == 26


def test_perigee_distance_matches_jpl():
    # Перигей 10 августа 2026: 363265 км (сверено с JPL Horizons)
    events = moon.apsides(*month(2026, 8))
    perigee = find(events, "перигее")[0]
    assert perigee.when.day == 10
    assert "36326" in perigee.text or "36327" in perigee.text


def test_total_solar_eclipse_12_august_2026():
    # Полное солнечное затмение 12 августа 2026, наибольшая фаза 17:46 UTC
    events, _report = eclipses.all_events(*month(2026, 8))
    eclipse = find(events, "полное солнечное затмение")[0]
    assert eclipse.when.day == 12
    assert abs(eclipse.when.hour - 20) <= 1


def test_partial_lunar_eclipse_28_august_2026():
    events, _report = eclipses.all_events(*month(2026, 8))
    eclipse = find(events, "лунное затмение")[0]
    assert eclipse.when.day == 28


def test_neptune_opposition_september_2026():
    events = planets.solar_configurations(*month(2026, 9))
    opposition = find(events, "нептун")[0]
    assert opposition.when.day == 26
    assert "противостоянии" in opposition.text


def test_uranus_station_is_10_september_not_8():
    # Проверено дважды: Skyfield/DE440s и выборка JPL Horizons с шагом 2 часа
    events = planets.stations(*month(2026, 9))
    station = find(events, "уран")[0]
    assert station.when.day == 10


def test_mercury_greatest_western_elongation_august_2026():
    events = planets.solar_configurations(*month(2026, 8))
    elongation = find(events, "элонгации")[0]
    assert elongation.when.day == 2
    assert "западной" in elongation.text


def test_perseids_peak_falls_on_12_13_august():
    events = meteors.all_events(*month(2026, 8))
    perseids = find(events, "персеиды")[0]
    assert perseids.when.day in (12, 13)


@pytest.mark.parametrize("m, expected", [(8, 1), (9, 1)])
def test_one_lunar_apsis_pair_per_month(m, expected):
    events = moon.apsides(*month(2026, m))
    assert len([e for e in events if "перигее" in e.text]) == expected
    assert len([e for e in events if "апогее" in e.text]) == expected
