"""Семантические типы живой ленты.

Предсказанное событие и открытие — принципиально разные вещи, и складывать их
в один тип нельзя. Покрытие звезды астероидом 19 сентября известно заранее: его
можно поставить в месячный календарь, свёрстанный 1-го числа. Сверхновая,
открытая 12 сентября, в календарь 1-го числа попасть не могла ни при каком
качестве расчёта — и делать вид, что могла, значит обманывать читателя.

Отсюда три типа:

* `ScheduledEvent` — прогнозируемое событие с известным моментом: сближение
  NEO, покрытие звезды. Имеет `when`, законно переносится в месячный выпуск.
* `DiscoveryEvent` — открытие: новая комета, новая или сверхновая. Имеет
  `discovered_at`; в выпуск попадает только как отдельная новость, помеченная
  происхождением.
* `LiveUpdate` — уточнение ранее известного прогноза: полоса покрытия
  сдвинулась, дата пуска изменилась. Ссылается на исходное событие и несёт
  список изменений.

Общее у них — устойчивый `live_id` и `payload`, по хэшу которого слой
состояния отличает NEW от UPDATED и от UNCHANGED.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field

from .. import config as cfg

KIND_NEO = "neo"
KIND_OCCULTATION = "occultation"
KIND_COMET = "comet"
KIND_TRANSIENT = "transient"

KIND_TITLES = {
    KIND_NEO: "Сближение с Землёй",
    KIND_OCCULTATION: "Покрытие звезды астероидом",
    KIND_COMET: "Новая комета",
    KIND_TRANSIENT: "Новая / сверхновая",
}
KIND_ICONS = {KIND_NEO: "☄", KIND_OCCULTATION: "★",
              KIND_COMET: "🆕", KIND_TRANSIENT: "🆕"}

SEMANTIC_SCHEDULED = "scheduled"
SEMANTIC_DISCOVERY = "discovery"
SEMANTIC_UPDATE = "update"

STATUS_NEW = "NEW"
STATUS_UPDATED = "UPDATED"
STATUS_UNCHANGED = "UNCHANGED"


@dataclass
class LiveRecord:
    """Общая часть записи живой ленты."""
    live_id: str
    kind: str
    title: str
    summary: str = ""
    lines: list[str] = field(default_factory=list)
    when: dt.datetime | None = None
    discovered_at: dt.datetime | None = None
    magnitude: float | None = None
    rank: str = "optional"
    stars: int = 0
    payload: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    observability: dict = field(default_factory=dict)
    changes: list[str] = field(default_factory=list)
    status: str = STATUS_NEW
    state: dict = field(default_factory=dict)
    # какие поля payload нужно помнить между запусками: по ним считается, что
    # именно изменилось (например, прежняя центральная линия полосы покрытия)
    retain: tuple = ()
    previous: dict = field(default_factory=dict)
    # тяжёлые данные для карт (полная полоса покрытия, орбита кометы): живут
    # только в памяти, в отпечаток не входят и на диск не пишутся
    extra: dict = field(default_factory=dict, repr=False, compare=False)

    semantic: str = SEMANTIC_SCHEDULED

    # ------------------------------------------------------------ идентичность

    def payload_hash(self) -> str:
        """Отпечаток содержательных полей.

        Считается только от `payload`: время получения, статус прочтения и
        прочая служебная обвязка меняются постоянно и не означают, что данные
        источника изменились.
        """
        raw = json.dumps(self.payload, sort_keys=True, ensure_ascii=False,
                         default=str)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def kind_title(self) -> str:
        return KIND_TITLES.get(self.kind, self.kind)

    @property
    def icon(self) -> str:
        return KIND_ICONS.get(self.kind, "•")

    @property
    def moment(self) -> dt.datetime | None:
        """Момент, по которому запись сортируется в ленте."""
        return self.when or self.discovered_at

    @property
    def unread(self) -> bool:
        return not self.state.get("read", False)

    @property
    def ignored(self) -> bool:
        return bool(self.state.get("ignored"))

    @property
    def stars_text(self) -> str:
        return "★" * self.stars + "·" * (5 - self.stars) if self.stars else "—"

    @property
    def relative(self) -> str:
        """«2 ч назад» для открытий, «завтра» для прогнозов."""
        moment = self.moment
        if moment is None:
            return ""
        delta = (moment - dt.datetime.now(cfg.MSK)).total_seconds()
        ahead = delta > 0
        hours = abs(delta) / 3600.0
        if hours < 1:
            text = f"{abs(delta) / 60:.0f} мин"
        elif hours < 36:
            text = f"{hours:.0f} ч"
        else:
            text = f"{hours / 24:.0f} дн"
        return f"через {text}" if ahead else f"{text} назад"

    # ------------------------------------------------------------ выпуск

    def to_event(self):
        """Перенести запись в месячный выпуск как связанное событие.

        Происхождение сохраняется явно: редактор должен видеть, что строка
        пришла из живой ленты, а не из детерминированного расчёта месяца.
        """
        from ..core import Event

        moment = self.moment
        if moment is None:
            raise ValueError("у записи нет момента, её нельзя поставить в выпуск")
        return Event(
            when=moment,
            text=self.summary or self.title,
            category=f"live_{self.kind}",
            confidence="средняя" if self.semantic == SEMANTIC_DISCOVERY
                       else "высокая",
            computed=" ".join(self.lines) or self.summary,
            sources=list(self.sources),
            rank=self.rank,
            precision="minute" if self.semantic == SEMANTIC_SCHEDULED else "hour",
            provenance={**self.provenance, "origin": "live",
                        "semantic": self.semantic,
                        "source_event_id": self.live_id,
                        "payload_hash": self.payload_hash()},
            meta={"live": True, "live_id": self.live_id, "live_kind": self.kind,
                  "magnitude": self.magnitude},
        )


@dataclass
class ScheduledEvent(LiveRecord):
    """Прогнозируемое событие: известно заранее, имеет момент наступления."""
    semantic: str = SEMANTIC_SCHEDULED


@dataclass
class DiscoveryEvent(LiveRecord):
    """Открытие: заранее непредсказуемо, имеет момент обнаружения."""
    semantic: str = SEMANTIC_DISCOVERY


@dataclass
class LiveUpdate(LiveRecord):
    """Уточнение ранее известного прогноза."""
    semantic: str = SEMANTIC_UPDATE
    target_id: str = ""


def sort_key(record: LiveRecord):
    """Сортировка ленты: сначала значимое, внутри — по времени."""
    weight = {"must": 0, "interesting": 1, "optional": 2, "technical": 3}
    moment = record.moment or dt.datetime.now(cfg.MSK)
    return (weight.get(record.rank, 3), -moment.timestamp())
