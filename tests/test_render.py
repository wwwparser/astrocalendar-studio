"""Карты: файлы создаются, проекция считает то, что нужно."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal.cities import by_key                        # noqa: E402
from astrocal.config import MSK                           # noqa: E402
from astrocal.core import Event                           # noqa: E402
from astrocal.render import event_map, skymap, styles     # noqa: E402

MOSCOW = by_key("москва")
WHEN = dt.datetime(2026, 9, 20, 22, 0, tzinfo=MSK)


# ------------------------------------------------------------------ проекция


def test_zenith_projects_to_centre():
    x, y = skymap.project([90], [0])
    assert abs(float(x[0])) < 1e-9
    assert abs(float(y[0])) < 1e-9


def test_horizon_projects_to_unit_circle():
    for azimuth in (0, 90, 180, 270):
        x, y = skymap.project([0], [azimuth])
        assert float(np.hypot(x[0], y[0])) == pytest.approx(1.0, abs=1e-9)


def test_north_is_up_and_east_is_left():
    """Карта неба смотрит вверх, а не вниз: восток слева от севера."""
    north_x, north_y = skymap.project([0], [0])
    east_x, _east_y = skymap.project([0], [90])
    assert float(north_y[0]) > 0.9          # север сверху
    assert float(east_x[0]) < -0.9          # восток слева


def test_radius_grows_as_altitude_falls():
    high_x, high_y = skymap.project([60], [45])
    low_x, low_y = skymap.project([10], [45])
    assert np.hypot(low_x[0], low_y[0]) > np.hypot(high_x[0], high_y[0])


def test_star_marker_size_grows_with_brightness():
    assert styles.star_marker_size(0.0) > styles.star_marker_size(3.0)
    assert styles.star_marker_size(3.0) > styles.star_marker_size(5.0)


# ------------------------------------------------------------------ файлы


def test_sky_map_is_written(tmp_path):
    path = skymap.sky_at(MOSCOW, WHEN, tmp_path / "sky.png")
    assert path.exists()
    assert path.stat().st_size > 20_000        # не пустая заглушка


def test_sky_map_marks_requested_object(tmp_path):
    highlights = skymap.planet_highlights(["saturn"], {"saturn": "Сатурн"})
    path = skymap.sky_at(MOSCOW, WHEN, tmp_path / "saturn.png",
                         highlights=highlights)
    assert path.exists()


def test_event_map_for_conjunction(tmp_path):
    event = Event(
        when=dt.datetime(2026, 9, 6, 22, 0, tzinfo=MSK),
        text="Луна (Ф=-0,23) проходит в 3.0° севернее Марса (V=+1,2m) "
             "в созвездии Близнецы",
        category="moon")
    path = event_map.for_event(event, MOSCOW, tmp_path / "conjunction.png")
    assert path is not None and path.exists()
    assert path.stat().st_size > 10_000


def test_event_map_returns_none_for_unsupported_kind(tmp_path):
    event = Event(when=WHEN, text="Запуск ракеты", category="spaceflight")
    assert event_map.for_event(event, MOSCOW, tmp_path / "nothing.png") is None


def test_light_theme_differs_from_dark(tmp_path):
    dark = skymap.sky_at(MOSCOW, WHEN, tmp_path / "dark.png", theme="dark")
    light = skymap.sky_at(MOSCOW, WHEN, tmp_path / "light.png", theme="light")
    assert dark.read_bytes() != light.read_bytes()


# ------------------------------------------------------------------ пролёты


def test_pass_geometry_and_map(tmp_path):
    from astrocal.render import satellite_map

    start = dt.datetime.now(MSK)
    passes = []
    # серии видимости чередуются, поэтому пробуем два города и широкое окно
    for city in (MOSCOW, by_key("краснодар")):
        for catnr in (25544, 48274):
            passes += satellite_map.passes_for_station(
                catnr, city, start, start + dt.timedelta(days=12))
    if not passes:
        pytest.skip("в ближайшие двенадцать суток видимых пролётов нет")

    best = max(passes, key=lambda item: item.max_altitude_deg)
    assert best.start < best.peak <= best.end
    assert 0 < best.max_altitude_deg <= 90
    assert best.duration_minutes > 0
    assert best.tle_age_days >= 0
    assert best.samples

    # высота в максимуме — действительно максимум трека
    assert best.max_altitude_deg == pytest.approx(
        max(sample["altitude"] for sample in best.samples), abs=1e-6)

    path = satellite_map.render(best, tmp_path / "pass.png")
    assert path.exists() and path.stat().st_size > 20_000


def test_tle_age_controls_confidence():
    from astrocal.render.satellite_map import Pass

    def make(age_days: float) -> Pass:
        moment = dt.datetime(2026, 9, 10, 20, 0, tzinfo=MSK)
        return Pass(station="МКС", city=MOSCOW, start=moment, peak=moment,
                    end=moment, max_altitude_deg=45.0, start_azimuth_deg=200.0,
                    peak_azimuth_deg=180.0, end_azimuth_deg=100.0,
                    sun_altitude_deg=-12.0, enters_shadow=False,
                    tle_epoch=moment, tle_age_days=age_days)

    assert "HIGH" in make(1.0).tle_status
    assert "WARNING" in make(5.0).tle_status
    assert "нельзя" in make(20.0).tle_status
