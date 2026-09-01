"""Независимая сверка расчётов Skyfield с JPL Horizons.

Для каждого проверяемого момента запрашиваем у Horizons видимые геоцентрические
RA/Dec участвующих тел и сравниваем с тем, что даёт локальный расчёт по DE440s.
Расхождение в угловых секундах — объективная мера согласия двух источников.
"""
from __future__ import annotations

import datetime as dt

from .catalogs import angular_distance_deg
from .core import body, earth, timescale
from .horizons import CODES, query, rows


def horizons_radec(name: str, when_utc: dt.datetime):
    """Видимое геоцентрическое RA/Dec тела на момент when_utc.

    Запрашиваем именно ВИДИМЫЕ координаты (quantities=2): Skyfield по нашей
    цепочке даёт `.apparent()`, то есть с аберрацией и отклонением света, а
    астрометрические координаты Horizons отличаются от них примерно на 20″ —
    сравнивать их между собой бессмысленно.
    """
    minute = when_utc.replace(second=0, microsecond=0)
    start = minute.strftime("%Y-%m-%d %H:%M")
    stop = (minute + dt.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
    txt = query(CODES[name], start, stop, "1m", quantities="2")
    for r in rows(txt):
        vals = [c for c in r[1:] if c.strip()]
        try:
            return float(vals[-2]), float(vals[-1])
        except (ValueError, IndexError):
            continue
    raise RuntimeError(f"Horizons не вернул положение для {name}")


def compare(name: str, when_msk: dt.datetime) -> dict:
    """Расхождение Skyfield ↔ Horizons для одного тела, угловые секунды.

    Оба источника берутся на один и тот же момент, округлённый до минуты:
    Луна за минуту проходит 33″, и сравнение на разные эпохи давало бы
    расхождение там, где его нет.
    """
    ts = timescale()
    when_utc = when_msk.astimezone(dt.timezone.utc).replace(second=0, microsecond=0)
    t = ts.from_datetime(when_utc)
    # Horizons отдаёт видимые координаты в системе истинного экватора и
    # равноденствия даты, поэтому и Skyfield просим о том же (epoch=t):
    # без этого разница составляет прецессию от J2000, около 1350″.
    ra, dec, _ = earth().at(t).observe(body(name)).apparent().radec(epoch=t)
    h_ra, h_dec = horizons_radec(name, when_utc)
    delta = float(angular_distance_deg(ra.degrees, dec.degrees, h_ra, h_dec)) * 3600.0
    return {"body": name, "skyfield": (float(ra.degrees), float(dec.degrees)),
            "horizons": (h_ra, h_dec), "delta_arcsec": delta}


def separation_pair(a: str, b: str, when_msk: dt.datetime) -> dict:
    """Угловое расстояние между двумя телами по обоим источникам."""
    ca, cb = compare(a, when_msk), compare(b, when_msk)
    sky = float(angular_distance_deg(*ca["skyfield"], *cb["skyfield"]))
    hor = float(angular_distance_deg(*ca["horizons"], *cb["horizons"]))
    return {"pair": f"{a}–{b}", "skyfield_deg": sky, "horizons_deg": hor,
            "diff_arcsec": abs(sky - hor) * 3600.0,
            "delta_a_arcsec": ca["delta_arcsec"], "delta_b_arcsec": cb["delta_arcsec"]}
