"""Астрономия для конкретной площадки: где что находится в данный момент.

Весь счёт делает ядро `astrocal` (Skyfield, эфемериды de440s и jup380s,
каталоги Hipparcos и OpenNGC). Здесь только наблюдательная обвязка: перевод в
горизонтальные координаты для площадки, снимок неба целиком и траектории.

Вся тяжёлая математика остаётся в Python. В JavaScript уходит уже готовый
снимок: азимут, высота, блеск. Пересчёт запускается при смене времени, места
или прибора, а не на каждом кадре анимации.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from ..models.observer import ObserverProfile
from ..models.target import (ASTEROID, COMET, JUPITER_MOON, MOON, PLANET, SUN,
                             Target)

PLANET_NAMES_RU = {
    "mercury": "Меркурий", "venus": "Венера", "mars": "Марс",
    "jupiter": "Юпитер", "saturn": "Сатурн", "uranus": "Уран",
    "neptune": "Нептун",
}

# Уран и Нептун в бинокль видны, но как звёзды: включаем — их приятно «поймать».
PLANET_ORDER = ["mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune"]

JUPITER_MOONS_RU = {"io": "Ио", "europa": "Европа",
                    "ganymede": "Ганимед", "callisto": "Каллисто"}

# Видимые угловые диаметры планет меняются, но для бинокля важен порядок
# величины: диск Юпитера различим, диск Марса — почти нет.
PLANET_DISK_ARCMIN = {
    "mercury": 0.15, "venus": 0.5, "mars": 0.25, "jupiter": 0.7,
    "saturn": 0.6, "uranus": 0.06, "neptune": 0.04,
}


@dataclass
class Position:
    """Положение цели на небе в конкретный момент."""

    target_id: str
    name: str
    kind: str
    azimuth_deg: float
    altitude_deg: float
    magnitude: float | None = None
    size_arcmin: float | None = None
    constellation: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.target_id, "name": self.name, "kind": self.kind,
            "az": round(self.azimuth_deg, 3), "alt": round(self.altitude_deg, 3),
            "mag": None if self.magnitude is None else round(self.magnitude, 2),
            "size": self.size_arcmin,
            "constellation": self.constellation,
            **self.extra,
        }


# ---------------------------------------------------------------- время

def to_skyfield(when: dt.datetime):
    from astrocal.core import timescale
    if when.tzinfo is None:
        raise ValueError("момент времени должен быть с часовым поясом")
    return timescale().from_datetime(when)


def time_grid(start: dt.datetime, end: dt.datetime, step_minutes: float):
    from astrocal.core import ts_range
    return ts_range(start, end, step_minutes)


# ---------------------------------------------------------------- звёзды

@lru_cache(maxsize=4)
def star_table(mag_limit: float = 6.5):
    """Яркие звёзды Hipparcos: (hip, блеск, RA, Dec) в виде массивов."""
    from astrocal.catalogs import bright_stars
    frame = bright_stars(mag_limit=mag_limit)
    return (frame.hip.to_numpy(), frame.magnitude.to_numpy(),
            frame.ra_degrees.to_numpy(), frame.dec_degrees.to_numpy())


@lru_cache(maxsize=4)
def _star_object(mag_limit: float):
    from skyfield.api import Star
    _, _, ra, dec = star_table(mag_limit)
    return Star(ra_hours=ra / 15.0, dec_degrees=dec)


def star_altaz(observer: ObserverProfile, when: dt.datetime,
               mag_limit: float = 6.5) -> tuple[np.ndarray, np.ndarray]:
    site = observer.topos()
    t = to_skyfield(when)
    altitude, azimuth, _ = site.at(t).observe(_star_object(mag_limit)).apparent().altaz()
    return altitude.degrees, azimuth.degrees


# ---------------------------------------------------------------- каталожные цели

def fixed_altaz(observer: ObserverProfile, targets, when: dt.datetime):
    """Высота и азимут набора целей с фиксированными координатами."""
    from skyfield.api import Star

    ra = np.array([t.ra_deg for t in targets], dtype=float)
    dec = np.array([t.dec_deg for t in targets], dtype=float)
    if len(ra) == 0:
        return np.zeros(0), np.zeros(0)
    star = Star(ra_hours=ra / 15.0, dec_degrees=dec)
    altitude, azimuth, _ = observer.topos().at(
        to_skyfield(when)).observe(star).apparent().altaz()
    return altitude.degrees, azimuth.degrees


def coarse_altaz_grid(observer: ObserverProfile, ra_deg, dec_deg, times):
    """Высота и азимут набора целей сразу на наборе моментов, форма (цели, моменты).

    Skyfield не умеет броадкастить «много целей × много моментов» — он считает
    либо одну цель на сетке, либо набор целей в один момент. Для грубого прохода
    по тысяче объектов каталога это означало бы тысячу вызовов.

    Поэтому здесь прямая формула через часовой угол. Гринвичское истинное
    звёздное время берётся у Skyfield, так что нутация и вращение Земли учтены
    точно; опущены только рефракция, аберрация и прецессия каталожных координат
    от J2000 — вместе это доли градуса. Для отбора «поднимается ли объект над
    крышей хотя бы раз за ночь» этого более чем достаточно, а окончательная
    видимость всё равно считается полной моделью Skyfield.
    """
    ra = np.atleast_1d(np.asarray(ra_deg, dtype=float))[:, None]
    dec = np.radians(np.atleast_1d(np.asarray(dec_deg, dtype=float)))[:, None]
    gast_hours = np.atleast_1d(np.asarray(times.gast, dtype=float))[None, :]
    local_sidereal = gast_hours * 15.0 + observer.longitude
    hour_angle = np.radians(local_sidereal - ra)

    latitude = math.radians(observer.latitude)
    sin_alt = (np.sin(dec) * math.sin(latitude)
               + np.cos(dec) * math.cos(latitude) * np.cos(hour_angle))
    altitude = np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))
    azimuth = np.degrees(np.arctan2(
        -np.cos(dec) * np.sin(hour_angle),
        np.sin(dec) * math.cos(latitude)
        - np.cos(dec) * math.sin(latitude) * np.cos(hour_angle))) % 360.0
    return altitude, azimuth


def refraction_deg(altitude_deg):
    """Поправка за атмосферную рефракцию по формуле Беннета, градусы.

    У горизонта она достигает половины градуса и сдвигает момент восхода на
    минуты, поэтому в расчёте появления из-за препятствий её опускать нельзя.
    Ниже −1° поправка обнуляется: под горизонтом она смысла не имеет.
    """
    h = np.asarray(altitude_deg, dtype=float)
    minutes = 1.0 / np.tan(np.radians(h + 7.31 / (h + 4.4)))
    return np.where(h > -1.0, minutes / 60.0, 0.0)


SIDEREAL_DEG_PER_DAY = 360.9856473662862


class SiderealClock:
    """Местное звёздное время как линейная функция времени.

    Гринвичское звёздное время берётся у Skyfield один раз, дальше используется
    его равномерный ход. За ночь ошибка такого приближения — тысячные доли
    градуса: нутация меняется медленно. Зато перебор сотен объектов перестаёт
    каждый раз пересчитывать ряд IAU 2000A, который и составлял основную долю
    времени расчёта «что посмотреть сегодня».
    """

    def __init__(self, observer: ObserverProfile, reference: dt.datetime):
        self.reference = reference
        self.latitude = math.radians(observer.latitude)
        self.lst0_deg = float(to_skyfield(reference).gast) * 15.0 + observer.longitude

    def lst_deg(self, offsets_days):
        return self.lst0_deg + SIDEREAL_DEG_PER_DAY * np.asarray(offsets_days,
                                                                 dtype=float)

    def offsets_of(self, moments) -> np.ndarray:
        return np.array([(m - self.reference).total_seconds() / 86400.0
                         for m in moments], dtype=float)

    def altaz(self, ra_deg: float, dec_deg: float, offsets_days):
        """Высота (с рефракцией) и азимут каталожной цели на смещениях от опоры."""
        hour_angle = np.radians(self.lst_deg(offsets_days) - ra_deg)
        dec = math.radians(dec_deg)
        sin_alt = (math.sin(dec) * math.sin(self.latitude)
                   + math.cos(dec) * math.cos(self.latitude) * np.cos(hour_angle))
        altitude = np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))
        azimuth = np.degrees(np.arctan2(
            -math.cos(dec) * np.sin(hour_angle),
            math.sin(dec) * math.cos(self.latitude)
            - math.cos(dec) * math.sin(self.latitude) * np.cos(hour_angle))) % 360.0
        return altitude + refraction_deg(altitude), azimuth

    def altaz_at(self, ra_deg: float, dec_deg: float, when: dt.datetime):
        offset = (when - self.reference).total_seconds() / 86400.0
        altitude, azimuth = self.altaz(ra_deg, dec_deg, [offset])
        return float(altitude[0]), float(azimuth[0])


def scan_altaz_series(observer: ObserverProfile, target: Target, times):
    """Быстрый ход по времени для поиска пересечений с горизонтом участка.

    Для тел Солнечной системы считает Skyfield: их всего полтора десятка, зато
    движутся они по собственным законам. Для каталожных объектов — прямая
    формула через часовой угол плюс рефракция: это на два порядка быстрее и
    отличается от полного расчёта на единицы угловых минут, то есть на секунды
    времени восхода. За ночь перебирается несколько сотен объектов, и без
    быстрого хода «что посмотреть сегодня» считалось бы минуту вместо секунды.
    """
    if target.is_solar:
        return body_altaz_series(observer, resolve_body(target), times)
    altitude, azimuth = coarse_altaz_grid(observer, target.ra_deg, target.dec_deg, times)
    altitude = altitude[0] + refraction_deg(altitude[0])
    return altitude, azimuth[0]


def scan_altaz_at(observer: ObserverProfile, target: Target,
                  when: dt.datetime) -> tuple[float, float]:
    altitude, azimuth = scan_altaz_series(observer, target, to_skyfield(when))
    return float(np.atleast_1d(altitude)[0]), float(np.atleast_1d(azimuth)[0])


def fixed_altaz_series(observer: ObserverProfile, target: Target, times):
    """Высота и азимут одной фиксированной цели на сетке моментов."""
    from skyfield.api import Star

    star = Star(ra_hours=target.ra_deg / 15.0, dec_degrees=target.dec_deg)
    altitude, azimuth, _ = observer.topos().at(times).observe(star).apparent().altaz()
    return altitude.degrees, azimuth.degrees


def body_altaz_series(observer: ObserverProfile, body_obj, times):
    altitude, azimuth, _ = observer.topos().at(times).observe(body_obj).apparent().altaz()
    return altitude.degrees, azimuth.degrees


def resolve_body(target: Target):
    """Объект Skyfield для цели Солнечной системы."""
    from astrocal.core import body

    if target.kind in (SUN, MOON, PLANET):
        return body(target.body_key)
    if target.kind == JUPITER_MOON:
        from astrocal.events.jupiter_moons import MOONS, satellite
        return satellite(MOONS[target.body_key])
    if target.kind == COMET:
        return _comet_body(target.body_key)
    if target.kind == ASTEROID:
        return _asteroid_body(target.body_key)
    raise ValueError(f"{target.kind} — не тело Солнечной системы")


def altaz_series(observer: ObserverProfile, target: Target, times):
    """Универсальная траектория: работает и для каталога, и для эфемерид."""
    if target.is_solar:
        return body_altaz_series(observer, resolve_body(target), times)
    return fixed_altaz_series(observer, target, times)


def altaz_at(observer: ObserverProfile, target: Target,
             when: dt.datetime) -> tuple[float, float]:
    altitude, azimuth = altaz_series(observer, target, to_skyfield(when))
    return float(np.atleast_1d(altitude)[0]), float(np.atleast_1d(azimuth)[0])


# ---------------------------------------------------------------- Солнечная система

def solar_targets(when: dt.datetime, include_jupiter_moons: bool = True,
                  comet_limit: int = 3) -> list[Target]:
    """Цели Солнечной системы на данную дату: Солнце, Луна, планеты, спутники, кометы."""
    targets = [
        Target(id="sun", name="Солнце", kind=SUN, body_key="sun",
               magnitude=-26.7, major_arcmin=32.0),
        Target(id="moon", name="Луна", kind=MOON, body_key="moon",
               magnitude=-12.7, major_arcmin=31.0,
               note="Кратеры вдоль терминатора видны даже в 10×50."),
    ]
    for name in PLANET_ORDER:
        targets.append(Target(
            id=name, name=PLANET_NAMES_RU[name], kind=PLANET, body_key=name,
            major_arcmin=PLANET_DISK_ARCMIN[name],
            aliases=(name, PLANET_NAMES_RU[name])))
    if include_jupiter_moons:
        for key, name_ru in JUPITER_MOONS_RU.items():
            targets.append(Target(
                id=f"jup_{key}", name=name_ru, kind=JUPITER_MOON, body_key=key,
                magnitude=5.5, major_arcmin=0.03,
                aliases=(name_ru, key),
                note="Галилеев спутник: в бинокль виден как звёздочка у Юпитера."))
    targets.extend(bright_comets(when, limit=comet_limit))
    return targets


@lru_cache(maxsize=8)
def _comet_rows(month_key: str):
    """Яркие кометы месяца. Кэш по месяцу: отбор идёт по всему каталогу MPC."""
    import pandas as pd

    from astrocal.events import comets

    year, month = (int(part) for part in month_key.split("-"))
    start = dt.datetime(year, month, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(year + (month == 12), month % 12 + 1, 1,
                      tzinfo=dt.timezone.utc)
    try:
        frame = comets.select_bright(start, end, mag_limit=10.5)
    except Exception:
        return ()
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return ()
    return tuple((str(row.designation), float(row.mag_min), row.row)
                 for row in frame.itertuples(index=False))


def bright_comets(when: dt.datetime, limit: int = 3) -> list[Target]:
    """Кометы ярче 10.5m в текущем месяце — реальные, а не список из головы."""
    from astrocal.events.comets import comet_name

    rows = _comet_rows(f"{when.year}-{when.month}")
    targets = []
    for designation, mag_min, _row in rows[:limit]:
        targets.append(Target(
            id=f"comet_{designation.split('/')[0].strip()}",
            name=f"Комета {comet_name(designation)}", kind=COMET,
            body_key=designation, magnitude=mag_min, major_arcmin=5.0,
            aliases=(comet_name(designation), designation),
            note="Блеск комет прогнозируется грубо; смотрите как на оценку."))
    return targets


@lru_cache(maxsize=16)
def _comet_body(designation: str):
    from astrocal.events.comets import load_elements, orbit
    frame = load_elements()
    rows = frame[frame["designation"] == designation]
    if rows.empty:
        raise KeyError(f"комета {designation} не найдена в CometEls")
    return orbit(rows.iloc[0])


@lru_cache(maxsize=16)
def _asteroid_body(designation: str):
    raise KeyError("астероиды в этой версии не подключены к 3D-сцене")


# ---------------------------------------------------------------- Солнце и Луна

def sun_altitude(observer: ObserverProfile, when: dt.datetime) -> float:
    from astrocal.core import body
    altitude, _ = body_altaz_series(observer, body("sun"), to_skyfield(when))
    return float(np.atleast_1d(altitude)[0])


@dataclass
class MoonState:
    altitude_deg: float
    azimuth_deg: float
    illumination: float          # 0..1
    waxing: bool
    phase_angle_deg: float       # угол Солнце–Луна по эклиптической долготе

    @property
    def phase_name(self) -> str:
        percent = self.illumination * 100.0
        if percent < 2:
            return "новолуние"
        if percent > 98:
            return "полнолуние"
        if 48 <= percent <= 52:
            return "первая четверть" if self.waxing else "последняя четверть"
        growing = "растущая" if self.waxing else "убывающая"
        shape = "серп" if percent < 50 else "Луна"
        return f"{growing} {shape}"

    def to_dict(self) -> dict:
        return {"alt": round(self.altitude_deg, 2),
                "az": round(self.azimuth_deg, 2),
                "illumination": round(self.illumination, 4),
                "waxing": self.waxing,
                "phase_angle": round(self.phase_angle_deg, 2),
                "phase_name": self.phase_name}


def moon_state(observer: ObserverProfile, when: dt.datetime) -> MoonState:
    from skyfield import almanac

    from astrocal.core import body, planets
    t = to_skyfield(when)
    altitude, azimuth = body_altaz_series(observer, body("moon"), t)
    illumination = float(almanac.fraction_illuminated(planets(), "moon", t))
    earth = planets()["earth"]
    sun_lon = earth.at(t).observe(body("sun")).apparent().ecliptic_latlon()[1].degrees
    moon_lon = earth.at(t).observe(body("moon")).apparent().ecliptic_latlon()[1].degrees
    elongation = (float(moon_lon) - float(sun_lon)) % 360.0
    return MoonState(
        altitude_deg=float(np.atleast_1d(altitude)[0]),
        azimuth_deg=float(np.atleast_1d(azimuth)[0]),
        illumination=illumination, waxing=elongation < 180.0,
        phase_angle_deg=elongation)


def moon_radec(observer: ObserverProfile, when: dt.datetime) -> tuple[float, float]:
    """Видимые RA/Dec Луны с площадки — чтобы считать удаление от неё пачкой."""
    from astrocal.core import body

    apparent = observer.topos().at(to_skyfield(when)).observe(body("moon")).apparent()
    ra, dec, _ = apparent.radec()
    return float(ra.degrees), float(dec.degrees)


def separation_from_moon_fixed(target: Target, moon_ra_deg: float,
                               moon_dec_deg: float) -> float:
    """Удаление каталожной цели от Луны по её экваториальным координатам.

    Обходится без Skyfield: при переборе сотен объектов два топоцентрических
    наблюдения на каждый превращались в половину времени расчёта.
    """
    from astrocal.catalogs import angular_distance_deg

    return float(angular_distance_deg(target.ra_deg, target.dec_deg,
                                      moon_ra_deg, moon_dec_deg))


def separation_from_moon(observer: ObserverProfile, target: Target,
                         when: dt.datetime) -> float:
    """Угловое расстояние цели от Луны, градусы."""
    from astrocal.core import body

    site = observer.topos()
    t = to_skyfield(when)
    moon = site.at(t).observe(body("moon")).apparent()
    if target.is_solar:
        other = site.at(t).observe(resolve_body(target)).apparent()
    else:
        from skyfield.api import Star
        star = Star(ra_hours=target.ra_deg / 15.0, dec_degrees=target.dec_deg)
        other = site.at(t).observe(star).apparent()
    return float(moon.separation_from(other).degrees)


# ---------------------------------------------------------------- ночь

@dataclass
class Night:
    """Границы тёмного времени вокруг выбранной даты."""

    date: dt.date
    sunset: dt.datetime | None
    sunrise: dt.datetime | None
    dark_start: dt.datetime | None      # Солнце ниже −12° (навигационные сумерки)
    dark_end: dt.datetime | None
    astro_start: dt.datetime | None     # Солнце ниже −18°
    astro_end: dt.datetime | None

    @property
    def start(self) -> dt.datetime:
        return self.dark_start or self.sunset

    @property
    def end(self) -> dt.datetime:
        return self.dark_end or self.sunrise

    @property
    def has_darkness(self) -> bool:
        return self.dark_start is not None and self.dark_end is not None

    def to_dict(self) -> dict:
        def stamp(value):
            return value.isoformat() if value else None
        return {"date": self.date.isoformat(), "sunset": stamp(self.sunset),
                "sunrise": stamp(self.sunrise), "dark_start": stamp(self.dark_start),
                "dark_end": stamp(self.dark_end),
                "astro_start": stamp(self.astro_start),
                "astro_end": stamp(self.astro_end)}


def night_for(observer: ObserverProfile, date: dt.date) -> Night:
    """Ночь с `date` на следующий день: от заката до восхода.

    Границы ищутся по сетке высот Солнца с шагом 2 минуты и уточняются линейной
    интерполяцией. Для белых ночей и полярного дня соответствующие моменты
    остаются None — приложение обязано корректно показать «темноты не будет».
    """
    from astrocal.core import body

    tz = observer.tz
    start = dt.datetime.combine(date, dt.time(12, 0), tzinfo=tz)
    end = start + dt.timedelta(hours=24)
    grid = time_grid(start, end, 2.0)
    altitude, _ = body_altaz_series(observer, body("sun"), grid)
    stamps = [t.utc_datetime().astimezone(tz) for t in grid]

    def crossing(level: float, falling: bool):
        for index in range(len(altitude) - 1):
            a, b = altitude[index], altitude[index + 1]
            if falling and a > level >= b or (not falling and a < level <= b):
                weight = (a - level) / (a - b) if a != b else 0.0
                delta = (stamps[index + 1] - stamps[index]) * weight
                return stamps[index] + delta
        return None

    return Night(
        date=date,
        sunset=crossing(-0.833, True), sunrise=crossing(-0.833, False),
        dark_start=crossing(-12.0, True), dark_end=crossing(-12.0, False),
        astro_start=crossing(-18.0, True), astro_end=crossing(-18.0, False))


def default_moment(observer: ObserverProfile, date: dt.date) -> dt.datetime:
    """Разумный момент по умолчанию для выбранной даты — середина тёмного времени."""
    night = night_for(observer, date)
    if night.start and night.end:
        return night.start + (night.end - night.start) / 2
    return dt.datetime.combine(date, dt.time(23, 0), tzinfo=observer.tz)
