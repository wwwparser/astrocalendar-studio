"""Местный горизонт: закрыт объект или виден, и когда это изменится.

Главный вопрос приложения звучит не «взошёл ли Юпитер», а «когда он вылезет
из-за крыши». Астрономический восход и наблюдательный расходятся на десятки
минут, и именно эта разница определяет, во сколько человек выйдет во двор.

Момент появления ищется как корень функции

    f(t) = высота_объекта(t) − горизонт_участка(азимут_объекта(t))

Обе части меняются со временем: объект движется и по высоте, и по азимуту, а
маска горизонта на новом азимуте другая. Поэтому смена знака ищется на сетке, а
затем уточняется бисекцией — прямой формулы здесь нет.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
import numpy as np

from ..models import horizon as horizon_model
from ..models.observer import ObserverProfile
from ..models.scene import HOUSE, KIND_RU, TREE
from . import astronomy_service as astro

# Шаг сетки поиска пересечений. Две минуты — компромисс: Луна за это время
# смещается на четверть своего диаметра, а перебрать ночь получается за доли
# секунды.
SCAN_STEP_MINUTES = 2.0


def profile_for(landscape, observer: ObserverProfile) -> horizon_model.HorizonProfile:
    return horizon_model.build(landscape, observer.eye_height_m)


@dataclass
class Crossing:
    """Момент, когда объект пересекает местный горизонт."""

    when: dt.datetime
    rising: bool                 # True — появляется, False — скрывается
    azimuth_deg: float
    horizon_deg: float
    obstacle_name: str = ""


@dataclass
class VisibilityWindow:
    """Окно, в течение которого объект реально виден с площадки."""

    start: dt.datetime
    end: dt.datetime
    max_altitude_deg: float
    best_time: dt.datetime

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(),
                "minutes": round(self.minutes), "best": self.best_time.isoformat(),
                "max_alt": round(self.max_altitude_deg, 1)}


@dataclass
class LocalVisibility:
    """Полная картина видимости цели за интервал времени."""

    visible_now: bool
    altitude_now: float
    azimuth_now: float
    clearance_now: float                 # запас над препятствием, градусы
    above_math_horizon: bool
    windows: list
    crossings: list
    blocking_obstacle: str = ""

    @property
    def blocked_by_terrain(self) -> bool:
        """Объект над математическим горизонтом, но закрыт домом или деревом."""
        return self.above_math_horizon and not self.visible_now

    @property
    def next_rise(self) -> dt.datetime | None:
        for crossing in self.crossings:
            if crossing.rising:
                return crossing.when
        return None

    @property
    def next_set(self) -> dt.datetime | None:
        for crossing in self.crossings:
            if not crossing.rising:
                return crossing.when
        return None

    @property
    def total_minutes(self) -> float:
        return sum(w.minutes for w in self.windows)

    @property
    def best_window(self) -> VisibilityWindow | None:
        if not self.windows:
            return None
        return max(self.windows, key=lambda w: w.max_altitude_deg)


def obstacle_at(landscape, azimuth_deg: float, eye_height_m: float,
                tolerance_deg: float = 0.6) -> str:
    """Какое препятствие поднимает горизонт на этом азимуте.

    Возвращает пустую строку, если ни одно препятствие не отвечает за высоту
    маски: тогда фразу «смотрите над крышей» строить нельзя — геометрии нет.
    """
    best_name, best_altitude = "", -np.inf
    for obstacle in getattr(landscape, "obstacles", []):
        azimuth, altitude = obstacle.silhouette(eye_height_m)
        if len(azimuth) == 0:
            continue
        delta = np.abs((np.asarray(azimuth) - azimuth_deg + 180.0) % 360.0 - 180.0)
        near = delta <= tolerance_deg
        if not near.any():
            continue
        top = float(np.max(np.asarray(altitude)[near]))
        if top > best_altitude:
            best_altitude, best_name = top, obstacle.name or KIND_RU.get(obstacle.kind, "")
    natural = float(getattr(landscape, "natural_horizon_deg", 0.0))
    if best_altitude <= natural + 0.05:
        return ""
    return best_name


def obstacle_kind_at(landscape, azimuth_deg: float, eye_height_m: float) -> str:
    for obstacle in getattr(landscape, "obstacles", []):
        if (obstacle.name or KIND_RU.get(obstacle.kind, "")) == obstacle_at(
                landscape, azimuth_deg, eye_height_m):
            return obstacle.kind
    return ""


@dataclass
class ScanGrid:
    """Общая сетка времени для перебора многих целей.

    Строится один раз на ночь: и моменты Skyfield, и их местные метки, и
    звёздные часы. Без этого перебор нескольких сотен объектов сто тысяч раз
    переводил бы одни и те же моменты в datetime.
    """

    times: object                    # skyfield Time на всей сетке
    stamps: list                     # те же моменты как местные datetime
    clock: astro.SiderealClock

    @classmethod
    def build(cls, observer: ObserverProfile, start: dt.datetime, end: dt.datetime,
              step_minutes: float = SCAN_STEP_MINUTES) -> "ScanGrid":
        times = astro.time_grid(start, end, step_minutes)
        tz = observer.tz
        stamps = [t.utc_datetime().astimezone(tz) for t in times]
        return cls(times=times, stamps=stamps,
                   clock=astro.SiderealClock(observer, stamps[0]))


def analyse(observer: ObserverProfile, target, horizon, when: dt.datetime,
            start: dt.datetime, end: dt.datetime,
            landscape=None, step_minutes: float = SCAN_STEP_MINUTES,
            min_window_minutes: float = 10.0, scan=None) -> LocalVisibility:
    """Видимость цели с учётом местного горизонта на интервале [start, end]."""
    scan = scan or ScanGrid.build(observer, start, end, step_minutes)
    grid, stamps, clock = scan.times, scan.stamps, scan.clock

    if target.is_solar:
        altitude, azimuth = astro.scan_altaz_series(observer, target, grid)
    else:
        altitude, azimuth = clock.altaz(target.ra_deg, target.dec_deg,
                                        clock.offsets_of(stamps))
    altitude = np.atleast_1d(altitude)
    azimuth = np.atleast_1d(azimuth)
    mask = horizon.altitude_at(azimuth)
    clearance = altitude - mask

    windows, crossings = [], []
    inside = clearance > 0.0
    index = 0
    while index < len(inside):
        if not inside[index]:
            index += 1
            continue
        begin = index
        while index + 1 < len(inside) and inside[index + 1]:
            index += 1
        finish = index

        rise_time = (_refine(observer, target, horizon, stamps[begin - 1],
                             stamps[begin], clock) if begin > 0 else stamps[0])
        set_time = (_refine(observer, target, horizon, stamps[finish],
                            stamps[finish + 1], clock) if finish + 1 < len(inside)
                    else stamps[-1])
        segment = altitude[begin:finish + 1]
        peak = begin + int(np.argmax(segment))
        window = VisibilityWindow(start=rise_time, end=set_time,
                                  max_altitude_deg=float(altitude[peak]),
                                  best_time=stamps[peak])
        if window.minutes >= min_window_minutes:
            windows.append(window)
            if begin > 0:
                crossings.append(Crossing(
                    when=rise_time, rising=True, azimuth_deg=float(azimuth[begin]),
                    horizon_deg=float(mask[begin]),
                    obstacle_name=_name_at(landscape, float(azimuth[begin]), observer)))
            if finish + 1 < len(inside):
                crossings.append(Crossing(
                    when=set_time, rising=False, azimuth_deg=float(azimuth[finish]),
                    horizon_deg=float(mask[finish]),
                    obstacle_name=_name_at(landscape, float(azimuth[finish]), observer)))
        index += 1

    crossings.sort(key=lambda c: c.when)
    now_alt, now_az = _altaz_at(observer, target, when, clock)
    now_mask = horizon.altitude_at(now_az)
    blocking = ""
    if now_alt > 0.0 and now_alt <= now_mask:
        blocking = _name_at(landscape, now_az, observer)

    return LocalVisibility(
        visible_now=bool(now_alt > now_mask),
        altitude_now=now_alt, azimuth_now=now_az,
        clearance_now=now_alt - now_mask,
        above_math_horizon=bool(now_alt > 0.0),
        windows=windows,
        crossings=[c for c in crossings if c.when >= when] or crossings,
        blocking_obstacle=blocking)


def _name_at(landscape, azimuth_deg: float, observer: ObserverProfile) -> str:
    if landscape is None:
        return ""
    return obstacle_at(landscape, azimuth_deg, observer.eye_height_m)


def _altaz_at(observer: ObserverProfile, target, when: dt.datetime,
              clock: astro.SiderealClock | None):
    if target.is_solar or clock is None:
        return astro.scan_altaz_at(observer, target, when)
    return clock.altaz_at(target.ra_deg, target.dec_deg, when)


def _refine(observer: ObserverProfile, target, horizon,
            low: dt.datetime, high: dt.datetime,
            clock: astro.SiderealClock | None = None,
            iterations: int = 14) -> dt.datetime:
    """Бисекция по времени: где `высота − горизонт` меняет знак.

    14 половинных делений двухминутного интервала дают точность лучше секунды —
    заметно точнее, чем имеет смысл сообщать наблюдателю.
    """
    def clearance(moment: dt.datetime) -> float:
        altitude, azimuth = _altaz_at(observer, target, moment, clock)
        return altitude - horizon.altitude_at(azimuth)

    low_value = clearance(low)
    a, b = low, high
    for _ in range(iterations):
        middle = a + (b - a) / 2
        value = clearance(middle)
        if (value < 0) == (low_value < 0):
            a, low_value = middle, value
        else:
            b = middle
        if (b - a).total_seconds() < 1.0:
            break
    return a + (b - a) / 2


# ---------------------------------------------------------------- формулировки

def where_to_look(azimuth_deg: float, altitude_deg: float,
                  landscape, observer: ObserverProfile) -> str:
    """Фраза «куда смотреть», привязанная к реальной геометрии участка.

    Если на этом азимуте нет ни дома, ни дерева, привязка не строится: выдумывать
    «над правым скатом крыши» там, где крыши нет, значит уводить человека в
    сторону. Тогда остаются только сторона света и высота.
    """
    from astrocal.observing import compass_direction

    direction = compass_direction(azimuth_deg)
    base = f"{direction}, азимут {azimuth_deg:.0f}°, высота {altitude_deg:.0f}°"

    name = _name_at(landscape, azimuth_deg, observer)
    if not name:
        return base

    obstacle = _find_obstacle(landscape, name)
    if obstacle is None:
        return base
    top = _top_altitude(obstacle, observer.eye_height_m, azimuth_deg)
    if top is None:
        return base
    if altitude_deg > top + 1.0:
        side = _side_hint(obstacle, azimuth_deg)
        return f"{base}. Выше, чем {name.lower()}{side}"
    return f"{base}. Сейчас закрыт: {name.lower()}"


def _find_obstacle(landscape, name: str):
    for obstacle in getattr(landscape, "obstacles", []):
        if (obstacle.name or KIND_RU.get(obstacle.kind, "")) == name:
            return obstacle
    return None


def _top_altitude(obstacle, eye_height_m: float, azimuth_deg: float,
                  tolerance_deg: float = 0.6) -> float | None:
    azimuth, altitude = obstacle.silhouette(eye_height_m)
    if len(azimuth) == 0:
        return None
    delta = np.abs((np.asarray(azimuth) - azimuth_deg + 180.0) % 360.0 - 180.0)
    near = delta <= tolerance_deg
    if not near.any():
        return None
    return float(np.max(np.asarray(altitude)[near]))


def _side_hint(obstacle, azimuth_deg: float) -> str:
    """С какой стороны препятствия находится объект.

    Только для точечных препятствий с явным центром — дома и дерева. У забора
    и полосы леса «правая сторона» смысла не имеет.
    """
    if obstacle.kind not in (HOUSE, TREE):
        return ""
    offset = (azimuth_deg - obstacle.azimuth_deg + 180.0) % 360.0 - 180.0
    if abs(offset) < 1.5:
        return " — прямо над ним"
    return " — правее" if offset > 0 else " — левее"


def summarise(visibility: LocalVisibility, landscape,
              observer: ObserverProfile) -> str:
    """Строка для панели «где искать» и результата поиска."""
    if visibility.visible_now:
        return where_to_look(visibility.azimuth_now, visibility.altitude_now,
                             landscape, observer)
    rise = visibility.next_rise
    if visibility.blocked_by_terrain:
        name = visibility.blocking_obstacle or "препятствие"
        if rise:
            return (f"Над горизонтом, но закрыт: {name.lower()}. "
                    f"Станет виден в {rise:%H:%M}.")
        return f"Над горизонтом, но закрыт: {name.lower()}. Сегодня не откроется."
    if rise:
        return f"Сейчас под горизонтом. Появится в {rise:%H:%M}."
    return "Сейчас под горизонтом и этой ночью не поднимется."
