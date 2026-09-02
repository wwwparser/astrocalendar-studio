"""Наблюдательный слой: где, когда и чем смотреть.

Модуль отвечает на вопрос наблюдателя, а не вычислителя: во сколько выйти,
куда смотреть, хватит ли глаз, помешает ли Луна. Всё это считается по явным
правилам — рейтинг «★★★★» не назначается на глаз, а выводится из высоты
объекта, глубины сумерек, помех от Луны, блеска и длительности окна.

Алгоритм рейтинга (см. `score_conditions`):

* высота объекта над горизонтом      до 35 очков
* темнота неба (погружение Солнца)   до 25 очков
* помеха от Луны                     до 20 очков
* доступность инструменту            до 12 очков
* длительность окна наблюдения       до  8 очков

Сумма 0–100 переводится в пять градаций. Такое разбиение отражает практику:
объект у горизонта не спасёт ни блеск, ни идеальная ночь, поэтому высота весит
больше всего, а полная Луна рядом с целью бьёт сильнее, чем недостаток блеска.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from .cities import City, topos
from .core import body, separation_deg, to_msk, ts_range

# Порог инструмента по блеску: что видно глазом, что в бинокль, что в телескоп
NAKED_EYE_LIMIT = 6.0
BINOCULARS_LIMIT = 9.5

INSTRUMENT_RU = {
    "eye": "Невооружённым глазом",
    "binoculars": "Бинокль",
    "telescope": "Телескоп",
}


def instrument_for(magnitude: float | None) -> str:
    if magnitude is None:
        return "eye"
    if magnitude <= NAKED_EYE_LIMIT:
        return "eye"
    if magnitude <= BINOCULARS_LIMIT:
        return "binoculars"
    return "telescope"


@dataclass
class Circumstances:
    """Обстоятельства события в конкретном городе."""
    city: City
    visible: bool
    best_time: dt.datetime | None = None
    altitude_deg: float | None = None
    azimuth_deg: float | None = None
    direction: str = ""
    sun_altitude_deg: float | None = None
    moon_altitude_deg: float | None = None
    moon_illumination: float | None = None
    moon_separation_deg: float | None = None
    window_start: dt.datetime | None = None
    window_end: dt.datetime | None = None
    window_minutes: float = 0.0
    score: int = 0
    stars: int = 0
    instrument: str = "eye"
    note: str = ""

    @property
    def stars_text(self) -> str:
        return "★" * self.stars + "☆" * (5 - self.stars)

    @property
    def instrument_ru(self) -> str:
        return INSTRUMENT_RU[self.instrument]


COMPASS = ["С", "ССВ", "СВ", "ВСВ", "В", "ВЮВ", "ЮВ", "ЮЮВ",
           "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ", "З", "ЗСЗ", "СЗ", "ССЗ"]


def compass_direction(azimuth_deg: float) -> str:
    return COMPASS[int((azimuth_deg % 360) / 22.5 + 0.5) % 16]


def score_conditions(altitude_deg: float, sun_altitude_deg: float,
                     moon_altitude_deg: float, moon_illumination: float,
                     moon_separation_deg: float, magnitude: float | None,
                     window_minutes: float) -> tuple[int, int]:
    """Очки условий наблюдения 0–100 и число звёзд 1–5.

    Правила формализованы намеренно: одинаковая геометрия всегда даёт одинаковую
    оценку, и её можно проверить тестом.
    """
    # высота: у горизонта смотреть нечего, выше 45° прибавка почти не растёт
    height = np.clip(altitude_deg, 0, 60) / 60.0
    points = 35.0 * height ** 0.7

    # темнота: гражданские сумерки уже сносно, астрономическая ночь — максимум
    darkness = np.clip((-sun_altitude_deg - 6.0) / 12.0, 0.0, 1.0)
    points += 25.0 * darkness

    # Луна мешает, только если она сама над горизонтом
    if moon_altitude_deg is not None and moon_altitude_deg > 0:
        glare = (moon_illumination or 0.0) ** 1.5
        proximity = np.clip(1.0 - (moon_separation_deg or 180.0) / 90.0, 0.0, 1.0)
        interference = glare * (0.45 + 0.55 * proximity)
        points += 20.0 * (1.0 - interference)
    else:
        points += 20.0

    instrument = instrument_for(magnitude)
    points += {"eye": 12.0, "binoculars": 8.0, "telescope": 4.0}[instrument]

    points += 8.0 * np.clip(window_minutes / 120.0, 0.0, 1.0)

    total = int(round(np.clip(points, 0, 100)))
    if total >= 80:
        stars = 5
    elif total >= 65:
        stars = 4
    elif total >= 48:
        stars = 3
    elif total >= 30:
        stars = 2
    else:
        stars = 1
    return total, stars


def moon_interference_text(illumination: float | None, altitude_deg: float | None,
                           separation_deg_value: float | None) -> str:
    if altitude_deg is None or altitude_deg <= 0:
        return "Луна под горизонтом, не мешает"
    fraction = illumination or 0.0
    if fraction < 0.25:
        return "Луна почти не мешает"
    if fraction < 0.6:
        near = separation_deg_value is not None and separation_deg_value < 40
        return "Луна подсвечивает небо" + (" рядом с объектом" if near else "")
    if separation_deg_value is not None and separation_deg_value < 40:
        return "яркая Луна рядом с объектом, условия плохие"
    return "яркая Луна засвечивает небо"


def circumstances(target, city: City, when: dt.datetime,
                  magnitude: float | None = None,
                  window_hours: float = 6.0,
                  min_altitude_deg: float = 5.0,
                  max_sun_altitude_deg: float = -6.0) -> Circumstances:
    """Обстоятельства наблюдения цели из города вокруг момента `when`.

    `target` — любой объект Skyfield: планета, Луна, `Star`, комета.
    """
    site = topos(city)
    grid = ts_range(when - dt.timedelta(hours=window_hours / 2),
                    when + dt.timedelta(hours=window_hours / 2), 5)

    apparent = site.at(grid).observe(target).apparent()
    altitude, azimuth, _ = apparent.altaz()
    altitude = altitude.degrees
    azimuth = azimuth.degrees
    sun_alt = site.at(grid).observe(body("sun")).apparent().altaz()[0].degrees
    moon_alt = site.at(grid).observe(body("moon")).apparent().altaz()[0].degrees

    good = (altitude > min_altitude_deg) & (sun_alt < max_sun_altitude_deg)
    if not good.any():
        best = int(np.argmax(altitude))
        return Circumstances(
            city=city, visible=False,
            best_time=to_msk(grid[best]),
            altitude_deg=float(altitude[best]),
            azimuth_deg=float(azimuth[best]),
            direction=compass_direction(float(azimuth[best])),
            sun_altitude_deg=float(sun_alt[best]),
            moon_altitude_deg=float(moon_alt[best]),
            note="объект не поднимается достаточно высоко на тёмном небе")

    indices = np.where(good)[0]
    best = int(indices[np.argmax(altitude[indices])])
    window_start, window_end = to_msk(grid[indices[0]]), to_msk(grid[indices[-1]])
    window_minutes = (window_end - window_start).total_seconds() / 60.0

    from skyfield import almanac

    from .core import planets
    t_best = grid[best]
    illumination = float(almanac.fraction_illuminated(planets(), "moon", t_best))
    moon_sep = float(separation_deg(t_best, target, body("moon"), center=site))

    score, stars = score_conditions(
        float(altitude[best]), float(sun_alt[best]), float(moon_alt[best]),
        illumination, moon_sep, magnitude, window_minutes)

    return Circumstances(
        city=city, visible=True, best_time=to_msk(t_best),
        altitude_deg=float(altitude[best]), azimuth_deg=float(azimuth[best]),
        direction=compass_direction(float(azimuth[best])),
        sun_altitude_deg=float(sun_alt[best]),
        moon_altitude_deg=float(moon_alt[best]),
        moon_illumination=illumination, moon_separation_deg=moon_sep,
        window_start=window_start, window_end=window_end,
        window_minutes=window_minutes, score=score, stars=stars,
        instrument=instrument_for(magnitude),
        note=moon_interference_text(illumination, float(moon_alt[best]), moon_sep))


def summarise(circumstance: Circumstances) -> list[str]:
    """Человеко-читаемая сводка для панели события."""
    if not circumstance.visible:
        return [f"{circumstance.city.name}: не наблюдается — {circumstance.note}"]
    c = circumstance
    return [
        f"{c.city.name}: {c.stars_text} ({c.score}/100)",
        f"Лучшее время: {c.best_time:%d.%m %H:%M} МСК",
        f"Высота: {c.altitude_deg:.0f}°, азимут {c.azimuth_deg:.0f}° ({c.direction})",
        f"Окно наблюдения: {c.window_start:%H:%M}–{c.window_end:%H:%M} "
        f"({c.window_minutes:.0f} мин)",
        f"Солнце: {c.sun_altitude_deg:.0f}°, Луна: {c.moon_altitude_deg:.0f}° "
        f"(Ф={c.moon_illumination:.2f}), {c.moon_separation_deg:.0f}° от объекта",
        f"Инструмент: {c.instrument_ru}",
        f"Помехи: {c.note}",
    ]


# ------------------------------------------------------------------ цель события


TARGET_KEYWORDS = {
    "меркури": "mercury", "венер": "venus", "марс": "mars", "юпитер": "jupiter",
    "сатурн": "saturn", "уран": "uranus", "нептун": "neptune", "луна": "moon",
}


def guess_target(event) -> tuple[object | None, float | None]:
    """Определить наблюдаемый объект и его блеск по событию.

    Возвращает (объект Skyfield, звёздная величина) — или (None, None), если
    событие не привязано к конкретному телу (равноденствие, пуск ракеты).
    """
    import re

    text = event.text.lower()
    magnitude = None
    found = re.search(r"V=([+-]\d+),(\d+)m", event.text)
    if found:
        magnitude = float(f"{found.group(1)}.{found.group(2)}")

    # координаты цели, если модуль их сохранил
    meta = event.meta or {}
    if meta.get("ra_deg") is not None and meta.get("dec_deg") is not None:
        from skyfield.api import Star
        return (Star(ra_hours=float(meta["ra_deg"]) / 15.0,
                     dec_degrees=float(meta["dec_deg"])), magnitude)

    for marker, name in TARGET_KEYWORDS.items():
        if marker in text:
            return body(name), magnitude
    return None, magnitude


def for_event(event, cities=None) -> list[Circumstances]:
    """Обстоятельства события во всех выбранных городах."""
    from .cities import all_cities

    target, magnitude = guess_target(event)
    if target is None:
        return []
    return [circumstances(target, city, event.when, magnitude)
            for city in (cities or all_cities())]


def best_city(event, cities=None) -> Circumstances | None:
    results = [c for c in for_event(event, cities) if c.visible]
    return max(results, key=lambda c: c.score) if results else None
