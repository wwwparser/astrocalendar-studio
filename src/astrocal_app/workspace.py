"""Сохранение редакторского состояния выпуска.

Смысл файла один: работа редактора не должна пропадать. Снятые галочки,
переписанные формулировки, ручной порядок, добавленные вручную события —
всё это переживает и закрытие программы, и пересчёт по свежим данным.

Расчётные значения в файле не хранятся: при открытии они считаются заново, а
редакторские решения переносятся по `event_id`. Если у события изменился
отпечаток расчёта, оно помечается — редактор увидит, что правил текст,
описывавший другие числа.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from astrocal import config as cfg

from .models import Issue
from .service import add_manual_event

FORMAT_VERSION = 2
WORKSPACE_DIR = cfg.ROOT / "workspace"


def path_for(year: int, month: int, directory: Path | None = None) -> Path:
    target = directory or WORKSPACE_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target / f"{year:04d}-{month:02d}.astudio.json"


def dump(issue: Issue) -> dict:
    return {
        "format": FORMAT_VERSION,
        "year": issue.year,
        "month": issue.month,
        "saved_at": dt.datetime.now(cfg.MSK).isoformat(),
        "enabled_kinds": sorted(issue.enabled_kinds),
        "enabled_ranks": sorted(issue.enabled_ranks),
        "primary_city": issue.primary_city,
        "cities": issue.cities,
        "events": [
            {
                "id": item.event_id,
                "selected": item.selected,
                "order": item.order,
                "editor_text": item.editor_text,
                "manual": item.manual,
                "fingerprint": item.event.fingerprint(),
                # ручное событие целиком хранится в файле: пересчёт его не вернёт
                "manual_payload": ({
                    "when": item.event.when.isoformat(),
                    "text": item.event.text,
                    "rank": item.event.rank,
                } if item.manual else None),
            }
            for item in issue.ordered()
        ],
    }


def save(issue: Issue, directory: Path | None = None) -> Path:
    target = path_for(issue.year, issue.month, directory)
    target.write_text(json.dumps(dump(issue), ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return target


def load_raw(year: int, month: int, directory: Path | None = None) -> dict | None:
    target = path_for(year, month, directory)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def apply_to(issue: Issue, payload: dict) -> dict:
    """Наложить сохранённое состояние на свежерассчитанный выпуск.

    Возвращает сводку: сколько решений восстановлено, сколько событий исчезло
    из расчёта и у скольких изменились исходные данные.
    """
    if not payload:
        return {"restored": 0, "missing": 0, "changed": 0, "manual": 0}

    if payload.get("enabled_kinds"):
        issue.enabled_kinds = set(payload["enabled_kinds"])
    if payload.get("enabled_ranks"):
        issue.enabled_ranks = set(payload["enabled_ranks"])
    issue.primary_city = payload.get("primary_city", issue.primary_city)
    if payload.get("cities"):
        issue.cities = payload["cities"]

    restored = missing = changed = manual = 0
    for record in payload.get("events", []):
        item = issue.by_id(record["id"])

        if item is None and record.get("manual_payload"):
            data = record["manual_payload"]
            item = add_manual_event(
                issue, dt.datetime.fromisoformat(data["when"]),
                data["text"], data.get("rank", "interesting"))
            manual += 1

        if item is None:
            missing += 1
            continue

        item.selected = bool(record.get("selected", True))
        item.order = int(record.get("order", item.order))
        item.editor_text = record.get("editor_text")
        saved_fingerprint = record.get("fingerprint")
        if saved_fingerprint and saved_fingerprint != item.event.fingerprint():
            item.source_changed = True
            item.stale_fingerprint = saved_fingerprint
            changed += 1
        restored += 1

    issue.normalise_order()
    return {"restored": restored, "missing": missing, "changed": changed,
            "manual": manual}


def load_into(issue: Issue, directory: Path | None = None) -> dict:
    payload = load_raw(issue.year, issue.month, directory)
    return apply_to(issue, payload or {})


def describe_changes(issue: Issue) -> list[str]:
    """Тексты предупреждений о событиях, чьи исходные данные изменились."""
    messages = []
    for item in issue.events:
        if not item.source_changed:
            continue
        note = (f"{item.when:%d.%m %H:%M} — {item.calculated_text}")
        if item.edited:
            note += ("\n    Исходные данные этого события изменились после вашей "
                     "редакторской правки.")
        else:
            note += "\n    Исходные данные события изменились после сохранения."
        messages.append(note)
    return messages
