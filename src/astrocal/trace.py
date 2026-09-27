"""Трассировка расчёта: что происходило и откуда взялись данные.

У каждого события в календаре есть поле «как посчитано» и список источников.
Этого хватает, чтобы проверить готовую строку, но не хватает, чтобы понять
работу целиком: сколько кандидатов рассмотрел модуль, сколько отбросил и
почему, к каким адресам ходил, что взял из кэша, а что скачал заново, сколько
это заняло.

Трассировка отвечает на эти вопросы. Она записывает ход расчёта по шагам:

* **шаг** — один модуль или одна осмысленная фаза внутри него;
* **счётчики** — рассмотрено, отобрано, отброшено;
* **причины отсева** — не общим числом, а с примерами: «полоса не задевает
  Россию», «падение блеска меньше порога»;
* **обращения к сети** — адрес, размер, из кэша или заново, сколько заняло;
* **заметки** — то, что модуль хочет сказать человеку своими словами.

Устройство подчинено одному требованию: модуль не должен ничего знать о
трассировке. Поэтому текущая трассировка живёт в контекстной переменной, а
функции `note`, `count`, `reject` работают вхолостую, если трассировки нет.
Расчёт из командной строки и тесты от этого не меняются ни на строку.
"""
from __future__ import annotations

import datetime as dt
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from . import config as cfg

CURRENT: ContextVar["Trace | None"] = ContextVar("astrocal_trace", default=None)

MAX_REJECTS = 12          # примеров отсева на шаг: больше человек не читает
MAX_NOTES = 40


@dataclass
class Fetch:
    """Одно обращение к внешнему источнику."""
    url: str
    from_cache: bool = False
    size_bytes: int = 0
    seconds: float = 0.0
    status: int = 200
    at: str = ""

    @property
    def size_text(self) -> str:
        if self.size_bytes >= 1024 * 1024:
            return f"{self.size_bytes / 1048576:.1f} МБ"
        if self.size_bytes >= 1024:
            return f"{self.size_bytes / 1024:.0f} КБ"
        return f"{self.size_bytes} Б"

    @property
    def host(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self.url).netloc

    def as_dict(self) -> dict:
        return {"url": self.url, "from_cache": self.from_cache,
                "size_bytes": self.size_bytes, "seconds": round(self.seconds, 3),
                "status": self.status, "at": self.at}


@dataclass
class Stage:
    """Один шаг расчёта."""
    key: str
    title: str
    description: str = ""
    started_at: str = ""
    seconds: float = 0.0
    counts: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    rejects: list = field(default_factory=list)
    rejected_total: int = 0
    fetches: list = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def produced(self) -> int:
        return int(self.counts.get("отобрано", 0))

    @property
    def network_seconds(self) -> float:
        return sum(item.seconds for item in self.fetches)

    @property
    def fresh_fetches(self) -> int:
        return sum(1 for item in self.fetches if not item.from_cache)

    def as_dict(self) -> dict:
        return {"key": self.key, "title": self.title,
                "description": self.description,
                "started_at": self.started_at, "seconds": round(self.seconds, 2),
                "counts": dict(self.counts), "notes": list(self.notes),
                "rejects": list(self.rejects),
                "rejected_total": self.rejected_total,
                "fetches": [item.as_dict() for item in self.fetches],
                "error": self.error}

    @classmethod
    def from_dict(cls, payload: dict) -> "Stage":
        stage = cls(key=payload.get("key", ""), title=payload.get("title", ""),
                    description=payload.get("description", ""),
                    started_at=payload.get("started_at", ""),
                    seconds=float(payload.get("seconds", 0.0)),
                    counts=dict(payload.get("counts") or {}),
                    notes=list(payload.get("notes") or []),
                    rejects=list(payload.get("rejects") or []),
                    rejected_total=int(payload.get("rejected_total", 0)),
                    error=payload.get("error", ""))
        stage.fetches = [Fetch(**item) for item in payload.get("fetches") or []]
        return stage


@dataclass
class Trace:
    """Ход расчёта целиком."""
    stages: list = field(default_factory=list)
    started_at: str = ""
    seconds: float = 0.0
    _open: list = field(default_factory=list, repr=False)

    # ------------------------------------------------------------ запись

    @contextmanager
    def stage(self, key: str, title: str, description: str = ""):
        entry = Stage(key=key, title=title, description=description,
                      started_at=dt.datetime.now(cfg.MSK).isoformat())
        self.stages.append(entry)
        self._open.append(entry)
        clock = time.perf_counter()
        try:
            yield entry
        except Exception as error:               # noqa: BLE001
            entry.error = f"{type(error).__name__}: {error}"
            raise
        finally:
            entry.seconds = time.perf_counter() - clock
            self._open.pop()

    @property
    def active(self) -> Stage | None:
        return self._open[-1] if self._open else None

    # ------------------------------------------------------------ чтение

    @property
    def total_seconds(self) -> float:
        return self.seconds or sum(stage.seconds for stage in self.stages)

    @property
    def network_seconds(self) -> float:
        return sum(stage.network_seconds for stage in self.stages)

    @property
    def fetch_count(self) -> int:
        return sum(len(stage.fetches) for stage in self.stages)

    @property
    def fresh_fetch_count(self) -> int:
        return sum(stage.fresh_fetches for stage in self.stages)

    @property
    def failed(self) -> list:
        return [stage for stage in self.stages if stage.error]

    def as_dict(self) -> dict:
        return {"started_at": self.started_at,
                "seconds": round(self.total_seconds, 2),
                "stages": [stage.as_dict() for stage in self.stages]}

    @classmethod
    def from_dict(cls, payload: dict) -> "Trace":
        trace = cls(started_at=payload.get("started_at", ""),
                    seconds=float(payload.get("seconds", 0.0)))
        trace.stages = [Stage.from_dict(item)
                        for item in payload.get("stages") or []]
        return trace


# ------------------------------------------------------------------ доступ


@contextmanager
def recording():
    """Включить трассировку на время блока."""
    trace = Trace(started_at=dt.datetime.now(cfg.MSK).isoformat())
    token = CURRENT.set(trace)
    clock = time.perf_counter()
    try:
        yield trace
    finally:
        trace.seconds = time.perf_counter() - clock
        CURRENT.reset(token)


def current() -> Trace | None:
    return CURRENT.get()


@contextmanager
def stage(key: str, title: str, description: str = ""):
    """Шаг расчёта. Без включённой трассировки — обычный блок кода."""
    trace = CURRENT.get()
    if trace is None:
        yield None
        return
    with trace.stage(key, title, description) as entry:
        yield entry


def note(text: str) -> None:
    """Заметка человеческим языком к текущему шагу."""
    trace = CURRENT.get()
    if trace is None or trace.active is None:
        return
    notes = trace.active.notes
    if len(notes) < MAX_NOTES:
        notes.append(str(text))


def count(**values) -> None:
    """Счётчики текущего шага: рассмотрено, отобрано и что угодно ещё."""
    trace = CURRENT.get()
    if trace is None or trace.active is None:
        return
    for key, value in values.items():
        trace.active.counts[key.replace("_", " ")] = value


def reject(what: str, why: str) -> None:
    """Отброшенный кандидат и причина. Хранятся первые несколько примеров."""
    trace = CURRENT.get()
    if trace is None or trace.active is None:
        return
    active = trace.active
    active.rejected_total += 1
    if len(active.rejects) < MAX_REJECTS:
        active.rejects.append({"what": str(what), "why": str(why)})


def fetched(url: str, from_cache: bool = False, size_bytes: int = 0,
            seconds: float = 0.0, status: int = 200) -> None:
    """Обращение к внешнему источнику. Вызывается сетевым слоем."""
    trace = CURRENT.get()
    if trace is None or trace.active is None:
        return
    trace.active.fetches.append(Fetch(
        url=url, from_cache=from_cache, size_bytes=size_bytes,
        seconds=seconds, status=status,
        at=dt.datetime.now(cfg.MSK).strftime("%H:%M:%S")))
