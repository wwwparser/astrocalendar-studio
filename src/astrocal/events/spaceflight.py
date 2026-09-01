"""Космонавтика: запуски, стыковки, расстыковки, затопления.

Эфемеридами это не считается — данные приходят из расписаний Роскосмоса, ЦУП,
NASA и агрегаторов. Поэтому модуль ничего не выдумывает: он читает JSON-файл,
где у каждой строки есть источник, статус проверки и флаг include. В календарь
попадают только события с include=true, остальные уходят в протокол с пометкой,
почему они не опубликованы.
"""
from __future__ import annotations

import datetime as dt
import json

from .. import config as cfg
from ..core import Event


def data_path(year: int, month: int):
    return cfg.DATA / f"spaceflight_{year:04d}-{month:02d}.json"


def load(year: int, month: int) -> list[dict]:
    path = data_path(year, month)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("events", [])


def all_events(start: dt.datetime, end: dt.datetime):
    """(события для календаря, все записи из файла — для протокола)."""
    records = load(start.year, start.month)
    events, rejected = [], []
    for rec in records:
        when = dt.datetime.strptime(rec["when_msk"], "%Y-%m-%d %H:%M").replace(
            tzinfo=cfg.MSK)
        ev = Event(
            when=when,
            text=rec["text"],
            category="spaceflight",
            confidence=rec.get("confidence", "низкая"),
            computed="не расчёт — данные расписания миссии",
            sources=rec.get("sources", []),
            notes=rec.get("notes", ""),
            precision="minute",
            meta={"include": bool(rec.get("include"))},
        )
        (events if ev.meta["include"] and start <= when < end else rejected).append(ev)
    return events, rejected
