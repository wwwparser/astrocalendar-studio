"""Покрытия планет Луной: поиск события и расчёт полосы видимости.

Геоцентрическое расстояние Луна–планета меньше ~1.25° означает, что где-то на
Земле планета скрывается за лунным диском: параллакс Луны доходит до ~1°.

Полосу видимости считаем геометрически, а не перебором городов. Наблюдатель в
точке O видит покрытие, когда угол между направлениями O→Луна и O→планета
меньше видимого радиуса лунного диска. Проверяем это условие на регулярной
сетке по всей Земле для каждого момента окна: узлы сетки переводим из ITRS в
ICRF матрицей вращения Земли, дальше всё считается векторно в numpy — Skyfield
вызывается один раз на весь массив времён, а не на каждую площадку.

Точность подхода — доли угловой минуты по границе полосы: не учитываются
дифракция, рельеф лимба Луны и суточная аберрация. Для формулировки «видимое
на Юге Европейской части России» этого достаточно с большим запасом.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
from skyfield.framelib import itrs

from ..core import (Event, body, constellation_at, earth, refine_minimum,
                    separation_deg, timescale, to_msk, ts_range)
from ..fmt import magnitude, phase_fraction, ru_constellation
from ..geo import RU_REGIONS, WORLD_REGIONS, bounds, describe, make_grid, region_coverage

MOON_RADIUS_KM = 1737.4
EARTH_A_KM = 6378.137
EARTH_F = 1.0 / 298.257223563

PLANETS = ("mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune")


def geodetic_to_itrs(lat_deg, lon_deg, height_km=0.0):
    """Координаты узлов сетки в ITRS (км) и локальная вертикаль (единичный вектор)."""
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    e2 = EARTH_F * (2.0 - EARTH_F)
    n = EARTH_A_KM / np.sqrt(1.0 - e2 * np.sin(lat) ** 2)
    x = (n + height_km) * np.cos(lat) * np.cos(lon)
    y = (n + height_km) * np.cos(lat) * np.sin(lon)
    z = (n * (1.0 - e2) + height_km) * np.sin(lat)
    position = np.stack([x, y, z], axis=1)
    up = np.stack([np.cos(lat) * np.cos(lon),
                   np.cos(lat) * np.sin(lon),
                   np.sin(lat)], axis=1)
    return position, up


def find_candidates(start: dt.datetime, end: dt.datetime,
                    geo_limit_deg: float = 1.30) -> list[dict]:
    """Минимумы геоцентрического расстояния Луна–планета ближе geo_limit."""
    ts = timescale()
    grid = ts_range(start - dt.timedelta(hours=12), end + dt.timedelta(hours=12), 20)
    moon = body("moon")
    found = []
    for name in PLANETS:
        target = body(name)
        sep = separation_deg(grid, moon, target)
        if sep.min() > geo_limit_deg + 1.0:
            continue

        def sep_at(tt, target=target):
            return float(separation_deg(ts.tt_jd(tt), moon, target))

        for i in range(1, len(sep) - 1):
            if not (sep[i] < sep[i - 1] and sep[i] <= sep[i + 1]):
                continue
            tt = refine_minimum(sep_at, grid[i - 1].tt, grid[i + 1].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            d = sep_at(tt)
            if d <= geo_limit_deg and start <= when < end:
                found.append({"planet": name, "t": t, "when": when, "geo_sep": d})
    return found


STAR_DISTANCE_KM = 1.0e14      # «бесконечность» для звезды: лучи практически параллельны


def visibility_band(t_center, planet=None, half_window_min: int = 240,
                    step_min: int = 2, grid_step_deg: float = 2.0,
                    star=None) -> dict:
    """Где на Земле планета скрывается за диском Луны.

    Возвращает сетку, маску видимости, времена начала и конца для каждого узла
    и высоту Солнца в середине явления.
    """
    ts = timescale()
    steps = int(2 * half_window_min / step_min) + 1
    times = ts.tt_jd(np.linspace(t_center.tt - half_window_min / 1440.0,
                                 t_center.tt + half_window_min / 1440.0, steps))

    e = earth()
    moon_pos = e.at(times).observe(body("moon")).apparent().position.km        # 3 × N
    if star is not None:
        # звезда бесконечно далека: берём единичное направление и уносим точку
        # вдоль него, чтобы дальше работала та же геометрия, что и для планеты
        direction = e.at(times).observe(star).apparent().position.km
        direction = direction / np.linalg.norm(direction, axis=0)
        planet_pos = direction * STAR_DISTANCE_KM
    else:
        planet_pos = e.at(times).observe(body(planet)).apparent().position.km
    sun_pos = e.at(times).observe(body("sun")).apparent().position.km

    lat, lon = make_grid(grid_step_deg)
    site_itrs, up_itrs = geodetic_to_itrs(lat, lon)

    occulted_any = np.zeros(len(lat), dtype=bool)
    first_idx = np.full(len(lat), -1, dtype=int)
    last_idx = np.full(len(lat), -1, dtype=int)
    sun_alt_at_event = np.full(len(lat), np.nan)

    for k in range(steps):
        rotation = itrs.rotation_at(times[k])          # ICRF → ITRS
        site = site_itrs @ rotation                     # ITRS → ICRF (умножение справа)
        up = up_itrs @ rotation

        to_moon = moon_pos[:, k][None, :] - site
        to_planet = planet_pos[:, k][None, :] - site
        to_sun = sun_pos[:, k][None, :] - site

        moon_range = np.linalg.norm(to_moon, axis=1)
        planet_range = np.linalg.norm(to_planet, axis=1)
        cos_sep = np.einsum("ij,ij->i", to_moon, to_planet) / (moon_range * planet_range)
        separation = np.arccos(np.clip(cos_sep, -1.0, 1.0))
        moon_radius = np.arcsin(MOON_RADIUS_KM / moon_range)

        above = np.einsum("ij,ij->i", to_planet, up) > 0.0
        hidden = (separation < moon_radius) & above

        new = hidden & (first_idx < 0)
        first_idx[new] = k
        last_idx[hidden] = k
        occulted_any |= hidden
        if new.any():
            sun_elev = np.degrees(np.arcsin(
                np.einsum("ij,ij->i", to_sun, up) / np.linalg.norm(to_sun, axis=1)))
            sun_alt_at_event[new] = sun_elev[new]

    return {"lat": lat, "lon": lon, "mask": occulted_any, "times": times,
            "first_idx": first_idx, "last_idx": last_idx,
            "sun_alt": sun_alt_at_event}


def russian_mask(lat, lon, mask, regions_hit):
    """Часть полосы, попавшая в перечисленные регионы России."""
    if not regions_hit:
        return mask
    names = {r[0] for r in regions_hit}
    box = np.zeros_like(mask)
    for entry in RU_REGIONS:
        if entry[0] in names:
            _, _, lat_lo, lat_hi, lon_lo, lon_hi = entry
            box |= (lat >= lat_lo) & (lat <= lat_hi) & (lon >= lon_lo) & (lon <= lon_hi)
    return mask & box


def daytime_over_russia(band, lat, lon, mask, regions_hit) -> bool:
    """Светло ли в среднем там, где покрытие видно из России.

    Оставлено для совместимости и для грубой оценки. Одной меткой на всю
    страну пользоваться нельзя: полоса тянется на тысячи километров, и пока в
    Якутии полдень, над Новой Землёй глубокая ночь.
    """
    local = russian_mask(lat, lon, mask, regions_hit)
    sun_alt = band["sun_alt"][local & ~np.isnan(band["sun_alt"])]
    return bool(len(sun_alt)) and float(np.nanmedian(sun_alt)) > -6.0


def sky_by_region(band, lat, lon, regions_hit) -> list[tuple]:
    """Высота Солнца в каждом регионе полосы.

    Возвращает (имя, предложная форма, высота Солнца, состояние неба).
    Именно из-за отсутствия такой разбивки покрытие Альционы 28 октября было
    целиком помечено как дневное, хотя над Новой Землёй Солнце на 11° под
    горизонтом и это полноценное ночное событие.
    """
    sun = band["sun_alt"]
    out = []
    for name, phrase, _share in regions_hit:
        entry = next((r for r in RU_REGIONS if r[0] == name), None)
        if entry is None:
            continue
        _n, _p, lat_lo, lat_hi, lon_lo, lon_hi = entry
        box = ((lat >= lat_lo) & (lat <= lat_hi) &
               (lon >= lon_lo) & (lon <= lon_hi) & band["mask"] & ~np.isnan(sun))
        if not box.any():
            continue
        altitude = float(np.nanmedian(sun[box]))
        # Четыре градации, а не две: −3° и −11° — это очень разное небо, и
        # объединять их в «сумерки» значит терять именно ту информацию, ради
        # которой наблюдатель читает строку.
        if altitude > -0.5:
            state = "day"
        elif altitude > -6.0:
            state = "light"
        elif altitude > -12.0:
            state = "twilight"
        else:
            state = "night"
        out.append((name, phrase, altitude, state))
    return out


SKY_WORDS = {"night": "ночью", "twilight": "в сумерках",
             "light": "в светлых сумерках", "day": "днём"}


def describe_sky(by_region: list[tuple]) -> str:
    """«ночью — на Новой Земле…, днём — в Якутии» одной фразой."""
    if not by_region:
        return ""
    groups: dict[str, list[str]] = {}
    for _name, phrase, _altitude, state in by_region:
        groups.setdefault(state, []).append(phrase)
    parts = []
    for state in ("night", "twilight", "light", "day"):
        places = groups.get(state)
        if not places:
            continue
        listing = (places[0] if len(places) == 1
                   else ", ".join(places[:-1]) + " и " + places[-1])
        parts.append(f"{SKY_WORDS[state]} {listing}")
    return "; ".join(parts)


def star_candidates(start: dt.datetime, end: dt.datetime,
                    geo_limit_deg: float = 1.30,
                    star_mag_limit: float = 3.5) -> list[dict]:
    """Тесные прохождения Луны у ярких звёзд — кандидаты в покрытия."""
    from skyfield.api import Star

    from ..catalogs import STAR_NAMES_RU, angular_distance_deg, bright_stars

    ts = timescale()
    grid = ts_range(start - dt.timedelta(hours=12), end + dt.timedelta(hours=12), 20)
    moon_ra, moon_dec, _ = earth().at(grid).observe(body("moon")).apparent().radec()
    stars = bright_stars(mag_limit=star_mag_limit)
    stars = stars[np.abs(stars.dec_degrees) < 32.0]

    found = []
    for _, row in stars.iterrows():
        d = angular_distance_deg(moon_ra.degrees, moon_dec.degrees,
                                 row.ra_degrees, row.dec_degrees)
        if d.min() > geo_limit_deg:
            continue
        target = Star(ra_hours=float(row.ra_degrees) / 15.0,
                      dec_degrees=float(row.dec_degrees))

        def sep_at(tt, target=target):
            return float(separation_deg(ts.tt_jd(tt), body("moon"), target))

        for i in range(1, len(d) - 1):
            if not (d[i] < d[i - 1] and d[i] <= d[i + 1]):
                continue
            tt = refine_minimum(sep_at, grid[i - 1].tt, grid[i + 1].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            best = sep_at(tt)
            if best <= geo_limit_deg and start <= when < end:
                found.append({"star": target, "hip": int(row.hip),
                              "name": STAR_NAMES_RU.get(int(row.hip)),
                              "mag": float(row.magnitude),
                              "t": t, "when": when, "geo_sep": best})
    return found


def build_stars(start: dt.datetime, end: dt.datetime):
    """Покрытия ярких звёзд Луной с полосой видимости."""
    from .moon import illum_and_waxing

    events, report = [], []
    for cand in star_candidates(start, end):
        band = visibility_band(cand["t"], star=cand["star"])
        lat, lon, mask = band["lat"], band["lon"], band["mask"]
        if not mask.any():
            continue
        ru = region_coverage(lat, lon, mask, RU_REGIONS)
        world = region_coverage(lat, lon, mask, WORLD_REGIONS)
        # Покрытий звёзд Луной за месяц бывает много, и почти все проходят мимо
        # России. В календарь идут только те, что видны с её территории —
        # остальные остаются в протоколе.
        if not ru:
            report.append({"planet": f"HIP {cand['hip']}", "when": cand["when"],
                           "geo_sep": cand["geo_sep"], "ru": ru, "world": world,
                           "extent": bounds(lat, lon, mask), "daytime": False})
            continue

        frac, waxing = illum_and_waxing(cand["t"])
        const = ru_constellation(constellation_at()(
            earth().at(cand["t"]).observe(cand["star"]).apparent()))
        label = (f"звезды {cand['name']}" if cand["name"]
                 else f"звезды HIP {cand['hip']}")
        sky = sky_by_region(band, lat, lon, ru)
        where = "видимое " + (describe_sky(sky) if sky else describe(ru))

        daytime = daytime_over_russia(band, lat, lon, mask, ru)

        text = (f"Покрытие {label} ({magnitude(cand['mag'])}) Луной "
                f"({phase_fraction(frac, waxing)}) в созвездии {const}, {where}")

        extent = bounds(lat, lon, mask)
        events.append(Event(
            when=cand["when"], text=text, category="occultation",
            computed=(f"минимум геоцентрического расстояния Луна–HIP {cand['hip']}: "
                      f"{cand['geo_sep']:.3f}°; полоса найдена сеткой 2° по всей Земле "
                      f"({extent.get('points', 0)} узлов)"),
            sources=["Skyfield/DE440s", "Hipparcos", "геометрия покрытия на сетке ITRS"],
            precision="minute",
            meta={"hip": cand["hip"], "band": extent},
        ))
        report.append({"planet": f"HIP {cand['hip']}", "when": cand["when"],
                       "geo_sep": cand["geo_sep"], "ru": ru, "world": world,
                       "extent": extent, "daytime": daytime})
    return events, report


def build(start: dt.datetime, end: dt.datetime):
    from ..magnitudes import planet_magnitude
    from .moon import PLANET_GEN, illum_and_waxing

    events, report = [], []
    for cand in find_candidates(start, end):
        t, name = cand["t"], cand["planet"]
        band = visibility_band(t, name)
        lat, lon, mask = band["lat"], band["lon"], band["mask"]

        ru = region_coverage(lat, lon, mask, RU_REGIONS)
        world = region_coverage(lat, lon, mask, WORLD_REGIONS)

        frac, waxing = illum_and_waxing(t)
        mag = planet_magnitude(name, t)
        const = ru_constellation(constellation_at()(
            earth().at(t).observe(body(name)).apparent()))

        sky = sky_by_region(band, lat, lon, ru)
        if ru:
            where = "видимое " + describe_sky(sky) if sky else "видимое " + describe(ru)
        elif world:
            where = "видимое в регионах: " + ", ".join(r[0] for r in world[:3])
        else:
            where = "не наблюдаемое с поверхности Земли"

        daytime = daytime_over_russia(band, lat, lon, mask, ru)

        text = (f"Покрытие {PLANET_GEN[name]} ({magnitude(mag)}) Луной "
                f"({phase_fraction(frac, waxing)}) {where}")

        extent = bounds(lat, lon, mask)
        events.append(Event(
            when=cand["when"], text=text, category="occultation",
            computed=(f"минимум геоцентрического расстояния {cand['geo_sep']:.3f}°; "
                      f"полоса найдена сеткой 2° по всей Земле "
                      f"({extent.get('points', 0)} узлов в полосе, широты "
                      f"{extent.get('lat_min', 0):.0f}…{extent.get('lat_max', 0):.0f}°)"),
            sources=["Skyfield/DE440s", "геометрия покрытия на сетке ITRS"],
            precision="minute",
            notes=f"созвездие {const}",
            meta={"planet": name, "band": extent},
        ))
        report.append({"planet": name, "when": cand["when"], "geo_sep": cand["geo_sep"],
                       "ru": ru, "world": world, "extent": extent,
                       "daytime": daytime})
    return events, report
