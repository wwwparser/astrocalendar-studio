"""Затмения Солнца и Луны.

Солнечное затмение — это покрытие Солнца Луной, поэтому геометрия та же, что в
`occultations`: наблюдатель видит затмение, если угловое расстояние между
центрами дисков меньше суммы их видимых радиусов. Разница только в том, что
нужны две полосы — полной (или кольцеобразной) фазы и частных фаз.

Лунное затмение геоцентрично: Луна входит в тень Земли, и видно его отовсюду,
где Луна над горизонтом. Моменты берём из `skyfield.eclipselib`.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
from skyfield import eclipselib
from skyfield.framelib import itrs

from ..core import (Event, body, earth, refine_minimum, separation_deg, timescale,
                    to_msk, ts_range)
from ..geo import RU_REGIONS, WORLD_REGIONS, bounds, describe, make_grid, region_coverage
from .occultations import MOON_RADIUS_KM, geodetic_to_itrs

SUN_RADIUS_KM = 695700.0

LUNAR_KIND_RU = {
    "penumbral": "Полутеневое лунное затмение",
    "partial": "Частное лунное затмение",
    "total": "Полное лунное затмение",
}


def solar_candidates(start: dt.datetime, end: dt.datetime,
                     limit_deg: float = 1.6) -> list[dict]:
    """Новолуния, в которых Солнце и Луна сходятся достаточно тесно."""
    ts = timescale()
    grid = ts_range(start - dt.timedelta(days=1), end + dt.timedelta(days=1), 30)
    sep = separation_deg(grid, body("moon"), body("sun"))
    found = []

    def sep_at(tt):
        return float(separation_deg(ts.tt_jd(tt), body("moon"), body("sun")))

    for i in range(1, len(sep) - 1):
        if not (sep[i] < sep[i - 1] and sep[i] <= sep[i + 1]):
            continue
        tt = refine_minimum(sep_at, grid[i - 1].tt, grid[i + 1].tt)
        t = ts.tt_jd(tt)
        when = to_msk(t)
        d = sep_at(tt)
        if d <= limit_deg and start <= when < end:
            found.append({"t": t, "when": when, "geo_sep": d})
    return found


def solar_bands(t_center, half_window_min: int = 260, step_min: int = 2,
                grid_step_deg: float = 2.0) -> dict:
    """Полосы частной и центральной фазы солнечного затмения по всей Земле."""
    ts = timescale()
    steps = int(2 * half_window_min / step_min) + 1
    times = ts.tt_jd(np.linspace(t_center.tt - half_window_min / 1440.0,
                                 t_center.tt + half_window_min / 1440.0, steps))
    e = earth()
    moon_pos = e.at(times).observe(body("moon")).apparent().position.km
    sun_pos = e.at(times).observe(body("sun")).apparent().position.km

    lat, lon = make_grid(grid_step_deg)
    site_itrs, up_itrs = geodetic_to_itrs(lat, lon)

    # Ось тени: прямая от Солнца через центр Луны. Наибольшее затмение — момент,
    # когда эта ось проходит ближе всего к центру Земли (стандартное определение).
    axis = moon_pos - sun_pos
    axis /= np.linalg.norm(axis, axis=0)
    along = np.einsum("ij,ij->j", moon_pos, axis)
    axis_miss = np.linalg.norm(moon_pos - axis * along, axis=0)
    greatest = int(np.argmin(axis_miss))

    partial = np.zeros(len(lat), dtype=bool)
    central = np.zeros(len(lat), dtype=bool)
    annular = np.zeros(len(lat), dtype=bool)
    max_obscuration = np.zeros(len(lat))
    peak_index = np.full(len(lat), -1, dtype=int)

    for k in range(steps):
        rotation = itrs.rotation_at(times[k])
        site = site_itrs @ rotation
        up = up_itrs @ rotation

        to_moon = moon_pos[:, k][None, :] - site
        to_sun = sun_pos[:, k][None, :] - site
        moon_range = np.linalg.norm(to_moon, axis=1)
        sun_range = np.linalg.norm(to_sun, axis=1)
        cos_sep = np.einsum("ij,ij->i", to_moon, to_sun) / (moon_range * sun_range)
        sep = np.arccos(np.clip(cos_sep, -1.0, 1.0))
        r_moon = np.arcsin(MOON_RADIUS_KM / moon_range)
        r_sun = np.arcsin(SUN_RADIUS_KM / sun_range)

        above = np.einsum("ij,ij->i", to_sun, up) > 0.0
        is_partial = (sep < r_moon + r_sun) & above
        is_central = (sep < np.abs(r_moon - r_sun)) & above

        partial |= is_partial
        central |= is_central
        annular |= is_central & (r_moon < r_sun)

        # грубая мера закрытия диска: 0 — касание, 1 — Солнце скрыто целиком
        coverage = np.clip((r_moon + r_sun - sep) / (2 * r_sun), 0.0, 1.0)
        coverage = np.where(above, coverage, 0.0)
        better = coverage > max_obscuration
        max_obscuration[better] = coverage[better]
        peak_index[better] = k

    return {"lat": lat, "lon": lon, "partial": partial, "central": central,
            "annular": annular, "obscuration": max_obscuration,
            "times": times, "peak_index": peak_index,
            "greatest_index": greatest, "axis_miss_km": float(axis_miss[greatest])}


def solar(start: dt.datetime, end: dt.datetime):
    events, report = [], []
    for cand in solar_candidates(start, end):
        bands = solar_bands(cand["t"])
        lat, lon = bands["lat"], bands["lon"]
        if not bands["partial"].any():
            continue

        # полоса полной фазы узкая: доля узлов в большом регионе всегда мала,
        # поэтому порог для неё отдельный и низкий
        central_ru = region_coverage(lat, lon, bands["central"], RU_REGIONS,
                                     min_fraction=0.01)
        central_world = region_coverage(lat, lon, bands["central"], WORLD_REGIONS,
                                        min_fraction=0.01)
        partial_ru = region_coverage(lat, lon, bands["partial"], RU_REGIONS,
                                     min_fraction=0.10)

        if bands["central"].any():
            kind = ("Кольцеобразное солнечное затмение" if bands["annular"].any()
                    else "Полное солнечное затмение")
        else:
            kind = "Частное солнечное затмение"

        parts = [kind]
        if bands["central"].any():
            names = ", ".join(c[0] for c in (central_ru[:2] + central_world[:3]))
            parts.append(f"полоса полной фазы проходит через {names}"
                         if names else "полоса полной фазы проходит по океану")
        if partial_ru:
            parts.append("частные фазы видны " + describe(partial_ru[:3]))

        peak_time = bands["times"][bands["greatest_index"]]

        events.append(Event(
            when=to_msk(peak_time),
            text=", ".join(parts),
            category="eclipse",
            computed=(f"минимум геоцентрического расстояния Луна–Солнце "
                      f"{cand['geo_sep']:.3f}°; полосы найдены сеткой 2° по всей Земле: "
                      f"частные фазы в {int(bands['partial'].sum())} узлах, "
                      f"центральная фаза в {int(bands['central'].sum())}; "
                      f"наибольшее затмение — минимум расстояния от центра Земли до "
                      f"оси тени, {bands['axis_miss_km']:.0f} км"),
            sources=["Skyfield/DE440s", "геометрия затмения на сетке ITRS"],
            precision="minute",
            meta={"partial_extent": bounds(lat, lon, bands["partial"]),
                  "central_extent": bounds(lat, lon, bands["central"])},
        ))
        report.append({"when": cand["when"], "kind": kind,
                       "central_ru": central_ru, "central_world": central_world,
                       "partial_ru": partial_ru,
                       "central_extent": bounds(lat, lon, bands["central"]),
                       "partial_extent": bounds(lat, lon, bands["partial"])})
    return events, report


def lunar_contacts(t_max, half_window_min: int = 300, step_min: int = 1):
    """Моменты, когда Луна находится в полутени и в тени Земли.

    Ось тени направлена от Солнца через центр Земли, поэтому «центр тени» на
    небе — точка, противоположная Солнцу. Радиусы тени считаем по классическим
    формулам с поправкой Данжона (множитель 1.02 за протяжённость атмосферы).
    """
    ts = timescale()
    steps = int(2 * half_window_min / step_min) + 1
    times = ts.tt_jd(np.linspace(t_max.tt - half_window_min / 1440.0,
                                 t_max.tt + half_window_min / 1440.0, steps))
    e = earth()
    moon = e.at(times).observe(body("moon")).apparent()
    sun = e.at(times).observe(body("sun")).apparent()
    moon_vec = moon.position.km
    anti_sun = -sun.position.km

    d_moon = np.linalg.norm(moon_vec, axis=0)
    d_sun = np.linalg.norm(sun.position.km, axis=0)
    cos_sep = np.einsum("ij,ij->j", moon_vec, anti_sun) / (
        d_moon * np.linalg.norm(anti_sun, axis=0))
    sep = np.arccos(np.clip(cos_sep, -1.0, 1.0))

    earth_radius_km = 6378.137
    parallax_moon = np.arcsin(earth_radius_km / d_moon)
    parallax_sun = np.arcsin(earth_radius_km / d_sun)
    sun_radius = np.arcsin(SUN_RADIUS_KM / d_sun)
    umbra = 1.02 * (parallax_moon + parallax_sun - sun_radius)
    penumbra = 1.02 * (parallax_moon + parallax_sun + sun_radius)
    moon_radius = np.arcsin(MOON_RADIUS_KM / d_moon)

    in_penumbra = sep < penumbra + moon_radius
    in_umbra = sep < umbra + moon_radius
    return times, in_penumbra, in_umbra


def lunar_visibility(grid, phase_mask, twilight_limit: float = -3.0):
    """Где на Земле затменную Луну видно над горизонтом на достаточно тёмном небе."""
    idx = np.where(phase_mask)[0]
    sample = grid[idx[np.linspace(0, len(idx) - 1, min(len(idx), 12)).astype(int)]]
    lat, lon = make_grid(2.0)
    site_itrs, up_itrs = geodetic_to_itrs(lat, lon)
    e = earth()
    moon_pos = e.at(sample).observe(body("moon")).apparent().position.km
    sun_pos = e.at(sample).observe(body("sun")).apparent().position.km

    seen = np.zeros(len(lat), dtype=bool)
    for k in range(len(sample)):
        rotation = itrs.rotation_at(sample[k])
        site = site_itrs @ rotation
        up = up_itrs @ rotation
        to_moon = moon_pos[:, k][None, :] - site
        to_sun = sun_pos[:, k][None, :] - site
        moon_up = np.einsum("ij,ij->i", to_moon, up) / np.linalg.norm(to_moon, axis=1)
        sun_up = np.einsum("ij,ij->i", to_sun, up) / np.linalg.norm(to_sun, axis=1)
        seen |= (moon_up > 0.0) & (np.degrees(np.arcsin(sun_up)) < twilight_limit)
    return lat, lon, seen


def lunar(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Лунные затмения: момент максимума и какие фазы реально видны из Москвы."""
    from ..core import observer, planets

    ts = timescale()
    t0, t1 = ts.from_datetime(start), ts.from_datetime(end)
    times, kinds, _details = eclipselib.lunar_eclipses(t0, t1, planets())
    site = observer()
    out = []
    for i, t in enumerate(times):
        when = to_msk(t)
        if not (start <= when < end):
            continue
        kind = eclipselib.LUNAR_ECLIPSES[int(kinds[i])].lower()

        grid, in_pen, in_umb = lunar_contacts(t)
        phase = in_umb if in_umb.any() else in_pen
        idx = np.where(phase)[0]
        phase_start, phase_end = grid[int(idx[0])], grid[int(idx[-1])]

        alt = site.at(grid).observe(body("moon")).apparent().altaz()[0].degrees
        sun_alt = site.at(grid).observe(body("sun")).apparent().altaz()[0].degrees
        visible = phase & (alt > 0) & (sun_alt < -6)
        twilight = phase & (alt > 0) & (sun_alt >= -6) & (sun_alt < 0)

        lat, lon, seen = lunar_visibility(grid, phase)
        ru = region_coverage(lat, lon, seen, RU_REGIONS, min_fraction=0.10)
        world = region_coverage(lat, lon, seen, WORLD_REGIONS, min_fraction=0.20)

        if visible.any():
            v = np.where(visible)[0]
            where = (f"видимое {describe(ru[:3]) if ru else 'в России'} "
                     f"с {to_msk(grid[int(v[0])]):%H:%M} до "
                     f"{to_msk(grid[int(v[-1])]):%H:%M}")
            if int(v[0]) > int(idx[0]) or int(v[-1]) < int(idx[-1]):
                where += " (Луна заходит до конца затмения)"
        elif twilight.any():
            v = np.where(twilight)[0]
            where = (f"видимое {describe(ru[:3]) if ru else 'в России'} на рассвете, "
                     f"низко над западной частью горизонта, около "
                     f"{to_msk(grid[int(v[0])]):%H:%M}")
        elif ru:
            where = "видимое " + describe(ru[:3]) + ", в Москве Луна уже под горизонтом"
        elif world:
            where = "видимое в регионах: " + ", ".join(r[0] for r in world[:3])
        else:
            where = "с территории России не видно"

        max_alt = float(alt[len(alt) // 2])
        out.append(Event(
            when=when,
            text=f"{LUNAR_KIND_RU.get(kind, 'Лунное затмение')}, {where}",
            category="eclipse",
            computed=(f"eclipselib.lunar_eclipses, тип «{kind}»; максимум "
                      f"{t.utc_strftime('%Y-%m-%d %H:%M UTC')}; "
                      f"{'теневая' if in_umb.any() else 'полутеневая'} фаза "
                      f"{to_msk(phase_start):%d.%m %H:%M}–{to_msk(phase_end):%H:%M} МСК; "
                      f"высота Луны над Москвой в максимуме {max_alt:.0f}°"),
            sources=["Skyfield/DE440s (eclipselib)",
                     "радиусы тени по формулам с поправкой Данжона"],
            precision="minute",
        ))
    return out


def all_events(start: dt.datetime, end: dt.datetime):
    solar_events, report = solar(start, end)
    return solar_events + lunar(start, end), report
