"""Живая лента для интерфейса.

Тонкий слой между `astrocal.live` и виджетами: хранит состояние ленты между
обновлениями, отдаёт отфильтрованный список карточек, помечает прочитанное и
переносит запись в текущий выпуск.

Важное свойство: обновление здесь ровно одно — по кнопке. Переход по карточкам
не вызывает ни одного сетевого запроса, потому что интерфейс работает с уже
полученным результатом. Иначе внешние API отвечали бы отказом по частоте.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from astrocal import config as cfg, qa_live
from astrocal.cities import by_key
from astrocal.live import discovery_service, post
from astrocal.live.model import LiveRecord, sort_key
from astrocal.live.state import LiveState


@dataclass
class Filters:
    """Что показывать в основной ленте."""
    hours: float | None = None          # None — без ограничения по времени
    show_all: bool = False              # игнорировать фильтры значимости
    kinds: set = field(default_factory=set)     # пусто — все виды
    novae: bool = True
    supernovae: bool = True
    confirmed_only: bool = True
    magnitude_limit: float = cfg.TRANSIENT_MAG_LIMIT
    only_visible: bool = True
    only_at_night: bool = True
    occultations_russia_only: bool = True
    occultation_star_mag_limit: float = cfg.OCC_STAR_MAG_LIMIT
    show_uncertain: bool = True


class Feed:
    """Состояние живой ленты в приложении."""

    def __init__(self, state: LiveState | None = None):
        self.state = state or LiveState()
        self.records: list[LiveRecord] = []
        self.result: discovery_service.RefreshResult | None = None
        self.filters = Filters()
        self.qa: dict = {}

    # ------------------------------------------------------------ обновление

    def refresh(self, kinds=discovery_service.KINDS, days: float = 30.0,
                city_key: str | None = None, use_cache: bool = True,
                progress=None) -> discovery_service.RefreshResult:
        cities = None
        if city_key:
            city = by_key(city_key)
            if city is not None:
                cities = [city]
        result = discovery_service.refresh(
            kinds, state=self.state, cities=cities, days=days,
            use_cache=use_cache, progress=progress)
        self.result = result
        self.records = result.records
        self.qa = qa_live.run(self.records)
        return result

    # ------------------------------------------------------------ выборка

    def visible(self) -> list[LiveRecord]:
        """Карточки после фильтров. Фильтр — это вид, а не удаление данных."""
        from astrocal.live import transients
        from astrocal.live.model import (KIND_OCCULTATION, KIND_TRANSIENT,
                                         SEMANTIC_SCHEDULED)

        filters = self.filters
        out = []
        for record in self.records:
            if filters.kinds and record.kind not in filters.kinds:
                continue
            if not filters.show_all:
                if record.ignored:
                    continue
                if record.kind == KIND_TRANSIENT and not transients.passes(
                        record, novae=filters.novae,
                        supernovae=filters.supernovae,
                        confirmed_only=filters.confirmed_only,
                        magnitude_limit=filters.magnitude_limit,
                        only_visible=filters.only_visible,
                        only_at_night=filters.only_at_night):
                    continue
                # Фильтры полосы применимы к самому покрытию, но не к
                # сообщению о том, что полоса сдвинулась: у уточнения своих
                # регионов и своей звезды нет
                if (record.kind == KIND_OCCULTATION
                        and record.semantic == SEMANTIC_SCHEDULED):
                    payload = record.payload or {}
                    star_mag = payload.get("star_mag")
                    if (star_mag is not None
                            and star_mag > filters.occultation_star_mag_limit):
                        continue
                    if filters.occultations_russia_only and not payload.get("regions"):
                        continue
                    if (not filters.show_uncertain
                            and qa_live.qa_level(record) == "REVIEW"):
                        continue
            if filters.hours is not None and record.moment is not None:
                delta = abs((record.moment
                             - dt.datetime.now(cfg.MSK)).total_seconds()) / 3600.0
                if delta > filters.hours:
                    continue
            out.append(record)
        return sorted(out, key=sort_key)

    def by_id(self, live_id: str) -> LiveRecord | None:
        return next((r for r in self.records if r.live_id == live_id), None)

    # ------------------------------------------------------------ состояние

    def mark_read(self, record: LiveRecord) -> None:
        self.state.mark_read(record.live_id)
        record.state = dict(self.state.entry(record.live_id) or record.state)

    def ignore(self, record: LiveRecord, ignored: bool = True) -> None:
        self.state.mark_ignored(record.live_id, ignored)
        record.state = dict(self.state.entry(record.live_id) or record.state)

    def badge(self) -> int:
        return self.state.unread_count()

    # ------------------------------------------------------------ выпуск и пост

    def post_text(self, record: LiveRecord) -> str:
        return post.build(record)

    def add_to_issue(self, issue, record: LiveRecord):
        """Перенести запись ленты в текущий выпуск."""
        from .service import add_live_event

        item = add_live_event(issue, record)
        self.state.mark_added(record.live_id, f"{issue.year:04d}-{issue.month:02d}")
        record.state = dict(self.state.entry(record.live_id) or record.state)
        return item

    def source_changes(self, issue) -> list[tuple]:
        """События выпуска, у которых данные источника изменились после переноса.

        Редакторская формулировка при этом не трогается: мы только сообщаем,
        что расчётная часть разошлась с той, по которой писался текст.
        """
        changed = []
        for item in issue.events:
            provenance = item.event.provenance or {}
            if provenance.get("origin") != "live":
                continue
            record = self.by_id(provenance.get("source_event_id", ""))
            if record is None:
                continue
            if record.payload_hash() != provenance.get("payload_hash"):
                changed.append((item, record))
        return changed

    def apply_source_update(self, item, record: LiveRecord) -> None:
        """Обновить расчётные данные события, сохранив редакторский текст."""
        fresh = record.to_event()
        editor_text = item.editor_text
        item.event.when = fresh.when
        item.event.text = fresh.text
        item.event.computed = fresh.computed
        item.event.sources = fresh.sources
        item.event.provenance = fresh.provenance
        item.event.meta = fresh.meta
        item.editor_text = editor_text          # редакцию не трогаем никогда
        item.source_changed = False

    # ------------------------------------------------------------ отчёт

    def status_lines(self) -> list[str]:
        """Состояние источников для панели данных."""
        if self.result is None:
            return ["Лента ещё не обновлялась"]
        lines = []
        for key, summary in self.result.sources.items():
            title = summary.get("title", key)
            status = summary.get("status", "ок")
            note = summary.get("error") or summary.get("note") or ""
            lines.append(f"{title}: {status}" + (f" — {note}" if note else ""))
        return lines
