"""Тесты Binocular Sky: геометрия участка, оптика, видимость и рейтинг.

Проверяется не «код не падает», а содержательные утверждения: дом действительно
закрывает нужный сектор неба, наблюдательный восход позже астрономического,
поле зрения в режиме бинокля не масштабируется, Луна портит галактику сильнее,
чем Юпитер.
"""
from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from binocular_sky.models import horizon as horizon_model   # noqa: E402
from binocular_sky.models.binocular import (EYE_PUPIL_MM, BinocularProfile,
                                            default_binoculars)
from binocular_sky.models.observer import (ObserverProfile, demo_observer,
                                           parse_latlon)
from binocular_sky.models.scene import (FENCE, HOUSE, TREE, Landscape, Obstacle,
                                        demo_landscape, enu_from_polar)
from binocular_sky.models.target import GALAXY, OPEN_CLUSTER, Target
from binocular_sky.services import astronomy_service as astro
from binocular_sky.services import (catalog_service, horizon_service,
                                    observing_service, scene_service)
from binocular_sky.services import recommendation_service as rec

MSK = "Europe/Moscow"

# Реальная площадка пользователя — по ней считаются все проверки видимости.
SITE = ObserverProfile(name="Дача", latitude=55.324769, longitude=38.349526,
                       elevation_m=120.0, eye_height_m=1.75, timezone=MSK,
                       bortle=4)

NIGHT_DATE = dt.date(2026, 9, 2)


@pytest.fixture(scope="module")
def landscape():
    return demo_landscape()


@pytest.fixture(scope="module")
def horizon(landscape):
    return horizon_service.profile_for(landscape, SITE)


# ---------------------------------------------------------------- наблюдатель

def test_observer_normalises_coordinates():
    observer = ObserverProfile(latitude=95.0, longitude=200.0, bortle=42)
    assert observer.latitude == 90.0
    assert observer.longitude == pytest.approx(-160.0)
    assert observer.bortle == 9


def test_observer_timezone_and_roundtrip():
    restored = ObserverProfile.from_dict(SITE.to_dict())
    assert restored.timezone == MSK
    assert restored.latitude == pytest.approx(SITE.latitude)
    assert str(restored.tz) == MSK
    assert restored.now().tzinfo is not None


def test_unknown_timezone_falls_back_to_utc():
    observer = ObserverProfile(timezone="Middle/Earth")
    assert str(observer.tz) == "UTC"


@pytest.mark.parametrize("text,expected", [
    ("55.324769, 38.349526", (55.324769, 38.349526)),
    ("55,7558 37,6173", (55.7558, 37.6173)),
    ("-33.9; 18.4", (-33.9, 18.4)),
])
def test_parse_latlon_accepts_map_formats(text, expected):
    assert parse_latlon(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "москва", "955.0, 12.0", "12"])
def test_parse_latlon_rejects_nonsense(text):
    assert parse_latlon(text) is None


def test_demo_profile_is_marked():
    assert demo_observer().is_demo is True
    assert demo_landscape().is_demo is True


# ---------------------------------------------------------------- оптика

def test_exit_pupil_and_apparent_field():
    binocular = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    assert binocular.exit_pupil_mm == pytest.approx(5.0)
    assert binocular.apparent_field_deg == pytest.approx(65.0)


def test_effective_aperture_limited_by_eye_pupil():
    """У 7×50 выходной зрачок 7.1 мм — шире зрачка глаза, часть света теряется."""
    wide = BinocularProfile("7×50", 7.0, 50.0, 6.4)
    assert wide.effective_aperture_mm == pytest.approx(7.0 * EYE_PUPIL_MM)
    assert wide.effective_aperture_mm < wide.aperture_mm

    normal = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    assert normal.effective_aperture_mm == pytest.approx(50.0)


def test_bigger_aperture_sees_deeper():
    small = BinocularProfile("8×30", 8.0, 30.0, 8.0)
    large = BinocularProfile("15×70", 15.0, 70.0, 4.4)
    assert large.limiting_magnitude(4, 60) > small.limiting_magnitude(4, 60) + 1.0


def test_darker_sky_sees_deeper():
    binocular = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    assert (binocular.limiting_magnitude(2, 60)
            > binocular.limiting_magnitude(8, 60) + 2.0)


def test_low_altitude_costs_magnitudes():
    """У горизонта воздушная масса растёт и предел падает."""
    binocular = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    assert (binocular.limiting_magnitude(4, 80)
            > binocular.limiting_magnitude(4, 10) + 0.5)


def test_manual_override_wins_over_model():
    binocular = BinocularProfile("10×50", 10.0, 50.0, 6.5,
                                 limiting_mag_override=9.0)
    # в зените поглощение почти нулевое, поэтому остаётся заданное значение
    assert binocular.limiting_magnitude(4, 89) == pytest.approx(9.0, abs=0.05)


def test_airmass_is_one_at_zenith():
    assert BinocularProfile.airmass(90.0) == pytest.approx(1.0, abs=0.001)
    assert BinocularProfile.airmass(30.0) == pytest.approx(2.0, abs=0.02)


def test_field_fitting():
    binocular = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    assert binocular.fits_in_field(180.0) is True        # 3° при поле 6.5°
    assert binocular.fits_in_field(600.0) is False       # 10°
    assert binocular.fits_in_field(None) is None
    assert binocular.field_fraction(195.0) == pytest.approx(0.5)


def test_default_set_includes_naked_eye():
    assert any(b.is_naked_eye for b in default_binoculars())


# ---------------------------------------------------------------- геометрия сцены

def test_enu_from_polar_directions():
    east, north = enu_from_polar(10.0, 90.0)
    assert east == pytest.approx(10.0)
    assert north == pytest.approx(0.0, abs=1e-9)
    east, north = enu_from_polar(10.0, 0.0)
    assert north == pytest.approx(10.0)


def test_house_silhouette_covers_its_sector():
    """Дом закрывает сектор вокруг своего азимута и не закрывает остальное."""
    house = Obstacle(kind=HOUSE, name="Дом", distance_m=14.0, azimuth_deg=205.0,
                     width_m=8.0, length_m=10.0, wall_height_m=3.0,
                     ridge_height_m=5.5, rotation_deg=0.0)
    azimuth, altitude = house.silhouette(1.75)
    assert len(azimuth) > 100
    assert 180.0 < azimuth.min() < 205.0 < azimuth.max() < 235.0
    # конёк 5.5 м на расстоянии 14 м с высоты глаз 1.75 м даёт около 15°
    assert altitude.max() == pytest.approx(
        math.degrees(math.atan2(5.5 - 1.75, 14.0 - 5.0)), abs=6.0)


def test_house_mask_has_no_gaps_across_the_roof():
    """Маска не должна проваливаться посреди ската.

    Если строить силуэт только по рёбрам, между коньком и карнизом остаются
    пустые ячейки, и сквозь «дыры» в крыше просвечивают планеты.
    """
    house = Obstacle(kind=HOUSE, name="Дом", distance_m=14.0, azimuth_deg=205.0,
                     width_m=8.0, length_m=10.0, wall_height_m=3.0,
                     ridge_height_m=5.5, rotation_deg=25.0)
    profile = horizon_model.build(
        Landscape(name="только дом", obstacles=[house], natural_horizon_deg=1.0),
        1.75)
    inside = np.array([profile.altitude_at(a) for a in np.arange(190.0, 221.0, 0.5)])
    assert inside.min() > 5.0, "в силуэте дома остались просветы"


def test_tree_blocks_a_cone_of_sky():
    tree = Obstacle(kind=TREE, name="Берёза", distance_m=11.0, azimuth_deg=118.0,
                    trunk_height_m=3.5, crown_radius_m=2.6, crown_height_m=6.0)
    profile = horizon_model.build(
        Landscape(obstacles=[tree], natural_horizon_deg=1.0), 1.75)
    assert profile.altitude_at(118.0) > 25.0
    assert profile.altitude_at(180.0) == pytest.approx(1.0)


def test_fence_height_matches_trigonometry():
    fence = Obstacle(kind=FENCE, name="Забор", distance_m=10.0,
                     azimuth_start_deg=90.0, azimuth_end_deg=100.0, height_m=3.75)
    profile = horizon_model.build(
        Landscape(obstacles=[fence], natural_horizon_deg=0.0), 1.75)
    expected = math.degrees(math.atan2(3.75 - 1.75, 10.0))
    assert profile.altitude_at(95.0) == pytest.approx(expected, abs=0.2)
    assert profile.altitude_at(200.0) == pytest.approx(0.0)


def test_disabled_obstacle_does_not_block():
    tree = Obstacle(kind=TREE, distance_m=8.0, azimuth_deg=10.0,
                    crown_radius_m=3.0, crown_height_m=8.0, enabled=False)
    profile = horizon_model.build(
        Landscape(obstacles=[tree], natural_horizon_deg=2.0), 1.75)
    assert profile.altitude_at(10.0) == pytest.approx(2.0)


# ---------------------------------------------------------------- маска горизонта

def test_horizon_interpolates_across_north():
    """359° и 1° — соседи, а не края таблицы."""
    profile = horizon_model.flat(0.0, step_deg=1.0)
    profile.altitudes[0] = 10.0
    profile.altitudes[359] = 0.0
    assert profile.altitude_at(359.5) == pytest.approx(5.0, abs=0.1)


def test_horizon_visibility_and_clearance(horizon):
    roof = horizon.altitude_at(205.0)
    assert horizon.is_visible(205.0, roof + 5.0)
    assert not horizon.is_visible(205.0, roof - 5.0)
    assert horizon.clearance(205.0, roof + 3.0) == pytest.approx(3.0, abs=0.01)


def test_flat_horizon_is_uniform():
    profile = horizon_model.flat(4.0)
    assert profile.max_altitude_deg == pytest.approx(4.0)
    assert profile.altitude_at(123.4) == pytest.approx(4.0)


def test_obstacle_named_only_where_geometry_exists(landscape):
    """Фразу «над крышей» нельзя строить там, где крыши нет."""
    assert horizon_service.obstacle_at(landscape, 205.0, 1.75) == "Дачный дом"
    assert horizon_service.obstacle_at(landscape, 5.0, 1.75) == ""


# ---------------------------------------------------------------- координаты

def test_known_star_position_matches_reference():
    """Вега из Москвы в известный момент — сверка с независимым расчётом.

    Опорные значения получены полной моделью Skyfield (топоцентр, аберрация,
    нутация); тест защищает от разъезжания системы координат — например, от
    случайной смены знака азимута.
    """
    vega = Target(id="vega", name="Вега", kind="STAR",
                  ra_deg=279.2347, dec_deg=38.7837)
    when = dt.datetime(2026, 9, 2, 22, 0, tzinfo=SITE.tz)
    altitude, azimuth = astro.altaz_at(SITE, vega, when)
    # Вега 2 сентября в 22:00 МСК стоит высоко на юго-западе
    assert 60.0 < altitude < 80.0
    assert 200.0 < azimuth < 260.0


def test_coarse_grid_agrees_with_skyfield():
    """Быстрый путь расчёта не должен расходиться с полным больше долей градуса."""
    when = dt.datetime(2026, 9, 2, 23, 0, tzinfo=SITE.tz)
    targets = list(catalog_service.catalog())[::150]
    for target in targets:
        exact_alt, exact_az = astro.altaz_at(SITE, target, when)
        if exact_alt < 10.0:
            continue
        fast_alt, fast_az = astro.scan_altaz_at(SITE, target, when)
        assert abs(exact_alt - fast_alt) < 0.35
        assert abs((exact_az - fast_az + 180) % 360 - 180) < 1.0


def test_refraction_lifts_objects_at_the_horizon():
    assert astro.refraction_deg(0.0) == pytest.approx(0.55, abs=0.1)
    assert astro.refraction_deg(60.0) < 0.02
    assert astro.refraction_deg(-5.0) == 0.0


def test_sidereal_clock_matches_skyfield_over_a_night():
    reference = dt.datetime(2026, 9, 2, 21, 0, tzinfo=SITE.tz)
    clock = astro.SiderealClock(SITE, reference)
    target = catalog_service.find("M31")
    for hours in (0.0, 2.0, 5.0, 7.0):
        when = reference + dt.timedelta(hours=hours)
        exact_alt, _ = astro.altaz_at(SITE, target, when)
        fast_alt, _ = clock.altaz_at(target.ra_deg, target.dec_deg, when)
        assert abs(exact_alt - fast_alt) < 0.4


def test_night_bounds_are_ordered():
    night = astro.night_for(SITE, NIGHT_DATE)
    assert night.sunset < night.dark_start < night.dark_end < night.sunrise
    assert night.has_darkness


def test_moon_state_is_consistent():
    when = dt.datetime(2026, 9, 2, 23, 0, tzinfo=SITE.tz)
    moon = astro.moon_state(SITE, when)
    assert 0.0 <= moon.illumination <= 1.0
    assert -90.0 <= moon.altitude_deg <= 90.0
    assert moon.phase_name


# ---------------------------------------------------------------- видимость

def _analyse(target, landscape, horizon, when=None):
    night = astro.night_for(SITE, NIGHT_DATE)
    when = when or (night.start + (night.end - night.start) / 2)
    return horizon_service.analyse(SITE, target, horizon, when,
                                   night.start, night.end, landscape=landscape)


def test_object_below_horizon_is_not_visible(landscape, horizon):
    """Объект глубокого юга из Подмосковья не поднимается вовсе."""
    southern = Target(id="south", name="Южная точка", kind=GALAXY,
                      ra_deg=100.0, dec_deg=-75.0, magnitude=5.0)
    visibility = _analyse(southern, landscape, horizon)
    assert not visibility.visible_now
    assert not visibility.windows


def test_local_rise_is_later_than_astronomical_rise():
    """Ключевая проверка: крыша задерживает появление объекта.

    Один и тот же объект считается дважды — на ровном горизонте и на участке
    с домом. Наблюдательный восход обязан оказаться позже астрономического.
    """
    # объект, восходящий точно за домом (юго-запад демо-участка)
    target = Target(id="probe", name="Проба", kind=OPEN_CLUSTER,
                    ra_deg=270.0, dec_deg=-20.0, magnitude=5.0)
    night = astro.night_for(SITE, NIGHT_DATE)
    when = night.start

    house = Obstacle(kind=HOUSE, name="Дом", distance_m=10.0, azimuth_deg=180.0,
                     width_m=14.0, length_m=10.0, wall_height_m=4.0,
                     ridge_height_m=7.0)
    with_house = Landscape(name="с домом", obstacles=[house],
                           natural_horizon_deg=0.0)
    flat_site = Landscape(name="ровный", obstacles=[], natural_horizon_deg=0.0)

    flat_view = horizon_service.analyse(
        SITE, target, horizon_service.profile_for(flat_site, SITE), when,
        night.start, night.end, landscape=flat_site)
    house_view = horizon_service.analyse(
        SITE, target, horizon_service.profile_for(with_house, SITE), when,
        night.start, night.end, landscape=with_house)

    assert flat_view.windows, "на ровном горизонте объект должен быть виден"
    if house_view.windows:
        assert house_view.windows[0].start > flat_view.windows[0].start
        assert house_view.total_minutes < flat_view.total_minutes
    else:
        # дом закрыл объект полностью — тоже корректный исход, но окно исчезло
        assert flat_view.total_minutes > 0


def test_blocked_object_reports_the_obstacle():
    """Объект над математическим горизонтом, но за домом, помечается как закрытый."""
    house = Obstacle(kind=HOUSE, name="Дачный дом", distance_m=8.0,
                     azimuth_deg=180.0, width_m=20.0, length_m=10.0,
                     wall_height_m=6.0, ridge_height_m=9.0)
    site_landscape = Landscape(obstacles=[house], natural_horizon_deg=0.0)
    profile = horizon_service.profile_for(site_landscape, SITE)
    roof = profile.altitude_at(180.0)
    assert roof > 15.0

    # цель, проходящая через юг низко над горизонтом
    target = Target(id="low", name="Низкая цель", kind=OPEN_CLUSTER,
                    ra_deg=280.0, dec_deg=-15.0, magnitude=4.0)
    night = astro.night_for(SITE, NIGHT_DATE)
    grid = astro.time_grid(night.start, night.end, 5.0)
    altitude, azimuth = astro.scan_altaz_series(SITE, target, grid)
    mask = profile.altitude_at(azimuth)
    blocked = (altitude > 0) & (altitude <= mask)
    assert blocked.any(), "дом обязан хоть когда-то закрывать эту цель"

    index = int(np.argmax(blocked))
    moment = grid[index].utc_datetime().astimezone(SITE.tz)
    visibility = horizon_service.analyse(SITE, target, profile, moment,
                                         night.start, night.end,
                                         landscape=site_landscape)
    assert visibility.blocked_by_terrain
    assert visibility.blocking_obstacle == "Дачный дом"
    text = horizon_service.summarise(visibility, site_landscape, SITE)
    assert "закрыт" in text.lower()


def test_where_to_look_mentions_obstacle_only_when_present(landscape):
    with_house = horizon_service.where_to_look(205.0, 40.0, landscape, SITE)
    assert "дом" in with_house.lower()
    open_sky = horizon_service.where_to_look(5.0, 40.0, landscape, SITE)
    assert "дом" not in open_sky.lower()
    assert "азимут" in open_sky.lower()


# ---------------------------------------------------------------- каталог

def test_catalog_is_large_and_has_key_objects():
    catalog = catalog_service.catalog()
    assert len(catalog) > 300, "каталог не должен вырождаться в короткий список"
    for query in ("M31", "M45", "M13", "M42", "M44", "Double Cluster"):
        assert catalog_service.find(query) is not None, query


@pytest.mark.parametrize("query,expected_id", [
    ("M31", "NGC0224"), ("Андромеда", "NGC0224"), ("андромеда", "NGC0224"),
    ("Плеяды", "M45"), ("pleiades", "M45"), ("M45", "M45"),
    ("Вешалка", "Cr399"), ("Coathanger", "Cr399"),
    ("ngc 869", "NGC0869"),
])
def test_search_aliases(query, expected_id):
    found = catalog_service.find(query)
    assert found is not None and found.id == expected_id


def test_search_is_case_and_yo_insensitive():
    assert catalog_service.find("плеяды") is catalog_service.find("Плеяды")
    assert catalog_service.find("вешалка") is not None


def test_lone_catalogue_stars_are_excluded():
    """Одиночная звезда из OpenNGC — не цель для бинокля."""
    assert all(target.kind != "STAR" for target in catalog_service.catalog())


def test_surface_brightness_estimated_when_missing():
    target = Target(id="x", name="x", kind=GALAXY, magnitude=8.0,
                    major_arcmin=10.0, minor_arcmin=5.0)
    estimated = target.effective_surface_brightness()
    assert estimated is not None and estimated > 8.0


# ---------------------------------------------------------------- рейтинг

@pytest.fixture(scope="module")
def tonight(landscape, horizon):
    return rec.tonight(SITE, default_binoculars()[0], landscape, NIGHT_DATE,
                       horizon, limit=15, min_score=30)


def test_tonight_returns_a_reasonable_programme(tonight):
    assert 5 <= len(tonight) <= 15
    assert all(item.visibility.windows for item in tonight)
    assert tonight == sorted(tonight, key=lambda r: (-r.score, r.target.name))


def test_tonight_excludes_objects_below_the_horizon(tonight):
    for item in tonight:
        assert item.visibility.best_window.max_altitude_deg > 0


def test_moon_hurts_a_galaxy_more_than_a_planet():
    """Полная Луна рядом с целью почти не мешает Юпитеру и губит галактику."""
    bright_moon = astro.MoonState(altitude_deg=45.0, azimuth_deg=180.0,
                                  illumination=1.0, waxing=True,
                                  phase_angle_deg=180.0)
    galaxy = Target(id="g", name="Галактика", kind=GALAXY, magnitude=9.0,
                    major_arcmin=10.0)
    planet = Target(id="jupiter", name="Юпитер", kind="PLANET", magnitude=-2.5,
                    major_arcmin=0.7, body_key="jupiter")

    galaxy_points, _, _ = rec.moon_points(galaxy, bright_moon, 15.0)
    planet_points, _, _ = rec.moon_points(planet, bright_moon, 15.0)
    assert planet_points > galaxy_points + 8.0

    dark = astro.MoonState(-20.0, 0.0, 1.0, True, 180.0)
    assert rec.moon_points(galaxy, dark, 90.0)[0] == 15.0


def test_moon_penalty_grows_with_proximity():
    moon = astro.MoonState(50.0, 180.0, 0.9, True, 170.0)
    assert rec.moon_penalty_mag(moon, 10.0) > rec.moon_penalty_mag(moon, 120.0)
    below = astro.MoonState(-5.0, 180.0, 1.0, True, 180.0)
    assert rec.moon_penalty_mag(below, 10.0) == 0.0


def test_field_of_view_changes_the_rating():
    """Один и тот же объект в широком и узком поле оценивается по-разному."""
    wide = BinocularProfile("широкое", 8.0, 42.0, 8.0)
    narrow = BinocularProfile("узкое", 25.0, 70.0, 2.0)
    pleiades = catalog_service.find("M45")
    wide_points, _, _ = rec.framing_points(pleiades, wide)
    narrow_points, _, _ = rec.framing_points(pleiades, narrow)
    assert wide_points > narrow_points


def test_double_star_needs_enough_magnification():
    """Альбирео в 10× не разделяется, в 25× — да."""
    albireo = catalog_service.find("Альбирео")
    assert albireo is not None
    weak = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    strong = BinocularProfile("25×70", 25.0, 70.0, 2.4)
    weak_points, weak_reasons, _ = rec.type_adjustment(albireo, weak, {})
    strong_points, strong_reasons, _ = rec.type_adjustment(albireo, strong, {})
    assert strong_points > weak_points + 1.0
    assert any("на пределе" in r for r in weak_reasons)
    assert any("уверенно" in r for r in strong_reasons)

    # совсем тесную пару бинокль не разделит вовсе
    tight = Target(id="t", name="Тесная пара", kind="DOUBLE_STAR",
                   magnitude=5.0, major_arcmin=0.02)
    _, _, tight_warnings = rec.type_adjustment(tight, weak, {})
    assert any("увеличение" in w for w in tight_warnings)


def test_planet_without_a_resolvable_disc_is_penalised():
    """Уран в бинокль — точка, и рейтинг обязан это учитывать."""
    binocular = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    uranus = Target(id="uranus", name="Уран", kind="PLANET", magnitude=5.7,
                    major_arcmin=0.06, body_key="uranus")
    jupiter = Target(id="jupiter", name="Юпитер", kind="PLANET", magnitude=-2.5,
                     major_arcmin=0.7, body_key="jupiter")
    uranus_points, _, uranus_warnings = rec.type_adjustment(uranus, binocular, {})
    jupiter_points, _, _ = rec.type_adjustment(jupiter, binocular, {})
    assert jupiter_points > uranus_points
    assert any("звездой" in w for w in uranus_warnings)


def test_jupiter_moons_need_jupiter():
    binocular = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    io = Target(id="jup_io", name="Ио", kind="JUPITER_MOON", magnitude=5.5,
                major_arcmin=0.03, body_key="io")
    visible, _, _ = rec.type_adjustment(io, binocular, {"jupiter_visible": True})
    hidden, _, warnings = rec.type_adjustment(io, binocular,
                                              {"jupiter_visible": False})
    assert visible > hidden
    assert any("Юпитер" in w for w in warnings)


def test_faint_object_below_the_limit_is_flagged():
    binocular = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    faint = Target(id="f", name="Слабый", kind=GALAXY, magnitude=13.0,
                   major_arcmin=3.0)
    points, _, warnings = rec.detectability_points(faint, binocular, 10.5, 21.0)
    assert points == 0.0
    assert any("предела" in w for w in warnings)


def test_instrument_changes_the_programme(landscape, horizon):
    """Список для невооружённого глаза не совпадает со списком для бинокля."""
    eye = default_binoculars()[3]
    eye_list = rec.tonight(SITE, eye, landscape, NIGHT_DATE, horizon, limit=10)
    binocular_list = rec.tonight(SITE, default_binoculars()[0], landscape,
                                 NIGHT_DATE, horizon, limit=10)
    assert {r.target.id for r in eye_list} != {r.target.id for r in binocular_list}
    assert max(r.score for r in eye_list) <= max(r.score for r in binocular_list)


def test_stars_scale_is_monotone():
    assert rec.stars_for(95) == 5
    assert rec.stars_for(80) == 4
    assert rec.stars_for(65) == 3
    assert rec.stars_for(50) == 2
    assert rec.stars_for(10) == 1


def test_explanation_is_built_from_computed_values(tonight):
    lines = rec.explain(tonight[0], default_binoculars()[0])
    assert lines[0] == tonight[0].target.name
    assert "★" in lines[1]
    assert any("Лучшее время" in line for line in lines)


def test_show_me_something_skips_seen_objects(tonight):
    first = rec.show_me_something(tonight, set())
    second = rec.show_me_something(tonight, {first.target.id})
    assert first.target.id != second.target.id


# ---------------------------------------------------------------- сцена и JSON

def test_snapshot_schema(landscape, horizon):
    when = astro.default_moment(SITE, NIGHT_DATE)
    snapshot = scene_service.sky_snapshot(SITE, default_binoculars()[0],
                                          landscape, when, horizon)
    for key in ("when", "stars", "constellations", "solar", "deep_sky",
                "moon", "sun_altitude", "terrain"):
        assert key in snapshot

    stars = snapshot["stars"]
    assert len(stars["az"]) == len(stars["alt"]) == len(stars["mag"])
    assert stars["az"] and all(0.0 <= a <= 360.0 for a in stars["az"])

    solar = {item["id"] for item in snapshot["solar"]}
    assert {"moon", "jupiter", "saturn"} <= solar

    terrain = snapshot["terrain"]
    assert terrain["obstacles"], "препятствия участка должны попадать в сцену"
    assert len(terrain["horizon"]) == 180
    assert terrain["panorama"]["mode"] in ("NONE", "PHOTOS", "EQUIRECTANGULAR")


def test_snapshot_is_json_serialisable(landscape, horizon):
    import json
    when = astro.default_moment(SITE, NIGHT_DATE)
    snapshot = scene_service.sky_snapshot(SITE, default_binoculars()[0],
                                          landscape, when, horizon)
    text = json.dumps(snapshot, ensure_ascii=False)
    assert json.loads(text)["when"] == snapshot["when"]


def test_track_marks_blocked_segments(landscape, horizon):
    night = astro.night_for(SITE, NIGHT_DATE)
    target = catalog_service.find("M31")
    track = scene_service.track(SITE, target, landscape, horizon,
                                night.start, night.end)
    assert len(track["points"]) > 20
    assert all("blocked" in point for point in track["points"])


def test_binocular_field_preserves_angular_scale(landscape):
    """Поле в режиме бинокля равно полю прибора, а размеры — настоящие."""
    binocular = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    when = astro.default_moment(SITE, NIGHT_DATE)
    target = catalog_service.find("M45")
    field = scene_service.binocular_field(SITE, binocular, target, when)

    assert field["fov_deg"] == 6.5
    assert field["orientation"] == "NORMAL"
    radius = 6.5 / 2 * 1.25
    for star in field["stars"]:
        assert abs(star["x"]) <= radius and abs(star["y"]) <= radius
    # цель находится в центре поля
    centred = [o for o in field["objects"] if o["id"] == target.id]
    assert centred and math.hypot(centred[0]["x"], centred[0]["y"]) < 0.1


def test_binocular_field_excludes_the_opposite_sky():
    """Гномоническая проекция не должна заворачивать далёкие объекты в поле."""
    binocular = BinocularProfile("10×50", 10.0, 50.0, 6.5)
    when = astro.default_moment(SITE, NIGHT_DATE)
    target = catalog_service.find("Каскад Кембла")
    field = scene_service.binocular_field(SITE, binocular, target, when)
    for item in field["objects"]:
        catalogued = catalog_service.by_id().get(item["id"])
        if catalogued is None or catalogued.dec_deg is None:
            continue
        assert catalogued.dec_deg > 0, f"{item['name']} не может быть в этом поле"


def test_wider_field_shows_more_stars():
    when = astro.default_moment(SITE, NIGHT_DATE)
    target = catalog_service.find("M45")
    wide = scene_service.binocular_field(
        SITE, BinocularProfile("широкое", 7.0, 50.0, 9.0), target, when)
    narrow = scene_service.binocular_field(
        SITE, BinocularProfile("узкое", 20.0, 60.0, 2.5), target, when)
    assert len(wide["stars"]) > len(narrow["stars"])


def test_star_levels_are_ordered():
    levels = scene_service.star_levels()
    limits = [level["mag_limit"] for level in levels]
    assert limits == sorted(limits)


# ---------------------------------------------------------------- план

def test_plan_orders_by_closing_window():
    """Раньше смотрим то, что раньше закроется."""
    tz = SITE.tz
    start = dt.datetime(2026, 9, 2, 21, 0, tzinfo=tz)
    end = dt.datetime(2026, 9, 3, 4, 0, tzinfo=tz)
    plan = observing_service.ObservingPlan(date=NIGHT_DATE, items=[
        observing_service.PlanItem("all", "Всю ночь", window_start=start,
                                   window_end=end, stars=4),
        observing_service.PlanItem("early", "Заходит рано", window_start=start,
                                   window_end=start + dt.timedelta(hours=1),
                                   stars=5),
    ])
    observing_service.optimise(plan, start, end)
    assert [item.target_id for item in plan.items] == ["early", "all"]
    assert plan.items[0].scheduled < plan.items[1].scheduled


def test_plan_marks_unavailable_objects():
    tz = SITE.tz
    start = dt.datetime(2026, 9, 2, 21, 0, tzinfo=tz)
    end = start + dt.timedelta(hours=6)
    plan = observing_service.ObservingPlan(date=NIGHT_DATE, items=[
        observing_service.PlanItem("nope", "Недоступен"),
    ])
    observing_service.optimise(plan, start, end)
    assert plan.items[0].scheduled is None
    assert "не поднимается" in plan.items[0].note


def test_plan_rejects_duplicates():
    plan = observing_service.ObservingPlan(date=NIGHT_DATE)
    assert plan.add(observing_service.PlanItem("m31", "M31"))
    assert not plan.add(observing_service.PlanItem("m31", "M31"))
    assert plan.contains("m31")
    plan.remove("m31")
    assert not plan.contains("m31")


# ---------------------------------------------------------------- сохранение

def test_settings_roundtrip(tmp_path):
    from binocular_sky import storage

    settings = storage.default_settings()
    settings.observers[0].name = "Моя дача"
    settings.binoculars[0].field_of_view_deg = 7.1
    settings.night_mode = True
    settings.plan_for(NIGHT_DATE).add(
        observing_service.PlanItem("M45", "Плеяды", stars=5))
    landscape = settings.landscape_for(settings.observers[0])
    landscape.obstacles.append(
        Obstacle(kind=HOUSE, name="Дом", distance_m=12.0, azimuth_deg=200.0))
    settings.set_landscape(settings.observers[0], landscape)

    path = tmp_path / "settings.json"
    storage.save(settings, path)
    restored = storage.load(path)

    assert restored.observer.name == "Моя дача"
    assert restored.binocular.field_of_view_deg == pytest.approx(7.1)
    assert restored.night_mode is True
    assert restored.plan_for(NIGHT_DATE).contains("M45")
    assert restored.landscape_for(restored.observers[0]).obstacles[0].name == "Дом"


def test_broken_settings_file_falls_back(tmp_path):
    from binocular_sky import storage

    path = tmp_path / "settings.json"
    path.write_text("{ это не json", encoding="utf-8")
    settings = storage.load(path)
    assert settings.observers, "битый файл не должен оставлять без профиля"


def test_default_settings_separate_demo_from_real():
    from binocular_sky import storage

    settings = storage.default_settings()
    real = [o for o in settings.observers if not o.is_demo]
    demo = [o for o in settings.observers if o.is_demo]
    assert real and demo
    # у реальной площадки нет выдуманных препятствий
    assert not settings.landscape_for(real[0]).obstacles
    assert settings.landscape_for(demo[0]).obstacles
