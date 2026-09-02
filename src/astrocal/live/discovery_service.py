"""Один цикл обновления живой ленты.

Схема одна для всех источников:

    источник → текущий набор объектов → сравнение со снимком → кандидат →
    обогащение → наблюдаемость → рейтинг → запись ленты

Здесь эта цепочка собрана вместе и снабжена двумя обязательными свойствами.

**Отказ одного источника не ломает остальные.** TNS может быть недоступен, у
пользователя может не быть ключей, MPC может отдать 503 — на кометах и NEO это
не должно сказываться никак. Поэтому каждый наблюдатель вызывается отдельно, а
его ошибка попадает в сводку, а не наверх.

**Одно обновление — один цикл запросов.** Переход по карточкам в интерфейсе
ничего не запрашивает: данные берутся из результата последнего обновления,
а сетевой слой кэширует ответы. Иначе внешние API отвечали бы 429.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .. import config as cfg
from .model import (LiveRecord, STATUS_NEW, STATUS_UNCHANGED, STATUS_UPDATED,
                    sort_key)
from .state import LiveState

KINDS = ("occultations", "neo", "comets", "transients")
TITLES = {"occultations": "Покрытия звёзд астероидами",
          "neo": "Сближения астероидов с Землёй",
          "comets": "Новые кометы (MPC)",
          "transients": "Новые и сверхновые (TNS)"}


@dataclass
class RefreshResult:
    """Итог одного обновления."""
    records: list[LiveRecord] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None

    @property
    def new(self) -> int:
        return self.counts.get(STATUS_NEW, 0)

    @property
    def updated(self) -> int:
        return self.counts.get(STATUS_UPDATED, 0)

    @property
    def unchanged(self) -> int:
        return self.counts.get(STATUS_UNCHANGED, 0)

    @property
    def errors(self) -> int:
        return sum(1 for summary in self.sources.values()
                   if summary.get("status") in ("недоступен", "нет ключей"))

    def summary_text(self) -> str:
        return (f"New: {self.new}\nUpdated: {self.updated}\n"
                f"Unchanged: {self.unchanged}\nErrors: {self.errors}")

    def as_dict(self) -> dict:
        return {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "new": self.new, "updated": self.updated,
            "unchanged": self.unchanged, "errors": self.errors,
            "sources": self.sources,
            "records": [
                {"live_id": item.live_id, "kind": item.kind,
                 "semantic": item.semantic, "status": item.status,
                 "rank": item.rank, "stars": item.stars, "title": item.title,
                 "summary": item.summary,
                 "when": item.when.isoformat() if item.when else None,
                 "discovered_at": (item.discovered_at.isoformat()
                                   if item.discovered_at else None),
                 "magnitude": item.magnitude,
                 "payload": item.payload, "provenance": item.provenance}
                for item in self.records],
        }


def refresh(kinds=KINDS, *, state: LiveState | None = None, cities=None,
            days: float = 30.0, use_cache: bool = True,
            with_observability: bool = True, progress=None) -> RefreshResult:
    """Обновить выбранные источники и учесть результат в состоянии ленты."""
    from . import neo_watch, new_comets, occultation_watch, transients

    live_state = state or LiveState()
    result = RefreshResult(started_at=dt.datetime.now(cfg.MSK))
    selected = [kind for kind in KINDS if kind in kinds]

    def step(index: int, name: str) -> None:
        if progress:
            progress(TITLES.get(name, name),
                     int(100 * index / max(1, len(selected))))

    for index, kind in enumerate(selected):
        step(index, kind)
        try:
            if kind == "neo":
                records, summary = neo_watch.check(
                    days=days, cities=cities, use_cache=use_cache,
                    with_observability=with_observability)
            elif kind == "occultations":
                records, summary = occultation_watch.check(
                    days=days, cities=cities, state=live_state)
            elif kind == "comets":
                records, summary = new_comets.check(
                    cities=cities, use_cache=use_cache)
            else:
                records, summary = transients.check(
                    cities=cities, use_cache=use_cache)
        except Exception as error:               # noqa: BLE001
            # Источник упал — записываем и идём дальше: остальные должны работать
            result.sources[kind] = {"status": "недоступен", "error": str(error),
                                    "title": TITLES.get(kind, kind)}
            continue
        summary.setdefault("status", "ок")
        summary["title"] = TITLES.get(kind, kind)
        result.sources[kind] = summary
        result.records += records

    counts = live_state.observe_all(result.records)
    result.counts = counts
    result.records.sort(key=sort_key)
    result.finished_at = dt.datetime.now(cfg.MSK)
    if progress:
        progress("Готово", 100)
    return result


def visible(records: list[LiveRecord], *, show_all: bool = False,
            hours: float | None = None,
            ranks=("must", "interesting")) -> list[LiveRecord]:
    """Что показывать в основной ленте.

    Скрытые записи и слабые события не выбрасываются: `show_all` возвращает
    полный список. Фильтр — это вид, а не удаление данных.
    """
    now = dt.datetime.now(cfg.MSK)
    out = []
    for record in records:
        if not show_all:
            if record.ignored:
                continue
            if record.rank not in ranks:
                continue
        if hours is not None and record.moment is not None:
            delta = abs((record.moment - now).total_seconds()) / 3600.0
            if delta > hours:
                continue
        out.append(record)
    return out


def unread_badge(state: LiveState | None = None) -> int:
    return (state or LiveState()).unread_count()
