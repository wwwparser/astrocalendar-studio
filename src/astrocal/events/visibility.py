"""Периоды видимости планет: начало и окончание утренней/вечерней видимости.

Критерий практический: смотрим, где находится планета в тот момент, когда
Солнце опускается на нужную глубину под горизонт (arcus visionis — она зависит
от блеска объекта). Если планета в этот момент выше 2°, считаем, что её видно.

Событием календаря считается первый день серии (после перерыва не меньше пяти
суток) и последний. Внутри серии ничего не публикуется: «Венера видна вечером»
каждый день — это не событие.

Это **редакционный критерий календаря**, а не абсолютная астрономическая
граница: другой наблюдатель с другим порогом получит дату на несколько суток
раньше или позже. Критерий целиком выписан в протоколе у каждой такой строки,
поэтому расхождение с чужим календарём всегда объяснимо.
"""
from __future__ import annotations

import datetime as dt

from ..core import Event, body, constellation_at, earth, observer, to_msk, ts_range
from ..fmt import magnitude, ru_constellation

PLANET_GEN = {
    "mercury": "Меркурия", "venus": "Венеры", "mars": "Марса", "jupiter": "Юпитера",
    "saturn": "Сатурна", "uranus": "Урана", "neptune": "Нептуна",
}
MIN_ALT_DEG = 2.0
NAKED_EYE = ("mercury", "venus", "mars", "jupiter", "saturn")

# Arcus visionis — насколько глубоко должно опуститься Солнце, чтобы объект
# данного блеска стал различим у горизонта. Венеру видно почти в сумерках,
# Марсу нужна настоящая ночь. Порог заметно двигает дату начала видимости,
# поэтому он вынесен в таблицу и указывается в протоколе.
ARCUS_VISIONIS = ((-3.0, -4.0), (-1.0, -5.0), (0.5, -8.0), (1.5, -10.0),
                  (99.0, -12.0))


def sun_limit_for(mag: float) -> float:
    for bound, limit in ARCUS_VISIONIS:
        if mag <= bound:
            return limit
    return -12.0


def _daily_windows(start: dt.datetime, end: dt.datetime, name: str,
                   sun_limit: float, step_minutes: int = 5):
    """Для каждых суток: видна ли планета утром и вечером.

    Критерий берём в момент, когда Солнце проходит нужную глубину погружения
    (arcus visionis), и смотрим, где в этот момент планета. Требовать «планета
    выше 5° и одновременно Солнце ниже −6°» нельзя: у Венеры в северных широтах
    в конце лета такого момента не бывает вовсе, хотя вечером её прекрасно видно
    в сумерках.
    """
    site = observer()
    grid = ts_range(start - dt.timedelta(days=8), end + dt.timedelta(days=8),
                    step_minutes)
    planet_alt = site.at(grid).observe(body(name)).apparent().altaz()[0].degrees
    sun_alt = site.at(grid).observe(body("sun")).apparent().altaz()[0].degrees
    moments = [to_msk(t) for t in grid]

    days: dict[dt.date, dict] = {}
    for i in range(len(grid) - 1):
        crossing_down = sun_alt[i] >= sun_limit > sun_alt[i + 1]
        crossing_up = sun_alt[i] <= sun_limit < sun_alt[i + 1]
        if not (crossing_down or crossing_up):
            continue
        when = moments[i]
        alt = float(planet_alt[i])
        if alt <= MIN_ALT_DEG:
            continue
        slot = "evening" if crossing_down else "morning"
        day = (when - dt.timedelta(hours=6)).date()   # ночь относим к её вечеру
        record = days.setdefault(day, {})
        if slot not in record or alt > record[slot][1]:
            record[slot] = (when, alt, i)
    return days


STABLE_DAYS = 3


def _series_edges(days: dict, slot: str, gap_days: int = 5,
                  stable_days: int = STABLE_DAYS):
    """Границы серий видимости: (день начала, день конца) для каждой серии.

    Требуем устойчивости: критерий должен выполняться stable_days суток подряд.
    У самой границы объект то проходит порог, то нет из-за погоды вычислений —
    высоты меняются на десятые доли градуса, — и без этого условия дата начала
    видимости прыгала бы на несколько суток от прогона к прогону.
    """
    present = sorted(d for d, rec in days.items() if slot in rec)
    if not present:
        return []
    runs, current = [], [present[0]]
    for day in present[1:]:
        if (day - current[-1]).days > gap_days:
            runs.append(current)
            current = [day]
        else:
            current.append(day)
    runs.append(current)
    return [(run[0], run[-1]) for run in runs if len(run) >= stable_days]


def all_events(start: dt.datetime, end: dt.datetime) -> list[Event]:
    from ..magnitudes import planet_magnitude
    from ..core import timescale

    ts = timescale()
    out: list[Event] = []
    mid = ts.from_datetime(start + (end - start) / 2)
    for name in NAKED_EYE:
        sun_limit = sun_limit_for(planet_magnitude(name, mid))
        days = _daily_windows(start, end, name, sun_limit)
        for slot, slot_ru in (("morning", "утренней"), ("evening", "вечерней")):
            for first, last in _series_edges(days, slot):
                for day, kind in ((first, "Начало"), (last, "Окончание")):
                    when, alt, _ = days[day][slot]
                    if not (start <= when < end):
                        continue
                    t = ts.from_datetime(when)
                    const = ru_constellation(constellation_at()(
                        earth().at(t).observe(body(name)).apparent()))
                    out.append(Event(
                        when=when,
                        text=(f"{kind} {slot_ru} видимости {PLANET_GEN[name]} "
                              f"({magnitude(planet_magnitude(name, t))}) "
                              f"в созвездии {const}"),
                        category="visibility",
                        confidence="средняя",
                        rank="interesting",
                        computed=(f"критерий: в момент, когда Солнце над Москвой "
                                  f"опускается до {sun_limit:.0f}° (arcus visionis по "
                                  f"блеску), планета выше {MIN_ALT_DEG:.0f}°; "
                                  f"фактическая высота {alt:.1f}°; "
                                  f"серия {first:%d.%m}–{last:%d.%m}, устойчиво "
                                  f"не менее {STABLE_DAYS} суток подряд"),
                        sources=["Skyfield/DE440s"],
                        precision="hour",
                        meta={"planet": name, "slot": slot, "kind": kind},
                    ))
    return out
