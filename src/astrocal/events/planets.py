"""События планет: стояния, противостояния, соединения, элонгации, сближения."""
from __future__ import annotations

import datetime as dt
import itertools

import numpy as np

from ..core import (Event, body, constellation_at, earth, find_zero, local_minima,
                    refine_minimum, separation_deg, timescale, to_msk, ts_range)
from ..apparent import planet_label
from ..fmt import PLANETS_RU, angle_deg, ru_constellation
from ..magnitudes import planet_magnitude

OUTER = ("mars", "jupiter", "saturn", "uranus", "neptune")
INNER = ("mercury", "venus")
ALL = INNER + OUTER

RU_NOM = PLANETS_RU
RU_GEN = {"mercury": "Меркурия", "venus": "Венеры", "mars": "Марса",
          "jupiter": "Юпитера", "saturn": "Сатурна", "uranus": "Урана",
          "neptune": "Нептуна"}


def _ecliptic_lon(t, target) -> np.ndarray:
    """Видимая геоцентрическая эклиптическая долгота, градусы."""
    lat, lon, _ = earth().at(t).observe(target).apparent().ecliptic_latlon()
    return lon.degrees


def _lon_rate(tt: float, target) -> float:
    """Скорость по долготе, °/сут (центральная разность, шаг 0.5 сут)."""
    ts = timescale()
    h = 0.5
    a = _ecliptic_lon(ts.tt_jd(tt - h), target)
    b = _ecliptic_lon(ts.tt_jd(tt + h), target)
    return float((b - a + 180.0) % 360.0 - 180.0) / (2 * h)


def stations(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Переходы прямое↔попятное движение (смена знака скорости по долготе)."""
    ts = timescale()
    grid = ts_range(start - dt.timedelta(days=2), end + dt.timedelta(days=2), 360)
    out = []
    for name in ALL:
        target = body(name)
        rates = np.array([_lon_rate(t.tt, target) for t in grid])
        for i in range(len(rates) - 1):
            if rates[i] == 0 or (rates[i] > 0) == (rates[i + 1] > 0):
                continue
            tt = find_zero(lambda x, tgt=target: _lon_rate(x, tgt),
                           grid[i].tt, grid[i + 1].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            if not (start <= when < end):
                continue
            to_retro = rates[i] > 0
            const = ru_constellation(constellation_at()(
                earth().at(t).observe(target).apparent()))
            out.append(Event(
                when=when,
                text=(f"{RU_NOM[name]} ({planet_label(name, t)}) переходит от "
                      + ("прямого движения к попятному" if to_retro
                         else "попятного движения к прямому")
                      + f" в созвездии {const}"),
                category="planet",
                computed=("смена знака видимой геоцентрической эклиптической долготы, "
                          f"нуль скорости в {t.utc_strftime('%Y-%m-%d %H:%M UTC')}"),
                sources=["Skyfield/DE440s"],
                precision="hour",
            ))
    return out


def solar_configurations(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Противостояния и соединения внешних планет, элонгации внутренних."""
    from .moon import direction

    ts = timescale()
    sun = body("sun")
    grid = ts_range(start - dt.timedelta(days=2), end + dt.timedelta(days=2), 180)
    out = []

    # Противостояние/соединение определяются разностью видимых геоцентрических
    # эклиптических долгот, а не угловым расстоянием: из-за наклона орбиты
    # элонгация Нептуна, например, вообще не достигает 180°.
    def dlon(tt, tgt):
        t = ts.tt_jd(tt)
        return float((_ecliptic_lon(t, tgt) - _ecliptic_lon(t, sun) + 180.0) % 360.0 - 180.0)

    for name in OUTER:
        target = body(name)
        d = np.array([dlon(t.tt, target) for t in grid])
        for i in range(len(d) - 1):
            crossing_opp = abs(d[i]) > 90 and abs(d[i + 1]) > 90 and (d[i] > 0) != (d[i + 1] > 0)
            crossing_conj = abs(d[i]) < 90 and (d[i] > 0) != (d[i + 1] > 0)
            if not (crossing_opp or crossing_conj):
                continue
            func = ((lambda x, tgt=target: (dlon(x, tgt) % 360.0) - 180.0) if crossing_opp
                    else (lambda x, tgt=target: dlon(x, tgt)))
            tt = find_zero(func, grid[i].tt, grid[i + 1].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            if not (start <= when < end):
                continue
            const = ru_constellation(constellation_at()(
                earth().at(t).observe(target).apparent()))
            kind = "в противостоянии с Солнцем" if crossing_opp else "в соединении с Солнцем"
            out.append(Event(
                when=when,
                text=(f"{RU_NOM[name]} ({planet_label(name, t)}) "
                      f"{kind} в созвездии {const}"),
                category="planet",
                computed=("разность видимых геоцентрических эклиптических долгот "
                          f"планеты и Солнца проходит через {180 if crossing_opp else 0}°"),
                sources=["Skyfield/DE440s"],
                precision="hour",
            ))

    # Нижние и верхние соединения внутренних планет
    for name in INNER:
        target = body(name)
        d = np.array([dlon(t.tt, target) for t in grid])
        for i in range(len(d) - 1):
            if abs(d[i]) > 90 or (d[i] > 0) == (d[i + 1] > 0):
                continue
            tt = find_zero(lambda x, tgt=target: dlon(x, tgt), grid[i].tt, grid[i + 1].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            if not (start <= when < end):
                continue
            planet_range = earth().at(t).observe(target).distance().au
            sun_range = earth().at(t).observe(sun).distance().au
            inferior = planet_range < sun_range
            # Долготы совпали, но планета не садится на Солнце: по широте
            # остаётся заметный просвет, и наблюдателю важно знать какой.
            gap = float(separation_deg(t, target, sun))
            side = direction(t, target, sun)
            out.append(Event(
                when=when,
                text=(f"{RU_NOM[name]} ({planet_label(name, t)}) в "
                      f"{'нижнем' if inferior else 'верхнем'} соединении "
                      f"в {angle_deg(gap)} {side} Солнца"),
                category="planet",
                computed=("разность видимых геоцентрических эклиптических долгот "
                          f"проходит через 0°; угловое расстояние до Солнца "
                          f"{gap:.2f}°; расстояние до планеты "
                          f"{planet_range:.3f} а.е. против {sun_range:.3f} а.е. до Солнца"),
                sources=["Skyfield/DE440s"],
                precision="hour",
            ))

    for name in INNER:
        target = body(name)
        elong = separation_deg(grid, target, sun)

        def negf(tt, tgt=target):
            return -float(separation_deg(ts.tt_jd(tt), tgt, sun))

        for i in range(1, len(elong) - 1):
            if not (elong[i] > elong[i - 1] and elong[i] >= elong[i + 1]):
                continue
            tt = refine_minimum(negf, grid[i - 1].tt, grid[i + 1].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            if not (start <= when < end):
                continue
            e = -negf(tt)
            # западная элонгация — планета видна утром (долгота меньше солнечной)
            lon_p = _ecliptic_lon(t, target)
            lon_s = _ecliptic_lon(t, sun)
            west = ((lon_p - lon_s + 360.0) % 360.0) > 180.0
            out.append(Event(
                when=when,
                text=(f"{RU_NOM[name]} ({planet_label(name, t)}) "
                      f"в наибольшей {'западной' if west else 'восточной'} элонгации "
                      f"{e:.0f}° от Солнца, {'утренняя' if west else 'вечерняя'} видимость"),
                category="planet",
                computed=f"максимум элонгации: {e:.2f}°",
                sources=["Skyfield/DE440s"],
                precision="hour",
            ))
    return out


def mutual_approaches(start: dt.datetime, end: dt.datetime,
                      limit_deg: float = 5.0,
                      min_elongation_deg: float = 10.0) -> list[Event]:
    """Тесные сближения планета–планета.

    Как и в календарях, событие ставится не в момент математического минимума
    (он часто приходится на светлое время), а на ближайший момент, когда пару
    реально видно из Москвы, — при условии, что сближение к тому времени ещё в
    силе.
    """
    from ..core import observer
    from .moon import direction

    ts = timescale()
    sun = body("sun")
    site = observer()
    grid = ts_range(start - dt.timedelta(days=1), end + dt.timedelta(days=1), 15)
    grid_tt = grid.tt
    sun_alt = site.at(grid).observe(sun).apparent().altaz()[0].degrees
    out = []
    for a_name, b_name in itertools.combinations(ALL, 2):
        a, b = body(a_name), body(b_name)
        sep = separation_deg(grid, a, b)
        if sep.min() > limit_deg + 2:
            continue
        alt_a = site.at(grid).observe(a).apparent().altaz()[0].degrees
        alt_b = site.at(grid).observe(b).apparent().altaz()[0].degrees
        observable = (alt_a > 2.0) & (alt_b > 2.0) & (sun_alt < -4.0)

        def f(tt, a=a, b=b):
            return float(separation_deg(ts.tt_jd(tt), a, b))

        for i in local_minima(grid, sep):
            tt_min = refine_minimum(f, grid[i - 1].tt, grid[i + 1].tt)
            sep_min = f(tt_min)
            if sep_min > limit_deg:
                continue
            if separation_deg(ts.tt_jd(tt_min), a, sun) < min_elongation_deg:
                continue        # пара тонет в лучах Солнца

            candidates = np.where(observable & (sep <= limit_deg))[0]
            if len(candidates):
                j = int(candidates[np.argmin(np.abs(candidates - i))])
                if abs(grid_tt[j] - tt_min) * 24 > 18:
                    continue    # видно только за сутки до/после — это уже не событие
                t, d = grid[j], float(sep[j])
                visible = True
            else:
                t, d = ts.tt_jd(tt_min), sep_min
                visible = False

            when = to_msk(t)
            if not (start <= when < end):
                continue
            const = ru_constellation(constellation_at()(
                earth().at(t).observe(a).apparent()))
            out.append(Event(
                when=when,
                text=(f"{RU_NOM[a_name]} ({planet_label(a_name, t)}) "
                      f"проходит в {angle_deg(d)} {direction(t, a, b)} "
                      f"{RU_GEN[b_name]} ({planet_label(b_name, t)}) "
                      f"в созвездии {const}"),
                category="planet",
                computed=(f"минимум расстояния {a_name}–{b_name}: {sep_min:.3f}° в "
                          f"{to_msk(ts.tt_jd(tt_min)):%d.%m %H:%M} МСК; в календаре "
                          f"момент наблюдаемости, разделение {d:.3f}°"),
                sources=["Skyfield/DE440s"],
                precision="hour",
                notes=("" if visible else "из Москвы в эти сутки пара не наблюдается"),
            ))
    return out


# Соединения планет со звёздами. Порог зависит от звезды: яркую видно рядом
# с планетой и на двух градусах, слабую имеет смысл упоминать только при
# тесном сближении, иначе календарь заполнят проходы мимо безымянных звёзд.
STAR_CONJ_BRIGHT = (3.0, 2.0)     # звезда ярче +3,0ᵐ — расстояние до 2°
STAR_CONJ_FAINT = (7.0, 1.0)      # от +3,0ᵐ до +7,0ᵐ — до 1°


def star_conjunction_limit(star_mag: float) -> float:
    """Максимальное расстояние, при котором сближение идёт в календарь."""
    if star_mag <= STAR_CONJ_BRIGHT[0]:
        return STAR_CONJ_BRIGHT[1]
    if star_mag <= STAR_CONJ_FAINT[0]:
        return STAR_CONJ_FAINT[1]
    return 0.0


def star_approaches(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Соединения планет со звёздами.

    Планета за месяц проходит по небу считанные градусы, поэтому звёзды
    отбираются не по всему каталогу, а по коридору вокруг её трассы: иначе
    пришлось бы считать расстояние до пятнадцати тысяч звёзд на каждом узле
    сетки.
    """
    from skyfield.api import Star

    from ..catalogs import STAR_NAMES_RU, angular_distance_deg, bright_stars
    from ..core import observer
    from ..fmt import magnitude as fmt_magnitude
    from .moon import direction

    ts = timescale()
    site = observer()
    sun = body("sun")
    grid = ts_range(start - dt.timedelta(days=1), end + dt.timedelta(days=1), 60)
    grid_tt = grid.tt
    sun_alt = site.at(grid).observe(sun).apparent().altaz()[0].degrees
    stars = bright_stars(mag_limit=STAR_CONJ_FAINT[0])
    margin = STAR_CONJ_BRIGHT[1] + 0.5

    out: list[Event] = []
    for name in ALL:
        target = body(name)
        track = earth().at(grid).observe(target).apparent()
        ra, dec, _distance = track.radec()
        ra_deg, dec_deg = ra.degrees, dec.degrees
        alt = site.at(grid).observe(target).apparent().altaz()[0].degrees
        observable = (alt > 5.0) & (sun_alt < -6.0)

        near = stars[(stars.dec_degrees > dec_deg.min() - margin)
                     & (stars.dec_degrees < dec_deg.max() + margin)]
        for _index, row in near.iterrows():
            limit = star_conjunction_limit(float(row.magnitude))
            if limit <= 0.0:
                continue
            separation = angular_distance_deg(ra_deg, dec_deg,
                                              row.ra_degrees, row.dec_degrees)
            if separation.min() > limit:
                continue
            star = Star(ra_hours=float(row.ra_degrees) / 15.0,
                        dec_degrees=float(row.dec_degrees))

            def closest(tt, star=star, target=target):
                return float(separation_deg(ts.tt_jd(tt), target, star))

            for i in local_minima(grid, separation):
                tt_min = refine_minimum(closest, grid[i - 1].tt, grid[i + 1].tt)
                sep_min = closest(tt_min)
                if sep_min > limit:
                    continue

                # как и у пар планет: в календаре стоит ближайший момент,
                # когда сближение реально видно, а не математический минимум
                candidates = np.where(observable & (separation <= limit))[0]
                if not len(candidates):
                    continue
                j = int(candidates[np.argmin(np.abs(candidates - i))])
                if abs(grid_tt[j] - tt_min) * 24 > 18:
                    continue
                t, gap = grid[j], float(separation[j])
                when = to_msk(t)
                if not (start <= when < end):
                    continue

                hip = int(row.hip)
                named = STAR_NAMES_RU.get(hip)
                label = (f"звезды {named} (HIP {hip}, "
                         f"{fmt_magnitude(float(row.magnitude))})" if named
                         else f"звезды HIP {hip} "
                              f"({fmt_magnitude(float(row.magnitude))})")
                const = ru_constellation(constellation_at()(
                    earth().at(t).observe(target).apparent()))
                out.append(Event(
                    when=when,
                    text=(f"{RU_NOM[name]} ({planet_label(name, t)}) проходит "
                          f"в {angle_deg(gap)} {direction(t, target, star)} "
                          f"{label} в созвездии {const}"),
                    category="planet",
                    computed=(f"минимум расстояния {name}–HIP {hip}: "
                              f"{sep_min:.3f}° в "
                              f"{to_msk(ts.tt_jd(tt_min)):%d.%m %H:%M} МСК; "
                              f"в календаре момент наблюдаемости, разделение "
                              f"{gap:.3f}°; порог для звезды "
                              f"{row.magnitude:+.1f}ᵐ — {limit:.1f}°"),
                    sources=["Skyfield/DE440s", "Hipparcos"],
                    precision="hour",
                    meta={"planet": name, "hip": hip,
                          "star_mag": float(row.magnitude),
                          "sep_deg": gap},
                ))
    return _deduplicate_stars(out)


def _deduplicate_stars(events: list[Event]) -> list[Event]:
    """Не больше одного сближения на планету за ночь — самое тесное.

    Без этого октябрь превращается в двадцать строк подряд: Марс идёт через
    Рак и всю дорогу проходит мимо безымянных звёзд шестой величины. Каждая
    такая строка по правилу законна, но вместе они вытесняют из выпуска всё
    остальное.

    Сближения с яркими звёздами из ограничения выведены: их мало, у них есть
    имена, и именно ради них правило и задумано.
    """
    kept, best = [], {}
    for event in sorted(events, key=lambda e: e.meta["sep_deg"]):
        if event.meta["star_mag"] <= STAR_CONJ_BRIGHT[0]:
            kept.append(event)
            continue
        best.setdefault((event.meta["planet"], event.when.date()), event)
    return sorted(kept + list(best.values()), key=lambda e: e.when)


def greatest_brilliancy(start: dt.datetime, end: dt.datetime) -> list[Event]:
    """Наибольший блеск Венеры и Меркурия.

    Максимум яркости не совпадает ни с элонгацией, ни с соединением: он там,
    где произведение фазы на видимый диаметр наибольшее. Обзорные календари
    это событие публикуют, поэтому считаем его отдельно.
    """

    ts = timescale()
    grid = ts_range(start - dt.timedelta(days=3), end + dt.timedelta(days=3), 180)
    out = []
    for name in INNER:
        magnitudes = np.array([planet_magnitude(name, t) for t in grid])
        for i in range(1, len(magnitudes) - 1):
            if not (magnitudes[i] < magnitudes[i - 1]
                    and magnitudes[i] <= magnitudes[i + 1]):
                continue

            def negative(tt, name=name):
                return float(planet_magnitude(name, ts.tt_jd(tt)))

            tt = refine_minimum(negative, grid[i - 1].tt, grid[i + 1].tt)
            t = ts.tt_jd(tt)
            when = to_msk(t)
            if not (start <= when < end):
                continue
            elongation = float(separation_deg(t, body(name), body("sun")))
            if elongation < 10.0:
                continue        # у самого Солнца блеск не наблюдают
            const = ru_constellation(constellation_at()(
                earth().at(t).observe(body(name)).apparent()))
            out.append(Event(
                when=when,
                text=(f"{RU_NOM[name]} в максимальном блеске "
                      f"({planet_label(name, ts.tt_jd(tt), negative(tt))}) в созвездии {const}"),
                category="planet",
                computed=(f"минимум звёздной величины по модели Mallama 2018: "
                          f"{negative(tt):.2f}m; элонгация {elongation:.0f}°"),
                sources=["Skyfield/DE440s", "модель блеска Mallama 2018"],
                precision="hour",
            ))
    return out


def all_events(start: dt.datetime, end: dt.datetime) -> list[Event]:
    return (stations(start, end) + solar_configurations(start, end)
            + mutual_approaches(start, end) + star_approaches(start, end)
            + greatest_brilliancy(start, end))
