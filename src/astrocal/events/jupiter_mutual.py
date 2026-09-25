"""Взаимные явления галилеевых спутников.

Спутник может закрыть не только диск планеты, но и другой спутник: пройти
перед ним (взаимное покрытие) или уронить на него свою тень (взаимное
затмение). Для наблюдателя это самое интересное, что вообще происходит в
системе Юпитера, — падение блеска видно даже в небольшой телескоп, и его можно
измерить фотометрически.

Случаются такие явления не каждый год. Орбиты галилеевых спутников лежат почти
в плоскости экватора Юпитера, и увидеть их «с ребра» можно только когда Земля
и Солнце проходят через эту плоскость — раз в шесть лет, вблизи равноденствия
Юпитера. Сезон 2026–2027 годов как раз такой. В остальное время модуль честно
возвращает пустой список: явлений нет, а не «не нашли».

Геометрия та же, что у прохождений по диску планеты, только вместо диска
Юпитера — диск второго спутника:

* **покрытие** — угловое расстояние между спутниками, как их видно с Земли,
  меньше суммы угловых радиусов; закрывает тот, что ближе к Земле;
* **затмение** — то же самое, но если смотреть от Солнца; тень отбрасывает
  тот, что ближе к Солнцу.

Солнце считается точечным. На деле у него с Юпитера угловой размер около 6′,
поэтому у настоящего затмения есть полутеневая фаза, и начинается оно чуть
раньше, а заканчивается чуть позже расчётного. Это записано в протоколе
события, а не спрятано.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from itertools import permutations

import numpy as np

from ..core import Event, body, earth, to_msk, ts_range
from .jupiter_moons import MOON_RU, MOONS, satellite

# Средние радиусы, км (IAU)
MOON_RADIUS_KM = {"io": 1821.6, "europa": 1560.8,
                  "ganymede": 2631.2, "callisto": 2410.3}

KIND_RU = {"occultation": "покрывает", "eclipse": "затмевает"}


@dataclass
class MutualEvent:
    """Одно взаимное явление."""
    kind: str                    # occultation | eclipse
    front: str                   # спутник, который закрывает или отбрасывает тень
    back: str                    # спутник, который закрывается
    start: dt.datetime
    middle: dt.datetime
    end: dt.datetime
    min_separation_arcsec: float
    obscuration: float           # доля закрытого диска, 0…1
    observable: bool             # виден ли момент максимума из России

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0

    @property
    def title(self) -> str:
        return (f"{MOON_RU[self.front]} {KIND_RU[self.kind]} "
                f"{MOON_RU[self.back]}")


def overlap_fraction(separation: float, radius_front: float,
                     radius_back: float) -> float:
    """Какая доля заднего диска закрыта передним.

    Обычная площадь пересечения двух кругов, делённая на площадь заднего.
    Нужна, чтобы отличать касание от полного закрытия: наблюдателю разница
    между «закрыто 5 %» и «закрыто 90 %» важнее самого факта явления.
    """
    if separation >= radius_front + radius_back:
        return 0.0
    if separation <= abs(radius_front - radius_back):
        # один диск целиком внутри другого
        return min(1.0, (radius_front / radius_back) ** 2)

    r1, r2, d = float(radius_front), float(radius_back), float(separation)
    angle1 = np.arccos(np.clip((d * d + r1 * r1 - r2 * r2) / (2 * d * r1), -1, 1))
    angle2 = np.arccos(np.clip((d * d + r2 * r2 - r1 * r1) / (2 * d * r2), -1, 1))
    area = (r1 * r1 * (angle1 - np.sin(2 * angle1) / 2)
            + r2 * r2 * (angle2 - np.sin(2 * angle2) / 2))
    return float(min(1.0, area / (np.pi * r2 * r2)))


def _positions(grid, origin, apparent: bool = True):
    """Векторы на спутники от наблюдателя, км, и расстояния до них.

    Для взгляда со стороны Солнца видимое положение не считается: поправка за
    отклонение света требует Земли как наблюдателя, и Skyfield на таком запросе
    выходит за пределы эфемериды. Геометрии тени достаточно астрометрического
    положения с учётом времени распространения света — его `observe` уже даёт.
    """
    vectors, distances = {}, {}
    for name, code in MOONS.items():
        position = origin.at(grid).observe(satellite(code))
        if apparent:
            position = position.apparent()
        vectors[name] = position.position.km
        distances[name] = np.linalg.norm(vectors[name], axis=0)
    return vectors, distances


def _separations(vectors, distances, front: str, back: str):
    """Угловое расстояние между спутниками и сумма их угловых радиусов, рад."""
    cosine = np.einsum("ij,ij->j", vectors[front], vectors[back]) / (
        distances[front] * distances[back])
    separation = np.arccos(np.clip(cosine, -1.0, 1.0))
    radius_front = MOON_RADIUS_KM[front] / distances[front]
    radius_back = MOON_RADIUS_KM[back] / distances[back]
    return separation, radius_front, radius_back


def _episodes(mask) -> list[tuple[int, int]]:
    """Непрерывные участки True как пары индексов."""
    out, start = [], None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        elif not value and start is not None:
            out.append((start, index - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def find(start: dt.datetime, end: dt.datetime,
         step_minutes: int = 2) -> list[MutualEvent]:
    """Все взаимные явления за период.

    Шаг две минуты: типичное явление длится от нескольких минут до получаса,
    и более крупная сетка его просто перешагнёт.
    """
    from .jupiter_moons import _observable_mask

    grid = ts_range(start, end, step_minutes)
    earth_vectors, earth_distances = _positions(grid, earth())
    sun_vectors, sun_distances = _positions(grid, body("sun"),
                                            apparent=False)
    observable = _observable_mask(grid)

    found: list[MutualEvent] = []
    for first, second in permutations(MOONS, 2):
        for kind, vectors, distances in (
                ("occultation", earth_vectors, earth_distances),
                ("eclipse", sun_vectors, sun_distances)):
            # закрывает тот, кто ближе к наблюдателю (или к Солнцу)
            nearer = distances[first] < distances[second]
            separation, radius_front, radius_back = _separations(
                vectors, distances, first, second)
            touching = separation < (radius_front + radius_back)
            mask = touching & nearer
            if not mask.any():
                continue

            for begin, finish in _episodes(mask):
                window = slice(begin, finish + 1)
                index = begin + int(np.argmin(separation[window]))
                fraction = overlap_fraction(
                    float(separation[index]), float(radius_front[index]),
                    float(radius_back[index]))
                if fraction <= 0.01:
                    continue
                found.append(MutualEvent(
                    kind=kind, front=first, back=second,
                    start=to_msk(grid[begin]),
                    middle=to_msk(grid[index]),
                    end=to_msk(grid[finish]),
                    min_separation_arcsec=float(
                        np.degrees(separation[index]) * 3600.0),
                    obscuration=fraction,
                    observable=bool(observable[index])))
    return sorted(found, key=lambda item: item.middle)


def to_event(item: MutualEvent) -> Event:
    from ..fmt import number

    kind_ru = ("взаимное покрытие" if item.kind == "occultation"
               else "взаимное затмение")
    percent = f"{item.obscuration * 100:.0f} %"
    return Event(
        when=item.middle,
        text=(f"Спутники Юпитера: {item.title} "
              f"({kind_ru}), закрыто {percent} диска, "
              f"{number(item.duration_minutes)} мин"),
        category="jupiter_mutual",
        confidence="средняя",
        rank="interesting" if item.observable else "optional",
        computed=(
            f"минимальное угловое расстояние между спутниками "
            f"{number(item.min_separation_arcsec, 2)}″; закрыто "
            f"{item.obscuration * 100:.1f} % диска "
            f"{MOON_RU[item.back]}; явление с "
            f"{item.start:%H:%M} до {item.end:%H:%M} МСК"
            + ("; из Москвы в максимуме наблюдаемо"
               if item.observable else "; из Москвы в максимуме не наблюдаемо")
            + ("; Солнце считается точечным, поэтому полутеневая фаза "
               "затмения начинается раньше и заканчивается позже расчётной"
               if item.kind == "eclipse" else "")),
        sources=["JPL jup380s (эфемериды спутников)", "Skyfield/DE440s"],
        precision="minute",
        meta={"mutual": item.kind, "front": item.front, "back": item.back,
              "obscuration": item.obscuration,
              "duration_min": item.duration_minutes,
              "observable": item.observable},
    )


def significant(items: list[MutualEvent]) -> list[MutualEvent]:
    """Что из явлений стоит публиковать.

    В сезон их случаются десятки в месяц, и большинство — касания на проценты
    диска, неотличимые от шума даже фотометрически. Остаются заметные
    перекрытия, которые можно наблюдать с территории России.
    """
    from .. import config as cfg

    chosen = [item for item in items
              if item.observable
              and item.obscuration >= cfg.JUPITER_MUTUAL_MIN_OBSCURATION
              and item.duration_minutes >= cfg.JUPITER_MUTUAL_MIN_MINUTES]
    chosen.sort(key=lambda item: -item.obscuration)
    return sorted(chosen[:cfg.JUPITER_MUTUAL_MAX_IN_CALENDAR],
                  key=lambda item: item.middle)


def all_events(start: dt.datetime, end: dt.datetime) -> tuple[list[Event], list]:
    """Взаимные явления месяца: строки календаря и полный список для протокола.

    Вне сезона оба списка пусты — это нормальный результат, а не сбой.
    """
    items = find(start, end)
    return [to_event(item) for item in significant(items)], items
