"""Автоматический сбор пусков из Launch Library 2 (thespacedevs).

LL2 — единственный публичный источник, который отдаёт запуски структурированно
и, что важнее, со статусом: `Go`, `TBD`, `TBC`, `Hold`, `Success`. Именно
статуса не хватает в календарях, где «запуск 9 сентября» и «запуск когда-нибудь
в сентябре» выглядят одинаково.

Стыковки, расстыковки и затопления грузовых кораблей LL2 не публикует —
их по-прежнему заполняет человек в `data/spaceflight_YYYY-MM.json`.

Бесплатный тариф ограничен по частоте запросов, поэтому ответы кэшируются.
"""
from __future__ import annotations

import datetime as dt
import json

import requests

from . import config as cfg

API = "https://ll.thespacedevs.com/2.2.0/launch/"

# Статусы LL2: в календарь без ручного подтверждения годятся только Go/Success
STATUS_RU = {
    "Go": ("подтверждён", "высокая"),
    "Success": ("состоялся", "высокая"),
    "TBC": ("дата уточняется", "средняя"),
    "TBD": ("дата не определена", "низкая"),
    "Hold": ("отложен", "низкая"),
    "In Flight": ("в полёте", "высокая"),
    "Failure": ("аварийный", "высокая"),
    "Partial Failure": ("частично аварийный", "высокая"),
}

# Что считаем значимым для астрономического календаря
INTERESTING = (
    "прогресс", "progress", "союз", "soyuz", "crew dragon", "cygnus", "tianzhou",
    "shenzhou", "cargo dragon", "starliner", "iss", "мкс", "artemis", "axiom",
)


def _cache_path(start: dt.date, end: dt.date):
    return cfg.CACHE / f"ll2_{start:%Y%m%d}_{end:%Y%m%d}.json"


def fetch(start: dt.datetime, end: dt.datetime, timeout: int = 60,
          use_cache: bool = True) -> list[dict]:
    """Пуски в окне [start, end) — сырые записи LL2."""
    path = _cache_path(start.date(), end.date())
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    results, offset = [], 0
    while True:
        params = {
            "net__gte": start.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "net__lt": end.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 100, "offset": offset, "mode": "list", "format": "json",
        }
        r = requests.get(API, params=params, timeout=timeout)
        r.raise_for_status()
        payload = r.json()
        results.extend(payload.get("results", []))
        if not payload.get("next"):
            break
        offset += 100
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


def _flat(record: dict, list_key: str, object_key: str) -> str:
    value = record.get(list_key)
    if isinstance(value, str):
        return value
    value = record.get(object_key)
    if isinstance(value, dict):
        return value.get("name", "")
    return "" if value is None else str(value)


def is_interesting(record: dict) -> bool:
    haystack = " ".join(str(record.get(k, "")) for k in
                        ("name", "mission", "pad", "location", "lsp_name")).lower()
    return any(word in haystack for word in INTERESTING)


def to_draft(record: dict) -> dict:
    """Запись LL2 → черновик строки для spaceflight_YYYY-MM.json."""
    net = dt.datetime.fromisoformat(record["net"].replace("Z", "+00:00"))
    status = (record.get("status") or {}).get("abbrev", "TBD")
    status_ru, confidence = STATUS_RU.get(status, ("статус неизвестен", "низкая"))
    # mode=list отдаёт эти поля плоскими строками, полный режим — объектами
    provider = _flat(record, "lsp_name", "launch_service_provider")
    pad = _flat(record, "pad", "pad")
    location = _flat(record, "location", "location")
    return {
        "when_msk": net.astimezone(cfg.MSK).strftime("%Y-%m-%d %H:%M"),
        "text": (f"Запуск {record['name']}"
                 + (f" с космодрома {location.split(',')[0]}" if location else "")),
        "include": status in ("Go", "Success", "In Flight"),
        "confidence": confidence,
        "sources": [f"Launch Library 2 (thespacedevs), id {record['id']}, "
                    f"статус «{status}» — {status_ru}, оператор {provider}, "
                    f"площадка {pad}"],
        "notes": ("Черновик получен автоматически. Русское название и формулировку "
                  "проверить и поправить руками."),
        "_ll2_status": status,
    }


def drafts(start: dt.datetime, end: dt.datetime, only_interesting: bool = True):
    records = fetch(start, end)
    if only_interesting:
        records = [r for r in records if is_interesting(r)]
    return [to_draft(r) for r in records]
