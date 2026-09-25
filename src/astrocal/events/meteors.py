"""Метеорные потоки.

Максимум потока задаётся не датой, а долготой Солнца λ☉ (эпоха J2000) —
именно так публикует данные IMO. Момент максимума мы вычисляем: ищем, когда
видимая геоцентрическая эклиптическая долгота Солнца, отнесённая к равноденствию
J2000, равна табличной λ☉. Это даёт правильное время в конкретном году, а не
переписанную из прошлогоднего календаря дату.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
from skyfield import almanac

from ..core import (Event, body, earth, find_zero, observer, planets, timescale,
                    to_msk, ts_range)

# Рабочий список IMO: код, русское название, λ☉ максимума, ZHR, окно активности
# радиант: прямое восхождение и склонение в градусах (IMO)
RADIANTS = {
    "QUA": (230.0, 49.0), "LYR": (271.0, 34.0), "ETA": (338.0, -1.0),
    "SDA": (340.0, -16.0), "CAP": (307.0, -10.0), "PER": (46.2, 57.4),
    "KCG": (286.0, 59.0), "AUR": (91.0, 39.0), "SPE": (48.0, 40.0),
    "DSX": (152.0, 0.0), "DRA": (262.0, 54.0), "STA": (32.0, 9.0),
    "ORI": (95.0, 16.0), "NTA": (58.0, 22.0), "LEO": (152.0, 22.0),
    "GEM": (112.0, 33.0), "URS": (217.0, 76.0),
}

# Рабочий список IMO. Раньше здесь было десять потоков, и из-за этого из
# октябрьского выпуска выпали Дракониды — поток с вечерним максимумом,
# незаходящим радиантом и в 2026 году с новолунием. Список расширен до
# основных потоков года.
SHOWERS = [
    ("QUA", "Квадрантиды", 283.15, 110, "28.12–12.01"),
    ("LYR", "Лириды", 32.32, 18, "16.04–25.04"),
    ("ETA", "Эта-Аквариды", 45.5, 50, "19.04–28.05"),
    ("SDA", "Южные дельта-Аквариды", 125.0, 25, "12.07–23.08"),
    ("CAP", "Альфа-Каприкорниды", 127.0, 5, "03.07–15.08"),
    ("PER", "Персеиды", 140.0, 100, "17.07–24.08"),
    ("KCG", "Каппа-Лебедиды", 145.0, 3, "03.08–25.08"),
    ("AUR", "Ауригиды", 158.6, 6, "28.08–05.09"),
    ("SPE", "Сентябрьские эпсилон-Персеиды", 166.7, 5, "05.09–21.09"),
    ("DSX", "Дневные Секстантиды", 186.7, 5, "09.09–09.10"),
    ("DRA", "Дракониды", 195.4, 10, "06.10–10.10"),
    ("STA", "Южные Таблиды (Тауриды)", 196.3, 5, "10.09–20.11"),
    ("ORI", "Ориониды", 208.0, 20, "02.10–07.11"),
    ("NTA", "Северные Таблиды (Тауриды)", 230.0, 5, "20.10–10.12"),
    ("LEO", "Леониды", 235.27, 10, "06.11–30.11"),
    ("GEM", "Геминиды", 262.2, 150, "04.12–17.12"),
    ("URS", "Урсиды", 270.7, 10, "17.12–26.12"),
]

# Потоки с непостоянной активностью: числовое ZHR у них — ориентир, а не
# обещание. Дракониды в год вспышки давали тысячи метеоров в час, а в обычный
# год — единицы.
VARIABLE = {"DRA", "CAP", "KCG"}


def solar_longitude_j2000(t) -> float:
    """Видимая геоцентрическая эклиптическая долгота Солнца в системе J2000."""
    ts = timescale()
    lat, lon, _ = earth().at(t).observe(body("sun")).apparent().ecliptic_latlon(ts.J2000)
    return lon.degrees


def all_events(start: dt.datetime, end: dt.datetime) -> list[Event]:
    ts = timescale()
    grid = ts_range(start, end, 360)
    lon = np.array([solar_longitude_j2000(t) for t in grid])
    eph = planets()
    out = []
    for code, name_ru, lam, zhr, window in SHOWERS:
        target = (lon - lam + 180.0) % 360.0 - 180.0
        for i in range(len(target) - 1):
            if abs(target[i]) > 5 or (target[i] > 0) == (target[i + 1] > 0):
                continue
            tt = find_zero(
                lambda x: (solar_longitude_j2000(ts.tt_jd(x)) - lam + 180.0) % 360.0 - 180.0,
                grid[i].tt, grid[i + 1].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            if not (start <= when < end):
                continue
            frac = float(almanac.fraction_illuminated(eph, "moon", t))
            waxing = bool(almanac.moon_phase(eph, t).degrees < 180.0)
            moon_note = ("Луна не мешает" if frac < 0.35
                         else "яркая Луна засвечивает небо" if frac > 0.7
                         else "Луна частично мешает")
            observing = radiant_conditions(code, when, frac)
            out.append(Event(
                when=when,
                text=f"Максимум активности метеорного потока {name_ru}",
                category="meteors",
                confidence="средняя",
                computed=(f"λ☉ = {lam}° (J2000) достигается в "
                          f"{t.utc_strftime('%Y-%m-%d %H:%M UTC')}; ожидаемое ZHR ≈ {zhr}"
                          + (" (активность непостоянна, в разные годы отличается "
                             "в разы)" if code in VARIABLE else "")
                          + f"; активность {window}; фаза Луны {frac:.2f} "
                          f"({'растущая' if waxing else 'убывающая'}), {moon_note}"
                          + (f". {observing['summary']}" if observing else "")),
                sources=["IMO Meteor Shower Calendar (λ☉, ZHR)", "Skyfield/DE440s (момент)"],
                precision="hour",
                meta={"code": code, "zhr": zhr, "moon_illum": frac,
                      "observing": observing},
            ))
    return out


def radiant_conditions(code: str, when: dt.datetime, moon_illumination: float,
                       min_altitude: float = 20.0) -> dict | None:
    """Практические условия наблюдения потока: радиант, окно, помеха Луны.

    Максимум активности сам по себе мало что говорит: поток видно тогда, когда
    радиант достаточно высоко и небо тёмное. Считаем окно на ночь максимума.
    """
    from skyfield.api import Star

    coordinates = RADIANTS.get(code)
    if coordinates is None:
        return None
    ra, dec = coordinates
    radiant = Star(ra_hours=ra / 15.0, dec_degrees=dec)
    site = observer()

    night_start = when.replace(hour=18, minute=0, second=0, microsecond=0)
    grid = ts_range(night_start, night_start + dt.timedelta(hours=14), 10)
    altitude = site.at(grid).observe(radiant).apparent().altaz()[0].degrees
    sun_altitude = site.at(grid).observe(body("sun")).apparent().altaz()[0].degrees
    moon_altitude = site.at(grid).observe(body("moon")).apparent().altaz()[0].degrees

    good = (altitude > min_altitude) & (sun_altitude < -12)
    if not good.any():
        return {"summary": "радиант не поднимается достаточно высоко на тёмном небе",
                "max_altitude": float(np.max(altitude)), "window": None}

    indices = np.where(good)[0]
    window_start, window_end = to_msk(grid[indices[0]]), to_msk(grid[indices[-1]])
    best = int(indices[np.argmax(altitude[indices])])
    moon_up = bool(np.any(moon_altitude[indices] > 0))
    interference = ("Луна под горизонтом" if not moon_up
                    else "Луна почти не мешает" if moon_illumination < 0.3
                    else "Луна подсвечивает небо" if moon_illumination < 0.65
                    else "яркая Луна сильно мешает")
    stars = 4 if (not moon_up or moon_illumination < 0.3) else \
        (3 if moon_illumination < 0.65 else 2)
    if altitude[best] > 55:
        stars = min(5, stars + 1)

    return {
        "summary": (f"лучшее время {window_start:%H:%M}–{window_end:%H:%M} МСК, "
                    f"радиант поднимается до {altitude[best]:.0f}°, {interference}, "
                    f"условия {'★' * stars}"),
        "window": (window_start, window_end),
        "max_altitude": float(altitude[best]),
        "moon_interference": interference,
        "stars": stars,
    }
