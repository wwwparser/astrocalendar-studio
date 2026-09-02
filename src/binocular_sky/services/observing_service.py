"""План наблюдений: чем заняться ночью и в каком порядке.

Оптимизация порядка здесь не задача коммивояжёра. Наблюдателю важно не
минимизировать повороты головы, а не упустить объект: то, что заходит за
крышу в полночь, надо посмотреть до полуночи, а то, что доступно всю ночь,
можно отложить. Поэтому порядок строится по окнам доступности.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class PlanItem:
    """Пункт плана: объект и время, на которое он назначен."""

    target_id: str
    name: str
    scheduled: dt.datetime | None = None
    window_start: dt.datetime | None = None
    window_end: dt.datetime | None = None
    stars: int = 0
    note: str = ""
    done: bool = False

    def to_dict(self) -> dict:
        def stamp(value):
            return value.isoformat() if value else None
        return {"target_id": self.target_id, "name": self.name,
                "scheduled": stamp(self.scheduled),
                "window_start": stamp(self.window_start),
                "window_end": stamp(self.window_end),
                "stars": self.stars, "note": self.note, "done": self.done}

    @classmethod
    def from_dict(cls, payload: dict) -> "PlanItem":
        def parse(value):
            return dt.datetime.fromisoformat(value) if value else None
        return cls(target_id=payload.get("target_id", ""),
                   name=payload.get("name", ""),
                   scheduled=parse(payload.get("scheduled")),
                   window_start=parse(payload.get("window_start")),
                   window_end=parse(payload.get("window_end")),
                   stars=int(payload.get("stars", 0)),
                   note=payload.get("note", ""),
                   done=bool(payload.get("done", False)))


@dataclass
class ObservingPlan:
    """Программа на одну ночь."""

    date: dt.date
    items: list = field(default_factory=list)

    def add(self, item: PlanItem) -> bool:
        if any(existing.target_id == item.target_id for existing in self.items):
            return False
        self.items.append(item)
        return True

    def remove(self, target_id: str) -> None:
        self.items = [i for i in self.items if i.target_id != target_id]

    def contains(self, target_id: str) -> bool:
        return any(i.target_id == target_id for i in self.items)

    def to_dict(self) -> dict:
        return {"date": self.date.isoformat(),
                "items": [i.to_dict() for i in self.items]}

    @classmethod
    def from_dict(cls, payload: dict) -> "ObservingPlan":
        try:
            date = dt.date.fromisoformat(payload.get("date", ""))
        except ValueError:
            date = dt.date.today()
        return cls(date=date,
                   items=[PlanItem.from_dict(i) for i in payload.get("items", [])])


def item_from_recommendation(recommendation) -> PlanItem:
    window = recommendation.visibility.best_window
    return PlanItem(
        target_id=recommendation.target.id,
        name=recommendation.target.name,
        window_start=window.start if window else None,
        window_end=window.end if window else None,
        scheduled=window.best_time if window else None,
        stars=recommendation.stars)


def optimise(plan: ObservingPlan, night_start: dt.datetime,
             night_end: dt.datetime, slot_minutes: int = 20) -> ObservingPlan:
    """Разложить пункты плана по ночи.

    Правило простое и проверяемое: сначала идут объекты с самым ранним концом
    окна — их можно потерять. Каждому выделяется слот; если ближайший свободный
    слот выходит за окно объекта, время сдвигается к началу его окна. Объекты
    без окна остаются без времени и помечаются: обещать наблюдение того, что
    этой ночью недоступно, нельзя.
    """
    scheduled, unscheduled = [], []
    for item in plan.items:
        (scheduled if item.window_start and item.window_end
         else unscheduled).append(item)

    scheduled.sort(key=lambda i: (i.window_end, -i.stars))

    cursor = night_start
    slot = dt.timedelta(minutes=slot_minutes)
    for item in scheduled:
        begin = max(cursor, item.window_start)
        if begin + slot > item.window_end:
            begin = max(item.window_start, item.window_end - slot)
        item.scheduled = begin
        item.note = ""
        cursor = max(cursor, begin + slot)
        if cursor > night_end:
            cursor = night_end

    for item in unscheduled:
        item.scheduled = None
        item.note = "этой ночью не поднимается над участком"

    plan.items = sorted(scheduled, key=lambda i: i.scheduled) + unscheduled
    return plan


def as_text(plan: ObservingPlan) -> list[str]:
    """Строки для панели «моя ночь»."""
    lines = []
    for item in plan.items:
        mark = "✓" if item.done else " "
        when = f"{item.scheduled:%H:%M}" if item.scheduled else "  —  "
        stars = "★" * item.stars
        suffix = f"  ({item.note})" if item.note else ""
        lines.append(f"{mark} {when}  {item.name} {stars}{suffix}")
    return lines
