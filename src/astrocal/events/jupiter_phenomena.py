"""Явления галилеевых спутников: прохождения, тени, затмения, покрытия.

За месяц таких явлений сотни, и вываливать их все в календарь бессмысленно.
Публикуется то, что действительно стоит смотреть: два спутника на диске
одновременно, две тени, спутник вместе со своей тенью, а из одиночных —
только хорошо наблюдаемые из России.

Геометрия считается напрямую по эфемеридам:

* **прохождение** — спутник проецируется на диск Юпитера со стороны Земли;
* **тень** — спутник проецируется на диск со стороны Солнца;
* **покрытие** — спутник за диском, если смотреть с Земли;
* **затмение** — спутник в тени планеты, если смотреть от Солнца.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from ..core import (Event, body, constellation_at, earth, observer, southern_observer,
                    timescale, to_msk, ts_range)
from ..fmt import magnitude, ru_constellation
from .jupiter_moons import MOON_RU, MOONS, satellite

JUPITER_RADIUS_KM = 71492.0
SUN_RADIUS_KM = 695700.0

PHENOMENON_RU = {
    "transit": "прохождение по диску",
    "shadow": "тень на диске",
    "occultation": "покрытие диском",
    "eclipse": "затмение в тени планеты",
}


@dataclass
class Phenomenon:
    kind: str
    moon: str
    start: dt.datetime
    end: dt.datetime

    @property
    def middle(self) -> dt.datetime:
        return self.start + (self.end - self.start) / 2

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


def _projected(position_moon, position_jupiter, viewpoint_distance_km):
    """Смещение спутника от центра диска в радиусах Юпитера и знак «перед/за»."""
    delta = position_moon - position_jupiter
    direction = position_jupiter / np.linalg.norm(position_jupiter, axis=0)
    along = np.einsum("ij,ij->j", delta, direction)
    perpendicular = delta - direction * along
    offset = np.linalg.norm(perpendicular, axis=0)
    # угловой радиус диска на расстоянии наблюдателя
    scale = JUPITER_RADIUS_KM * (1.0 - along / viewpoint_distance_km)
    return offset / scale, along


def phenomena(start: dt.datetime, end: dt.datetime,
              step_minutes: int = 4) -> list[Phenomenon]:
    """Все явления спутников за период."""
    grid = ts_range(start, end, step_minutes)
    e, sun = earth(), body("sun")
    jupiter = body("jupiter")

    jupiter_from_earth = e.at(grid).observe(jupiter).apparent().position.km
    jupiter_from_sun = sun.at(grid).observe(jupiter).position.km
    earth_distance = np.linalg.norm(jupiter_from_earth, axis=0)
    sun_distance = np.linalg.norm(jupiter_from_sun, axis=0)

    found: list[Phenomenon] = []
    for name, code in MOONS.items():
        target = satellite(code)
        from_earth = e.at(grid).observe(target).apparent().position.km
        from_sun = sun.at(grid).observe(target).position.km

        offset_earth, along_earth = _projected(from_earth, jupiter_from_earth,
                                               earth_distance)
        offset_sun, along_sun = _projected(from_sun, jupiter_from_sun, sun_distance)

        masks = {
            "transit": (offset_earth < 1.0) & (along_earth < 0),
            "occultation": (offset_earth < 1.0) & (along_earth > 0),
            "shadow": (offset_sun < 1.0) & (along_sun < 0),
            "eclipse": (offset_sun < 1.0) & (along_sun > 0),
        }
        for kind, mask in masks.items():
            for first, last in _runs(mask):
                found.append(Phenomenon(kind=kind, moon=name,
                                        start=to_msk(grid[first]),
                                        end=to_msk(grid[last])))
    return sorted(found, key=lambda item: item.start)


def _runs(mask) -> list[tuple[int, int]]:
    runs, index = [], 0
    while index < len(mask):
        if not mask[index]:
            index += 1
            continue
        finish = index
        while finish + 1 < len(mask) and mask[finish + 1]:
            finish += 1
        runs.append((index, finish))
        index = finish + 1
    return runs


def _observable(when: dt.datetime, min_altitude: float = 12.0) -> bool:
    """Виден ли Юпитер из России в этот момент на тёмном небе."""
    t = timescale().from_datetime(when)
    for site in (observer(), southern_observer()):
        altitude = float(site.at(t).observe(body("jupiter")).apparent()
                         .altaz()[0].degrees)
        sun_altitude = float(site.at(t).observe(body("sun")).apparent()
                             .altaz()[0].degrees)
        if altitude > min_altitude and sun_altitude < -8:
            return True
    return False


def combinations(items: list[Phenomenon]) -> list[dict]:
    """Найти совпадения по времени — ради них всё и затевалось."""
    result = []
    for index, first in enumerate(items):
        for second in items[index + 1:]:
            if second.start >= first.end:
                continue
            overlap_start = max(first.start, second.start)
            overlap_end = min(first.end, second.end)
            if (overlap_end - overlap_start).total_seconds() < 300:
                continue
            result.append({"a": first, "b": second,
                           "start": overlap_start, "end": overlap_end})
    return result


def describe_combination(pair: dict) -> str | None:
    a, b = pair["a"], pair["b"]
    kinds = {a.kind, b.kind}
    moons = f"{MOON_RU[a.moon]} и {MOON_RU[b.moon]}"

    if kinds == {"transit"}:
        return f"Два спутника ({moons}) одновременно проходят по диску Юпитера"
    if kinds == {"shadow"}:
        return f"Две тени ({moons}) одновременно на диске Юпитера"
    if kinds == {"transit", "shadow"}:
        transit = a if a.kind == "transit" else b
        shadow = a if a.kind == "shadow" else b
        if transit.moon == shadow.moon:
            return (f"Спутник {MOON_RU[transit.moon]} проходит по диску Юпитера "
                    f"вместе со своей тенью")
        return (f"Спутник {MOON_RU[transit.moon]} на диске Юпитера, "
                f"одновременно тень {MOON_RU[shadow.moon]}")
    return None


def all_events(start: dt.datetime, end: dt.datetime,
               min_duration_minutes: float = 20.0) -> list[Event]:
    """События календаря: редкие сочетания и заметные одиночные явления."""
    from ..magnitudes import planet_magnitude

    items = phenomena(start, end)
    ts = timescale()
    out: list[Event] = []
    used: set[int] = set()

    for pair in combinations(items):
        text = describe_combination(pair)
        if text is None:
            continue
        moment = pair["start"] + (pair["end"] - pair["start"]) / 2
        if not (start <= moment < end) or not _observable(moment):
            continue
        t = ts.from_datetime(moment)
        const = ru_constellation(constellation_at()(
            earth().at(t).observe(body("jupiter")).apparent()))
        out.append(Event(
            when=moment,
            text=(f"{text} ({magnitude(planet_magnitude('jupiter', t))}) "
                  f"в созвездии {const}"),
            category="jupiter_phenomena",
            rank="interesting",
            computed=(f"совпадение по времени {pair['start']:%d.%m %H:%M}–"
                      f"{pair['end']:%H:%M} МСК; расчёт проекции спутников на диск "
                      f"по эфемеридам jup380s"),
            sources=["Skyfield + JPL jup380s"],
            precision="hour",
            meta={"phenomenon": "combination"},
        ))
        used.add(id(pair["a"]))
        used.add(id(pair["b"]))

    # одиночные явления — только длинные и наблюдаемые, иначе календарь утонет
    for item in items:
        if id(item) in used or item.duration_minutes < min_duration_minutes:
            continue
        if item.kind not in ("transit", "shadow"):
            continue
        moment = item.middle
        if not (start <= moment < end) or not _observable(moment):
            continue
        t = ts.from_datetime(moment)
        const = ru_constellation(constellation_at()(
            earth().at(t).observe(body("jupiter")).apparent()))
        subject = ("Спутник " + MOON_RU[item.moon] if item.kind == "transit"
                   else "Тень спутника " + MOON_RU[item.moon])
        action = ("проходит по диску Юпитера" if item.kind == "transit"
                  else "на диске Юпитера")
        out.append(Event(
            when=moment,
            text=(f"{subject} {action} ({magnitude(planet_magnitude('jupiter', t))}) "
                  f"в созвездии {const}"),
            category="jupiter_phenomena",
            rank="optional",
            computed=(f"{PHENOMENON_RU[item.kind]}, {item.start:%d.%m %H:%M}–"
                      f"{item.end:%H:%M} МСК, длительность "
                      f"{item.duration_minutes:.0f} мин"),
            sources=["Skyfield + JPL jup380s"],
            precision="hour",
            meta={"phenomenon": item.kind, "moon": item.moon},
        ))
    return sorted(out, key=lambda event: event.when)
