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
        # время в тексте округляется так же, как в заголовке строки
        assert f", с {event.display_time:%H:%M} до " in event.text


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


def test_mutual_event_line_agrees_with_its_own_headline():
    """В строке стояло «04:21 … с 04:20»: заголовок округлял, текст обрезал."""
    from astrocal.events import jupiter_mutual

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    events, _items = jupiter_mutual.all_events(start, end)
    assert events
    for event in events:
        assert f"с {event.display_time:%H:%M} до " in event.text


def test_mutual_contacts_are_refined_below_the_grid_step():
    """5 октября по Stellarium: начало 04:20, максимум 04:22."""
    from astrocal.events import jupiter_mutual

    found = jupiter_mutual.find(dt.datetime(2026, 10, 5, tzinfo=cfg.MSK),
                                dt.datetime(2026, 10, 6, tzinfo=cfg.MSK))
    eclipse = [item for item in found if item.kind == "eclipse"]
    assert len(eclipse) == 1
    item = eclipse[0]
    assert item.start.strftime("%H:%M") == "04:19"
    assert item.middle.strftime("%H:%M") == "04:22"
    # контакты не лежат на узлах двухминутной сетки
    assert item.start.second not in (0,) or item.end.second not in (0,)


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


def test_mutual_titles_use_the_accusative():
    """«Ио затмевает Европа» не даёт понять, кто кого закрывает."""
    from astrocal.events.jupiter_mutual import MOON_RU_ACC, MutualEvent

    from astrocal.events.jupiter_moons import MOON_RU

    assert set(MOON_RU_ACC) == set(MOON_RU)
    moment = dt.datetime(2026, 10, 5, 4, 20, tzinfo=cfg.MSK)
    item = MutualEvent(kind="eclipse", front="io", back="europa",
                       start=moment, middle=moment, end=moment,
                       min_separation_arcsec=0.5, obscuration=0.8,
                       observable=True)
    assert item.title == "Ио затмевает Европу"


# ---------------------------------------------------- вторая порция замечаний


def test_jupiter_magnitude_stands_next_to_the_planet():
    """Блеск уезжал в конец фразы и выглядел как блеск тени."""
    from astrocal.events import jupiter_phenomena

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    events = jupiter_phenomena.all_events(start, end)
    assert events
    for event in events:
        assert "Юпитера (V=" in event.text
        assert "тенью (V=" not in event.text


def test_inferior_conjunction_states_the_gap_from_the_sun():
    """Долготы совпали, но просвет в шесть градусов остаётся."""
    from astrocal.events import planets

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    found = [e for e in planets.solar_configurations(start, end)
             if "нижнем соединении" in e.text]
    assert len(found) == 1
    text = found[0].text
    assert "Венера (V=" in text and "D=" in text and "Ф=" in text
    assert "южнее Солнца" in text or "севернее Солнца" in text


def test_venus_phase_keeps_three_digits_when_tiny():
    """Ф=0,01 и Ф=0,006 отличаются вдвое, а выглядели бы одинаково."""
    from astrocal.apparent import planet_label
    from astrocal.core import timescale

    t = timescale().utc(2026, 10, 24, 3, 44)
    assert "Ф=0,006" in planet_label("venus", t)


def test_planet_diameter_stays_in_arcseconds():
    """У планет диаметр в секундах даже за минутой: 61″, а не 1′1″."""
    from astrocal.apparent import format_diameter

    assert format_diameter(61.1, minutes_allowed=False) == "61,1″"
    assert format_diameter(1941.0) == "32′21″"


def test_station_says_what_the_planet_looks_like():
    from astrocal.events import planets

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    found = planets.stations(start, end)
    assert found
    for event in found:
        assert "V=" in event.text and "D=" in event.text
        assert "в созвездии" in event.text


def test_planet_pairs_are_looked_for_up_to_five_degrees():
    import inspect

    from astrocal.events import planets

    default = inspect.signature(planets.mutual_approaches) \
        .parameters["limit_deg"].default
    assert default == 5.0


def test_star_conjunction_thresholds_depend_on_the_star():
    """Три ступени: ярче +3,0ᵐ — 2°, до +5,0ᵐ — 1°, до +7,0ᵐ — полградуса."""
    from astrocal.events.planets import star_conjunction_limit

    assert star_conjunction_limit(2.0) == 2.0
    assert star_conjunction_limit(3.0) == 2.0
    assert star_conjunction_limit(3.5) == 1.0
    assert star_conjunction_limit(5.0) == 1.0
    assert star_conjunction_limit(5.5) == 0.5
    assert star_conjunction_limit(7.0) == 0.5
    assert star_conjunction_limit(7.5) == 0.0


def test_planet_star_conjunctions_are_found_and_capped():
    """Марс идёт через Рак и за месяц минует два десятка слабых звёзд."""
    from astrocal.events import planets

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    found = planets.star_approaches(start, end)
    assert found
    for event in found:
        assert event.meta["sep_deg"] <= \
            planets.star_conjunction_limit(event.meta["star_mag"])
    # одна пара планета–звезда за сутки, без дублей в соседние часы
    keys = [(e.meta["planet"], e.meta["hip"], e.when.date()) for e in found]
    assert len(keys) == len(set(keys))


# ---------------------------------------------------- покрытия Луной звёзд


def test_lunar_occultation_reports_first_contact():
    """В календаре нужен момент начала, а не середина явления."""
    from astrocal.events import occultations

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    events, _report = occultations.build_stars(start, end)
    assert events
    for event in events:
        assert "момент первого контакта над Россией" in event.computed


def test_pleiades_are_named_instead_of_alcyone():
    """Про Альциону знают немногие, про Плеяды — все."""
    from astrocal.events import occultations

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    events, _report = occultations.build_stars(start, end)
    pleiades = [e for e in events if "Плеяды" in e.text]
    assert len(pleiades) == 1
    text = pleiades[0].text
    assert "Альциона" not in text
    assert text.startswith("Тесное соединение и покрытие звёздного скопления")
    assert "видимое почти со всей территории России" in text


def test_cluster_band_is_wider_than_one_star():
    """Полоса по Альционе узкая, по всему скоплению — почти вся страна."""
    from astrocal.events import occultations

    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 11, 1, tzinfo=cfg.MSK)
    cand = [c for c in occultations.star_candidates(start, end)
            if c["hip"] == 17702]
    assert cand, "28 октября Луна закрывает Альциону"
    one = occultations.visibility_band(cand[0]["t"], star=cand[0]["star"])
    many = occultations.cluster_band("Плеяды", cand[0]["t"])
    assert many["mask"].sum() > one["mask"].sum()


def test_all_four_librations_are_published():
    """Максимум в каждую сторону раз в месяц: восток, запад, север, юг."""
    from astrocal import config as config_module
    from astrocal.events import lunar_features

    for year, month in ((2026, 10), (2026, 11), (2026, 12)):
        start, end = config_module.month_bounds(year, month)
        events = lunar_features.librations(start, end)
        edges = sorted(event.meta["edge"] for event in events)
        assert edges == ["восточный", "западный", "северный", "южный"], \
            f"{year}-{month}: {edges}"
        for event in events:
            assert event.rank == "interesting"


def test_libration_wording_marks_the_strong_ones():
    from astrocal import config as config_module
    from astrocal.events import lunar_features

    start, end = config_module.month_bounds(2026, 10)
    for event in lunar_features.librations(start, end):
        if event.meta["strong"]:
            assert event.text.startswith("Благоприятная либрация")
        else:
            assert event.text.startswith("Либрация:")
