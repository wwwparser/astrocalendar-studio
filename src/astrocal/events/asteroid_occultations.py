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
from dataclasses import dataclass, field

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
        "track": fine, "axis_miss_km": miss, "hits_earth": bool(path),
        "regions": regions, "regions_within_sigma": regions_sigma,
        "recomputed_utc": path[len(path) // 2]["utc"] if path else closest,
        "feed_shift_hours": shift_hours,
    }


def star_constellation(ra_deg: float, dec_deg: float) -> str:
    """Созвездие, в котором находится покрываемая звезда."""
    from skyfield.api import Star

    from ..core import constellation_at, earth, timescale
    from ..fmt import ru_constellation

    try:
        t = timescale().from_datetime(dt.datetime.now(dt.timezone.utc))
        star = Star(ra_hours=ra_deg / 15.0, dec_degrees=dec_deg)
        return ru_constellation(constellation_at()(
            earth().at(t).observe(star).apparent()))
    except Exception:                            # noqa: BLE001
        return ""


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
        # Наблюдателю нужны все пять величин: чем покрывается, что покрывается,
        # где на небе это искать, насколько провалится блеск и сколько времени
        # есть на съёмку. Раньше в строке были только две из них.
        from ..fmt import number

        star_mag = f"V={number(c.star_mag, 1, sign=True)}m"
        asteroid_mag = (f" ({number(c.asteroid_mag, 1, sign=True)}m)"
                        if np.isfinite(c.asteroid_mag) else "")
        drop = (", падение блеска " + number(c.magnitude_drop) + "ᵐ"
                if np.isfinite(c.magnitude_drop) else "")
        duration = (", максимум " + number(c.max_duration_s) + " с"
                    if np.isfinite(c.max_duration_s) else "")
        width = (f", полоса шириной {c.diameter_km:.0f} км — "
                 if np.isfinite(c.diameter_km) and c.diameter_km >= 1
                 else ", полоса — ")
        constellation = star_constellation(c.star_ra_deg, c.star_dec_deg)
        where = f" в созвездии {constellation}" if constellation else ""
        events.append(Event(
            when=when,
            text=(f"Астероид ({c.asteroid_number}) {c.asteroid_name}"
                  f"{asteroid_mag} покрывает звезду {c.star_id} ({star_mag})"
                  f"{where}{drop}{duration}"
                  f"{width}"
                  f"{', '.join(result['regions'])}"),
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
                  "sigma_km": c.sigma_km, "path": result["path"],
                  "star_mag": c.star_mag, "asteroid_mag": c.asteroid_mag,
                  "magnitude_drop": c.magnitude_drop,
                  "duration_s": c.max_duration_s,
                  "path_width_km": c.diameter_km,
                  "constellation": constellation},
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


# ------------------------------------------------------------------ запись события


SBDB_API = "https://ssd-api.jpl.nasa.gov/sbdb.api"


@dataclass
class Occultation:
    """Полная карточка покрытия: и геометрия, и происхождение прогноза.

    Отдельный тип нужен потому, что строка календаря — это ещё не событие.
    Редактору нужны полоса и её границы, наблюдаемость по городам, возраст
    прогноза и возраст орбиты: по ним принимается решение, публиковать ли
    событие и не пора ли его пересчитать.
    """
    event_id: str
    asteroid_number: int
    asteroid_name: str
    star_id: str
    star_name: str
    star_ra_deg: float
    star_dec_deg: float
    star_mag: float
    asteroid_mag: float
    magnitude_drop: float
    event_utc: dt.datetime
    event_local: dt.datetime
    duration_sec: float
    asteroid_diameter_km: float
    path_width_km: float
    central_path: list = field(default_factory=list)
    north_limit: list = field(default_factory=list)
    south_limit: list = field(default_factory=list)
    prediction_epoch: dt.datetime | None = None
    orbit_epoch: str = ""
    orbit_solution: str = ""
    source: str = ""
    source_updated_at: str = ""
    uncertainty_km: float = float("nan")
    confidence: str = "средняя"
    regions: list = field(default_factory=list)
    regions_within_sigma: list = field(default_factory=list)
    cities_visible: list = field(default_factory=list)
    sun_altitude_deg: float | None = None
    star_altitude_deg: float | None = None
    moon_altitude_deg: float | None = None
    moon_separation_deg: float | None = None
    sky_state: str = ""
    instrument: str = ""
    quality: str = ""
    stars: int = 0
    feed_shift_hours: float | None = None
    axis_miss_km: float = float("nan")

    @property
    def live_id(self) -> str:
        return self.event_id

    @property
    def prediction_age_days(self) -> float | None:
        if self.prediction_epoch is None:
            return None
        return (dt.datetime.now(dt.timezone.utc)
                - self.prediction_epoch).total_seconds() / 86400.0

    @property
    def orbit_age_days(self) -> float | None:
        if not self.orbit_epoch:
            return None
        stamp = _parse_epoch(self.orbit_epoch)
        if stamp is None:
            return None
        return (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds() / 86400.0

    @property
    def needs_refresh(self) -> bool:
        """Прогноз пора пересчитать: он стар, а событие уже близко.

        Оба условия обязательны. Полугодовой прогноз на событие через год
        обновлять незачем, а тот же прогноз за неделю до покрытия обновить
        необходимо: именно на этом сроке уточнение орбиты сдвигает полосу.
        """
        age = self.prediction_age_days
        if age is None:
            return False
        days_left = (self.event_utc
                     - dt.datetime.now(dt.timezone.utc)).total_seconds() / 86400.0
        return age > cfg.OCC_PREDICTION_STALE_DAYS and 0 <= days_left <= 60

    @property
    def freshness_note(self) -> str:
        parts = []
        age = self.prediction_age_days
        if age is not None:
            parts.append(f"прогноз рассчитан {age:.0f} дн назад")
        orbit_age = self.orbit_age_days
        if orbit_age is not None:
            parts.append(f"орбита решена {orbit_age:.0f} дн назад")
        if self.needs_refresh:
            parts.append("рекомендуется пересчёт перед публикацией")
        return "; ".join(parts)


def _parse_epoch(value: str) -> dt.datetime | None:
    """Дата решения орбиты: SBDB отдаёт её в нескольких форматах."""
    text = str(value).strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, pattern).replace(
                tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    try:                       # эпоха может прийти юлианской датой
        jd = float(text)
    except ValueError:
        return None
    if jd < 2000000:
        return None
    return (dt.datetime(1858, 11, 17, tzinfo=dt.timezone.utc)
            + dt.timedelta(days=jd - 2400000.5))


def occultation_id(number: int, star_id: str, when: dt.datetime) -> str:
    """Устойчивый идентификатор покрытия.

    Момент входит с точностью до минуты: уточнение орбиты сдвигает событие на
    десятки секунд, и по идентификатору оно должно остаться тем же.
    """
    stamp = when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    return f"astocc:{number}:{star_id.strip().replace(' ', '')}:{stamp}"


def orbit_epoch(number: int, use_cache: bool = True) -> str:
    """Дата решения орбиты астероида из JPL SBDB.

    Без неё нельзя ответить на главный вопрос о покрытии: не устарел ли
    прогноз. Один дешёвый запрос на объект, кэш на сутки.
    """
    from ..net import NetworkError, fetch

    try:
        response = fetch(SBDB_API, params={"sstr": str(number)},
                         ttl_hours=24.0, use_cache=use_cache, timeout=30.0)
        orbit = (response.json() or {}).get("orbit") or {}
    except (NetworkError, ValueError, KeyError, TypeError):
        return ""
    return str(orbit.get("soln_date") or orbit.get("epoch") or "")


def star_name_ru(star_id: str) -> str:
    """Русское имя звезды, если она есть в списке именованных."""
    from ..catalogs import STAR_NAMES_RU

    digits = "".join(ch for ch in star_id if ch.isdigit())
    if star_id.upper().startswith("HIP") and digits:
        return STAR_NAMES_RU.get(int(digits), "")
    return ""


def sky_state(sun_altitude_deg: float | None) -> str:
    if sun_altitude_deg is None:
        return "неизвестно"
    if sun_altitude_deg > -0.5:
        return "день"
    if sun_altitude_deg > -18.0:
        return "сумерки"
    return "ночь"


def local_circumstances(path: list, star_ra_deg: float, star_dec_deg: float,
                        star_mag: float | None = None, cities=None,
                        band_half_width_km: float = 0.0) -> list[dict]:
    """Обстоятельства покрытия по городам: кто в полосе и что там на небе."""
    from skyfield.api import Star, wgs84

    from ..cities import all_cities
    from ..core import body, planets, timescale
    from ..geo import haversine_km
    from ..observing import instrument_for

    if not path:
        return []
    ts = timescale()
    star = Star(ra_hours=star_ra_deg / 15.0, dec_degrees=star_dec_deg)
    out = []
    for city in (cities or all_cities()):
        nearest = min(path, key=lambda p: haversine_km(city.lat, city.lon,
                                                       p["lat"], p["lon"]))
        distance = haversine_km(city.lat, city.lon, nearest["lat"], nearest["lon"])
        t = ts.from_datetime(nearest["utc"])
        site = planets()["earth"] + wgs84.latlon(city.lat, city.lon, city.elevation_m)
        star_alt = float(site.at(t).observe(star).apparent().altaz()[0].degrees)
        sun_alt = float(site.at(t).observe(body("sun")).apparent().altaz()[0].degrees)
        moon_alt = float(site.at(t).observe(body("moon")).apparent().altaz()[0].degrees)
        out.append({
            "city": city.name,
            "distance_km": distance,
            "inside": distance <= max(band_half_width_km, 1.0),
            "when": nearest["utc"].astimezone(cfg.MSK),
            "star_altitude_deg": star_alt,
            "sun_altitude_deg": sun_alt,
            "moon_altitude_deg": moon_alt,
            "sky": sky_state(sun_alt),
            "instrument": instrument_for(star_mag),
        })
    return sorted(out, key=lambda item: item["distance_km"])


def record_for(candidate: Candidate, result: dict, cities=None,
               with_orbit_epoch: bool = True) -> Occultation:
    """Собрать полную карточку покрытия из кандидата и пересчитанной геометрии."""
    from skyfield import almanac
    from skyfield.api import Star, wgs84

    from ..core import body, planets, timescale
    from ..observing import instrument_for, score_conditions

    path = result.get("path") or []
    when_utc = result.get("recomputed_utc") or candidate.predicted_utc
    width = candidate.diameter_km if np.isfinite(candidate.diameter_km) else 0.0

    # Границы полосы — та же ось тени, сдвинутая на половину диаметра астероида
    fine = result.get("track")
    north: list = []
    south: list = []
    if fine and width:
        north = shadow_path(fine, candidate.star_ra_deg, candidate.star_dec_deg,
                            width / 2.0)
        south = shadow_path(fine, candidate.star_ra_deg, candidate.star_dec_deg,
                            -width / 2.0)

    entry = next((p for p in path if point_in_russia(p["lat"], p["lon"])),
                 path[0] if path else None)
    star_alt = sun_alt = moon_alt = moon_sep = None
    stars_rating, quality = 0, ""
    if entry is not None:
        ts = timescale()
        t = ts.from_datetime(entry["utc"])
        site = planets()["earth"] + wgs84.latlon(entry["lat"], entry["lon"])
        star = Star(ra_hours=candidate.star_ra_deg / 15.0,
                    dec_degrees=candidate.star_dec_deg)
        star_alt = float(site.at(t).observe(star).apparent().altaz()[0].degrees)
        sun_alt = float(site.at(t).observe(body("sun")).apparent().altaz()[0].degrees)
        moon_alt = float(site.at(t).observe(body("moon")).apparent().altaz()[0].degrees)
        moon_sep = float(site.at(t).observe(star).apparent().separation_from(
            site.at(t).observe(body("moon")).apparent()).degrees)
        illumination = float(almanac.fraction_illuminated(planets(), "moon", t))
        duration_minutes = (candidate.max_duration_s / 60.0
                            if np.isfinite(candidate.max_duration_s) else 1.0)
        score, stars_rating = score_conditions(
            star_alt, sun_alt, moon_alt, illumination, moon_sep,
            candidate.star_mag, duration_minutes)
        quality = f"{score}/100"

    prediction_epoch = None
    year = candidate.predicted_utc.year
    for name in (f"occ{year}-raw-generic.zip", f"occ{year}-iota.zip"):
        feed_file = cfg.CACHE / name
        if feed_file.exists():
            prediction_epoch = dt.datetime.fromtimestamp(
                feed_file.stat().st_mtime, tz=dt.timezone.utc)
            break

    return Occultation(
        event_id=occultation_id(candidate.asteroid_number, candidate.star_id,
                                when_utc),
        asteroid_number=candidate.asteroid_number,
        asteroid_name=candidate.asteroid_name,
        star_id=candidate.star_id,
        star_name=star_name_ru(candidate.star_id),
        star_ra_deg=candidate.star_ra_deg,
        star_dec_deg=candidate.star_dec_deg,
        star_mag=candidate.star_mag,
        asteroid_mag=candidate.asteroid_mag,
        magnitude_drop=candidate.magnitude_drop,
        event_utc=when_utc,
        event_local=when_utc.astimezone(cfg.MSK),
        duration_sec=candidate.max_duration_s,
        asteroid_diameter_km=candidate.diameter_km,
        path_width_km=width,
        central_path=path,
        north_limit=north,
        south_limit=south,
        prediction_epoch=prediction_epoch,
        orbit_epoch=(orbit_epoch(candidate.asteroid_number)
                     if with_orbit_epoch else ""),
        orbit_solution=candidate.orbit_solution,
        source=f"IOTA/asteroidoccultation.com ({candidate.feed})",
        source_updated_at=(prediction_epoch.isoformat() if prediction_epoch else ""),
        uncertainty_km=candidate.sigma_km,
        confidence=("средняя" if result.get("regions_within_sigma") else "низкая"),
        regions=list(result.get("regions") or []),
        regions_within_sigma=list(result.get("regions_within_sigma") or []),
        cities_visible=local_circumstances(path, candidate.star_ra_deg,
                                           candidate.star_dec_deg,
                                           candidate.star_mag, cities,
                                           width / 2.0),
        sun_altitude_deg=sun_alt,
        star_altitude_deg=star_alt,
        moon_altitude_deg=moon_alt,
        moon_separation_deg=moon_sep,
        sky_state=sky_state(sun_alt),
        instrument=instrument_for(candidate.star_mag),
        quality=quality,
        stars=stars_rating,
        feed_shift_hours=result.get("feed_shift_hours"),
        axis_miss_km=result.get("axis_miss_km", float("nan")),
    )


# ------------------------------------------------------------------ полнота


def control_list(year: int) -> dict:
    """Контрольный список покрытий над Россией на год.

    Ведут его наблюдатели (astrovert.ru), собирается скриптом
    `scripts/fetch_control_occultations.py`. Это не источник данных — свои
    события мы считаем сами. Это эталон полноты: если заметное покрытие есть
    у наблюдателей, а у нас его нет, надо понять почему.
    """
    import json

    path = cfg.DATA / f"control_occultations_{year}.json"
    if not path.exists():
        return {"year": year, "events": [], "missing_file": str(path)}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        return {"year": year, "events": [], "error": str(error)}


def _our_number(item) -> int | None:
    """Номер астероида и из события календаря, и из полной карточки."""
    number = getattr(item, "asteroid_number", None)
    if number is not None:
        return int(number)
    meta = getattr(item, "meta", None) or {}
    value = meta.get("asteroid")
    return int(value) if value is not None else None


def _our_date(item):
    when = getattr(item, "event_local", None) or getattr(item, "when", None)
    return when.date() if when is not None else None


def compare_with_control(items: list, year: int, month: int | None = None,
                         day_tolerance: int = 1) -> dict:
    """Что из контрольного списка мы нашли, а что потеряли.

    Совпадением считается тот же астероид в пределах `day_tolerance` суток:
    пересчёт по свежей орбите законно сдвигает момент на часы, и требовать
    совпадения минут было бы неправильно.
    """
    import datetime as dt

    control = control_list(year)
    expected = control.get("events", [])
    if month is not None:
        expected = [e for e in expected if int(e["date"][:2]) == month]

    ours = [(item, _our_number(item), _our_date(item)) for item in items]
    matched, missing = [], []

    for entry in expected:
        month_number, day = (int(part) for part in entry["date"].split("-"))
        control_date = dt.date(year, month_number, day)
        found = None
        for item, number, when in ours:
            if number != entry["asteroid_number"] or when is None:
                continue
            if abs((when - control_date).days) <= day_tolerance:
                found = item
                break
        if found is not None:
            matched.append({"control": entry, "ours": found})
        else:
            missing.append(entry)

    numbers = {entry["asteroid_number"] for entry in expected}
    extra = [item for item, number, _when in ours if number not in numbers]

    return {"year": year, "month": month, "source": control.get("url", ""),
            "expected": len(expected), "matched": matched, "missing": missing,
            "extra": extra,
            "coverage": (len(matched) / len(expected)) if expected else None}


def describe_comparison(result: dict) -> str:
    """Человеко-читаемый итог сверки — для отчёта и командной строки."""
    lines = []
    total = result["expected"]
    if not total:
        return ("Контрольный список пуст: соберите его командой "
                "python scripts/fetch_control_occultations.py")
    lines.append(f"Контрольный список: {total} событий, "
                 f"найдено {len(result['matched'])}, "
                 f"не найдено {len(result['missing'])}")
    for record in result["matched"]:
        entry = record["control"]
        ours = record["ours"]
        when = _our_date(ours)
        lines.append(f"  ✓ ({entry['asteroid_number']}) {entry['asteroid_name']} "
                     f"{entry['date']} {entry['time_msk']} — у нас {when}")
    for entry in result["missing"]:
        lines.append(f"  ✕ ({entry['asteroid_number']}) {entry['asteroid_name']} "
                     f"{entry['date']} {entry['time_msk']}, звезда "
                     f"{entry['star']} (+{entry['star_magnitude']}m), "
                     f"видимость: {', '.join(entry['regions'])}")
    if result["extra"]:
        lines.append(f"  Сверх списка у нас {len(result['extra'])} событий — "
                     f"это нормально: список ограничен яркими звёздами")
    return "\n".join(lines)
