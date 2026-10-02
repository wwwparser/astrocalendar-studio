"""Наблюдательное время сближения; минимум хранится отдельно."""
from __future__ import annotations

import datetime as dt
import numpy as np

from .core import body, observer, southern_observer, timescale, ts_range

MIN_ALTITUDE_DEG = 5.0
MAX_SUN_ALTITUDE_DEG = -6.0
MAX_SHIFT_HOURS = 18.0


def observing_time(when, target, companion, limit_deg, min_altitude=MIN_ALTITUDE_DEG):
    grid = ts_range(when - dt.timedelta(hours=MAX_SHIFT_HOURS),
                    when + dt.timedelta(hours=MAX_SHIFT_HOURS), 10)
    choices = []
    for city, site in (("Москва", observer()), ("Краснодар", southern_observer())):
        a = site.at(grid).observe(target).apparent()
        b = site.at(grid).observe(companion).apparent()
        alt = a.altaz()[0].degrees
        other_alt = b.altaz()[0].degrees
        sun = site.at(grid).observe(body("sun")).apparent().altaz()[0].degrees
        sep = a.separation_from(b).degrees
        good = ((alt >= min_altitude) & (other_alt >= min_altitude)
                & (sun <= MAX_SUN_ALTITUDE_DEG) & (sep <= limit_deg))
        indices = np.flatnonzero(good)
        if len(indices):
            distances = abs(grid.tt[indices] - timescale().from_datetime(when).tt)
            index = int(indices[np.argmin(distances)])
            choices.append((float(min(distances)), city, site, grid[index]))
    if not choices:
        return None
    _, city, site, t = min(choices, key=lambda x: x[0])
    return t, site, city


def direction_at(t, target, reference, site):
    ar, ad, _ = site.at(t).observe(target).apparent().radec()
    br, bd, _ = site.at(t).observe(reference).apparent().radec()
    dec = float(ad.degrees - bd.degrees)
    ra = float((ar.degrees - br.degrees + 180) % 360 - 180)
    ra *= np.cos(np.radians(float((ad.degrees + bd.degrees) / 2)))
    return ("восточнее" if ra > 0 else "западнее") if abs(ra) > abs(dec) else (
        "севернее" if dec > 0 else "южнее")
