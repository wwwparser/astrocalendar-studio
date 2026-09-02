"""Редакционная значимость события.

Технически верное событие и событие, которое стоит публиковать, — разные вещи.
Проход Цереры в 1,8° от рассеянного скопления посчитан правильно, но в посте на
широкую аудиторию он занимает строку, вытесняя затмение. Поэтому у каждого
события есть ранг, и в публикацию по умолчанию идут только два верхних.

    must        — событие месяца: затмения, покрытия ярких планет, фазы Луны,
                  противостояния, максимумы крупных потоков, пуски к МКС
    interesting — заметное явление: соединения, элонгации, конфигурации
                  спутников, покрытия звёзд, кометы у ярких объектов
    optional    — верно, но узко: слабые кометы у слабых звёзд, астероиды
                  у скоплений, малозаметные сближения
    technical   — служебное: события с низкой уверенностью, ненаблюдаемые,
                  требующие пересчёта ближе к дате
"""
from __future__ import annotations

from .core import Event

ORDER = {"must": 0, "interesting": 1, "optional": 2, "technical": 3}
PUBLISH_DEFAULT = ("must", "interesting")


def rank_event(event: Event) -> str:
    category = event.category
    meta = event.meta or {}
    text = event.text.lower()

    if category.startswith("live_"):
        # ранг записи живой ленты уже определён её источником и порогами
        # значимости — пересматривать его по тексту строки неправильно
        return event.rank

    if event.confidence == "низкая":
        return "technical"

    if category == "eclipse":
        return "must"

    if category == "occultation":
        # покрытие планеты — событие месяца; покрытие звезды — по её блеску
        if any(word in text for word in ("венеры", "юпитера", "сатурна", "марса",
                                         "меркурия")):
            return "must"
        return "interesting"

    if category == "asteroid_occultation":
        return "interesting" if event.confidence != "низкая" else "technical"

    if category == "moon":
        if "фазе" in text or "перигее" in text or "апогее" in text:
            return "must"
        if meta.get("object"):          # сближение с объектом глубокого космоса
            close = meta.get("sep_deg", 9) <= 1.5
            bright = meta.get("object_mag", 99) <= 4.0
            return "interesting" if close or bright else "optional"
        return "interesting"

    if category == "planet":
        if "противостоянии" in text or "элонгации" in text:
            return "must"
        if "движения" in text or "соединении с солнцем" in text:
            return "interesting"
        return "interesting"

    if category == "season":
        return "must"

    if category == "meteors":
        return "must" if meta.get("zhr", 0) >= 20 else "interesting"

    if category == "spaceflight":
        return "must"

    if category in ("jupiter_moons", "saturn_moons", "visibility"):
        return "interesting"

    if category in ("jupiter_phenomena", "lunar_feature", "comet_milestone"):
        # у этих модулей ранг проставлен при создании события: он зависит от
        # редкости сочетания и наблюдаемости, а не только от типа
        return event.rank

    if category == "iss":
        return "interesting" if event.confidence != "низкая" else "technical"

    if category == "asteroid":
        if meta.get("distance_km"):                       # пролёт у Земли
            return "interesting" if meta.get("diameter_km", 0) >= 0.3 else "optional"
        return "optional"

    if category.startswith("comet"):
        # яркая комета у яркого объекта заслуживает строки, слабая — нет
        comet_mag = meta.get("comet_mag")
        object_mag = meta.get("object_mag", 99)
        separation = meta.get("sep_deg", 9)
        if comet_mag is not None and comet_mag <= 10.0 and separation <= 1.0:
            return "interesting"
        if object_mag <= 4.5 or meta.get("messier"):
            return "interesting"
        return "optional"

    return "optional"


def apply(events: list[Event]) -> list[Event]:
    for event in events:
        event.rank = rank_event(event)
    return events


def for_publication(events: list[Event], ranks=PUBLISH_DEFAULT) -> list[Event]:
    return [e for e in events if e.rank in ranks]
