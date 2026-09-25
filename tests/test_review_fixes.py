"""Замечания по октябрьскому выпуску: метеоры, видимость планет, небо в полосе.

Каждый тест здесь вырос из конкретной ошибки, найденной при разборе готового
выпуска. Смысл в том, чтобы она не вернулась.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg                                 # noqa: E402
from astrocal.events import meteors, occultations, visibility      # noqa: E402


# ------------------------------------------------------------------ метеоры


def codes() -> set[str]:
    return {code for code, *_rest in meteors.SHOWERS}


def test_draconids_are_in_the_list():
    """Из октябрьского выпуска выпал целый поток с вечерним максимумом."""
    assert "DRA" in codes()


def test_draconids_peak_in_early_october():
    lam = next(lam for code, _n, lam, *_r in meteors.SHOWERS if code == "DRA")
    assert 195.0 <= lam <= 196.0          # начало октября


def test_draconid_radiant_is_circumpolar_from_moscow():
    ra, dec = meteors.RADIANTS["DRA"]
    assert dec > 50.0                     # склонение Дракона — радиант не заходит
    assert 250.0 < ra < 275.0


def test_main_annual_showers_are_covered():
    expected = {"QUA", "LYR", "ETA", "SDA", "CAP", "PER", "KCG", "AUR", "SPE",
                "DSX", "DRA", "STA", "ORI", "NTA", "LEO", "GEM", "URS"}
    assert expected <= codes()


def test_every_shower_has_a_radiant():
    assert codes() <= set(meteors.RADIANTS)


def test_solar_longitudes_are_ordered_within_a_year():
    values = [lam for _c, _n, lam, *_r in meteors.SHOWERS]
    assert all(0.0 <= value < 360.0 for value in values)
    assert len(set(values)) == len(values), "две одинаковые λ☉ — опечатка"


def test_variable_showers_are_marked():
    """У Драконид активность скачет на порядки — обещать ZHR нельзя."""
    assert "DRA" in meteors.VARIABLE


def test_draconid_event_warns_about_variability():
    start, end = cfg.month_bounds(2026, 10)
    events = meteors.all_events(start, end)
    draconids = [e for e in events if "Дракониды" in e.text]
    assert draconids, "Дракониды не попали в октябрь"
    assert "непостоянна" in draconids[0].computed


def test_draconids_are_an_evening_shower_in_2026():
    start, end = cfg.month_bounds(2026, 10)
    draconids = [e for e in meteors.all_events(start, end)
                 if "Дракониды" in e.text][0]
    assert "19:" in draconids.computed or "20:" in draconids.computed


# ------------------------------------------------------------------ видимость


def test_inner_planets_have_all_four_boundaries():
    assert "mercury" in visibility.INNER and "venus" in visibility.INNER


def test_outer_planets_only_appear_and_depart():
    """«Окончание утренней видимости Сатурна» — события такого не бывает."""
    assert visibility.OUTER_SLOTS == {("morning", "Начало"),
                                      ("evening", "Окончание")}


def test_saturn_has_no_morning_ending_in_october():
    start, end = cfg.month_bounds(2026, 10)
    texts = [e.text for e in visibility.all_events(start, end)]
    assert not [t for t in texts
                if "Окончание утренней" in t and "Сатурна" in t]


def test_mercury_boundaries_survive():
    """Проверка не должна заодно убить законные события внутренних планет."""
    start, end = cfg.month_bounds(2026, 12)
    texts = [e.text for e in visibility.all_events(start, end)]
    assert any("Меркурия" in t for t in texts)


# ------------------------------------------------------------------ небо в полосе


def band_for(altitudes: dict):
    """Полоса-заглушка: в каждом регионе своя высота Солнца."""
    lats, lons, sun = [], [], []
    for name, altitude in altitudes.items():
        entry = next(r for r in occultations.RU_REGIONS if r[0] == name)
        _n, _p, lat_lo, lat_hi, lon_lo, lon_hi = entry
        lats.append((lat_lo + lat_hi) / 2)
        lons.append((lon_lo + lon_hi) / 2)
        sun.append(altitude)
    lat = np.array(lats)
    lon = np.array(lons)
    mask = np.ones(len(lats), dtype=bool)
    return {"lat": lat, "lon": lon, "mask": mask,
            "sun_alt": np.array(sun)}, lat, lon


def coverage(names):
    return [(name, next(r[1] for r in occultations.RU_REGIONS if r[0] == name), 1.0)
            for name in names]


def test_sky_is_reported_per_region():
    """Полоса тянется на тысячи километров: одной метки на всю страну мало."""
    altitudes = {"Новая Земля и Арктика России": -11.0, "Якутия": 9.0}
    band, lat, lon = band_for(altitudes)
    result = occultations.sky_by_region(band, lat, lon, coverage(altitudes))
    states = {name: state for name, _p, _a, state in result}
    assert states["Новая Земля и Арктика России"] == "twilight"
    assert states["Якутия"] == "day"


def test_four_gradations_of_sky():
    altitudes = {"Новая Земля и Арктика России": -20.0, "Таймыр": -8.0,
                 "Западная Сибирь": -3.0, "Якутия": 9.0}
    band, lat, lon = band_for(altitudes)
    states = {name: state for name, _p, _a, state
              in occultations.sky_by_region(band, lat, lon, coverage(altitudes))}
    assert states["Новая Земля и Арктика России"] == "night"
    assert states["Таймыр"] == "twilight"
    assert states["Западная Сибирь"] == "light"
    assert states["Якутия"] == "day"


def test_description_groups_regions_by_sky():
    altitudes = {"Новая Земля и Арктика России": -20.0, "Якутия": 9.0}
    band, lat, lon = band_for(altitudes)
    text = occultations.describe_sky(
        occultations.sky_by_region(band, lat, lon, coverage(altitudes)))
    assert text.startswith("ночью")
    assert "днём" in text
    assert "российской Арктике" in text


def test_dark_part_is_not_lost_behind_the_bright_one():
    """Покрытие Альционы было целиком помечено дневным из-за медианы."""
    altitudes = {"Новая Земля и Арктика России": -11.0,
                 "Восточная Сибирь": 8.0, "Якутия": 9.0}
    band, lat, lon = band_for(altitudes)
    text = occultations.describe_sky(
        occultations.sky_by_region(band, lat, lon, coverage(altitudes)))
    assert "в сумерках" in text
    assert occultations.daytime_over_russia(
        band, lat, lon, band["mask"], coverage(altitudes)) is True, \
        "старая грубая оценка по-прежнему считает полосу дневной"


def test_empty_band_gives_empty_description():
    assert occultations.describe_sky([]) == ""


@pytest.mark.parametrize("altitude,expected", [
    (10.0, "day"), (-2.0, "light"), (-9.0, "twilight"), (-30.0, "night")])
def test_thresholds(altitude, expected):
    altitudes = {"Якутия": altitude}
    band, lat, lon = band_for(altitudes)
    result = occultations.sky_by_region(band, lat, lon, coverage(altitudes))
    assert result[0][3] == expected


def test_all_regions_are_listed_not_just_three():
    """Раньше в строку попадали только три региона из шести."""
    names = ["Таймыр", "Новая Земля и Арктика России", "Восточная Сибирь",
             "Якутия", "Западная Сибирь", "Камчатка и Чукотка"]
    altitudes = {name: -20.0 for name in names}
    band, lat, lon = band_for(altitudes)
    text = occultations.describe_sky(
        occultations.sky_by_region(band, lat, lon, coverage(altitudes)))
    for name in ("Таймыре", "Якутии", "Камчатке"):
        assert name in text


def test_occultation_time_is_moscow():
    start = dt.datetime(2026, 10, 27, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 10, 29, tzinfo=cfg.MSK)
    events, _report = occultations.build_stars(start, end)
    assert events
    for event in events:
        assert event.when.utcoffset() == dt.timedelta(hours=3)
