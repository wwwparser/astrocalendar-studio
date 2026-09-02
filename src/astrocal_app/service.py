"""Сервисный слой: единственная дверь из интерфейса в расчётное ядро.

GUI не знает ни про Skyfield, ни про Horizons — он вызывает методы отсюда и
получает готовую модель выпуска. Благодаря этому та же логика доступна из CLI
и из тестов, а астрономия не дублируется в виджетах.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

from astrocal import config as cfg, qa, rating, telegram
from astrocal.build import collect, render_post, render_protocol, render_qa_report
from astrocal.cities import all_cities, by_key
from astrocal.core import Event
from astrocal.taxonomy import KINDS, classify

from .models import EditableEvent, Issue

Progress = Callable[[str, int], None]

SOURCES = {
    "ephemeris": "JPL DE440s (планеты и Луна), jup380s (галилеевы спутники), "
                 "JPL Horizons (Титан, астероиды, сверка)",
    "catalogs": "Hipparcos, OpenNGC, MPC CometEls, IOTA, CNEOS, Celestrak, "
                "Launch Library 2",
}


def _noop(stage: str, percent: int) -> None:
    return None


def compute_issue(year: int, month: int, *, use_horizons: bool = True,
                  with_circumstances: bool = True,
                  progress: Progress | None = None) -> Issue:
    """Полный расчёт выпуска месяца.

    Долгая операция: в интерфейсе вызывается из рабочего потока.
    """
    report = progress or _noop
    start, end = cfg.month_bounds(year, month)

    report("Расчёт событий", 5)
    events, extra = collect(start, end)

    report("Ранжирование", 60)
    rating.apply(events)
    qa.stamp_provenance(events, SOURCES)

    report("Проверки" + (" и сверка с Horizons" if use_horizons else ""), 70)
    qa_result = qa.run(events, start, end, use_horizons=use_horizons)

    report("Сборка выпуска", 92)
    issue = Issue(year=year, month=month, extra=extra, qa=qa_result,
                  enabled_kinds={kind.key for kind in KINDS},
                  computed_at=dt.datetime.now(cfg.MSK),
                  cities=[city.key for city in all_cities()])
    issue.events = [EditableEvent(event=event, order=index,
                                  selected=event.rank in issue.enabled_ranks)
                    for index, event in enumerate(sorted(events,
                                                         key=lambda e: e.display_time))]

    if with_circumstances:
        report("Обстоятельства наблюдения", 96)
        attach_circumstances(issue)

    report("Готово", 100)
    return issue


def attach_circumstances(issue: Issue, city_keys: list[str] | None = None) -> None:
    """Досчитать обстоятельства наблюдения по городам."""
    from astrocal.observing import for_event

    cities = [by_key(key) for key in (city_keys or issue.cities)]
    cities = [city for city in cities if city is not None]
    for item in issue.events:
        try:
            item.circumstances = for_event(item.event, cities)
        except Exception:
            item.circumstances = []


# ------------------------------------------------------------------ публикация


def publication(issue: Issue) -> telegram.Publication:
    return telegram.build(issue.header, issue.lines())


def publication_markdown(issue: Issue) -> str:
    return telegram.as_markdown(issue.header, issue.lines())


def publication_json(issue: Issue) -> dict:
    """Машинная выдача выпуска — для архива и внешних инструментов."""
    return {
        "year": issue.year,
        "month": issue.month,
        "computed_at": issue.computed_at.isoformat() if issue.computed_at else None,
        "header": issue.header,
        "events": [
            {
                "id": item.event_id,
                "when": item.event.when.isoformat(),
                "display_time": item.when.isoformat(),
                "kind": item.kind,
                "category": item.event.category,
                "rank": item.event.rank,
                "confidence": item.event.confidence,
                "selected": item.selected,
                "manual": item.manual,
                "calculated_text": item.calculated_text,
                "text": item.text,
                "line": item.line(),
                "computed": item.event.computed,
                "sources": item.event.sources,
                "notes": item.event.notes,
                "provenance": item.event.provenance,
                "qa": [{"level": f.level, "check": f.check, "message": f.message}
                       for f in item.event.flags],
            }
            for item in issue.ordered()
        ],
    }


# ------------------------------------------------------------------ отчёты


def protocol_text(issue: Issue) -> str:
    events = [item.event for item in issue.ordered()]
    checks = [{"when": f"{e.when:%d.%m %H:%M}", "pair": name,
               "skyfield_deg": 0.0, "horizons_deg": 0.0, "diff_arcsec": delta}
              for e in events
              for name, delta in (e.provenance.get("horizons") or {}).items()]
    return render_protocol(events, issue.extra, issue.year, issue.month, checks)


def qa_report_text(issue: Issue) -> str:
    events = [item.event for item in issue.ordered()]
    published = [item.event for item in issue.published()]
    return render_qa_report(events, published, issue.extra, issue.qa,
                            issue.year, issue.month)


def calendar_text(issue: Issue) -> str:
    return render_post([item.event for item in issue.published()],
                       issue.year, issue.month)


def write_outputs(issue: Issue, directory=None) -> dict:
    """Сохранить пост, протокол и QA-отчёт так же, как это делает CLI."""
    target = directory or cfg.OUT
    target.mkdir(parents=True, exist_ok=True)
    stem = f"{issue.year:04d}-{issue.month:02d}"
    files = {
        "calendar": target / f"calendar_{stem}.txt",
        "protocol": target / f"protocol_{stem}.md",
        "qa": target / f"QA_REPORT_{stem}.md",
    }
    files["calendar"].write_text(publication(issue).plain_text, encoding="utf-8")
    files["protocol"].write_text(protocol_text(issue), encoding="utf-8")
    files["qa"].write_text(qa_report_text(issue), encoding="utf-8")
    return files


# ------------------------------------------------------------------ ручные события


def add_manual_event(issue: Issue, when: dt.datetime, text: str,
                     rank: str = "interesting") -> EditableEvent:
    """Добавить событие, которого нет в расчёте.

    Помечается как ручное явно: календарь не должен выдавать редакторскую
    заметку за результат вычисления.
    """
    event = Event(
        when=when, text=text, category="manual", rank=rank,
        confidence="ручной ввод",
        computed="введено редактором вручную, расчётом не подтверждается",
        sources=["ручной ввод"],
        meta={"manual": True},
        provenance={"origin": "manual",
                    "added_at": dt.datetime.now(cfg.MSK).isoformat()},
    )
    item = EditableEvent(event=event, manual=True, selected=True,
                         order=len(issue.events))
    issue.events.append(item)
    issue.normalise_order()
    return item


def kind_counts(issue: Issue) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in issue.events:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return counts


def classify_event(event: Event) -> str:
    return classify(event)
