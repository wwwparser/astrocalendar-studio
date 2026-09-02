"""Снимок сцены для трёхмерного вида: то, что уходит в JavaScript.

Граница между Python и JS проведена жёстко: астрономия считается здесь, JS
только рисует. Поэтому наружу отдаётся плоский JSON с готовыми азимутами и
высотами, а не элементы орбит и не время, из которого JS сам что-то выводил бы.

Снимок пересчитывается при смене момента, площадки или прибора — а не каждый
кадр анимации. За кадр JS двигает только камеру.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np

from ..models.binocular import BinocularProfile
from ..models.observer import ObserverProfile
from ..models.target import MOON, PLANET
from . import astronomy_service as astro
from . import catalog_service, horizon_service

# Предел блеска звёзд в сцене. Глубже 6.5m точек становится десятки тысяч, а
# на экране они всё равно сливаются; каталог до +11m архитектурно поддержан
# через `star_levels`, но грузится по запросу.
SKY_STAR_MAG = 6.5

# Объекты каталога, которые попадают в сцену: показывать все девятьсот бессмысленно.
SCENE_DSO_MAG = 8.5


def star_levels() -> list[dict]:
    """Уровни глубины звёздного каталога.

    Задел под каталог до +11m: сцена запрашивает уровень, а не «все звёзды»,
    поэтому переход на более глубокий каталог не потребует менять протокол —
    добавится ещё один уровень с большим `mag_limit`.
    """
    return [{"level": 0, "mag_limit": 4.5, "label": "только яркие"},
            {"level": 1, "mag_limit": 5.5, "label": "городское небо"},
            {"level": 2, "mag_limit": 6.5, "label": "тёмное небо"}]


def sky_snapshot(observer: ObserverProfile, binocular: BinocularProfile,
                 landscape, when: dt.datetime, horizon=None,
                 star_mag_limit: float = SKY_STAR_MAG,
                 dso_mag_limit: float = SCENE_DSO_MAG,
                 include_terrain: bool = True) -> dict:
    """Полный снимок неба и участка на момент `when`."""
    horizon = horizon if horizon is not None else horizon_service.profile_for(
        landscape, observer)

    payload = {
        "when": when.isoformat(),
        "when_text": f"{when:%d.%m.%Y %H:%M}",
        "observer": observer.to_dict(),
        "binocular": binocular.to_dict(),
        "binocular_fov": binocular.field_of_view_deg,
        "stars": _stars(observer, when, star_mag_limit),
        "constellations": _constellation_lines(observer, when, star_mag_limit),
        "solar": _solar(observer, when),
        "deep_sky": _deep_sky(observer, when, dso_mag_limit, horizon),
        "moon": astro.moon_state(observer, when).to_dict(),
        "sun_altitude": round(astro.sun_altitude(observer, when), 2),
        "star_levels": star_levels(),
    }
    if include_terrain:
        payload["terrain"] = terrain_snapshot(landscape, observer, horizon)
    return payload


def terrain_snapshot(landscape, observer: ObserverProfile, horizon=None) -> dict:
    """Геометрия участка и профиль местного горизонта."""
    horizon = horizon if horizon is not None else horizon_service.profile_for(
        landscape, observer)
    return {
        "name": landscape.name,
        "is_demo": bool(getattr(landscape, "is_demo", False)),
        "eye_height_m": observer.eye_height_m,
        "natural_horizon_deg": landscape.natural_horizon_deg,
        "obstacles": landscape.scene_geometry(),
        "horizon": _horizon_curve(horizon),
        "panorama": _panorama(landscape),
    }


def _horizon_curve(horizon, step_deg: float = 2.0) -> list[list[float]]:
    """Прореженный профиль горизонта для отрисовки: 180 точек вместо 720."""
    azimuths = np.arange(0.0, 360.0, step_deg)
    return [[float(a), round(float(horizon.altitude_at(a)), 3)] for a in azimuths]


def _panorama(landscape) -> dict:
    """Привязка фотографий. Сейчас — метаданные, дальше сюда ляжет склейка."""
    return {
        "mode": landscape.panorama_mode,
        "equirectangular": landscape.equirectangular_path,
        "north_offset_deg": landscape.equirectangular_north_offset_deg,
        "photos": [{"path": p.path, "azimuth": p.center_azimuth_deg,
                    "fov": p.horizontal_fov_deg,
                    "horizon_fraction": p.horizon_pixel_fraction,
                    "label": p.label}
                   for p in landscape.photos],
    }


def _stars(observer: ObserverProfile, when: dt.datetime,
           mag_limit: float) -> dict:
    """Звёзды над горизонтом в виде плоских массивов.

    Массивы, а не список словарей: три тысячи объектов в JSON как словари — это
    сотни килобайт на каждый шаг ползунка времени, а как три массива чисел —
    десятки, и JS кладёт их в буфер геометрии без перебора.
    """
    hip, magnitude, _, _ = astro.star_table(mag_limit)
    altitude, azimuth = astro.star_altaz(observer, when, mag_limit)
    above = altitude > -2.0
    return {
        "hip": [int(v) for v in hip[above]],
        "az": [round(float(v), 3) for v in azimuth[above]],
        "alt": [round(float(v), 3) for v in altitude[above]],
        "mag": [round(float(v), 2) for v in magnitude[above]],
        "mag_limit": mag_limit,
    }


def _constellation_lines(observer: ObserverProfile, when: dt.datetime,
                         mag_limit: float) -> list[dict]:
    """Фигуры созвездий: отрезки в горизонтальных координатах плюс подпись."""
    from astrocal.constellations import constellation_lines, name_ru

    hip, _, _, _ = astro.star_table(mag_limit)
    altitude, azimuth = astro.star_altaz(observer, when, mag_limit)
    position = {int(h): (float(altitude[i]), float(azimuth[i]))
                for i, h in enumerate(hip)}

    figures = []
    for abbreviation, pairs in constellation_lines():
        segments = []
        for start, finish in pairs:
            a, b = position.get(start), position.get(finish)
            if a is None or b is None or (a[0] < -5.0 and b[0] < -5.0):
                continue
            segments.append([round(a[1], 2), round(a[0], 2),
                             round(b[1], 2), round(b[0], 2)])
        if not segments:
            continue
        visible = [s for s in segments if s[1] > 0 or s[3] > 0]
        label = None
        if visible:
            label = {"az": round(float(np.mean([s[0] for s in visible])), 2),
                     "alt": round(float(np.mean([s[1] for s in visible])), 2),
                     "text": name_ru(abbreviation)}
        figures.append({"abbr": abbreviation, "name": name_ru(abbreviation),
                        "segments": segments, "label": label})
    return figures


def _solar(observer: ObserverProfile, when: dt.datetime) -> list[dict]:
    """Солнце, Луна, планеты и галилеевы спутники с блеском на момент."""
    from astrocal.magnitudes import planet_magnitude

    t = astro.to_skyfield(when)
    result = []
    for target in astro.solar_targets(when):
        try:
            altitude, azimuth = astro.altaz_at(observer, target, when)
        except Exception:
            continue
        magnitude = target.magnitude
        if target.kind == PLANET:
            try:
                magnitude = float(planet_magnitude(target.body_key, t))
            except Exception:
                pass
        entry = {"id": target.id, "name": target.name, "kind": target.kind,
                 "az": round(azimuth, 3), "alt": round(altitude, 3),
                 "mag": None if magnitude is None else round(magnitude, 2),
                 "size": target.major_arcmin}
        if target.kind == MOON:
            state = astro.moon_state(observer, when)
            entry["illumination"] = round(state.illumination, 4)
            entry["phase_name"] = state.phase_name
            entry["waxing"] = state.waxing
        result.append(entry)
    return result


def _deep_sky(observer: ObserverProfile, when: dt.datetime, mag_limit: float,
              horizon) -> list[dict]:
    """Объекты глубокого космоса над горизонтом, с флагом «закрыт участком»."""
    targets = [t for t in catalog_service.catalog()
               if t.magnitude is not None and t.magnitude <= mag_limit]
    if not targets:
        return []
    altitude, azimuth = astro.fixed_altaz(observer, targets, when)
    mask = horizon.altitude_at(azimuth)
    result = []
    for target, alt, az, floor in zip(targets, altitude, azimuth, mask):
        if alt < -2.0:
            continue
        result.append({
            "id": target.id, "name": target.name, "kind": target.kind,
            "az": round(float(az), 3), "alt": round(float(alt), 3),
            "mag": round(float(target.magnitude), 2),
            "size": target.major_arcmin,
            "blocked": bool(alt <= floor),
        })
    return result


# ---------------------------------------------------------------- траектория

def track(observer: ObserverProfile, target, landscape, horizon,
          start: dt.datetime, end: dt.datetime,
          step_minutes: float = 10.0) -> dict:
    """Путь объекта по небу за ночь с отметкой, где он закрыт участком."""
    grid = astro.time_grid(start, end, step_minutes)
    altitude, azimuth = astro.scan_altaz_series(observer, target, grid)
    altitude = np.atleast_1d(altitude)
    azimuth = np.atleast_1d(azimuth)
    mask = horizon.altitude_at(azimuth)
    tz = observer.tz
    points = []
    for index, moment in enumerate(grid):
        local = moment.utc_datetime().astimezone(tz)
        points.append({
            "t": local.isoformat(), "label": f"{local:%H:%M}",
            "az": round(float(azimuth[index]), 2),
            "alt": round(float(altitude[index]), 2),
            "blocked": bool(altitude[index] <= mask[index]),
            "hour": local.minute == 0,
        })
    return {"id": target.id, "name": target.name, "points": points}


def binocular_field(observer: ObserverProfile, binocular: BinocularProfile,
                    target, when: dt.datetime,
                    star_mag_limit: float | None = None) -> dict:
    """Содержимое поля зрения бинокля вокруг цели.

    Возвращает смещения объектов от центра поля в градусах — настоящие угловые
    расстояния. Масштабирование «для красоты» здесь недопустимо: смысл режима
    именно в том, чтобы человек заранее увидел, как объект соотносится с полем.
    """
    limit = star_mag_limit if star_mag_limit is not None else \
        binocular.limiting_magnitude(observer.bortle, 45.0, 0.0)
    limit = min(limit, 9.0)          # глубже Hipparcos всё равно не знает

    centre_alt, centre_az = astro.altaz_at(observer, target, when)
    radius = binocular.field_of_view_deg / 2.0
    margin = radius * 1.25

    hip, magnitude, _, _ = astro.star_table(min(limit, 8.0))
    altitude, azimuth = astro.star_altaz(observer, when, min(limit, 8.0))
    dx, dy = _offsets(centre_az, centre_alt, azimuth, altitude)
    near = (np.abs(dx) <= margin) & (np.abs(dy) <= margin) & (magnitude <= limit)

    stars = [{"x": round(float(a), 4), "y": round(float(b), 4),
              "mag": round(float(m), 2)}
             for a, b, m in zip(dx[near], dy[near], magnitude[near])]

    objects = []
    catalog = [t for t in catalog_service.catalog()
               if t.magnitude is not None and t.magnitude <= limit + 1.5]
    if catalog:
        obj_alt, obj_az = astro.fixed_altaz(observer, catalog, when)
        odx, ody = _offsets(centre_az, centre_alt, obj_az, obj_alt)
        for item, x, y in zip(catalog, odx, ody):
            if abs(x) <= margin and abs(y) <= margin:
                objects.append({
                    "id": item.id, "name": item.name, "kind": item.kind,
                    "x": round(float(x), 4), "y": round(float(y), 4),
                    "size": item.major_arcmin, "mag": item.magnitude})

    for solar in astro.solar_targets(when):
        try:
            alt, az = astro.altaz_at(observer, solar, when)
        except Exception:
            continue
        x, y = _offsets(centre_az, centre_alt, np.array([az]), np.array([alt]))
        if abs(float(x[0])) <= margin and abs(float(y[0])) <= margin:
            objects.append({"id": solar.id, "name": solar.name,
                            "kind": solar.kind, "x": round(float(x[0]), 4),
                            "y": round(float(y[0]), 4),
                            "size": solar.major_arcmin, "mag": solar.magnitude})

    return {
        "target": {"id": target.id, "name": target.name, "kind": target.kind,
                   "size": target.major_arcmin},
        "fov_deg": binocular.field_of_view_deg,
        "orientation": binocular.orientation,
        "centre": {"az": round(centre_az, 2), "alt": round(centre_alt, 2)},
        "limiting_mag": round(limit, 1),
        "stars": stars, "objects": objects,
    }


def _offsets(centre_az: float, centre_alt: float, azimuth, altitude):
    """Смещения точек от центра поля в градусах (гномоническая проекция).

    По оси X — вправо по азимуту, по оси Y — вверх по высоте. Вблизи центра
    поля искажения проекции пренебрежимо малы, а поле бинокля редко превышает
    десяток градусов.
    """
    az = np.radians(np.asarray(azimuth, dtype=float))
    alt = np.radians(np.asarray(altitude, dtype=float))
    az0, alt0 = math.radians(centre_az), math.radians(centre_alt)

    cos_c = (np.sin(alt0) * np.sin(alt)
             + np.cos(alt0) * np.cos(alt) * np.cos(az - az0))
    # Точки дальше 90° от центра поля проекция отображает так же, как близкие:
    # без этой отсечки в поле бинокля, наведённого на Жирафа, оказывался
    # Южный Треугольник. Такие точки помечаем бесконечностью и отбрасываем.
    behind = cos_c <= 1e-6
    safe = np.where(behind, 1.0, cos_c)
    x = np.cos(alt) * np.sin(az - az0) / safe
    y = (np.cos(alt0) * np.sin(alt)
         - np.sin(alt0) * np.cos(alt) * np.cos(az - az0)) / safe
    dx = np.degrees(np.arctan(x))
    dy = np.degrees(np.arctan(y))
    return (np.where(behind, np.inf, dx), np.where(behind, np.inf, dy))
