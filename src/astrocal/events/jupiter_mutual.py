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

**Про время затмений.** Покрытие мы видим тогда, когда оно происходит по
земным часам: это геометрия со стороны Земли, и момент события — сразу
наблюдаемый. С затмением иначе. Тень падает на спутник у Юпитера, а до нас
свет идёт около сорока девяти минут, и наблюдатель увидит явление настолько
же позже. Поэтому затмение считается в два приёма: сначала геометрия обоих
спутников на один и тот же момент (а не «как это видно с Солнца»), потом
найденные моменты сдвигаются на время хода света от затмеваемого спутника до
Земли. Без этой поправки расчёт расходился с наблюдением на несколько минут.

Тень, покинувшая один спутник, доходит до другого за секунду-две — это ниже
шага сетки, и такой поправки здесь нет.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from itertools import permutations

import numpy as np

from ..core import (Event, earth, find_zero, refine_minimum, round_to_minute,
                    timescale, to_msk, ts_range)
from .jupiter_moons import MOON_RU, MOONS, satellite

# Средние радиусы, км (IAU)
MOON_RADIUS_KM = {"io": 1821.6, "europa": 1560.8,
                  "ganymede": 2631.2, "callisto": 2410.3}

KIND_RU = {"occultation": "покрывает", "eclipse": "затмевает"}

# Кто кого — винительный падеж: «Европа затмевает Ио», но «Ио затмевает
# Европу» и «Европа покрывает Ганимеда». Без этого в календаре встречались
# фразы, где непонятно, какой спутник закрывает какой.
MOON_RU_ACC = {"io": "Ио", "europa": "Европу",
               "ganymede": "Ганимеда", "callisto": "Каллисто"}


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
    light_minutes: float = 0.0   # поправка за ход света до Земли, минуты

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0

    @property
    def title(self) -> str:
        return (f"{MOON_RU[self.front]} {KIND_RU[self.kind]} "
                f"{MOON_RU_ACC[self.back]}")


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


LIGHT_KM_S = 299792.458


def _positions_from_earth(grid):
    """Видимые положения спутников с Земли: готовая геометрия покрытий."""
    vectors, distances = {}, {}
    for name, code in MOONS.items():
        position = earth().at(grid).observe(satellite(code)).apparent()
        vectors[name] = position.position.km
        distances[name] = np.linalg.norm(vectors[name], axis=0)
    return vectors, distances


def _positions_from_sun(grid):
    """Направления Солнце→спутник, взятые на один и тот же момент.

    Именно так падает тень: оба спутника берутся в один момент времени.
    `observe` со стороны Солнца дал бы каждому своё запаздывание — это ответ
    на другой вопрос, «что увидел бы наблюдатель на Солнце».
    """
    from ..core import planets

    sun = planets()["sun"].at(grid).position.km
    vectors, distances = {}, {}
    for name, code in MOONS.items():
        vectors[name] = satellite(code).at(grid).position.km - sun
        distances[name] = np.linalg.norm(vectors[name], axis=0)
    return vectors, distances


def light_time_to_earth(grid, moon: str):
    """Время хода света от спутника до Земли, сутки."""
    distance = np.linalg.norm(
        earth().at(grid).observe(satellite(MOONS[moon])).position.km, axis=0)
    return distance / LIGHT_KM_S / 86400.0


def _gap_at(tt: float, kind: str, front: str, back: str) -> float:
    """Зазор между дисками в один момент: отрицательный — диски перекрыты.

    Нужен для уточнения контактов. Сетка в две минуты находит явление, но
    начало и конец на ней округлены до узла, а в календаре теперь стоит
    интервал с точностью до минуты — значит, контакты надо доводить.
    """
    t = timescale().tt_jd([tt])
    vectors, distances = (_positions_from_earth(t) if kind == "occultation"
                          else _positions_from_sun(t))
    separation, radius_front, radius_back = _separations(
        vectors, distances, front, back)
    return float(separation[0] - (radius_front[0] + radius_back[0]))


def _separation_at(tt: float, kind: str, front: str, back: str) -> float:
    """Угловое расстояние между спутниками в один момент, радианы."""
    t = timescale().tt_jd([tt])
    vectors, distances = (_positions_from_earth(t) if kind == "occultation"
                          else _positions_from_sun(t))
    separation, _front, _back = _separations(vectors, distances, front, back)
    return float(separation[0])


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
    earth_vectors, earth_distances = _positions_from_earth(grid)
    sun_vectors, sun_distances = _positions_from_sun(grid)
    observable = _observable_mask(grid)
    ts = timescale()

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

            # затмение происходит у Юпитера, а видим мы его почти на час
            # позже: моменты сдвигаются на время хода света до Земли
            delay = (light_time_to_earth(grid, second)
                     if kind == "eclipse" else np.zeros(len(grid)))

            for begin, finish in _episodes(mask):
                window = slice(begin, finish + 1)
                index = begin + int(np.argmin(separation[window]))
                fraction = overlap_fraction(
                    float(separation[index]), float(radius_front[index]),
                    float(radius_back[index]))
                if fraction <= 0.01:
                    continue

                # Контакты доводим бисекцией между соседними узлами сетки,
                # максимум — золотым сечением. Без этого начало и конец
                # округлены до двух минут, а в строке стоит точная минута.
                gap = (lambda tt, k=kind, f=first, s=second:
                       _gap_at(tt, k, f, s))
                begin_tt = float(grid[begin].tt)
                if begin > 0:
                    begin_tt = find_zero(gap, float(grid[begin - 1].tt),
                                         begin_tt)
                finish_tt = float(grid[finish].tt)
                if finish + 1 < len(grid):
                    finish_tt = find_zero(gap, float(grid[finish + 1].tt),
                                          finish_tt)
                middle_tt = refine_minimum(
                    lambda tt, k=kind, f=first, s=second:
                    _separation_at(tt, k, f, s),
                    float(grid[max(index - 1, 0)].tt),
                    float(grid[min(index + 1, len(grid) - 1)].tt))

                # время хода света берём на сам момент, а не на узел сетки
                def seen(tt: float, k=kind, s=second) -> dt.datetime:
                    shift = (float(light_time_to_earth(ts.tt_jd([tt]), s)[0])
                             if k == "eclipse" else 0.0)
                    return to_msk(ts.tt_jd(tt + shift))

                # глубину и разделение берём в уточнённом максимуме
                closest = _separation_at(middle_tt, kind, first, second)
                fraction = overlap_fraction(
                    closest, float(radius_front[index]),
                    float(radius_back[index]))

                found.append(MutualEvent(
                    kind=kind, front=first, back=second,
                    start=seen(begin_tt), middle=seen(middle_tt),
                    end=seen(finish_tt),
                    min_separation_arcsec=float(
                        np.degrees(closest) * 3600.0),
                    obscuration=fraction,
                    observable=bool(observable[index]),
                    light_minutes=float(delay[index] * 1440.0)))
    return sorted(found, key=lambda item: item.middle)


def to_event(item: MutualEvent) -> Event:
    from ..fmt import number

    kind_ru = ("взаимное покрытие" if item.kind == "occultation"
               else "взаимное затмение")
    percent = f"{item.obscuration * 100:.0f} %"
    return Event(
        when=item.start,
        text=(f"Спутники Юпитера: {item.title} "
              f"({kind_ru}), закрыто {percent} диска, "
              # округляем так же, как заголовок строки, иначе в одной
              # фразе стоят «04:21» и «с 04:20»
              f"с {round_to_minute(item.start):%H:%M} "
              f"до {round_to_minute(item.end):%H:%M}, "
              f"максимум в {round_to_minute(item.middle):%H:%M}"),
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
            + (f"; моменты указаны как их видно с Земли: к расчёту у Юпитера "
               f"добавлено время хода света {item.light_minutes:.0f} мин"
               if item.kind == "eclipse" else "")
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
