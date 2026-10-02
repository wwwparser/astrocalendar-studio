"""События Луны: фазы, перигей/апогей, сближения с планетами."""
from __future__ import annotations

import datetime as dt

import numpy as np
from skyfield import almanac

from ..core import (Event, body, constellation_at, earth, local_minima, planets,
                    refine_minimum, separation_deg, timescale, to_msk, ts_range)
from ..apparent import moon_label, planet_label, angular_diameter_arcsec, format_diameter
from ..encounters import observing_time, direction_at
from ..fmt import angle_deg, distance_km, ru_constellation

# Формулировки как в AstroAlert: "в фазе новолуние", но "в фазе последней четверти"
PHASE_NAMES = {
    0: "новолуние",
    1: "первой четверти",
    2: "полнолуние",
    3: "последней четверти",
}

PLANET_GEN = {
    "mercury": "Меркурия", "venus": "Венеры", "mars": "Марса", "jupiter": "Юпитера",
    "saturn": "Сатурна", "uranus": "Урана", "neptune": "Нептуна",
}


def illum_and_waxing(t):
    """Доля освещённой поверхности Луны и признак растущей фазы."""
    eph = planets()
    frac = float(almanac.fraction_illuminated(eph, "moon", t))
    waxing = bool(almanac.moon_phase(eph, t).degrees < 180.0)
    return frac, waxing


def _moon_constellation(t) -> str:
    return ru_constellation(constellation_at()(
        earth().at(t).observe(body("moon")).apparent()))


def phases(start: dt.datetime, end: dt.datetime) -> list[Event]:
    ts = timescale()
    times, which = almanac.find_discrete(ts.from_datetime(start), ts.from_datetime(end),
                                         almanac.moon_phases(planets()))
    out = []
    for t, w in zip(times, which):
        out.append(Event(
            when=to_msk(t),
            text=(f"Луна в фазе {PHASE_NAMES[int(w)]} (D={format_diameter(angular_diameter_arcsec('moon', t))}) "
                  f"в созвездии {_moon_constellation(t)}"),
            category="moon",
            computed=("almanac.moon_phases по DE440s, точный момент "
                      f"{t.utc_strftime('%Y-%m-%d %H:%M:%S UTC')}"),
            sources=["Skyfield/DE440s"],
            precision="hour",
        ))
    return out


def apsides(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Перигей и апогей — экстремумы геоцентрического расстояния до Луны."""
    ts = timescale()
    grid = ts_range(start - dt.timedelta(days=1), end + dt.timedelta(days=1), 60)
    dist = earth().at(grid).observe(body("moon")).distance().km

    def dist_at(tt: float) -> float:
        return float(earth().at(ts.tt_jd(tt)).observe(body("moon")).distance().km)

    out = []
    for i in range(1, len(dist) - 1):
        is_min = dist[i] < dist[i - 1] and dist[i] <= dist[i + 1]
        is_max = dist[i] > dist[i - 1] and dist[i] >= dist[i + 1]
        if not (is_min or is_max):
            continue
        func = dist_at if is_min else (lambda tt: -dist_at(tt))
        tt = refine_minimum(func, grid[i - 1].tt, grid[i + 1].tt)
        t = ts.tt_jd(tt)
        when = to_msk(t)
        if not (start <= when < end):
            continue
        frac, waxing = illum_and_waxing(t)
        km = dist_at(tt)
        out.append(Event(
            when=when,
            text=(f"Луна ({moon_label(t, frac, waxing)}) в "
                  f"{'перигее' if is_min else 'апогее'} своей орбиты "
                  f"на расстоянии {distance_km(km)} км от Земли"),
            category="moon",
            computed=f"экстремум расстояния Земля–Луна (центр–центр): {km:.0f} км",
            sources=["Skyfield/DE440s"],
            precision="hour",
        ))
    return out


def direction(t, target, reference) -> str:
    """Смещение target относительно reference: севернее/южнее/восточнее/западнее."""
    a_ra, a_dec, _ = earth().at(t).observe(target).apparent().radec()
    b_ra, b_dec, _ = earth().at(t).observe(reference).apparent().radec()
    d_dec = a_dec.degrees - b_dec.degrees
    d_ra = (a_ra.degrees - b_ra.degrees + 180.0) % 360.0 - 180.0
    d_ra *= np.cos(np.radians((a_dec.degrees + b_dec.degrees) / 2.0))
    if abs(d_ra) >= abs(d_dec):
        return "восточнее" if d_ra > 0 else "западнее"
    return "севернее" if d_dec > 0 else "южнее"


def conjunctions_with_planets(start: dt.datetime, end: dt.datetime,
                              limit_deg: float = 7.5,
                              skip_below_deg: float = 0.0) -> list[Event]:
    """Минимумы геоцентрического углового расстояния Луна–планета.

    По умолчанию тесные сближения не теряются: покрытие может проходить
    вне России или днём. Геоцентрический минимум сохраняется отдельно.
    """
    from ..magnitudes import planet_magnitude

    ts = timescale()
    grid = ts_range(start - dt.timedelta(hours=12), end + dt.timedelta(hours=12), 30)
    moon = body("moon")
    out: list[Event] = []

    for name in PLANET_GEN:
        target = body(name)
        sep = separation_deg(grid, moon, target)

        def sep_at(tt, target=target):
            return float(separation_deg(ts.tt_jd(tt), moon, target))

        for i in local_minima(grid, sep):
            if sep[i] > limit_deg + 2:
                continue
            tt = refine_minimum(sep_at, grid[i - 1].tt, grid[i + 1].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            d = sep_at(tt)
            if not (start <= when < end) or d > limit_deg or d < skip_below_deg:
                continue
            minimum_when, minimum_sep = when, d
            visible = observing_time(when, moon, target, limit_deg)
            if visible is None:
                continue
            t, site, city = visible
            when = to_msk(t)
            if not start <= when < end:
                continue
            d = float(site.at(t).observe(moon).apparent().separation_from(site.at(t).observe(target).apparent()).degrees)
            frac, waxing = illum_and_waxing(t)
            mag = planet_magnitude(name, t)
            const = ru_constellation(constellation_at()(
                earth().at(t).observe(target).apparent()))
            out.append(Event(
                when=when,
                text=(f"Луна ({moon_label(t, frac, waxing)}) проходит в "
                      f"{angle_deg(d)} {direction_at(t, moon, target, site)} "
                      f"{PLANET_GEN[name]} ({planet_label(name, t, mag)}) "
                      f"в созвездии {const} ({city})"),
                category="moon",
                computed=f"геоцентрический минимум {minimum_sep:.3f}° в {minimum_when.isoformat()}; наблюдательное время для {city}, топоцентрическое разделение {d:.3f}°",
                meta={"planet": name, "time_semantics": "observing", "city": city, "minimum_when": minimum_when.isoformat(), "minimum_sep_deg": minimum_sep, "sep_deg": d},
                sources=["Skyfield/DE440s"],
                precision="minute",
            ))
    return out


def conjunctions_with_stars(start: dt.datetime, end: dt.datetime,
                            limit_deg: float = 4.0,
                            star_mag_limit: float = 2.6,
                            skip_below_deg: float = 0.0) -> list[Event]:
    """Сближения Луны с яркими звёздами (только те, что Луна вообще может задеть).

    Прохождения теснее skip_below_deg отдаём модулю покрытий: там считается
    полоса видимости.
    """
    from skyfield.api import Star

    from ..catalogs import STAR_NAMES_RU, angular_distance_deg, bright_stars

    ts = timescale()
    grid = ts_range(start - dt.timedelta(hours=12), end + dt.timedelta(hours=12), 30)
    moon_ra, moon_dec, _ = earth().at(grid).observe(body("moon")).apparent().radec()
    moon_ra = moon_ra.degrees
    moon_dec = moon_dec.degrees

    stars = bright_stars(mag_limit=star_mag_limit)
    # Луна не отходит от эклиптики дальше ~6°, поэтому далёкие от неё звёзды
    # можно даже не проверять
    stars = stars[np.abs(stars.dec_degrees) < 32.0]

    out: list[Event] = []
    for _, star_row in stars.iterrows():
        d = angular_distance_deg(moon_ra, moon_dec,
                                 star_row.ra_degrees, star_row.dec_degrees)
        if d.min() > limit_deg:
            continue
        target = Star(ra_hours=float(star_row.ra_degrees) / 15.0,
                      dec_degrees=float(star_row.dec_degrees))

        def sep_at(tt, target=target):
            return float(separation_deg(ts.tt_jd(tt), body("moon"), target))

        for i in local_minima(grid, d):
            if d[i] > limit_deg:
                continue
            tt = refine_minimum(sep_at, grid[max(i - 1, 0)].tt,
                                grid[min(i + 1, len(grid) - 1)].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            best = sep_at(tt)
            if not (start <= when < end) or best > limit_deg or best < skip_below_deg:
                continue
            hip = int(star_row.hip)
            name = STAR_NAMES_RU.get(hip)
            if name is None:
                continue  # безымянные слабые звёзды оставляем в каталоге покрытий
            label = (f"звезды {name} (V={star_row.magnitude:+.1f}m)".replace(".", ",")
                     if name else
                     f"звезды HIP {hip} (V={star_row.magnitude:+.1f}m)".replace(".", ","))
            minimum_when, minimum_sep = when, best
            visible = observing_time(when, body("moon"), target, limit_deg + 1.5, min_altitude=2.0)
            if visible is None:
                continue
            t, site, city = visible
            when = to_msk(t)
            if not start <= when < end:
                continue
            best = float(site.at(t).observe(body("moon")).apparent().separation_from(site.at(t).observe(target).apparent()).degrees)
            frac, waxing = illum_and_waxing(t)
            const = ru_constellation(constellation_at()(
                earth().at(t).observe(target).apparent()))
            out.append(Event(
                when=when,
                text=(f"Луна ({moon_label(t, frac, waxing)}) проходит в "
                      f"{angle_deg(best)} {direction_at(t, body('moon'), target, site)} "
                      f"{label} в созвездии {const} ({city})"),
                category="moon",
                computed=(f"минимум геоцентрического расстояния Луна–HIP {hip}: "
                          f"{minimum_sep:.3f}° в {minimum_when.isoformat()}; наблюдательное время для {city}, топоцентрическое разделение {best:.3f}°"),
                sources=["Skyfield/DE440s", "Hipparcos"],
                precision="minute",
                meta={"hip": hip, "time_semantics": "observing", "city": city, "minimum_when": minimum_when.isoformat(), "minimum_sep_deg": minimum_sep, "sep_deg": best},
            ))
    return out


def conjunctions_with_deep_sky(start: dt.datetime, end: dt.datetime,
                               limit_deg: float = 5.0,
                               object_mag_limit: float = 6.5) -> list[Event]:
    """Сближения Луны с яркими объектами глубокого космоса.

    Луна регулярно проходит у Плеяд и Ясель — это заметно невооружённым глазом
    и попадает во все обзорные календари. Ищем только объекты у эклиптики:
    остальных Луна коснуться не может.
    """
    from skyfield.api import Star

    from ..catalogs import (angular_distance_deg, deep_sky, dso_common_name,
                            is_messier)

    ts = timescale()
    grid = ts_range(start - dt.timedelta(hours=12), end + dt.timedelta(hours=12), 30)
    moon_ra, moon_dec, _ = earth().at(grid).observe(body("moon")).apparent().radec()
    moon_ra, moon_dec = moon_ra.degrees, moon_dec.degrees

    catalog = deep_sky(mag_limit=object_mag_limit)
    catalog = catalog[np.abs(catalog.dec_degrees) < 32.0]
    # У эклиптики много слабых скоплений, и Луна каждый месяц проходит мимо
    # десятка из них. В календаре осмысленны только те, что видны глазом или
    # в бинокль: объекты Мессье и всё ярче 4.5m.
    catalog = catalog[catalog.messier.notna() | (catalog.mag <= 4.5)]

    out: list[Event] = []
    for _, obj in catalog.iterrows():
        distance = angular_distance_deg(moon_ra, moon_dec,
                                        obj.ra_degrees, obj.dec_degrees)
        if distance.min() > limit_deg:
            continue
        target = Star(ra_hours=float(obj.ra_degrees) / 15.0,
                      dec_degrees=float(obj.dec_degrees))

        def sep_at(tt, target=target):
            return float(separation_deg(ts.tt_jd(tt), body("moon"), target))

        for i in local_minima(grid, distance):
            if distance[i] > limit_deg:
                continue
            tt = refine_minimum(sep_at, grid[max(i - 1, 0)].tt,
                                grid[min(i + 1, len(grid) - 1)].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            best = sep_at(tt)
            if not (start <= when < end) or best > limit_deg:
                continue
            minimum_when, minimum_sep = when, best
            visible = observing_time(when, body("moon"), target, limit_deg + 1.5)
            if visible is None:
                continue
            t, site, city = visible
            when = to_msk(t)
            if not start <= when < end:
                continue
            best = float(site.at(t).observe(body("moon")).apparent().separation_from(
                site.at(t).observe(target).apparent()).degrees)
            frac, waxing = illum_and_waxing(t)
            label = obj.messier if isinstance(obj.messier, str) and obj.messier \
                else obj.Name
            common = dso_common_name(obj.messier, obj.Name, obj.common)
            if common:
                label = f"{label} {common}"
            mag = f"V={obj.mag:+.1f}m".replace(".", ",")
            const = ru_constellation(constellation_at()(
                earth().at(t).observe(target).apparent()))
            out.append(Event(
                when=when,
                text=(f"Луна ({moon_label(t, frac, waxing)}) проходит в "
                      f"{angle_deg(best)} {direction_at(t, body('moon'), target, site)} "
                      f"{obj.type_gen} {label} ({mag}) в созвездии {const}"),
                category="moon",
                computed=(f"минимум геоцентрического расстояния Луна–{obj.Name}: "
                          f"{minimum_sep:.3f}° в {minimum_when.isoformat()}; наблюдательное время для {city}, топоцентрическое разделение {best:.3f}°"),
                sources=["Skyfield/DE440s", "OpenNGC"],
                precision="minute",
                meta={"object": obj.Name, "sep_deg": best, "minimum_when": minimum_when.isoformat(), "minimum_sep_deg": minimum_sep, "time_semantics": "observing", "city": city,
                      "object_mag": float(obj.mag), "messier": is_messier(obj.messier)},
            ))
    return _closest_per_night(out)


def _closest_per_night(events: list[Event], hours: float = 8.0) -> list[Event]:
    """Одна ночь — одно сближение: рядом с M8 лежит NGC 6530, и это одно и то же."""
    kept: list[Event] = []
    for event in sorted(events, key=lambda e: e.meta["sep_deg"]):
        if any(abs((other.when - event.when).total_seconds()) < hours * 3600
               for other in kept):
            continue
        kept.append(event)
    return sorted(kept, key=lambda e: e.when)


def all_events(start: dt.datetime, end: dt.datetime) -> list[Event]:
    return (phases(start, end) + apsides(start, end)
            + conjunctions_with_planets(start, end)
            + conjunctions_with_stars(start, end)
            + conjunctions_with_deep_sky(start, end))
