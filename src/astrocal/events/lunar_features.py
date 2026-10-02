"""Лунные наблюдательные события: Lunar X и V, либрации, серпы.

Что здесь считается точно, а что приближённо — важно различать.

**Точно** (по эфемеридам и ядру ориентации Луны DE421): селенографическая
колонгитуда Солнца, либрации по долготе и широте, возраст Луны, высота над
горизонтом.

**Приближённо**: сам момент видимости Lunar X и Lunar V. Это игра света на
конкретных кратерных валах, и её нельзя вывести из положения тел — только из
рельефа. Общепринятый критерий наблюдателей: буква видна около четырёх часов
вокруг момента, когда колонгитуда Солнца проходит 358°. Мы этим критерием и
пользуемся, а точность честно указываем в протоколе: ±1 час по времени, и
итоговая видимость зависит от либрации и прозрачности неба.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

import numpy as np

from .. import config as cfg
from ..fmt import number
from ..core import (Event, body, find_zero, observer, planets, southern_observer,
                    timescale, to_msk, ts_range, refine_minimum)

MOON_FRAME_FILES = {
    "frame": cfg.CACHE / "moon_080317.tf",
    "constants": cfg.CACHE / "pck00010.tpc",
    "orientation": cfg.CACHE / "moon_pa_de421_1900-2050.bpc",
}
MOON_FRAME_URLS = {
    "frame": "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/fk/satellites/"
             "moon_080317.tf",
    "constants": "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/"
                 "pck00010.tpc",
    "orientation": "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/"
                   "moon_pa_de421_1900-2050.bpc",
}

# Колонгитуда Солнца, при которой наблюдатели видят букву на терминаторе
LUNAR_X_COLONGITUDE = 358.0
LUNAR_V_COLONGITUDE = 358.2
FEATURE_WINDOW_HOURS = 2.0          # ±2 часа вокруг момента

STRONG_LIBRATION_DEG = 6.5          # при большей либрации открывается лимб
YOUNG_MOON_HOURS = 40.0
SYNODIC_MONTH_DAYS = 29.530588


@lru_cache(maxsize=1)
def moon_frame():
    """Система координат, связанная с телом Луны (нужна для либраций)."""
    from skyfield.api import PlanetaryConstants

    for key, path in MOON_FRAME_FILES.items():
        if path.exists():
            continue
        try:
            import requests
            response = requests.get(MOON_FRAME_URLS[key], timeout=300)
            response.raise_for_status()
            path.write_bytes(response.content)
        except Exception:
            return None

    try:
        constants = PlanetaryConstants()
        constants.read_text(MOON_FRAME_FILES["frame"].open("rb"))
        constants.read_text(MOON_FRAME_FILES["constants"].open("rb"))
        constants.read_binary(MOON_FRAME_FILES["orientation"].open("rb"))
        return constants.build_frame_named("MOON_ME_DE421")
    except Exception:
        return None


def sun_colongitude(t) -> float:
    """Селенографическая колонгитуда Солнца, градусы.

    Классическая величина лунной топографии: 0° — восход Солнца на нулевом
    меридиане, 90° — первая четверть, 270° — последняя.
    """
    frame = moon_frame()
    if frame is None:
        raise RuntimeError("нет ядра ориентации Луны")
    position = planets()["moon"].at(t).observe(body("sun")).apparent()
    _lat, lon, _distance = position.frame_latlon(frame)
    return float((90.0 - lon.degrees) % 360.0)


def libration(t) -> tuple[float, float]:
    """Либрация по долготе и широте, градусы.

    Положительная долгота открывает восточный лимб (Море Краевое, Море
    Смита), положительная широта — северный (район кратера Пири).

    Долготу обязательно приводим к диапазону ±180°: `frame_latlon` отдаёт её
    в 0…360°, и либрация в −0,05° приходит как 359,95°. Без свёртки крошечный
    наклон выглядел как рекордный, и в календарь попадали несуществующие
    события «открыт западный край (359.9°)», а настоящие максимумы терялись.
    """
    frame = moon_frame()
    if frame is None:
        raise RuntimeError("нет ядра ориентации Луны")
    position = (planets()["earth"] - planets()["moon"]).at(t)
    lat, lon, _distance = position.frame_latlon(frame)
    longitude = (float(lon.degrees) + 180.0) % 360.0 - 180.0
    latitude = (float(lat.degrees) + 180.0) % 360.0 - 180.0
    return longitude, latitude


def _observable(when: dt.datetime, min_altitude: float = 10.0) -> tuple[bool, float]:
    t = timescale().from_datetime(when)
    best = -90.0
    for site in (observer(), southern_observer()):
        altitude = float(site.at(t).observe(body("moon")).apparent()
                         .altaz()[0].degrees)
        sun_altitude = float(site.at(t).observe(body("sun")).apparent()
                             .altaz()[0].degrees)
        if altitude > best and sun_altitude < 0:
            best = altitude
    return best > min_altitude, best


def clair_obscur(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Lunar X и Lunar V — «буквы» на терминаторе у первой четверти."""
    if moon_frame() is None:
        return []

    ts = timescale()
    grid = ts_range(start, end, 60)
    colongitudes = np.array([sun_colongitude(t) for t in grid])

    out: list[Event] = []
    for name, target, description in (
            ("Lunar X", LUNAR_X_COLONGITUDE,
             "светящаяся «X» на терминаторе у кратеров Бланкин, Ла-Каюм и Пурбах"),
            ("Lunar V", LUNAR_V_COLONGITUDE,
             "светящаяся «V» на терминаторе у кратера Укерт")):
        difference = (colongitudes - target + 180.0) % 360.0 - 180.0
        for index in range(len(difference) - 1):
            if difference[index] > 0 or difference[index + 1] < 0:
                continue
            if abs(difference[index]) > 20:
                continue
            tt = find_zero(
                lambda x, target=target: (sun_colongitude(ts.tt_jd(x)) - target
                                          + 180.0) % 360.0 - 180.0,
                grid[index].tt, grid[index + 1].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            if not (start <= when < end):
                continue
            visible, altitude = _observable(when)
            longitude_libration, latitude_libration = libration(t)
            out.append(Event(
                when=when,
                text=(f"{name} — {description}, видна около "
                      f"{FEATURE_WINDOW_HOURS:.0f} часов"
                      + ("" if visible else ", из России в этот момент Луна низко")),
                category="lunar_feature",
                confidence="средняя",
                rank="interesting" if visible else "optional",
                computed=(f"колонгитуда Солнца достигает {target}° в "
                          f"{t.utc_strftime('%Y-%m-%d %H:%M UTC')}; окно видимости "
                          f"±{FEATURE_WINDOW_HOURS:.0f} ч; высота Луны над Россией "
                          f"{altitude:.0f}°; либрация {longitude_libration:+.1f}° / "
                          f"{latitude_libration:+.1f}°. Критерий "
                          f"феноменологический: момент задаётся освещением рельефа, "
                          f"точность около часа"),
                sources=["Skyfield/DE440s", "ядро ориентации Луны DE421",
                         "критерий колонгитуды 358°, принятый наблюдателями"],
                precision="hour",
                meta={"feature": name, "colongitude": target},
            ))
    return out


LIBRATION_DIRECTIONS = (
    (0, +1, "восточный", "область Моря Краевого и Моря Смита"),
    (0, -1, "западный", "область Моря Восточного"),
    (1, +1, "северный", "область у кратера Пири"),
    (1, -1, "южный", "область у кратера Шеклтон"),
)


def librations(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Максимумы либрации — когда открывается дальний край лунного лимба.

    Либрация и по долготе, и по широте проходит через максимум примерно раз
    в месяц в каждую сторону, значит событий должно быть четыре: восточное,
    западное, северное и южное. Раньше публиковались только те, что
    перевалили за 6,5° и застали Луну над горизонтом, и в выпуск попадало
    одно из четырёх — остальные месяцы читатель просто не видел, когда
    открывается дальний край.

    Поэтому порог снят: в календарь идёт наибольший за месяц максимум в
    каждую сторону. Насколько он велик, сказано в самой строке, а высота
    Луны — в протоколе расчёта: момент максимума либрации от видимости не
    зависит, а лимб остаётся открытым не один час.
    """
    if moon_frame() is None:
        return []

    grid = ts_range(start, end, 180)
    values = np.array([libration(t) for t in grid])

    out: list[Event] = []
    for axis, sign, edge, features in LIBRATION_DIRECTIONS:
        series = values[:, axis] * sign
        peaks = [index for index in range(1, len(series) - 1)
                 if series[index] > series[index - 1]
                 and series[index] >= series[index + 1]]
        if not peaks:
            continue
        index = max(peaks, key=lambda position: series[position])
        ts = timescale()
        tt = refine_minimum(lambda x: -libration(ts.tt_jd(x))[axis] * sign,
                            grid[index - 1].tt, grid[index + 1].tt)
        moment = ts.tt_jd(tt)
        when = to_msk(moment)
        if not (start <= when < end):
            continue
        visible, altitude = _observable(when)
        longitude_libration, latitude_libration = libration(moment)
        axis_ru = "долготе" if axis == 0 else "широте"
        from .moon import illum_and_waxing
        from ..apparent import moon_label
        frac, waxing = illum_and_waxing(moment)
        strong = series[index] >= STRONG_LIBRATION_DEG
        out.append(Event(
            when=when,
            text=(f"Наибольшая {'восточная' if axis == 0 and sign > 0 else 'западная' if axis == 0 else 'северная' if sign > 0 else 'южная'} либрация Луны ({moon_label(moment, frac, waxing)}): "
                  f"открыт {edge} край лунного диска, либрация по {axis_ru} "
                  f"{number((longitude_libration, latitude_libration)[axis], 1, sign=True)}°, "
                  f"видна {features}"),
            category="lunar_feature",
            confidence="высокая",
            # все четыре максимума идут в выпуск: читателю нужна полная
            # картина месяца, а не только рекордные наклоны
            rank="interesting",
            computed=(f"наибольший за месяц максимум либрации по {axis_ru}: "
                      f"{longitude_libration:+.2f}° / {latitude_libration:+.2f}°; "
                      f"высота Луны над Россией в этот момент {altitude:.0f}°"
                      + ("" if visible else ", Луна под горизонтом — лимб "
                         "остаётся открытым и в ближайшие ночи")),
            sources=["Skyfield/DE440s", "ядро ориентации Луны DE421"],
            precision="hour",
            meta={"feature": "libration", "axis": axis, "edge": edge,
                  "strong": strong},
        ))
    return out


def crescents(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Молодой и старый серп — насколько тонкую Луну удастся поймать."""
    from skyfield import almanac

    ts = timescale()
    eph = planets()
    times, which = almanac.find_discrete(
        ts.from_datetime(start - dt.timedelta(days=2)),
        ts.from_datetime(end + dt.timedelta(days=2)),
        almanac.moon_phases(eph))
    new_moons = [t for t, phase in zip(times, which) if int(phase) == 0]

    out: list[Event] = []
    for new_moon in new_moons:
        for label, offset_hours, description in (
                ("Молодой серп", +YOUNG_MOON_HOURS, "вечером на западе"),
                ("Старый серп", -YOUNG_MOON_HOURS, "утром на востоке")):
            moment = to_msk(new_moon) + dt.timedelta(hours=offset_hours)
            if not (start <= moment < end):
                continue
            # ищем лучший момент в эти сутки: Луна выше всего на тёмном небе
            best_when, best_altitude = None, -90.0
            for minutes in range(-360, 361, 15):
                candidate = moment + dt.timedelta(minutes=minutes)
                visible, altitude = _observable(candidate, min_altitude=0.0)
                if altitude > best_altitude:
                    best_when, best_altitude = candidate, altitude
            if best_when is None or best_altitude < 3.0:
                continue
            age_hours = abs(offset_hours)
            t = ts.from_datetime(best_when)
            illumination = float(almanac.fraction_illuminated(eph, "moon", t))
            out.append(Event(
                when=best_when,
                text=(f"{label} возрастом около {age_hours:.0f} часов "
                      f"(Ф={illumination:.2f}".replace(".", ",")
                      + f") — тонкий серп {description}"),
                category="lunar_feature",
                confidence="средняя",
                rank="optional",
                computed=(f"новолуние {to_msk(new_moon):%d.%m %H:%M} МСК; "
                          f"возраст {age_hours:.0f} ч; наибольшая высота Луны над "
                          f"Россией в сумерках {best_altitude:.0f}°"),
                sources=["Skyfield/DE440s"],
                precision="hour",
                meta={"feature": "crescent"},
            ))
    return out


def all_events(start: dt.datetime, end: dt.datetime) -> list[Event]:
    events: list[Event] = []
    for producer in (clair_obscur, librations, crescents):
        try:
            events += producer(start, end)
        except Exception:
            continue
    return sorted(events, key=lambda event: event.when)
