"""Хранение рассчитанного выпуска.

Настольной программе это не нужно: она держит выпуск в памяти, а при новом
запуске считает заново. Для веб-версии так нельзя — расчёт месяца занимает
десять–пятнадцать минут, и делать его на каждый заход в браузер бессмысленно.

Поэтому результат расчёта сохраняется целиком: события со всеми полями,
редакторские решения, итог проверок. Файл самодостаточен — по нему выпуск
восстанавливается без обращения к эфемеридам и к сети.

Формат — JSON, а не pickle, сознательно. Pickle привязан к версиям классов:
переименовали поле — и архив годичной давности больше не читается. JSON
переживает такие изменения: незнакомые поля игнорируются, отсутствующие
получают значения по умолчанию.

Что не сохраняется: обстоятельства наблюдения по городам и пути к картам. И
то и другое пересчитывается быстро, а весит много.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from astrocal import config as cfg
from astrocal.core import Event
from astrocal.qa import Flag

from .models import EditableEvent, Issue

FORMAT_VERSION = 1
ARCHIVE_DIR = cfg.DATA / "issues"


def path_for(year: int, month: int, directory: Path | None = None) -> Path:
    target = directory or ARCHIVE_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target / f"{year:04d}-{month:02d}.json"


def _plain(value):
    """Значение, пригодное для JSON.

    В `meta` попадает всякое: массивы numpy, datetime, полосы покрытий. Всё,
    что не сериализуется, превращается в строку — эти поля нужны фильтрам и
    протоколу, а не расчёту, и точность представления здесь не важна.
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    return str(value)


def dump_event(item: EditableEvent) -> dict:
    event = item.event
    return {
        "when": event.when.isoformat(),
        "text": event.text,
        "category": event.category,
        "confidence": event.confidence,
        "computed": event.computed,
        "sources": list(event.sources),
        "notes": event.notes,
        "precision": event.precision,
        "rank": event.rank,
        "meta": _plain(event.meta),
        "provenance": _plain(event.provenance),
        "flags": [{"level": flag.level, "check": flag.check,
                   "message": flag.message} for flag in event.flags],
        "selected": item.selected,
        "editor_text": item.editor_text,
        "order": item.order,
        "manual": item.manual,
        "source_changed": item.source_changed,
    }


def load_event(record: dict) -> EditableEvent:
    event = Event(
        when=dt.datetime.fromisoformat(record["when"]),
        text=record.get("text", ""),
        category=record.get("category", "other"),
        confidence=record.get("confidence", "средняя"),
        computed=record.get("computed", ""),
        sources=list(record.get("sources") or []),
        notes=record.get("notes", ""),
        precision=record.get("precision", "minute"),
        meta=dict(record.get("meta") or {}),
        rank=record.get("rank", "interesting"),
        provenance=dict(record.get("provenance") or {}),
    )
    event.flags = [Flag(flag.get("level", "INFO"), flag.get("check", ""),
                        flag.get("message", ""))
                   for flag in record.get("flags") or []]
    return EditableEvent(
        event=event,
        selected=bool(record.get("selected", True)),
        editor_text=record.get("editor_text"),
        order=int(record.get("order", 0)),
        manual=bool(record.get("manual", False)),
        source_changed=bool(record.get("source_changed", False)),
    )


def dump(issue: Issue) -> dict:
    qa = issue.qa or {}
    return {
        "format": FORMAT_VERSION,
        "year": issue.year,
        "month": issue.month,
        "computed_at": (issue.computed_at.isoformat()
                        if issue.computed_at else None),
        "saved_at": dt.datetime.now(cfg.MSK).isoformat(),
        "enabled_kinds": sorted(issue.enabled_kinds),
        "enabled_ranks": sorted(issue.enabled_ranks),
        "primary_city": issue.primary_city,
        "cities": list(issue.cities),
        "icons": bool(getattr(issue, "icons", False)),
        # из результата проверки храним только счётчики: сами события со
        # своими флагами лежат рядом
        "qa": {"total": qa.get("total", 0),
               "review": len(qa.get("review", []) or []),
               "warn": len(qa.get("warn", []) or []),
               "clean": qa.get("clean", 0)},
        "events": [dump_event(item) for item in issue.ordered()],
    }


def load(payload: dict) -> Issue:
    issue = Issue(
        year=int(payload["year"]),
        month=int(payload["month"]),
        enabled_kinds=set(payload.get("enabled_kinds") or []),
        enabled_ranks=set(payload.get("enabled_ranks") or
                          ["must", "interesting"]),
        primary_city=payload.get("primary_city", "москва"),
        cities=list(payload.get("cities") or []),
    )
    issue.icons = bool(payload.get("icons", False))
    computed_at = payload.get("computed_at")
    if computed_at:
        issue.computed_at = dt.datetime.fromisoformat(computed_at)
    issue.events = [load_event(record) for record in payload.get("events") or []]
    counts = payload.get("qa") or {}
    issue.qa = {"total": counts.get("total", len(issue.events)),
                "review": [], "warn": [], "clean": counts.get("clean", 0),
                "restored": True}
    return issue


def save(issue: Issue, directory: Path | None = None) -> Path:
    target = path_for(issue.year, issue.month, directory)
    target.write_text(json.dumps(dump(issue), ensure_ascii=False, indent=1),
                      encoding="utf-8")
    return target


def read(year: int, month: int, directory: Path | None = None) -> Issue | None:
    target = path_for(year, month, directory)
    if not target.exists():
        return None
    try:
        return load(json.loads(target.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None


def available(directory: Path | None = None) -> list[dict]:
    """Список сохранённых выпусков, новые сверху."""
    target = directory or ARCHIVE_DIR
    target.mkdir(parents=True, exist_ok=True)
    out = []
    for path in sorted(target.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        events = payload.get("events") or []
        out.append({
            "year": int(payload.get("year", 0)),
            "month": int(payload.get("month", 0)),
            "computed_at": payload.get("computed_at"),
            "saved_at": payload.get("saved_at"),
            "total": len(events),
            "published": sum(1 for item in events if item.get("selected")),
            "review": (payload.get("qa") or {}).get("review", 0),
            "path": str(path),
        })
    return out


def remove(year: int, month: int, directory: Path | None = None) -> bool:
    target = path_for(year, month, directory)
    if not target.exists():
        return False
    target.unlink()
    return True
