"""Покрытия звёзд астероидами: полоса по актуальной орбите.

Список кандидатов приходит из ленты IOTA (`occultation_feeds`), а полосу мы
строим сами и по свежей орбите — это не дублирование чужой работы, а
необходимая проверка. Годовой файл предсказаний считается один раз и потом не
обновляется: для покрытия HIP 20901 астероидом (14717) он даёт 28 августа
01:16 UT, а по текущей орбите JPL событие происходит на 20 часов позже —
28 августа 21:18 UT. Опубликовать первое значение означало бы отправить
наблюдателей не в ту ночь.

Геометрия простая, потому что звезда бесконечно далека: её лучи параллельны,
и тень астероида — цилиндр радиусом с сам астероид, летящий вдоль направления
«от звезды». Центральная линия — след оси этого цилиндра на эллипсоиде Земли.

Чего этот расчёт не даёт: собственной оценки ошибки. Неопределённость полосы
берём из ленты (σ в километрах) и показываем сдвинутые на ±σ варианты — если
при сдвиге полоса уходит с территории России, событие помечается как
ненадёжное.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
from skyfield.framelib import itrs

from .. import config as cfg
from ..core import Event, timescale
from ..geo import (EARTH_A_KM, itrs_to_geodetic, point_in_russia,
                   ray_ellipsoid_intersection)
from ..horizons import query, rows
from ..occultation_feeds import Candidate, candidates

AU_KM = 149597870.7
RUSSIA_SITES = [(56.0, 38.0), (60.0, 30.0), (45.0, 39.0), (56.8, 60.6),
                (55.0, 82.9), (52.3, 104.3), (62.0, 129.7), (43.1, 131.9),
                (64.0, 100.0), (68.0, 33.0)]


def _unit(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    return np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])


def star_above_russia(when: dt.datetime, ra_deg: float, dec_deg: float) -> bool:
    """Быстрый предфильтр: видна ли звезда хоть где-то в России в этот момент.

    Дешёвая проверка без обращения к эфемеридам: если звезда под горизонтом по
    всей стране, полоса через Россию пройти не может, и запрашивать Horizons
    незачем.
    """
    ts = timescale()
    rotation = itrs.rotation_at(ts.from_datetime(when))
    direction = rotation @ _unit(ra_deg, dec_deg)
    for lat, lon in RUSSIA_SITES:
        up = _unit(lon, lat)          # локальная вертикаль в ITRS (сферическое приближение)
        if float(np.dot(direction, up)) > 0.02:
            return True
    return False


def asteroid_track(number: int, start: dt.datetime, end: dt.datetime,
                   intervals: int = 240):
    """RA/Dec/расстояние астероида из Horizons на мелкой сетке."""
    text = query(f"{number};", start.strftime("%Y-%m-%d %H:%M"),
                 end.strftime("%Y-%m-%d %H:%M"), str(intervals), quantities="1,20")
    track = []
    for row in rows(text):
        values = [c for c in row[1:] if c.strip()]
        try:
            ra, dec, delta = float(values[0]), float(values[1]), float(values[2])
        except (ValueError, IndexError):
            continue
        stamp = None
        for pattern in ("%Y-%b-%d %H:%M:%S.%f", "%Y-%b-%d %H:%M:%S", "%Y-%b-%d %H:%M"):
            try:
                stamp = dt.datetime.strptime(row[0], pattern).replace(
                    tzinfo=dt.timezone.utc)
                break
            except ValueError:
                continue
        if stamp is None:
            continue
        track.append((stamp, ra, dec, delta * AU_KM))
    return track


def shadow_path(track, star_ra_deg: float, star_dec_deg: float,
                offset_km: float = 0.0):
    """След оси тени на поверхности Земли.

    offset_km сдвигает ось поперёк движения — так проверяется, что остаётся от
    полосы при сдвиге на заявленную ленте неопределённость.
    """
    ts = timescale()
    star = _unit(star_ra_deg, star_dec_deg)
    path = []
    for stamp, ra, dec, distance in track:
        rotation = itrs.rotation_at(ts.from_datetime(stamp))
        origin = rotation @ (_unit(ra, dec) * distance)
        direction = rotation @ star
        if offset_km:
            side = np.cross(direction, np.array([0.0, 0.0, 1.0]))
            norm = np.linalg.norm(side)
            if norm > 0:
                origin = origin + side / norm * offset_km
        point = ray_ellipsoid_intersection(origin, direction)
        if point is None:
            continue
        lat, lon = itrs_to_geodetic(point)
        path.append({"utc": stamp, "lat": lat, "lon": lon})
    return path


def axis_miss_km(track, star_ra_deg: float, star_dec_deg: float) -> float:
    """Минимальное расстояние от центра Земли до оси тени, км."""
    ts = timescale()
    star = _unit(star_ra_deg, star_dec_deg)
    best = float("inf")
    for stamp, ra, dec, distance in track:
        rotation = itrs.rotation_at(ts.from_datetime(stamp))
        origin = rotation @ (_unit(ra, dec) * distance)
        direction = rotation @ star
        perpendicular = origin - float(np.dot(origin, direction)) * direction
        best = min(best, float(np.linalg.norm(perpendicular)))
    return best


def analyse(candidate: Candidate, window_hours: float = 26.0) -> dict | None:
    """Пересчитать событие по свежей орбите: где и когда прошла полоса."""
    # Предсказание может уехать на часы, поэтому сначала ищем истинный минимум
    # на широком окне, а уже потом считаем полосу с мелким шагом.
    coarse = asteroid_track(candidate.asteroid_number,
                            candidate.predicted_utc - dt.timedelta(hours=window_hours),
                            candidate.predicted_utc + dt.timedelta(hours=window_hours),
                            intervals=int(window_hours * 2))
    if not coarse:
        return None
    star = _unit(candidate.star_ra_deg, candidate.star_dec_deg)
    separations = []
    for stamp, ra, dec, _distance in coarse:
        cos = float(np.dot(_unit(ra, dec), star))
        separations.append((np.degrees(np.arccos(np.clip(cos, -1, 1))) * 3600, stamp))
    best_sep, closest = min(separations)

    # Дешёвая отсечка перед дорогим шагом: если в минимуме астероид отстоит от
    # звезды дальше, чем видна Земля с его расстояния, тень пройдёт мимо и
    # мелкая сетка не нужна.
    distance_km = coarse[len(coarse) // 2][3]
    miss_estimate = best_sep / 206264.806 * distance_km
    if miss_estimate > 3 * EARTH_A_KM:
        return {"candidate": candidate, "path": [], "shifted": {},
                "axis_miss_km": miss_estimate, "hits_earth": False,
                "regions": [], "regions_within_sigma": [],
                "recomputed_utc": closest, "feed_shift_hours":
                    (closest - candidate.predicted_utc).total_seconds() / 3600}

    fine = asteroid_track(candidate.asteroid_number,
                          closest - dt.timedelta(minutes=25),
                          closest + dt.timedelta(minutes=25), intervals=300)
    if not fine:
        return None
    miss = axis_miss_km(fine, candidate.star_ra_deg, candidate.star_dec_deg)
    path = shadow_path(fine, candidate.star_ra_deg, candidate.star_dec_deg)
    sigma = candidate.sigma_km if np.isfinite(candidate.sigma_km) else 0.0
    shifted = {
        "plus": shadow_path(fine, candidate.star_ra_deg, candidate.star_dec_deg, sigma),
        "minus": shadow_path(fine, candidate.star_ra_deg, candidate.star_dec_deg, -sigma),
    }

    regions, regions_sigma = [], []
    for point in path:
        name = point_in_russia(point["lat"], point["lon"])
        if name and name not in regions:
            regions.append(name)
    for variant in shifted.values():
        for point in variant:
            name = point_in_russia(point["lat"], point["lon"])
            if name and name not in regions_sigma:
                regions_sigma.append(name)

    shift_hours = (path[0]["utc"] - candidate.predicted_utc).total_seconds() / 3600 \
        if path else None
    return {
        "candidate": candidate, "path": path, "shifted": shifted,
        "axis_miss_km": miss, "hits_earth": bool(path),
        "regions": regions, "regions_within_sigma": regions_sigma,
        "recomputed_utc": path[len(path) // 2]["utc"] if path else closest,
        "feed_shift_hours": shift_hours,
    }


def sun_altitude(lat: float, lon: float, when: dt.datetime) -> float:
    """Высота Солнца в точке полосы — покрытие на дневном небе не наблюдают."""
    from skyfield.api import wgs84

    from ..core import body, planets
    site = planets()["earth"] + wgs84.latlon(lat, lon)
    t = timescale().from_datetime(when)
    return float(site.at(t).observe(body("sun")).apparent().altaz()[0].degrees)


def build(start: dt.datetime, end: dt.datetime, star_mag_limit: float = 6.0,
          min_drop_mag: float = 1.5, max_sun_alt: float = -6.0):
    """События календаря + полный отчёт по всем разобранным кандидатам.

    В календарь идут только покрытия, которые можно увидеть: падение блеска
    заметное, полоса над Россией и небо в этот момент тёмное.
    """
    events, report = [], []
    for candidate in candidates(start.year, start.month, star_mag_limit):
        if not star_above_russia(candidate.predicted_utc,
                                 candidate.star_ra_deg, candidate.star_dec_deg):
            continue
        try:
            result = analyse(candidate)
        except Exception as exc:
            report.append({"candidate": candidate, "error": str(exc)})
            continue
        if result is None:
            continue
        report.append(result)
        if not result["regions"]:
            continue
        if np.isfinite(candidate.magnitude_drop) and                 candidate.magnitude_drop < min_drop_mag:
            result["skipped"] = "падение блеска меньше порога"
            continue

        # В календарь ставим момент, когда полоса выходит на территорию России:
        # наблюдателю важно, когда явление начинается у него, а не середина трека.
        entry = next((p for p in result["path"]
                      if point_in_russia(p["lat"], p["lon"])), None)
        moment = entry["utc"] if entry else result["recomputed_utc"]
        when = moment.astimezone(cfg.MSK)
        if not (start <= when < end):
            continue
        if entry is not None:
            sun = sun_altitude(entry["lat"], entry["lon"], moment)
            result["sun_alt"] = sun
            if sun > max_sun_alt:
                result["skipped"] = f"на полосе светло, Солнце {sun:.0f}°"
                continue
        c = candidate
        reliable = bool(result["regions_within_sigma"])
        # запятая как десятичный разделитель — только в числах, не в имени звезды
        star_mag = f"V={c.star_mag:+.1f}m".replace(".", ",")
        drop = (", падение блеска "
                + f"{c.magnitude_drop:.1f}".replace(".", ",") + "ᵐ"
                if np.isfinite(c.magnitude_drop) else "")
        events.append(Event(
            when=when,
            text=(f"Астероид ({c.asteroid_number}) {c.asteroid_name} "
                  f"покрывает звезду {c.star_id} ({star_mag})"
                  f"{drop}, полоса проходит через "
                  f"{', '.join(result['regions'][:4])}"),
            category="asteroid_occultation",
            confidence="средняя" if reliable else "низкая",
            computed=(
                f"кандидат из ленты {c.feed} (орбита {c.orbit_solution}); "
                f"полоса пересчитана по актуальной эфемериде JPL Horizons: ось тени "
                f"проходит в {result['axis_miss_km']:.0f} км от центра Земли "
                f"(радиус Земли {EARTH_A_KM:.0f} км); ширина полосы ≈ "
                f"{c.diameter_km:.0f} км, максимальная длительность "
                f"{c.max_duration_s:.1f} с; заявленная неопределённость полосы "
                f"±{c.sigma_km:.0f} км"
                + (f"; момент по ленте сдвинут на {result['feed_shift_hours']:+.1f} ч "
                   f"относительно пересчёта" if result["feed_shift_hours"] else "")),
            sources=[f"IOTA/asteroidoccultation.com ({c.feed})",
                     "JPL Horizons (актуальная орбита)",
                     "Hipparcos/Tycho (положение звезды)"],
            precision="minute",
            notes=("при сдвиге полосы на заявленную ошибку она остаётся над Россией"
                   if reliable else
                   "при сдвиге полосы на заявленную ошибку она уходит с территории "
                   "России — событие ненадёжно"),
            meta={"asteroid": c.asteroid_number, "star": c.star_id,
                  "sigma_km": c.sigma_km, "path": result["path"]},
        ))
    return _deduplicate(events), report


def _deduplicate(events: list[Event], hours: float = 2.0) -> list[Event]:
    """Одна тень — одна строка: у двойных звёзд лента даёт две записи подряд."""
    kept: list[Event] = []
    for event in sorted(events, key=lambda e: e.when):
        if any(other.meta["asteroid"] == event.meta["asteroid"]
               and abs((other.when - event.when).total_seconds()) < hours * 3600
               for other in kept):
            continue
        kept.append(event)
    return kept
