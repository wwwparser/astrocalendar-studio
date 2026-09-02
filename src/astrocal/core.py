"""Загрузка эфемерид и базовые примитивы."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from skyfield.api import load, load_file, wgs84
from skyfield.constants import DAY_S

from . import config as cfg

# ---------------------------------------------------------------- эфемериды


@lru_cache(maxsize=1)
def timescale():
    return load.timescale()


@lru_cache(maxsize=1)
def planets():
    return load_file(str(cfg.EPH_PLANETS))


@lru_cache(maxsize=1)
def jupiter_moons():
    return load_file(str(cfg.EPH_JUPSAT))


@lru_cache(maxsize=1)
def constellation_at():
    from skyfield.api import load_constellation_map
    return load_constellation_map()


@lru_cache(maxsize=1)
def observer():
    """Топоцентрический наблюдатель (Москва) — для покрытий и видимости."""
    return planets()["earth"] + wgs84.latlon(cfg.SITE_LAT, cfg.SITE_LON, cfg.SITE_ELEV_M)


@lru_cache(maxsize=1)
def southern_observer():
    """Вторая площадка — юг Европейской части России (Краснодар)."""
    return planets()["earth"] + wgs84.latlon(cfg.SOUTH_LAT, cfg.SOUTH_LON,
                                             cfg.SOUTH_ELEV_M)


def earth():
    return planets()["earth"]


BODY_KEYS = {
    "mercury": "mercury barycenter",
    "venus": "venus barycenter",
    "mars": "mars barycenter",
    "jupiter": "jupiter barycenter",
    "saturn": "saturn barycenter",
    "uranus": "uranus barycenter",
    "neptune": "neptune barycenter",
    "sun": "sun",
    "moon": "moon",
}


def body(name: str):
    return planets()[BODY_KEYS[name]]


# ---------------------------------------------------------------- время


def to_msk(t) -> dt.datetime:
    """Skyfield Time -> aware datetime в МСК."""
    return t.utc_datetime().astimezone(cfg.MSK)


def ts_range(start: dt.datetime, end: dt.datetime, step_minutes: float):
    """Равномерная сетка Time между двумя aware-datetime."""
    ts = timescale()
    t0, t1 = ts.from_datetime(start), ts.from_datetime(end)
    n = int(round((t1.tt - t0.tt) * 1440.0 / step_minutes)) + 1
    return ts.tt_jd(np.linspace(t0.tt, t1.tt, n))


def round_to_minute(when: dt.datetime) -> dt.datetime:
    return (when + dt.timedelta(seconds=30)).replace(second=0, microsecond=0)


# ---------------------------------------------------------------- события


@dataclass
class Event:
    """Одно событие календаря + всё нужное для протокола проверки."""
    when: dt.datetime               # МСК, aware
    text: str                       # готовая строка без маркера
    category: str                   # moon / planet / jupiter_moons / comet / ...
    confidence: str = "высокая"     # высокая / средняя / низкая
    computed: str = ""              # что именно посчитано (для протокола)
    sources: list[str] = field(default_factory=list)
    notes: str = ""
    precision: str = "minute"       # minute | hour — до чего округляем в выводе
    meta: dict = field(default_factory=dict)   # служебные данные для фильтров
    rank: str = "interesting"       # must | interesting | optional | technical
    provenance: dict = field(default_factory=dict)   # источник, версия, время расчёта
    flags: list = field(default_factory=list)        # результаты проверок, в т.ч. REVIEW

    @property
    def display_time(self) -> dt.datetime:
        w = round_to_minute(self.when)
        if self.precision == "hour":
            w = (w + dt.timedelta(minutes=30)).replace(minute=0)
        return w

    def line(self) -> str:
        from .fmt import date_time_msk
        return f"▪️{date_time_msk(self.display_time)} — {self.text}"

    @property
    def event_id(self) -> str:
        """Устойчивый идентификатор события.

        Нужен, чтобы редакторская правка пережила пересчёт по свежим данным.
        Берём категорию, дату и «скелет» текста без чисел: время события может
        сдвинуться на час, блеск — на десятую величины, но «покрытие Венеры
        Луной 14 сентября» останется тем же событием.
        """
        import hashlib
        import re

        skeleton = re.sub(r"[-+]?\d+[.,]?\d*", "", self.text)
        skeleton = re.sub(r"\s+", " ", skeleton).strip().lower()
        key = f"{self.category}|{self.when:%Y-%m-%d}|{skeleton}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    def fingerprint(self) -> str:
        """Отпечаток вычисленных значений — меняется при пересчёте по новым данным."""
        import hashlib
        return hashlib.sha1(
            f"{self.when.isoformat()}|{self.text}".encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- геометрия


def separation_deg(t, a, b, center=None) -> np.ndarray:
    """Видимое угловое расстояние между двумя телами, градусы."""
    c = center if center is not None else earth()
    pa = c.at(t).observe(a).apparent()
    pb = c.at(t).observe(b).apparent()
    return pa.separation_from(pb).degrees


def local_minima(times, values):
    """Индексы локальных минимумов на сетке."""
    v = np.asarray(values)
    if len(v) < 3:
        return []
    inner = np.where((v[1:-1] < v[:-2]) & (v[1:-1] <= v[2:]))[0] + 1
    return list(inner)


def refine_minimum(func, t_lo, t_hi, iterations: int = 60):
    """Золотое сечение по TT-дням: находит минимум func(tt) на [t_lo, t_hi]."""
    phi = (np.sqrt(5.0) - 1.0) / 2.0
    a, b = t_lo, t_hi
    c, d = b - phi * (b - a), a + phi * (b - a)
    fc, fd = func(c), func(d)
    for _ in range(iterations):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = func(c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = func(d)
        if (b - a) * DAY_S < 1.0:      # точность 1 секунда
            break
    return (a + b) / 2.0


def find_zero(func, t_lo, t_hi, iterations: int = 60):
    """Бисекция по TT-дням для смены знака func."""
    f_lo = func(t_lo)
    a, b = t_lo, t_hi
    for _ in range(iterations):
        m = (a + b) / 2.0
        fm = func(m)
        if (fm < 0) == (f_lo < 0):
            a, f_lo = m, fm
        else:
            b = m
        if (b - a) * DAY_S < 1.0:
            break
    return (a + b) / 2.0
