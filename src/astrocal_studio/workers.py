"""Фоновые задачи.

Расчёт месяца занимает минуты, запросы к Horizons и Celestrak — секунды.
Ничего из этого нельзя выполнять в потоке интерфейса: окно перестанет
перерисовываться, и Windows объявит программу зависшей. Здесь единственный
механизм, которым GUI запускает долгую работу.
"""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class TaskSignals(QObject):
    started = Signal(str)
    progress = Signal(str, int)
    finished = Signal(object)
    failed = Signal(str, str)


class Task(QRunnable):
    """Одна фоновая операция.

    Функции передаётся именованный аргумент `progress`, если она его принимает,
    — так расчёт сообщает о ходе работы, не зная ничего про Qt.
    """

    def __init__(self, name: str, function: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.name = name
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        self.signals.started.emit(self.name)
        try:
            import inspect
            parameters = inspect.signature(self.function).parameters
            if "progress" in parameters and "progress" not in self.kwargs:
                self.kwargs["progress"] = self._report
            result = self.function(*self.args, **self.kwargs)
        except Exception as error:                      # noqa: BLE001
            # Пользователю — понятное сообщение, разработчику — полный traceback
            self.signals.failed.emit(f"{type(error).__name__}: {error}",
                                     traceback.format_exc())
            return
        self.signals.finished.emit(result)

    def _report(self, stage: str, percent: int) -> None:
        self.signals.progress.emit(stage, int(percent))


class TaskRunner:
    """Пул потоков приложения плюс подключение сигналов в одном месте."""

    def __init__(self, max_threads: int = 3):
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max(1, max_threads))
        self._active: list[Task] = []

    def submit(self, name: str, function: Callable[..., Any], *args,
               on_result: Callable[[Any], None] | None = None,
               on_error: Callable[[str, str], None] | None = None,
               on_progress: Callable[[str, int], None] | None = None,
               on_start: Callable[[str], None] | None = None,
               **kwargs) -> Task:
        task = Task(name, function, *args, **kwargs)
        if on_start:
            task.signals.started.connect(on_start)
        if on_progress:
            task.signals.progress.connect(on_progress)
        if on_result:
            task.signals.finished.connect(on_result)
        if on_error:
            task.signals.failed.connect(on_error)
        task.signals.finished.connect(lambda _=None, t=task: self._done(t))
        task.signals.failed.connect(lambda *_args, t=task: self._done(t))
        self._active.append(task)
        self.pool.start(task)
        return task

    def _done(self, task: Task) -> None:
        if task in self._active:
            self._active.remove(task)

    @property
    def busy(self) -> bool:
        return bool(self._active)

    def wait(self, milliseconds: int = 30000) -> bool:
        return self.pool.waitForDone(milliseconds)
