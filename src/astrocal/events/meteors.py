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

from ..core import Event, body, earth, find_zero, planets, timescale, to_msk, ts_range

# Рабочий список IMO: код, русское название, λ☉ максимума, ZHR, окно активности
SHOWERS = [
    ("AUR", "Ауригиды", 158.6, 6, "28.08–05.09"),
    ("SPE", "Сентябрьские эпсилон-Персеиды", 166.7, 5, "05.09–21.09"),
    ("DSX", "Дневные Секстантиды", 186.7, 5, "09.09–09.10"),
    ("STA", "Южные Таблиды (Тауриды)", 196.3, 5, "10.09–20.11"),
    ("ORI", "Ориониды", 208.0, 20, "02.10–07.11"),
    ("PER", "Персеиды", 140.0, 100, "17.07–24.08"),
    ("LYR", "Лириды", 32.32, 18, "16.04–25.04"),
    ("GEM", "Геминиды", 262.2, 150, "04.12–17.12"),
    ("QUA", "Квадрантиды", 283.15, 110, "28.12–12.01"),
    ("ETA", "Эта-Аквариды", 45.5, 50, "19.04–28.05"),
]


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
            out.append(Event(
                when=when,
                text=f"Максимум активности метеорного потока {name_ru}",
                category="meteors",
                confidence="средняя",
                computed=(f"λ☉ = {lam}° (J2000) достигается в "
                          f"{t.utc_strftime('%Y-%m-%d %H:%M UTC')}; ожидаемое ZHR ≈ {zhr}; "
                          f"активность {window}; фаза Луны {frac:.2f} "
                          f"({'растущая' if waxing else 'убывающая'}), {moon_note}"),
                sources=["IMO Meteor Shower Calendar (λ☉, ZHR)", "Skyfield/DE440s (момент)"],
                precision="hour",
                meta={"code": code, "zhr": zhr, "moon_illum": frac},
            ))
    return out
