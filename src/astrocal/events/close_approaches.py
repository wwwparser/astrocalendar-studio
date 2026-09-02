"""Близкие пролёты околоземных астероидов.

Источник — CNEOS Close Approach Data (NASA/JPL): официальный список тесных
сближений с датой, расстоянием, скоростью и абсолютной величиной H.

Главная трудность здесь не в получении данных, а в отборе. Мимо Земли каждый
месяц проходят десятки метровых камней, и если публиковать их все, календарь
превратится в ленту служебных сообщений, из которой читатель ничего не
вынесет. Поэтому значимость определяется явными порогами (см. `config`):
ближе Луны — событие месяца, десятки метров в пределах пяти лунных
расстояний — заметное явление, крупный объект интересен и дальше.

Второе отличие от «просто списка» — наблюдаемость. Физически близкий астероид
и астероид, который реально можно увидеть, — разные вещи: объект в 1 LD может
быть +19-й величины и висеть под горизонтом. Поэтому для отобранных сближений
считается видимый блеск, высота над горизонтом, лучшее время и скорость
движения по небу — это и отличает интересное наблюдателю событие от строки в
таблице.

Диаметр почти всегда оценочный: у большинства объектов измерен только H, и
размер выводится из него через альбедо. Мы храним и оценку, и границы при
альбедо 0.25…0.05, и никогда не выдаём оценку за измерение.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np

from .. import config as cfg
from ..core import Event
from ..fmt import number
from ..net import NetworkError, fetch

CAD_API = "https://ssd-api.jpl.nasa.gov/cad.api"
AU_KM = 149597870.7
SOURCE = "NASA/JPL CNEOS Close Approach Data API"

# Альбедо для границ оценки диаметра: светлый каменный объект даёт меньший
# размер при том же блеске, тёмный углистый — больший
ALBEDO_BRIGHT = 0.25
ALBEDO_DARK = 0.05

# Предел любительского инструмента: слабее объект в календарь для читателя не
# попадает как наблюдательный
AMATEUR_LIMIT = 15.5


def diameter_km(h_magnitude: float, albedo: float = cfg.NEO_ALBEDO) -> float:
    """Оценка диаметра по абсолютной величине H (стандартная формула)."""
    return 1329.0 / np.sqrt(albedo) * 10 ** (-0.2 * h_magnitude)


@dataclass
class CloseApproach:
    """Одно сближение по данным CNEOS."""
    designation: str
    fullname: str
    close_approach_datetime: dt.datetime          # МСК
    distance_au: float
    distance_km: float
    distance_ld: float
    velocity_km_s: float
    absolute_magnitude_H: float | None
    diameter_min: float | None                    # км, альбедо 0.25
    diameter_max: float | None                    # км, альбедо 0.05
    diameter_estimate: float | None               # км, альбедо 0.14
    diameter_measured: float | None = None        # км, если известен реально
    distance_min_au: float | None = None
    distance_max_au: float | None = None
    source: str = SOURCE
    source_updated_at: str = ""
    rank: str = "optional"
    observability: dict = field(default_factory=dict)

    # ------------------------------------------------------------ идентичность

    @property
    def live_id(self) -> str:
        """Устойчивый идентификатор: объект плюс момент сближения до минуты."""
        stamp = self.close_approach_datetime.astimezone(
            dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
        return f"neo:{self.designation.strip().replace(' ', '')}:{stamp}"

    @property
    def diameter_text(self) -> str:
        size = self.diameter_measured or self.diameter_estimate
        if size is None:
            return "размер неизвестен"
        measured = self.diameter_measured is not None
        prefix = "d=" if measured else "d≈"
        if size < 1.0:
            return f"{prefix}{size * 1000:.0f} м"
        return f"{prefix}{number(size)} км"

    @property
    def distance_text(self) -> str:
        if self.distance_km < 1e6:
            return f"{self.distance_km / 1e3:.0f} тыс. км"
        return f"{number(self.distance_km / 1e6)} млн км"

    @property
    def size_km(self) -> float:
        return self.diameter_measured or self.diameter_estimate or 0.0

    def provenance(self) -> dict:
        return {"origin": "cneos", "source": self.source,
                "source_updated_at": self.source_updated_at,
                "diameter_provenance": ("измерен" if self.diameter_measured
                                        else f"оценка по H={self.absolute_magnitude_H} "
                                             f"и альбедо {cfg.NEO_ALBEDO}"),
                "distance_range_au": [self.distance_min_au, self.distance_max_au]}


# ------------------------------------------------------------------ получение


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_payload(payload: dict, source_updated_at: str = "") -> list[CloseApproach]:
    """Разобрать ответ CNEOS в записи сближений."""
    fields = payload.get("fields", [])
    out: list[CloseApproach] = []
    for row in payload.get("data", []) or []:
        record = dict(zip(fields, row))
        distance_au = _to_float(record.get("dist"))
        if distance_au is None:
            continue
        try:
            when = dt.datetime.strptime(record["cd"], "%Y-%b-%d %H:%M").replace(
                tzinfo=dt.timezone.utc).astimezone(cfg.MSK)
        except (KeyError, ValueError):
            continue
        h = _to_float(record.get("h"))
        measured = _to_float(record.get("diameter"))
        out.append(CloseApproach(
            designation=str(record.get("des", "")).strip(),
            fullname=str(record.get("fullname") or record.get("des") or "").strip(),
            close_approach_datetime=when,
            distance_au=distance_au,
            distance_km=distance_au * AU_KM,
            distance_ld=distance_au * AU_KM / cfg.LUNAR_DISTANCE_KM,
            velocity_km_s=_to_float(record.get("v_rel")) or 0.0,
            absolute_magnitude_H=h,
            diameter_min=diameter_km(h, ALBEDO_BRIGHT) if h is not None else None,
            diameter_max=diameter_km(h, ALBEDO_DARK) if h is not None else None,
            diameter_estimate=diameter_km(h) if h is not None else None,
            diameter_measured=measured,
            distance_min_au=_to_float(record.get("dist_min")),
            distance_max_au=_to_float(record.get("dist_max")),
            source_updated_at=source_updated_at,
        ))
    return sorted(out, key=lambda a: a.close_approach_datetime)


def approaches(start: dt.datetime, end: dt.datetime,
               max_dist_au: float | None = None,
               use_cache: bool = True) -> list[CloseApproach]:
    """Сближения за период. Сеть — через общий слой с кэшем и лимитами."""
    params = {
        "date-min": start.strftime("%Y-%m-%d"),
        "date-max": end.strftime("%Y-%m-%d"),
        "dist-max": str(max_dist_au or cfg.NEO_SEARCH_RADIUS_AU),
        "sort": "date", "fullname": "true", "diameter": "true",
    }
    response = fetch(CAD_API, params=params, ttl_hours=12.0, use_cache=use_cache)
    return parse_payload(response.json(), response.fetched_at.isoformat())


# ------------------------------------------------------------------ значимость


def rank_of(approach: CloseApproach) -> str:
    """Редакционная значимость сближения. Пороги — в `config`."""
    size_m = (approach.diameter_measured or approach.diameter_estimate or 0.0) * 1000.0
    ld = approach.distance_ld

    if ld < cfg.NEO_MUST_LD:
        return "must"
    if ld < cfg.NEO_INTERESTING_LD and size_m >= cfg.NEO_INTERESTING_DIAMETER_M:
        return "interesting"
    if size_m >= cfg.NEO_LARGE_DIAMETER_M and ld < cfg.NEO_LARGE_LD:
        return "interesting"
    return "optional"


def significant(items: list[CloseApproach],
                ranks=("must", "interesting")) -> list[CloseApproach]:
    for item in items:
        item.rank = rank_of(item)
    return [item for item in items if item.rank in ranks]


# ------------------------------------------------------------------ наблюдаемость


def observe(approach: CloseApproach, city, window_hours: float = 14.0,
            step_minutes: int = 20) -> dict:
    """Реальная наблюдаемость сближения из конкретного города.

    Эфемерида берётся у Horizons для координат города: только так получается
    видимый блеск быстро летящего объекта и его высота над горизонтом. Солнце
    и Луна считаются локально — на них Horizons тратить запрос незачем.
    """
    from skyfield import almanac
    from skyfield.api import Star, wgs84

    from ..core import body, planets, timescale, to_msk
    from ..horizons import column_named, query, table
    from ..observing import (INSTRUMENT_RU, compass_direction, instrument_for,
                             score_conditions)

    centre = approach.close_approach_datetime.astimezone(dt.timezone.utc)
    start = centre - dt.timedelta(hours=window_hours / 2)
    stop = centre + dt.timedelta(hours=window_hours / 2)

    text = query(f"{approach.designation};",
                 start.strftime("%Y-%m-%d %H:%M"), stop.strftime("%Y-%m-%d %H:%M"),
                 f"{step_minutes}m", quantities="1,3,4,9",
                 site_coord=(city.lon, city.lat, city.elevation_m / 1000.0))
    records = table(text)
    if not records:
        return {"visible": False, "city": city.name,
                "note": "Horizons не дал эфемериду объекта"}

    ts = timescale()
    site = planets()["earth"] + wgs84.latlon(city.lat, city.lon, city.elevation_m)

    samples = []
    for record in records:
        try:
            stamp = dt.datetime.strptime(record["_time"], "%Y-%b-%d %H:%M").replace(
                tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        altitude = _to_float(column_named(record, "Elev", "El_"))
        azimuth = _to_float(column_named(record, "Azi"))
        magnitude = _to_float(column_named(record, "APmag"))
        ra = _to_float(column_named(record, "R.A."))
        dec = _to_float(column_named(record, "DEC"))
        d_ra = _to_float(column_named(record, "dRA"))
        d_dec = _to_float(column_named(record, "d(DEC)"))
        if altitude is None or ra is None or dec is None:
            continue
        samples.append({"utc": stamp, "alt": altitude, "az": azimuth or 0.0,
                        "mag": magnitude, "ra": ra, "dec": dec,
                        "rate": float(np.hypot(d_ra or 0.0, d_dec or 0.0))})
    if not samples:
        return {"visible": False, "city": city.name,
                "note": "эфемерида объекта не разобрана"}

    grid = ts.from_datetimes([s["utc"] for s in samples])
    sun_alt = site.at(grid).observe(body("sun")).apparent().altaz()[0].degrees
    moon_alt = site.at(grid).observe(body("moon")).apparent().altaz()[0].degrees
    for index, sample in enumerate(samples):
        sample["sun_alt"] = float(sun_alt[index])
        sample["moon_alt"] = float(moon_alt[index])

    visible = [s for s in samples if s["alt"] > 10.0 and s["sun_alt"] < -6.0]
    peak = max(samples, key=lambda s: s["alt"])
    if not visible:
        return {"visible": False, "city": city.name,
                "max_altitude_deg": peak["alt"], "magnitude": peak["mag"],
                "note": "объект не поднимается над горизонтом на тёмном небе"}

    best = max(visible, key=lambda s: s["alt"])
    window_start, window_end = visible[0]["utc"], visible[-1]["utc"]
    window_minutes = (window_end - window_start).total_seconds() / 60.0

    t_best = ts.from_datetime(best["utc"])
    illumination = float(almanac.fraction_illuminated(planets(), "moon", t_best))
    star = Star(ra_hours=best["ra"] / 15.0, dec_degrees=best["dec"])
    moon_sep = float(site.at(t_best).observe(star).apparent().separation_from(
        site.at(t_best).observe(body("moon")).apparent()).degrees)

    magnitude = best["mag"]
    score, stars = score_conditions(best["alt"], best["sun_alt"], best["moon_alt"],
                                    illumination, moon_sep, magnitude,
                                    window_minutes)
    # Оценка условий говорит о небе, а не о том, увидит ли объект человек.
    # Метровый камень в 12 лунных расстояниях бывает +22-й величины: небо
    # может быть идеальным, но любительскому телескопу это недоступно, и
    # ставить такому пролёту три звезды — вводить читателя в заблуждение.
    note = ""
    if magnitude is not None and magnitude > AMATEUR_LIMIT:
        stars = 1
        note = (f"расчётный блеск {magnitude:+.1f}m — за пределами любительских "
                f"инструментов, пролёт интересен как факт, а не как наблюдение")
    return {
        "note": note,
        "visible": True,
        "city": city.name,
        "magnitude": magnitude,
        "altitude_deg": best["alt"],
        "azimuth_deg": best["az"],
        "direction": compass_direction(best["az"]),
        "max_altitude_deg": peak["alt"],
        "best_time": to_msk(t_best),
        "window_start": window_start.astimezone(cfg.MSK),
        "window_end": window_end.astimezone(cfg.MSK),
        "window_minutes": window_minutes,
        "sun_altitude_deg": best["sun_alt"],
        "moon_altitude_deg": best["moon_alt"],
        "moon_illumination": illumination,
        "moon_separation_deg": moon_sep,
        "sky_motion_arcsec_per_hour": best["rate"],
        "ra": best["ra"], "dec": best["dec"],
        "instrument": INSTRUMENT_RU[instrument_for(magnitude)],
        "score": score, "stars": stars,
    }


def observe_cities(approach: CloseApproach, cities) -> list[dict]:
    """Наблюдаемость из нескольких городов; недоступный источник не роняет расчёт."""
    results = []
    for city in cities:
        try:
            results.append(observe(approach, city))
        except (NetworkError, RuntimeError, ValueError) as error:
            results.append({"visible": False, "city": city.name,
                            "note": f"не удалось получить эфемериду: {error}"})
    return results


def best_observability(approach: CloseApproach, cities) -> dict:
    """Лучший из городов — то, что показывается в карточке."""
    results = [item for item in observe_cities(approach, cities)
               if item.get("visible")]
    if not results:
        return {"visible": False,
                "note": "из выбранных городов объект не наблюдается"}
    return max(results, key=lambda item: item.get("score", 0))


# ------------------------------------------------------------------ события


def to_event(approach: CloseApproach) -> Event:
    """Строка календаря по сближению."""
    name = approach.fullname or approach.designation
    ld_text = number(approach.distance_ld)
    magnitude_note = ""
    if approach.absolute_magnitude_H is not None:
        magnitude_note = (
            f", H={approach.absolute_magnitude_H:.1f}m, диаметр "
            f"{(approach.diameter_min or 0) * 1000:.0f}–"
            f"{(approach.diameter_max or 0) * 1000:.0f} м при альбедо "
            f"{ALBEDO_BRIGHT}…{ALBEDO_DARK}")
    return Event(
        when=approach.close_approach_datetime,
        text=(f"Астероид {name} ({approach.diameter_text}) пролетает в "
              f"{approach.distance_text} от Земли "
              f"({ld_text} расстояния Земля—Луна)"),
        category="asteroid",
        confidence="высокая",
        computed=(f"CNEOS Close Approach: расстояние {approach.distance_au:.5f} а.е. "
                  f"= {approach.distance_ld:.2f} LD, относительная скорость "
                  f"{approach.velocity_km_s:.1f} км/с" + magnitude_note),
        sources=[SOURCE],
        precision="hour",
        rank=approach.rank,
        provenance=approach.provenance(),
        meta={"distance_km": approach.distance_km,
              "distance_ld": approach.distance_ld,
              "h": approach.absolute_magnitude_H,
              "diameter_km": approach.size_km,
              "designation": approach.designation,
              "neo_live_id": approach.live_id,
              "velocity_km_s": approach.velocity_km_s},
    )


def build(start: dt.datetime, end: dt.datetime,
          limit: int | None = None) -> list[Event]:
    """Сближения месяца, отобранные по значимости, для месячного календаря."""
    items = [item for item in approaches(start, end)
             if start <= item.close_approach_datetime < end]
    chosen = significant(items)
    chosen.sort(key=lambda a: (-{"must": 2, "interesting": 1}.get(a.rank, 0),
                               a.distance_ld))
    chosen = chosen[:limit or cfg.NEO_MAX_IN_CALENDAR]
    return sorted([to_event(item) for item in chosen], key=lambda e: e.when)
