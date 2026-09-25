"""Близкие пролёты астероидов в живой ленте.

Сближение — событие предсказанное: CNEOS знает о нём заранее, и в месячном
календаре оно стоит законно. В Live оно попадает по другой причине — потому
что список сближений постоянно пополняется. Объект, открытый вчера, может
пройти мимо Земли послезавтра, и в календаре, свёрстанном первого числа, его
не было и быть не могло. Именно такие записи и должны догонять редактора.

Поэтому здесь `ScheduledEvent`, а не `DiscoveryEvent`: событие прогнозируемое,
у него есть точный момент, и его можно перенести в выпуск как обычную строку.
"""
from __future__ import annotations

import datetime as dt

from .. import config as cfg
from ..events import close_approaches
from ..fmt import number
from ..net import NetworkError
from .model import KIND_NEO, ScheduledEvent

SOURCE = close_approaches.SOURCE


def describe(approach: close_approaches.CloseApproach,
             sky: dict | None = None) -> ScheduledEvent:
    """Карточка сближения для живой ленты."""
    sky = sky or {}
    name = approach.fullname or approach.designation
    lines = [
        f"Размер: {approach.diameter_text}",
        f"До Земли: {approach.distance_text} "
        f"({number(approach.distance_ld, 2)} LD)",
        f"Скорость: {number(approach.velocity_km_s)} км/с",
    ]
    if approach.absolute_magnitude_H is not None:
        lines.append(f"H = {number(approach.absolute_magnitude_H)}m, "
                     f"диаметр по альбедо "
                     f"{close_approaches.ALBEDO_BRIGHT}…"
                     f"{close_approaches.ALBEDO_DARK}: "
                     f"{(approach.diameter_min or 0) * 1000:.0f}–"
                     f"{(approach.diameter_max or 0) * 1000:.0f} м")
    if approach.feed_magnitude is not None:
        lines.append(f"Блеск по таблице ван Бёйтенена: "
                     f"{number(approach.feed_magnitude, 1, sign=True)}m")
    if sky.get("visible"):
        magnitude = sky.get("magnitude")
        if magnitude is not None:
            lines.append(f"Наш расчёт блеска: {number(magnitude, 1, sign=True)}m")
            difference = approach.magnitude_difference
            if difference is not None and abs(difference) > 0.5:
                lines.append(f"Расхождение источников: "
                             f"{number(abs(difference))}m — проверить")
        lines.append(f"Максимальная высота в городе {sky['city']}: "
                     f"{sky['max_altitude_deg']:.0f}°")
        lines.append(f"Лучшее время: {sky['window_start']:%H:%M}–"
                     f"{sky['window_end']:%H:%M} МСК")
        lines.append("Движение по небу: "
                     f"{number(sky.get('sky_motion_arcsec_per_hour', 0) / 60)}′/ч")
        lines.append(f"Инструмент: {sky['instrument']}, условия: "
                     + "★" * sky.get("stars", 0))
    elif sky:
        lines.append(f"Наблюдаемость: {sky.get('note', 'не определена')}")

    payload = {
        "designation": approach.designation,
        "fullname": approach.fullname,
        "close_approach_datetime":
            approach.close_approach_datetime.isoformat(),
        "distance_au": approach.distance_au,
        "distance_km": approach.distance_km,
        "distance_ld": approach.distance_ld,
        "velocity_km_s": approach.velocity_km_s,
        "absolute_magnitude_H": approach.absolute_magnitude_H,
        "diameter_min": approach.diameter_min,
        "diameter_max": approach.diameter_max,
        "diameter_estimate": approach.diameter_estimate,
        "diameter_measured": approach.diameter_measured,
        "source": approach.source,
        "magnitude_computed": (sky or {}).get("magnitude"),
        "feed_magnitude": approach.feed_magnitude,
        "feed_source": approach.feed_source,
    }
    return ScheduledEvent(
        live_id=approach.live_id,
        kind=KIND_NEO,
        title=f"{name} — {number(approach.distance_ld)} LD",
        summary=close_approaches.to_event(approach).text,
        lines=lines,
        when=approach.close_approach_datetime,
        magnitude=sky.get("magnitude"),
        rank=approach.rank,
        stars=sky.get("stars", 0),
        payload=payload,
        sources=[SOURCE],
        provenance=approach.provenance(),
        observability=sky,
    )


def check(days: float = 30.0, cities=None, use_cache: bool = True,
          with_observability: bool = True,
          progress=None) -> tuple[list[ScheduledEvent], dict]:
    """Значимые сближения ближайших `days` суток."""
    from ..cities import all_cities

    if progress:
        progress("Сближения астероидов (CNEOS)", 10)
    start = dt.datetime.now(cfg.MSK)
    end = start + dt.timedelta(days=days)
    try:
        items = close_approaches.approaches(start, end, use_cache=use_cache)
    except (NetworkError, ValueError) as error:
        return [], {"source": SOURCE, "status": "недоступен", "error": str(error),
                    "new": 0, "total": 0}

    chosen = close_approaches.significant(items)

    # второй источник по блеску: его отсутствие не мешает работе
    from ..neo_feeds import load
    try:
        feed = load()
        close_approaches.attach_feed(chosen, feed)
    except Exception:                        # noqa: BLE001
        feed = None
    records = []
    for index, approach in enumerate(chosen):
        if progress:
            progress(f"Наблюдаемость {approach.designation}",
                     20 + int(70 * index / max(1, len(chosen))))
        sky = {}
        if with_observability:
            try:
                sky = close_approaches.best_observability(
                    approach, cities or all_cities()[:3])
            except Exception as error:            # noqa: BLE001
                sky = {"visible": False, "note": f"эфемерида недоступна: {error}"}
        records.append(describe(approach, sky))

    records += bright_records(feed)
    return records, {"source": SOURCE, "status": "ок", "total": len(items),
                     "new": len(records)}


def bright_records(feed=None) -> list[ScheduledEvent]:
    """Яркие околоземные астероиды на год вперёд.

    Это не сближения ближайших недель, а объекты, ради которых стоит заранее
    освободить ночь: 1999 AN10 в августе 2027 года выйдет на +7,6m. Месячный
    расчёт о них молчит до самого месяца события.
    """
    from ..neo_feeds import SOURCE as FEED_SOURCE

    try:
        entries = close_approaches.bright_of_year(feed)
    except Exception:                        # noqa: BLE001
        return []

    out = []
    for entry in entries:
        when = entry.peak_when
        if when is None:
            continue
        lines = [f"Размер: {entry.diameter_text}",
                 f"Максимум блеска: "
                 f"{number(entry.peak_magnitude, 1, sign=True)}m "
                 f"около {when:%d.%m.%Y}"]
        if entry.magnitude_today is not None:
            lines.append(f"Сейчас: {number(entry.magnitude_today, 1, sign=True)}m")
        if entry.closest_ld is not None and entry.closest_date is not None:
            lines.append(f"Наибольшее сближение: {number(entry.closest_ld)} LD "
                         f"{entry.closest_date:%d.%m.%Y}")
        out.append(ScheduledEvent(
            live_id=f"neo:bright:{entry.designation.strip()}",
            kind=KIND_NEO,
            title=f"{entry.designation} — максимум "
                  f"{number(entry.peak_magnitude, 1, sign=True)}m",
            summary=close_approaches.bright_to_event(entry).text,
            lines=lines,
            when=when,
            magnitude=entry.peak_magnitude,
            rank=close_approaches.bright_rank(entry),
            payload={"designation": entry.designation,
                     "diameter_text": entry.diameter_text,
                     "peak_magnitude": entry.peak_magnitude,
                     "feed_magnitude": entry.peak_magnitude,
                     "closest_ld": entry.closest_ld,
                     "distance_ld": entry.closest_ld,
                     "distance_km": ((entry.closest_ld or 0)
                                     * cfg.LUNAR_DISTANCE_KM) or None,
                     "absolute_magnitude_H": entry.absolute_magnitude,
                     "bright_of_year": True},
            sources=[FEED_SOURCE],
            provenance=entry.provenance(),
        ))
    return out
