"""Фоновые расчёты: интерфейс не должен замирать.

Загрузка каталогов, снимок неба и перебор объектов на ночь занимают от долей
секунды до нескольких секунд. Если считать их в потоке интерфейса, окно
перестаёт перерисовываться, и программа выглядит зависшей ровно в тот момент,
когда человек нажал главную кнопку.

Реализация намеренно не использует `QRunnable`: Qt удаляет объект-задачу сразу
после её выполнения, и вспомогательный объект с сигналами исчезает вместе с ней
до того, как результат успевает уйти в интерфейс. Поэтому потоки берутся из
обычного питоновского пула, а результат возвращается сигналом самого `Runner` —
он живёт столько же, сколько окно, и не может исчезнуть посреди расчёта.
"""
from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal, Slot

# Расчёты упираются в numpy и Skyfield, которые отпускают GIL, поэтому пары
# потоков достаточно: больше только добавит конкуренции за кэши эфемерид.
_EXECUTOR = ThreadPoolExecutor(max_workers=3,
                               thread_name_prefix="binocular-sky")


def shutdown(wait: bool = True) -> None:
    """Дождаться фоновых расчётов при закрытии программы."""
    _EXECUTOR.shutdown(wait=wait, cancel_futures=True)


class Runner(QObject):
    """Очередь расчётов одного вида.

    Хранит номер последней запущенной задачи и отбрасывает результаты
    устаревших: при быстром перетаскивании ползунка времени успевают
    стартовать несколько снимков, и показать нужно последний, а не тот,
    что случайно досчитался первым.
    """

    finished = Signal(object)
    failed = Signal(str)
    busy_changed = Signal(bool)

    # Внутренний сигнал: мост из рабочего потока в поток интерфейса.
    _delivered = Signal(int, bool, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._generation = 0
        self._pending = 0
        self._delivered.connect(self._receive)

    def submit(self, function, *args, **kwargs) -> None:
        self._generation += 1
        generation = self._generation
        self._pending += 1
        if self._pending == 1:
            self.busy_changed.emit(True)
        _EXECUTOR.submit(self._work, generation, function, args, kwargs)

    def _work(self, generation: int, function, args, kwargs) -> None:
        """Тело задачи. Выполняется в рабочем потоке."""
        try:
            result = function(*args, **kwargs)
        except Exception:
            self._delivered.emit(generation, False, traceback.format_exc())
        else:
            self._delivered.emit(generation, True, result)

    @Slot(int, bool, object)
    def _receive(self, generation: int, ok: bool, payload) -> None:
        """Приём результата уже в потоке интерфейса."""
        self._pending = max(0, self._pending - 1)
        if self._pending == 0:
            self.busy_changed.emit(False)
        if generation != self._generation:
            return          # результат устарел: пришёл более свежий запрос
        if ok:
            self.finished.emit(payload)
        else:
            self.failed.emit(payload)

    @property
    def busy(self) -> bool:
        return self._pending > 0
