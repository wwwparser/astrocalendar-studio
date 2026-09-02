"""Постоянное состояние живой ленты.

Без этого файла вся затея не работает. «Новым» объект должен считаться один
раз — в тот момент, когда он впервые появился у источника, а не при каждом
перезапуске программы и не после очистки оперативной памяти. Поэтому на диске
хранятся две вещи:

* **снимок источника** — множество идентификаторов, которые источник отдавал в
  прошлый раз. Разница между текущим списком и снимком и есть открытия.
* **записи ленты** — когда объект впервые увиден, когда обновлялся, прочитан
  ли он, скрыт ли, перенесён ли в выпуск, и хэш данных на прошлый раз.

Отдельное правило для первого запуска: если снимка ещё нет, все несколько
тысяч объектов источника не объявляются открытиями. Снимок просто
записывается, а лента остаётся пустой — иначе первое же обновление TNS
завалило бы редактора историей за годы.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .. import config as cfg
from .model import (LiveRecord, STATUS_NEW, STATUS_UNCHANGED, STATUS_UPDATED)

STATE_FILE = "state.json"
FORMAT_VERSION = 1


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class LiveState:
    """Состояние ленты на диске. Все операции идемпотентны."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory or cfg.LIVE_DIR)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / STATE_FILE
        self.records: dict[str, dict] = {}
        self.load()

    # ------------------------------------------------------------ файл

    def load(self) -> None:
        if not self.path.exists():
            self.records = {}
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.records = dict(payload.get("records") or {})
        except (json.JSONDecodeError, OSError):
            self.records = {}

    def save(self) -> None:
        payload = {"format": FORMAT_VERSION, "saved_at": _now(),
                   "records": self.records}
        try:
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------ записи

    def prepare(self, record: LiveRecord) -> LiveRecord:
        """Подставить записи её прошлое состояние, ничего не меняя на диске.

        Нужна тем, кто должен сравнить новые данные со старыми до того, как
        состояние будет обновлено: наблюдатель за покрытиями так узнаёт
        прежнюю центральную линию полосы.
        """
        stored = self.records.get(record.live_id) or {}
        record.previous = dict(stored.get("retained") or {})
        if stored:
            record.state = dict(stored)
        return record

    def observe(self, record: LiveRecord) -> str:
        """Учесть запись и определить её статус: NEW / UPDATED / UNCHANGED."""
        current = record.payload_hash()
        stored = self.records.get(record.live_id)
        now = _now()
        retained = {key: record.payload.get(key) for key in record.retain}
        record.previous = dict((stored or {}).get("retained") or {})

        if stored is None:
            entry = {
                "kind": record.kind, "semantic": record.semantic,
                "title": record.title,
                "first_seen_at": now, "last_seen_at": now, "last_updated_at": now,
                "read": False, "ignored": False, "added_to_workspace": False,
                "current_payload_hash": current, "previous_payload_hash": None,
                "rank": record.rank, "retained": retained,
            }
            self.records[record.live_id] = entry
            record.status = STATUS_NEW
        else:
            entry = stored
            entry["last_seen_at"] = now
            entry["title"] = record.title
            entry["rank"] = record.rank
            if entry.get("current_payload_hash") != current:
                entry["previous_payload_hash"] = entry.get("current_payload_hash")
                entry["current_payload_hash"] = current
                entry["last_updated_at"] = now
                entry["retained"] = retained
                # изменившиеся данные снова требуют внимания редактора
                entry["read"] = False
                record.status = STATUS_UPDATED
            else:
                record.status = STATUS_UNCHANGED

        record.state = dict(entry)
        return record.status

    def observe_all(self, records: list[LiveRecord]) -> dict[str, int]:
        counts = {STATUS_NEW: 0, STATUS_UPDATED: 0, STATUS_UNCHANGED: 0}
        for record in records:
            counts[self.observe(record)] += 1
        self.save()
        return counts

    def entry(self, live_id: str) -> dict | None:
        return self.records.get(live_id)

    def mark_read(self, live_id: str, read: bool = True) -> None:
        entry = self.records.get(live_id)
        if entry is not None:
            entry["read"] = bool(read)
            self.save()

    def mark_ignored(self, live_id: str, ignored: bool = True) -> None:
        entry = self.records.get(live_id)
        if entry is not None:
            entry["ignored"] = bool(ignored)
            entry["read"] = True
            self.save()

    def mark_added(self, live_id: str, reference: str = "") -> None:
        entry = self.records.get(live_id)
        if entry is not None:
            entry["added_to_workspace"] = True
            entry["workspace_reference"] = reference
            entry["read"] = True
            self.save()

    def apply(self, records: list[LiveRecord]) -> list[LiveRecord]:
        """Проставить записям сохранённое состояние (прочитано, скрыто…)."""
        for record in records:
            entry = self.records.get(record.live_id)
            if entry is not None:
                record.state = dict(entry)
        return records

    def unread_count(self, ranks=("must", "interesting")) -> int:
        """Сколько значимых записей ещё не открывали — для счётчика на вкладке."""
        return sum(1 for entry in self.records.values()
                   if not entry.get("read") and not entry.get("ignored")
                   and entry.get("rank", "optional") in ranks)

    def prune(self, older_than_days: float = 400.0) -> int:
        """Убрать записи, которых источник давно не отдаёт."""
        limit = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=older_than_days)
        stale = []
        for live_id, entry in self.records.items():
            try:
                seen = dt.datetime.fromisoformat(entry["last_seen_at"])
            except (KeyError, ValueError):
                continue
            if seen < limit:
                stale.append(live_id)
        for live_id in stale:
            self.records.pop(live_id, None)
        if stale:
            self.save()
        return len(stale)


# ------------------------------------------------------------------ снимки


class Snapshot:
    """Снимок множества идентификаторов, отданных источником.

    `first_run` отличает «источник впервые опрошен» от «источник действительно
    отдал новые объекты» — без этого различия первое обновление объявляет
    открытием всё, что накопилось за годы.
    """

    def __init__(self, name: str, directory: Path | None = None):
        self.name = name
        self.directory = Path(directory or cfg.LIVE_DIR)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / f"{name}_state.json"
        self.keys: set[str] = set()
        self.updated_at: str | None = None
        self.first_run = True
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self.keys = set(payload.get("keys") or [])
        self.updated_at = payload.get("updated_at")
        self.first_run = False

    def difference(self, current: list[str] | set[str]) -> list[str]:
        """Идентификаторы, которых в прошлый раз не было.

        На первом запуске возвращает пустой список: снимка ещё нет, и объявлять
        открытием весь каталог неправильно.
        """
        if self.first_run:
            return []
        return sorted(set(current) - self.keys)

    def update(self, current: list[str] | set[str]) -> None:
        self.keys = set(current)
        self.updated_at = _now()
        try:
            self.path.write_text(json.dumps(
                {"name": self.name, "updated_at": self.updated_at,
                 "count": len(self.keys), "keys": sorted(self.keys)},
                ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        self.first_run = False

    @property
    def age_hours(self) -> float | None:
        if not self.updated_at:
            return None
        try:
            stamp = dt.datetime.fromisoformat(self.updated_at)
        except ValueError:
            return None
        return (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds() / 3600.0
