"""Конфигурации галилеевых спутников: все четыре с одной стороны от Юпитера.

Сторона определяется знаком смещения спутника по прямому восхождению
(с поправкой cos δ) относительно центра диска Юпитера: положительное — восточнее.
Момент для календаря выбираем внутри окна наблюдаемости из Москвы
(Юпитер выше 10°, Солнце ниже −6°).
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from ..core import (Event, body, constellation_at, earth, jupiter_moons, observer,
                    to_msk, ts_range)
from ..fmt import magnitude, ru_constellation

MOONS = {"io": 501, "europa": 502, "ganymede": 503, "callisto": 504}
MOON_RU = {"io": "Ио", "europa": "Европа", "ganymede": "Ганимед", "callisto": "Каллисто"}


def satellite(code: int):
    """Вектор «барицентр Юпитера + сегмент спутника» из jup380s."""
    from ..core import planets
    for seg in jupiter_moons().segments:
        if seg.target == code and seg.center == 5:
            return planets()["jupiter barycenter"] + seg
    raise KeyError(f"в jup380s нет сегмента 5->{code}")


def _offsets(grid):
    """Смещения четырёх спутников по востоку от Юпитера, угловые секунды."""
    e = earth()
    jup = e.at(grid).observe(body("jupiter")).apparent()
    j_ra, j_dec, _ = jup.radec()
    result = {}
    for name, code in MOONS.items():
        sat = satellite(code)
        pos = e.at(grid).observe(sat).apparent()
        s_ra, s_dec, _ = pos.radec()
        d_ra = (s_ra.degrees - j_ra.degrees + 180.0) % 360.0 - 180.0
        result[name] = d_ra * np.cos(np.radians(j_dec.degrees)) * 3600.0
    return result


def _observable_mask(grid):
    site = observer()
    jup_alt = site.at(grid).observe(body("jupiter")).apparent().altaz()[0].degrees
    sun_alt = site.at(grid).observe(body("sun")).apparent().altaz()[0].degrees
    return (jup_alt > 10.0) & (sun_alt < -6.0)


def all_events(start: dt.datetime, end: dt.datetime,
               step_minutes: int = 10) -> list[Event]:
    from ..magnitudes import planet_magnitude

    grid = ts_range(start, end, step_minutes)
    off = _offsets(grid)
    stack = np.vstack([off[m] for m in MOONS])
    all_east = np.all(stack > 0, axis=0)
    all_west = np.all(stack < 0, axis=0)
    visible = _observable_mask(grid)

    out: list[Event] = []
    for side, mask in (("восточнее", all_east), ("западнее", all_west)):
        i = 0
        n = len(mask)
        while i < n:
            if not mask[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            window = np.arange(i, j + 1)
            good = window[visible[window]]
            if len(good):
                k = int(good[0])   # начало окна наблюдаемости конфигурации
                t = grid[k]
                const = ru_constellation(constellation_at()(
                    earth().at(t).observe(body("jupiter")).apparent()))
                sep = ", ".join(
                    f"{MOON_RU[m]} {off[m][k]:+.0f}″" for m in MOONS)
                out.append(Event(
                    when=to_msk(t),
                    text=(f"Все 4 Галилеевы спутника окажутся {side} Юпитера "
                          f"({magnitude(planet_magnitude('jupiter', t))})"),
                    category="jupiter_moons",
                    computed=(f"интервал {to_msk(grid[i]):%d.%m %H:%M}–"
                              f"{to_msk(grid[j]):%d.%m %H:%M} МСК, момент выбран внутри "
                              f"окна наблюдаемости из Москвы; смещения: {sep}"),
                    sources=["Skyfield + JPL jup380s"],
                    precision="hour",
                    notes=f"созвездие {const}",
                ))
            i = j + 1
    return out
