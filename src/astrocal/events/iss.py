"""Пролёты МКС: начало периодов вечерней/утренней видимости.

Считаем по свежему TLE с Celestrak: видимый пролёт — станция выше 20°, освещена
Солнцем и наблюдатель в сумерках/ночью. Периоды видимости чередуются примерно
раз в месяц, и календарю нужен именно первый вечер (или утро) серии.

Важное ограничение: TLE стареет. Дальше ~10 суток от эпохи элементов прогноз
теряет точность по времени пролёта, поэтому такие события помечаются пониженной
уверенностью, а не публикуются как точные.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
from skyfield.api import EarthSatellite, wgs84

from .. import config as cfg
from ..core import Event, body, planets, timescale, to_msk, ts_range
from ..fmt import MONTHS_GEN

# Обе обитаемые станции. У них разное наклонение орбиты, поэтому и площадка
# наблюдения разная: МКС (i=51.6°) хорошо видна из Москвы, а китайская станция
# (i=41.5°) севернее 50° поднимается совсем низко — её смотрят с юга страны.
STATIONS = {
    25544: {"label": "МКС", "cache": "iss_tle.txt", "min_alt": 20.0,
            "lat": 55.76, "lon": 37.62, "where": "над Европейской частью России"},
    48274: {"label": "ККС", "cache": "css_tle.txt", "min_alt": 15.0,
            "lat": 47.24, "lon": 39.71,
            "where": "над югом Европейской части России"},
}
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=tle"


def load_tle(catnr: int, max_age_hours: float = 24.0) -> EarthSatellite | None:
    ts = timescale()
    cache = cfg.CACHE / STATIONS[catnr]["cache"]
    fresh = (cache.exists() and
             dt.datetime.now().timestamp() - cache.stat().st_mtime <
             max_age_hours * 3600)
    if not fresh:
        try:
            import requests
            r = requests.get(TLE_URL.format(catnr=catnr), timeout=30)
            r.raise_for_status()
            if r.text.strip():
                cache.write_text(r.text, encoding="utf-8")
        except Exception:
            if not cache.exists():
                return None
    lines = [ln.strip() for ln in cache.read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    if len(lines) < 3:
        return None
    return EarthSatellite(lines[1], lines[2], lines[0], ts)


def visible_passes(sat: EarthSatellite, start: dt.datetime, end: dt.datetime,
                   lat: float, lon: float, min_alt: float = 20.0,
                   step_minutes: int = 1):
    """Список видимых пролётов: (время максимума, максимальная высота)."""
    site = wgs84.latlon(lat, lon)
    grid = ts_range(start, end, step_minutes)
    topocentric = (sat - site).at(grid)
    alt = topocentric.altaz()[0].degrees
    sunlit = sat.at(grid).is_sunlit(planets())
    observer = planets()["earth"] + site
    sun_alt = observer.at(grid).observe(body("sun")).apparent().altaz()[0].degrees
    good = (alt > min_alt) & sunlit & (sun_alt < -6.0) & (sun_alt > -18.0)

    passes = []
    i = 0
    while i < len(good):
        if not good[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(good) and good[j + 1]:
            j += 1
        k = i + int(np.argmax(alt[i:j + 1]))
        passes.append((to_msk(grid[k]), float(alt[k])))
        i = j + 1
    return passes


# Срок годности TLE. Дальше трёх суток от эпохи элементов время пролёта уже
# гуляет на минуты, дальше десяти — на десятки минут и на сутки по дате начала
# серии. Поэтому месячный календарь публикует ПЕРИОД, а точное время выдаётся
# отдельно и только по свежим элементам (scripts/refresh_passes.py).
EXACT_TIME_MAX_AGE_DAYS = 3
PUBLISHABLE_MAX_AGE_DAYS = 10


def series(passes, gap_days: int = 5):
    """Разбить пролёты на серии видимости."""
    if not passes:
        return []
    groups, current = [], [passes[0]]
    for item in passes[1:]:
        if (item[0] - current[-1][0]).days >= gap_days:
            groups.append(current)
            current = [item]
        else:
            current.append(item)
    groups.append(current)
    return groups


def all_events(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Периоды видимости станций.

    Месячный календарь не обещает минуту пролёта: элементы орбиты к дате
    публикации всё равно устареют. Он называет период, а точный список
    генерируется за 2–3 суток до события по свежему TLE.
    """
    out: list[Event] = []
    for catnr, station in STATIONS.items():
        label, where = station["label"], station["where"]
        sat = load_tle(catnr)
        if sat is None:
            continue
        epoch = to_msk(sat.epoch)
        passes = visible_passes(sat, start, end, station["lat"], station["lon"],
                                station["min_alt"])
        for group in series(passes):
            first_when, first_alt = group[0]
            last_when, _ = group[-1]
            if first_when < start + dt.timedelta(days=1):
                continue        # серия началась в прошлом месяце
            age_days = abs((first_when - epoch).days)
            if age_days > PUBLISHABLE_MAX_AGE_DAYS:
                confidence, rank = "низкая", "technical"
            elif age_days > EXACT_TIME_MAX_AGE_DAYS:
                confidence, rank = "средняя", "interesting"
            else:
                confidence, rank = "высокая", "interesting"

            evening = 12 <= first_when.hour < 24
            best = max(group, key=lambda item: item[1])
            if age_days <= EXACT_TIME_MAX_AGE_DAYS:
                text = (f"Начало {'вечерней' if evening else 'утренней'} видимости "
                        f"пролётов {label} {where}")
                precision = "minute"
            else:
                text = (f"Период {'вечерней' if evening else 'утренней'} видимости "
                        f"пролётов {label} {where}: "
                        f"{first_when:%d}–{last_when:%d} {MONTHS_GEN[start.month]}, "
                        f"лучший пролёт {best[0]:%d} числа, "
                        f"высота до {best[1]:.0f}°")
                precision = "hour"

            out.append(Event(
                when=first_when,
                text=text,
                category="iss",
                confidence=confidence,
                rank=rank,
                computed=(f"серия {first_when:%d.%m}–{last_when:%d.%m}, пролётов "
                          f"{len(group)}, первый с максимальной высотой "
                          f"{first_alt:.0f}° (площадка {station['lat']:.1f}°N, "
                          f"{station['lon']:.1f}°E, порог {station['min_alt']:.0f}°); "
                          f"эпоха TLE {epoch:%Y-%m-%d %H:%M} МСК, возраст на дату "
                          f"события {age_days} сут"),
                sources=[f"Celestrak TLE {catnr}", "Skyfield SGP4"],
                precision=precision,
                notes=("точное время пролёта пересчитать за 2–3 суток до даты: "
                       "scripts/refresh_passes.py"
                       if age_days > EXACT_TIME_MAX_AGE_DAYS else ""),
                meta={"max_alt": best[1], "tle_age_days": age_days,
                      "station": label, "series": (first_when, last_when),
                      "passes": len(group)},
                provenance={"tle_epoch_msk": epoch.isoformat(),
                            "tle_age_days": age_days,
                            "exact_time_published": age_days <= EXACT_TIME_MAX_AGE_DAYS},
            ))
    return out
