"""Режим Live: ближайшие события по свежим данным.

Месячный выпуск и оперативная сводка живут по разным законам. В выпуске важна
воспроизводимость: те же входные данные — тот же результат. В Live важна
свежесть: пролёты станций считаются по элементам орбиты, полученным только что,
а расписание пусков перечитывается заново, потому что дата старта меняется.

Поэтому Live ничего не берёт из месячного расчёта и не кэширует результат.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from astrocal import config as cfg
from astrocal.cities import City, by_key


@dataclass
class LiveItem:
    when: dt.datetime
    title: str
    detail: str
    kind: str
    confidence: str = "высокая"
    payload: dict = field(default_factory=dict)

    @property
    def relative(self) -> str:
        delta = self.when - dt.datetime.now(cfg.MSK)
        hours = delta.total_seconds() / 3600.0
        if hours < 0:
            return "идёт сейчас"
        if hours < 1:
            return f"через {delta.total_seconds() / 60:.0f} мин"
        if hours < 24:
            return f"через {hours:.0f} ч"
        return f"через {hours / 24:.0f} дн"


def station_passes(city: City, hours: float, progress=None) -> list[LiveItem]:
    """Пролёты МКС и китайской станции по свежему TLE."""
    from astrocal.events.iss import STATIONS
    from astrocal.render.satellite_map import passes_for_station

    start = dt.datetime.now(cfg.MSK)
    end = start + dt.timedelta(hours=hours)
    items: list[LiveItem] = []
    for index, catnr in enumerate(STATIONS):
        if progress:
            progress(f"Пролёты {STATIONS[catnr]['label']}",
                     int(30 + 40 * index / max(1, len(STATIONS))))
        for pass_ in passes_for_station(catnr, city, start, end):
            items.append(LiveItem(
                when=pass_.start,
                title=f"Пролёт {pass_.station} — до {pass_.max_altitude_deg:.0f}°",
                detail=(f"{pass_.start:%H:%M:%S}–{pass_.end:%H:%M:%S}, "
                        f"из {pass_.city.name}, азимут "
                        f"{pass_.start_azimuth_deg:.0f}° → "
                        f"{pass_.end_azimuth_deg:.0f}°, условия: {pass_.quality}"
                        + (", уходит в тень Земли" if pass_.enters_shadow else "")),
                kind="pass",
                confidence=("высокая" if pass_.tle_age_days <= 3
                            else "средняя" if pass_.tle_age_days <= 7
                            else "низкая"),
                payload={"pass": pass_},
            ))
    return items


def upcoming_launches(hours: float, progress=None) -> list[LiveItem]:
    """Пуски ближайших суток с текущим статусом Launch Library 2."""
    from astrocal.launches import STATUS_RU, fetch, is_interesting

    if progress:
        progress("Расписание пусков", 75)
    start = dt.datetime.now(cfg.MSK)
    end = start + dt.timedelta(hours=hours)
    try:
        records = fetch(start, end, use_cache=False)
    except Exception:
        return []

    items = []
    for record in records:
        net = dt.datetime.fromisoformat(record["net"].replace("Z", "+00:00"))
        status = (record.get("status") or {}).get("abbrev", "TBD")
        status_ru, confidence = STATUS_RU.get(status, ("статус неизвестен", "низкая"))
        items.append(LiveItem(
            when=net.astimezone(cfg.MSK),
            title=f"Пуск: {record['name']}",
            detail=f"статус {status} — {status_ru}"
                   + ("" if is_interesting(record) else " (не связан с МКС)"),
            kind="launch", confidence=confidence,
            payload={"id": record.get("id")},
        ))
    return items


def near_events(hours: float, progress=None) -> list[LiveItem]:
    """Астрономические события ближайших часов из основного расчёта.

    Считаются только те категории, которые быстро вычисляются: полноценный
    месячный прогон здесь неуместен — Live должен отвечать за секунды.
    """
    from astrocal.events import moon, planets, seasons

    if progress:
        progress("Астрономические события", 10)
    start = dt.datetime.now(cfg.MSK)
    end = start + dt.timedelta(hours=hours)

    events = []
    for module in (moon.phases, moon.apsides, seasons.all_events,
                   planets.stations):
        try:
            events += module(start, end)
        except Exception:
            continue
    try:
        events += moon.conjunctions_with_planets(start, end)
    except Exception:
        pass

    return [LiveItem(when=event.when, title=event.text,
                     detail=event.computed, kind="astronomy",
                     confidence=event.confidence)
            for event in events]


def collect(city_key: str = "москва", hours: float = 48.0,
            progress=None) -> list[LiveItem]:
    """Полная оперативная сводка на ближайшие `hours` часов."""
    city = by_key(city_key) or by_key("москва")
    items: list[LiveItem] = []
    items += near_events(hours, progress)
    items += station_passes(city, hours, progress)
    items += upcoming_launches(hours, progress)
    if progress:
        progress("Готово", 100)
    now = dt.datetime.now(cfg.MSK)
    return sorted((item for item in items if item.when >= now - dt.timedelta(hours=1)),
                  key=lambda item: item.when)
