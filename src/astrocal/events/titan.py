"""Титан относительно Сатурна.

Эфемериды Титана берём из JPL Horizons: компактного BSP с крупными спутниками
Сатурна нет (полные ядра — сотни мегабайт), а Horizons даёт то же семейство
решений (sat441/sat452) без загрузки файла.

Календарное событие — прохождение Титана севернее/южнее Сатурна (момент, когда
разность прямых восхождений меняет знак) и наибольшая восточная/западная
элонгация.
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from ..core import Event, body, constellation_at, earth, observer, timescale
from ..apparent import planet_label
from ..fmt import magnitude, ru_constellation
from ..horizons import CODES, query, rows

TITAN_MAG = 8.4    # среднее значение, Титан меняется в пределах 8.2–9.0m


def _series(code: str, start: dt.datetime, end: dt.datetime, step: str = "20m"):
    txt = query(code, start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"),
                step, quantities="1")
    out = []
    for r in rows(txt):
        # Date, (solar presence), (lunar presence), RA, DEC
        vals = [c for c in r[1:] if c not in ("", "*", "m", "t", "N", "A", "C", "r")]
        try:
            ra, dec = float(vals[-2]), float(vals[-1])
        except (ValueError, IndexError):
            continue
        stamp = dt.datetime.strptime(r[0], "%Y-%b-%d %H:%M").replace(tzinfo=dt.timezone.utc)
        out.append((stamp, ra, dec))
    return out


def all_events(start: dt.datetime, end: dt.datetime) -> list[Event]:
    from ..config import MSK

    pad_start = start - dt.timedelta(days=1)
    pad_end = end + dt.timedelta(days=1)
    titan = _series(CODES["titan"], pad_start, pad_end)
    saturn = _series(CODES["saturn"], pad_start, pad_end)
    if not titan or len(titan) != len(saturn):
        return []

    ts = timescale()
    times = np.array([t[0] for t in titan])
    d_ra = np.array([(a[1] - b[1] + 180.0) % 360.0 - 180.0 for a, b in zip(titan, saturn)])
    d_dec = np.array([a[2] - b[2] for a, b in zip(titan, saturn)])
    cosd = np.cos(np.radians([b[2] for b in saturn]))
    x = d_ra * cosd * 3600.0     # восток, угловые секунды
    y = d_dec * 3600.0           # север, угловые секунды

    site = observer()
    out: list[Event] = []
    for i in range(len(x) - 1):
        if (x[i] > 0) == (x[i + 1] > 0):
            continue
        # линейная интерполяция момента пересечения
        w = abs(x[i]) / (abs(x[i]) + abs(x[i + 1]))
        moment = times[i] + (times[i + 1] - times[i]) * w
        when = moment.astimezone(MSK)
        if not (start <= when < end):
            continue
        # Момент пересечения нередко приходится на светлое время или на период,
        # когда Сатурн ещё под горизонтом. Сдвигаем событие вперёд до первого
        # наблюдаемого из Москвы момента, пока Титан ещё почти на одной линии
        # с планетой (|ΔRA| < 60″).
        k = i
        while True:
            t = ts.from_datetime(times[k])
            alt = site.at(t).observe(body("saturn")).apparent().altaz()[0].degrees
            sun_alt = site.at(t).observe(body("sun")).apparent().altaz()[0].degrees
            if alt >= 5 and sun_alt <= -6:
                break
            k += 1
            if k >= len(x) or abs(x[k]) > 60.0:
                k = None
                break
        if k is None:
            continue
        when = times[k].astimezone(MSK) if k != i else when
        if not (start <= when < end):
            continue
        north = y[k] > 0
        i = k
        const = ru_constellation(constellation_at()(
            earth().at(t).observe(body("saturn")).apparent()))
        sep = float(np.hypot(x[i], y[i]))
        out.append(Event(
            when=when,
            text=(f"Спутник Титан ({magnitude(TITAN_MAG)}) расположен "
                  f"{'севернее' if north else 'южнее'} Сатурна "
                  f"({planet_label('saturn', t)}) в {limb_text(sep, t)}, "
                  f"созвездие {const}"),
            category="saturn_moons",
            computed=(f"смена знака ΔRA·cosδ Титан–Сатурн; разделение от центра "
                      f"диска {sep:.0f}″, от края диска "
                      f"{sep - saturn_radius_arcsec(t):.0f}″, "
                      f"Δ по склонению {y[i]:+.0f}″; "
                      f"высота Сатурна из Москвы {alt:.0f}°"),
            sources=["JPL Horizons (sat-эфемериды)", "Skyfield/DE440s (Сатурн, видимость)"],
            precision="hour",
        ))
    return out


def saturn_radius_arcsec(t) -> float:
    """Видимый радиус диска Сатурна без колец, угловые секунды."""
    from ..apparent import angular_diameter_arcsec

    return angular_diameter_arcsec("saturn", t) / 2.0


def limb_text(separation_arcsec: float, t) -> str:
    """«19″ от края диска» — наблюдателю важно расстояние до лимба, а не до центра.

    Диск Сатурна занимает около двадцати угловых секунд, и при разделении в
    29″ Титан стоит от края всего в девяти: расстояние от центра эту картину
    передаёт плохо.
    """
    from ..fmt import number

    limb = separation_arcsec - saturn_radius_arcsec(t)
    if limb <= 0:
        return "проекции на диск планеты"
    return f"{number(limb)}″ от края диска"
