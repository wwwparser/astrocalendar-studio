"""AstroCalendar Live — то, что нельзя было предсказать заранее.

Месячный календарь отвечает на вопрос «что произойдёт» и строится один раз на
месяц вперёд. Живая лента отвечает на другой вопрос — «что только что открыли
или уточнили» — и потому устроена иначе: она не пересчитывает месяц, а
сравнивает текущее состояние внешнего источника с предыдущим снимком.

Четыре источника:

* покрытия звёзд астероидами (IOTA + пересчёт по свежей орбите JPL) —
  прогнозируемые события, которые стареют;
* близкие пролёты астероидов (CNEOS) — прогнозируемые события, список которых
  постоянно пополняется;
* новые кометы (MPC) — открытия;
* новые и сверхновые (TNS) — открытия.

Первые два класса имеют момент наступления и могут попасть в месячный выпуск.
Последние два — события открытия: они происходят тогда, когда происходят, и
задним числом в календарь не вставляются.
"""
from .discovery_service import RefreshResult, refresh, visible
from .model import (DiscoveryEvent, LiveRecord, LiveUpdate, ScheduledEvent,
                    STATUS_NEW, STATUS_UNCHANGED, STATUS_UPDATED)
from .state import LiveState, Snapshot

__all__ = ["RefreshResult", "refresh", "visible", "DiscoveryEvent",
           "LiveRecord", "LiveUpdate", "ScheduledEvent", "STATUS_NEW",
           "STATUS_UNCHANGED", "STATUS_UPDATED", "LiveState", "Snapshot"]
