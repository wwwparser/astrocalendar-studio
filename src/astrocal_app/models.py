"""Модель редакторского выпуска.

Редакторское состояние принципиально отделено от расчёта. `Event` из ядра —
это то, что посчитала астрономия; `EditableEvent` добавляет к нему решения
человека: включено ли событие в пост, переписан ли текст, где оно стоит в
порядке. При пересчёте по свежим данным расчётная часть заменяется, а
редакторская переносится по устойчивому `event_id`.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from astrocal.core import Event
from astrocal.taxonomy import classify, title_of

RANK_TITLES = {"must": "MUST", "interesting": "INT", "optional": "OPT",
               "technical": "TECH"}
CONFIDENCE_TITLES = {"высокая": "HIGH", "средняя": "MED", "низкая": "LOW"}


@dataclass
class EditableEvent:
    """Событие плюс всё, что с ним сделал редактор."""
    event: Event
    selected: bool = True
    editor_text: str | None = None
    order: int = 0
    manual: bool = False
    source_changed: bool = False
    stale_fingerprint: str | None = None
    circumstances: list = field(default_factory=list)
    maps: dict = field(default_factory=dict)

    # ------------------------------------------------------------ идентичность

    @property
    def event_id(self) -> str:
        return self.event.event_id

    @property
    def kind(self) -> str:
        return classify(self.event)

    @property
    def kind_title(self) -> str:
        return title_of(self.kind)

    # ------------------------------------------------------------ тексты

    @property
    def calculated_text(self) -> str:
        """Текст, который посчитала система. Редактор его не меняет."""
        return self.event.text

    @property
    def text(self) -> str:
        """Что пойдёт в публикацию."""
        return self.editor_text if self.editor_text is not None else self.event.text

    @property
    def edited(self) -> bool:
        return self.editor_text is not None and self.editor_text != self.event.text

    def line(self) -> str:
        from astrocal.fmt import date_time_msk
        return f"▪️{date_time_msk(self.event.display_time)} — {self.text}"

    def revert(self) -> None:
        self.editor_text = None

    # ------------------------------------------------------------ отображение

    @property
    def when(self) -> dt.datetime:
        return self.event.display_time

    @property
    def rank(self) -> str:
        return self.event.rank

    @property
    def rank_title(self) -> str:
        return RANK_TITLES.get(self.event.rank, self.event.rank.upper())

    @property
    def confidence_title(self) -> str:
        return CONFIDENCE_TITLES.get(self.event.confidence,
                                     self.event.confidence.upper())

    @property
    def stars(self) -> int:
        visible = [c for c in self.circumstances if c.visible]
        return max((c.stars for c in visible), default=0)

    @property
    def stars_text(self) -> str:
        return "★" * self.stars + "·" * (5 - self.stars) if self.stars else "—"

    @property
    def qa_level(self) -> str:
        levels = {f.level for f in self.event.flags}
        if "REVIEW" in levels:
            return "REVIEW"
        if "WARN" in levels:
            return "WARN"
        return "OK"


@dataclass
class Issue:
    """Выпуск: месяц, события и всё, что нужно редактору."""
    year: int
    month: int
    events: list[EditableEvent] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    qa: dict = field(default_factory=dict)
    enabled_kinds: set[str] = field(default_factory=set)
    enabled_ranks: set[str] = field(default_factory=lambda: {"must", "interesting"})
    primary_city: str = "москва"
    cities: list[str] = field(default_factory=list)
    computed_at: dt.datetime | None = None

    # ------------------------------------------------------------ выборка

    def visible_events(self) -> list[EditableEvent]:
        """События, прошедшие фильтры категорий и рангов."""
        kinds = self.enabled_kinds
        return [e for e in self.ordered()
                if (not kinds or e.kind in kinds or e.manual)
                and (e.rank in self.enabled_ranks or e.manual)]

    def ordered(self) -> list[EditableEvent]:
        return sorted(self.events, key=lambda e: (e.order, e.when, e.text))

    def published(self) -> list[EditableEvent]:
        """Что реально попадёт в пост."""
        return [e for e in self.visible_events() if e.selected]

    def lines(self) -> list[str]:
        return [e.line() for e in self.published()]

    def by_id(self, event_id: str) -> EditableEvent | None:
        for item in self.events:
            if item.event_id == event_id:
                return item
        return None

    # ------------------------------------------------------------ порядок

    def normalise_order(self) -> None:
        for index, item in enumerate(self.ordered()):
            item.order = index

    def sort_chronologically(self) -> None:
        """Вернуть хронологический порядок, отменив ручные перестановки."""
        for index, item in enumerate(sorted(self.events,
                                            key=lambda e: (e.when, e.text))):
            item.order = index

    def move(self, event_id: str, offset: int) -> None:
        items = self.ordered()
        index = next((i for i, e in enumerate(items) if e.event_id == event_id), None)
        if index is None:
            return
        target = max(0, min(len(items) - 1, index + offset))
        if target == index:
            return
        items.insert(target, items.pop(index))
        for position, item in enumerate(items):
            item.order = position

    def reorder(self, event_ids: list[str]) -> None:
        """Расставить порядок по явному списку идентификаторов."""
        position = {event_id: index for index, event_id in enumerate(event_ids)}
        for item in self.events:
            if item.event_id in position:
                item.order = position[item.event_id]
        self.normalise_order()

    # ------------------------------------------------------------ статистика

    @property
    def header(self) -> str:
        from astrocal.build import HEADER
        from astrocal.fmt import MONTHS_NOM_CAP
        return HEADER.format(month=MONTHS_NOM_CAP[self.month], year=self.year)

    def counts(self) -> dict:
        return {
            "total": len(self.events),
            "visible": len(self.visible_events()),
            "published": len(self.published()),
            "edited": sum(1 for e in self.events if e.edited),
            "manual": sum(1 for e in self.events if e.manual),
            "review": sum(1 for e in self.events if e.qa_level == "REVIEW"),
            "warn": sum(1 for e in self.events if e.qa_level == "WARN"),
            "stale": sum(1 for e in self.events if e.source_changed),
        }
