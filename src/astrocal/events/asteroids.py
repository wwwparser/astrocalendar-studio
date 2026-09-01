"""Астероиды: яркие малые планеты и сближения околоземных объектов с Землёй.

Два независимых сюжета, и источники у них разные.

1. **Яркие астероиды.** Церера, Веста и компания бывают ярче +9m и проходят
   рядом со звёздами и туманностями — тот же кросс-матч, что у комет. Эфемериды
   берём из JPL Horizons: он сразу отдаёт и координаты, и звёздную величину, а
   MPCORB.DAT весит четверть гигабайта ради тех же двух десятков объектов.

2. **Сближения с Землёй.** Список приходит из CNEOS Close Approach API — это
   официальный источник NASA/JPL по тесным пролётам. Диаметр оцениваем по
   абсолютной величине H (стандартная формула с альбедо 0.14).
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import requests

from .. import config as cfg
from ..catalogs import (STAR_NAMES_RU, angular_distance_deg, bright_stars, deep_sky)
from ..core import (Event, body, constellation_at, earth, observer,
                    southern_observer, timescale)
from ..fmt import angle_deg, ru_constellation
from ..horizons import query, rows

CAD_API = "https://ssd-api.jpl.nasa.gov/cad.api"
AU_KM = 149597870.7

# Классические яркие астероиды: те, что вообще способны попасть в календарь
BRIGHT_ASTEROIDS = {
    1: "Церера", 2: "Паллада", 3: "Юнона", 4: "Веста", 6: "Геба", 7: "Ирида",
    8: "Флора", 9: "Метида", 15: "Эвномия", 18: "Мельпомена", 20: "Массалия",
    27: "Эвтерпа", 29: "Амфитрита", 39: "Летиция", 40: "Гармония",
    192: "Навсикая", 324: "Бамберга", 349: "Дембовска", 433: "Эрос",
}
MAG_LIMIT = 10.5
APPROACH_LIMIT_DEG = 2.5


def track(number: int, start: dt.datetime, end: dt.datetime, step: str = "1h"):
    """RA/Dec/блеск астероида из Horizons."""
    # В Horizons номер малой планеты задаётся как "4;" — форма "DES=4;"
    # неоднозначна и цепляет комету 4P/Faye
    txt = query(f"{number};", start.strftime("%Y-%m-%d %H:%M"),
                end.strftime("%Y-%m-%d %H:%M"), step, quantities="1,9")
    times, ra, dec, mag = [], [], [], []
    for r in rows(txt):
        vals = [c for c in r[1:] if c.strip()]
        try:
            # разбираем строку целиком и только потом добавляем: иначе при
            # «n.a.» вместо блеска массивы разъезжаются по длине
            values = (float(vals[-4]), float(vals[-3]), float(vals[-2]))
            stamp = dt.datetime.strptime(r[0], "%Y-%b-%d %H:%M").replace(
                tzinfo=dt.timezone.utc)
        except (ValueError, IndexError):
            continue
        ra.append(values[0])
        dec.append(values[1])
        mag.append(values[2])
        times.append(stamp)
    return times, np.array(ra), np.array(dec), np.array(mag)


def _fmt_mag(value: float) -> str:
    return f"V={value:+.1f}m".replace(".", ",")


def _describe_star(row) -> str:
    hip = int(row.hip)
    name = STAR_NAMES_RU.get(hip)
    mag = f"V={row.magnitude:+.1f}m".replace(".", ",")
    return f"звезды {name} ({mag})" if name else f"звезды HIP {hip} ({mag})"


def _describe_dso(row) -> str:
    label = row.Name
    label = ("NGC " + label[3:] if label.startswith("NGC")
             else "IC " + label[2:] if label.startswith("IC") else label)
    label = label.replace(" 0", " ").rstrip()
    import pandas as pd
    if pd.notna(row.messier) and row.messier:
        label = f"{row.messier} ({label})"
    mag = f"V={row.mag:+.1f}m".replace(".", ",")
    return f"{row.type_gen} {label} ({mag})"


def _direction(d_ra_cos: float, d_dec: float) -> str:
    if abs(d_ra_cos) >= abs(d_dec):
        return "восточнее" if d_ra_cos > 0 else "западнее"
    return "севернее" if d_dec > 0 else "южнее"


def approaches(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Проходы ярких астероидов рядом со звёздами и объектами каталогов."""
    ts = timescale()
    site = observer()
    south = southern_observer()
    stars = bright_stars(mag_limit=4.5)
    dso = deep_sky(mag_limit=9.0)
    out: list[Event] = []

    for number, name_ru in BRIGHT_ASTEROIDS.items():
        try:
            times, ra, dec, mag = track(number, start, end)
        except Exception:
            continue
        if not len(times) or np.nanmin(mag) > MAG_LIMIT:
            continue

        grid = ts.from_datetimes(times)
        # тёмное небо хотя бы на одной из двух площадок России
        dark = None
        for place in (site, south):
            sun_alt = place.at(grid).observe(body("sun")).apparent().altaz()[0].degrees
            dark = sun_alt < -6 if dark is None else (dark | (sun_alt < -6))

        for catalog, describe, kind in ((stars, _describe_star, "star"),
                                        (dso, _describe_dso, "dso")):
            for _, obj in catalog.iterrows():
                d = angular_distance_deg(ra, dec, obj.ra_degrees, obj.dec_degrees)
                if not np.isfinite(d).any() or np.nanmin(d) > APPROACH_LIMIT_DEG:
                    continue
                # Берём наилучшее сближение за месяц, а не только внутренние
                # локальные минимумы: астероид может весь месяц приближаться к
                # звезде и разойтись с ней уже в следующем.
                candidates = np.where(dark & np.isfinite(d), d, 1e9)
                i = int(np.argmin(candidates))
                if not np.isfinite(candidates[i]) or candidates[i] > APPROACH_LIMIT_DEG:
                    continue
                if True:
                    when = times[i].astimezone(cfg.MSK)
                    if not (start <= when < end):
                        continue
                    d_dec = dec[i] - obj.dec_degrees
                    d_ra = ((ra[i] - obj.ra_degrees + 180) % 360 - 180) * \
                        np.cos(np.radians(obj.dec_degrees))
                    const = ru_constellation(constellation_at()(
                        earth().at(grid[i]).observe(
                            _star_at(ra[i], dec[i])).apparent()))
                    out.append(Event(
                        when=when,
                        text=(f"Астероид ({number}) {name_ru} ({_fmt_mag(mag[i])}) "
                              f"проходит в {angle_deg(float(d[i]))} "
                              f"{_direction(d_ra, d_dec)} {describe(obj)} "
                              f"в созвездии {const}"),
                        category="asteroid",
                        confidence="средняя",
                        computed=(f"эфемерида JPL Horizons с шагом 1 час; наименьшее "
                                  f"за месяц угловое расстояние на тёмном небе "
                                  f"{d[i] * 60:.1f}′"),
                        sources=["JPL Horizons", "Hipparcos / OpenNGC"],
                        precision="hour",
                        meta={"number": number, "sep_deg": float(d[i]),
                              "object_mag": float(obj.magnitude if kind == "star"
                                                  else obj.mag),
                              "kind": kind, "mag": float(mag[i]),
                              "messier": bool(kind == "dso" and obj.messier)},
                    ))
    return _deduplicate([e for e in out if interesting(e.meta)])


def _star_at(ra_deg: float, dec_deg: float):
    from skyfield.api import Star
    return Star(ra_hours=float(ra_deg) / 15.0, dec_degrees=float(dec_deg))


def interesting(meta: dict) -> bool:
    """Что из проходов астероида достойно строки в календаре."""
    if meta["mag"] > MAG_LIMIT:
        return False
    sep, obj_mag = meta["sep_deg"], meta["object_mag"]
    if meta["kind"] == "star":
        return ((obj_mag <= 4.0 and sep <= 2.5) or (obj_mag <= 6.0 and sep <= 1.0)
                or sep <= 0.3)
    return (meta["messier"] or obj_mag <= 8.0) and sep <= 1.5


def _deduplicate(events: list[Event], hours: float = 24.0,
                 per_asteroid: int = 3) -> list[Event]:
    """Не больше per_asteroid строк на объект за месяц, самые тесные."""
    kept: list[Event] = []
    counts: dict[int, int] = {}
    for ev in sorted(events, key=lambda e: e.meta["sep_deg"]):
        number = ev.meta["number"]
        if counts.get(number, 0) >= per_asteroid:
            continue
        if any(other.meta["number"] == number
               and abs((other.when - ev.when).total_seconds()) < hours * 3600
               for other in kept):
            continue
        kept.append(ev)
        counts[number] = counts.get(number, 0) + 1
    return sorted(kept, key=lambda e: e.when)


def diameter_km(h_magnitude: float, albedo: float = 0.14) -> float:
    """Оценка диаметра по абсолютной величине H (стандартная формула)."""
    return 1329.0 / np.sqrt(albedo) * 10 ** (-0.2 * h_magnitude)


def close_approaches(start: dt.datetime, end: dt.datetime,
                     max_dist_au: float = 0.05,
                     min_diameter_km: float = 0.30,
                     close_dist_au: float = 0.005,
                     close_min_diameter_km: float = 0.05,
                     limit: int = 4) -> list[Event]:
    """Пролёты околоземных астероидов по данным CNEOS.

    Мимо Земли ежемесячно проходят десятки метровых камней — в календарь они не
    нужны. Событием считаем либо крупный объект (от 300 м), либо заметный
    (от 50 м), прошедший ближе 0.005 а.е. (~750 тыс. км). Из отобранного берём
    несколько самых крупных.
    """
    cache = cfg.CACHE / f"cad_{start:%Y%m}.json"
    if cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        r = requests.get(CAD_API, params={
            "date-min": start.strftime("%Y-%m-%d"),
            "date-max": end.strftime("%Y-%m-%d"),
            "dist-max": str(max_dist_au), "sort": "date"}, timeout=60)
        r.raise_for_status()
        payload = r.json()
        cache.write_text(json.dumps(payload), encoding="utf-8")

    fields = payload.get("fields", [])
    out = []
    for row in payload.get("data", []):
        record = dict(zip(fields, row))
        h = float(record["h"]) if record.get("h") else None
        if h is None:
            continue
        size = diameter_km(h)
        distance_au = float(record["dist"])
        big = size >= min_diameter_km
        close = size >= close_min_diameter_km and distance_au <= close_dist_au
        if not (big or close):
            continue
        when = dt.datetime.strptime(record["cd"], "%Y-%b-%d %H:%M").replace(
            tzinfo=dt.timezone.utc).astimezone(cfg.MSK)
        if not (start <= when < end):
            continue
        distance = distance_au * AU_KM
        size_text = (f"d≈{size * 1000:.0f} м" if size < 1
                     else f"d≈{size:.1f} км")
        out.append(Event(
            when=when,
            text=(f"Астероид {record['des']} ({size_text}) пролетает "
                  + (f"в {distance / 1e3:.0f} тыс. км от Земли" if distance < 1e6
                     else f"в {distance / 1e6:.1f} млн км от Земли")),
            category="asteroid",
            confidence="высокая",
            computed=(f"CNEOS Close Approach API: расстояние "
                      f"{distance_au:.5f} а.е., относительная скорость "
                      f"{float(record['v_rel']):.1f} км/с, H={h:.1f}m, "
                      f"диаметр по альбедо 0.14"),
            sources=["NASA/JPL CNEOS Close Approach Data API"],
            precision="hour",
            meta={"distance_km": distance, "h": h, "diameter_km": size},
        ))
    out.sort(key=lambda e: -e.meta["diameter_km"])
    return sorted(out[:limit], key=lambda e: e.when)


def all_events(start: dt.datetime, end: dt.datetime) -> list[Event]:
    return close_approaches(start, end) + approaches(start, end)
