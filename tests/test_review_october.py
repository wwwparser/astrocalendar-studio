"""Замечания к октябрьскому выпуску: каждое закрыто проверкой.

Разбор прислал Станислав Короткий. Тесты здесь названы по замечаниям, чтобы
при следующей правке текста было видно, что именно нельзя сломать обратно.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg                                # noqa: E402


# ---------------------------------------------------- названия потоков


def test_taurids_are_not_called_tablids():
    """«Таблиды» — опечатка, разошедшаяся по русским календарям."""
    from astrocal.events.meteors import SHOWERS

    names = [name for _, name, *_ in SHOWERS]
    assert "Южные Тауриды" in names
    assert "Северные Тауриды" in names
    assert not any("Таблиды" in name for name in names)


def test_every_shower_has_a_unique_name():
    from astrocal.events.meteors import SHOWERS

    names = [name for _, name, *_ in SHOWERS]
    assert len(names) == len(set(names))


# ---------------------------------------------------- ZHR и фаза Луны


def test_variable_shower_shows_a_range():
    from astrocal.events.meteors import zhr_text

    assert zhr_text("DRA", 10) == "5 - 300"


def test_stable_shower_shows_one_number():
    from astrocal.events.meteors import zhr_text

    assert zhr_text("GEM", 150) == "150"


def test_every_variable_shower_with_a_range_is_marked_variable():
    from astrocal.events.meteors import VARIABLE, ZHR_RANGE

    assert set(ZHR_RANGE) <= VARIABLE


def test_meteor_line_carries_zhr_and_moon_phase():
    from astrocal.events import meteors

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    events = meteors.all_events(start, end)
    assert events, "в октябре есть максимумы потоков"
    for event in events:
        assert "ZHR ≈" in event.text
        assert "фаза Луны Ф=" in event.text


# ---------------------------------------------------- покрытия астероидами


def test_occultation_says_duration_not_maximum():
    """«Максимум 1,2 с» читается как момент, а речь о длительности."""
    source = (Path(__file__).resolve().parents[1] / "src" / "astrocal" /
              "events" / "asteroid_occultations.py").read_text(encoding="utf-8")
    assert '", длительность до "' in source
    assert '", максимум "' not in source


# ---------------------------------------------------- Титан


def test_titan_line_puts_distance_before_direction():
    from astrocal.events import titan

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    events = titan.all_events(start, end)
    assert events
    for event in events:
        assert "расположен в " in event.text
        head = event.text.split("Сатурна")[0]
        assert "″ севернее" in head or "″ южнее" in head


# ---------------------------------------------------- Ио с тенью


def test_combined_transit_reports_its_start_and_interval():
    """Середина, округлённая до часа, указывала на конец явления."""
    from astrocal.events import jupiter_phenomena

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    events = [e for e in jupiter_phenomena.all_events(start, end)
              if e.meta.get("phenomenon") == "combination"]
    assert events, "в октябре есть совпадения прохождения и тени"
    for event in events:
        assert event.precision == "minute"
        assert f", с {event.when:%H:%M} до " in event.text


def test_io_shadow_pair_matches_stellarium():
    """11 октября: тень с 01:52, спутник с 03:00, совпадение до 04:08."""
    from astrocal.events import jupiter_phenomena

    start = dt.datetime(2026, 10, 11, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 10, 12, tzinfo=cfg.MSK)
    events = [e for e in jupiter_phenomena.all_events(start, end)
              if e.meta.get("phenomenon") == "combination"]
    assert len(events) == 1
    event = events[0]
    assert event.when.hour == 3 and event.when.minute == 0
    assert "до 04:08" in event.text


# ---------------------------------------------------- либрация


def test_libration_stays_within_physical_limits():
    """359,9° в календаре означало несвёрнутый угол, а не рекордную либрацию."""
    from skyfield.api import load

    from astrocal.core import timescale
    from astrocal.events.lunar_features import libration

    ts = timescale()
    for day in range(0, 365, 7):
        t = ts.utc(2026, 1, 1 + day)
        longitude, latitude = libration(t)
        assert -10.0 < longitude < 10.0
        assert -10.0 < latitude < 10.0


# ---------------------------------------------------- взаимные явления


def test_mutual_eclipse_carries_light_time_correction():
    """Затмение происходит у Юпитера, а видим мы его почти на час позже."""
    from astrocal.events import jupiter_mutual

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    found = jupiter_mutual.find(start, end)
    eclipses = [item for item in found if item.kind == "eclipse"]
    assert eclipses, "в сезоне взаимных явлений затмения есть"
    for item in eclipses:
        assert 30.0 < item.light_minutes < 60.0
    for item in found:
        if item.kind == "occultation":
            assert item.light_minutes == 0.0
