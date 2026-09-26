"""Долгие операции вне запроса.

Расчёт месяца занимает десять–пятнадцать минут. В обработчике HTTP такое
делать нельзя: браузер отвалится по таймауту, прокси разорвёт соединение, а
повторное нажатие кнопки запустит вторую копию расчёта.

Поэтому кнопка только ставит задачу в очередь и сразу отвечает. Страница
опрашивает состояние и показывает, какой модуль считается сейчас.

Одновременно выполняется ровно одна задача. Причина не в бережливости:
расчётное ядро держит эфемериды и каталоги в кэшах уровня модуля, и два
параллельных расчёта будут мешать друг другу и займут вдвое больше памяти на
те же данные.

Состояние задач живёт в памяти процесса. При перезапуске сервиса незаконченный
расчёт теряется — это честнее, чем показывать прогресс задачи, которой больше
нет. Результат же сохраняется на диск, и его перезапуск не теряет.
"""
from __future__ import annotations

import datetime as dt
import threading
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from astrocal import config as cfg

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


@dataclass
class Job:
    """Одна фоновая задача."""
    id: str
    kind: str
    title: str
    status: str = PENDING
    stage: str = "в очереди"
    percent: int = 0
    created_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(cfg.MSK))
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    result: object = None
    error: str = ""
    details: str = ""
    payload: dict = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.status in (PENDING, RUNNING)

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or dt.datetime.now(cfg.MSK)
        return (end - self.started_at).total_seconds()

    @property
    def elapsed_text(self) -> str:
        seconds = self.elapsed_seconds
        if seconds < 60:
            return f"{seconds:.0f} с"
        return f"{seconds / 60:.0f} мин"

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title,
                "status": self.status, "stage": self.stage,
                "percent": self.percent, "error": self.error,
                "elapsed": self.elapsed_text,
                "payload": self.payload}


class JobManager:
    """Очередь на одного исполнителя."""

    def __init__(self, keep: int = 30):
        self._pool = ThreadPoolExecutor(max_workers=1,
                                        thread_name_prefix="astrocal-job")
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._keep = keep

    # ------------------------------------------------------------ запуск

    def submit(self, kind: str, title: str, function: Callable,
               *args, payload: dict | None = None, **kwargs) -> Job:
        """Поставить задачу. Функции передаётся `progress(stage, percent)`."""
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title,
                  payload=dict(payload or {}))
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._forget_old()
        future = self._pool.submit(self._run, job, function, args, kwargs)
        job.payload.setdefault("queued", True)
        self._watch(job, future)
        return job

    def _watch(self, job: Job, future: Future) -> None:
        def done(_future: Future) -> None:
            job.finished_at = dt.datetime.now(cfg.MSK)
        future.add_done_callback(done)

    def _run(self, job: Job, function: Callable, args, kwargs):
        job.status = RUNNING
        job.started_at = dt.datetime.now(cfg.MSK)
        job.stage = "начинаем"

        def progress(stage: str, percent: int) -> None:
            job.stage = str(stage)
            job.percent = max(0, min(100, int(percent)))

        try:
            import inspect
            parameters = inspect.signature(function).parameters
            if "progress" in parameters and "progress" not in kwargs:
                kwargs = {**kwargs, "progress": progress}
            job.result = function(*args, **kwargs)
        except Exception as error:               # noqa: BLE001
            job.status = FAILED
            job.error = f"{type(error).__name__}: {error}"
            job.details = traceback.format_exc()
            job.stage = "не удалось"
            return None
        job.status = DONE
        job.percent = 100
        job.stage = "готово"
        return job.result

    # ------------------------------------------------------------ чтение

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            return [self._jobs[key] for key in reversed(self._order)
                    if key in self._jobs]

    def active(self) -> list[Job]:
        return [job for job in self.all() if job.active]

    def active_of_kind(self, kind: str) -> Job | None:
        return next((job for job in self.active() if job.kind == kind), None)

    def find_for(self, kind: str, **payload) -> Job | None:
        """Задача того же вида с теми же параметрами — чтобы не запускать дважды."""
        for job in self.all():
            if job.kind != kind or not job.active:
                continue
            if all(job.payload.get(key) == value
                   for key, value in payload.items()):
                return job
        return None

    def _forget_old(self) -> None:
        """Держим последние `keep` задач: журнал не должен расти бесконечно."""
        while len(self._order) > self._keep:
            oldest = self._order.pop(0)
            job = self._jobs.get(oldest)
            if job is not None and job.active:
                self._order.insert(0, oldest)
                return
            self._jobs.pop(oldest, None)


MANAGER = JobManager()
