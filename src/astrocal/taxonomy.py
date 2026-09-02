"""Классификация событий для редакторских фильтров.

Внутренние категории модулей (`moon`, `planet`, `comet_star`) удобны коду, но
редактору нужны другие группы: «Луна — яркие звёзды» и «Покрытия Луной» живут
в одном модуле, а в интерфейсе это разные галочки. Здесь один раз описано
соответствие, и им пользуются и GUI, и CLI.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    key: str
    title: str
    group: str
    default_on: bool = True


GROUPS = ["Луна", "Планеты", "Спутники планет", "Малые тела", "Метеоры",
          "Космонавтика", "Наблюдательные явления", "Открытия (Live)"]

KINDS: tuple[Kind, ...] = (
    Kind("moon_phase", "Фазы Луны", "Луна"),
    Kind("moon_apsis", "Перигей / апогей", "Луна"),
    Kind("moon_planet", "Луна — планеты", "Луна"),
    Kind("moon_star", "Луна — яркие звёзды", "Луна"),
    Kind("moon_dso", "Луна — скопления и туманности", "Луна"),
    Kind("occultation", "Покрытия Луной", "Луна"),
    Kind("solar_eclipse", "Солнечные затмения", "Луна"),
    Kind("lunar_eclipse", "Лунные затмения", "Луна"),

    Kind("planet_opposition", "Противостояния", "Планеты"),
    Kind("planet_conjunction", "Соединения", "Планеты"),
    Kind("planet_elongation", "Элонгации", "Планеты"),
    Kind("planet_station", "Стояния", "Планеты"),
    Kind("planet_brilliancy", "Максимальный блеск", "Планеты"),
    Kind("planet_visibility", "Периоды видимости планет", "Планеты"),

    Kind("jupiter_moons", "Галилеевы спутники", "Спутники планет"),
    Kind("jupiter_phenomena", "Прохождения и тени спутников", "Спутники планет"),
    Kind("titan", "Титан", "Спутники планет"),

    Kind("comet", "Кометы", "Малые тела"),
    Kind("asteroid", "Астероиды", "Малые тела"),
    Kind("neo", "Сближения с Землёй (NEO)", "Малые тела"),
    Kind("asteroid_occultation", "Покрытия звёзд астероидами", "Малые тела"),

    Kind("meteors", "Метеорные потоки", "Метеоры"),

    # События, пришедшие из живой ленты. Отдельная группа нужна потому, что это
    # не результат детерминированного расчёта месяца: открытие нельзя было
    # предсказать первого числа, и в выпуске оно помечено происхождением.
    Kind("live_neo", "Сближения из Live", "Открытия (Live)", default_on=False),
    Kind("live_occultation", "Покрытия из Live", "Открытия (Live)",
         default_on=False),
    Kind("live_comet", "Открытые кометы", "Открытия (Live)", default_on=False),
    Kind("live_transient", "Новые и сверхновые", "Открытия (Live)",
         default_on=False),

    Kind("iss", "МКС", "Космонавтика"),
    Kind("css", "ККС / Tiangong", "Космонавтика"),
    Kind("launch", "Космические запуски", "Космонавтика"),

    Kind("lunar_feature", "Lunar X / V", "Наблюдательные явления"),
    Kind("libration", "Либрации", "Наблюдательные явления"),
    Kind("season", "Равноденствия и солнцестояния", "Наблюдательные явления"),
    Kind("manual", "Ручные события", "Наблюдательные явления"),
    Kind("other", "Прочее", "Наблюдательные явления"),
)

BY_KEY = {kind.key: kind for kind in KINDS}


def classify(event) -> str:
    """Определить редакторскую группу события."""
    category = event.category
    text = event.text.lower()
    meta = event.meta or {}

    if category.startswith("live_"):
        return category if category in BY_KEY else "other"

    if meta.get("manual"):
        return "manual"

    if category == "eclipse":
        return "solar_eclipse" if "солнечное" in text else "lunar_eclipse"

    if category == "occultation":
        return "occultation"

    if category == "asteroid_occultation":
        return "asteroid_occultation"

    if category == "moon":
        if "в фазе" in text:
            return "moon_phase"
        if "перигее" in text or "апогее" in text:
            return "moon_apsis"
        if meta.get("object"):
            return "moon_dso"
        if "звезды" in text:
            return "moon_star"
        return "moon_planet"

    if category == "planet":
        if "противостоянии" in text:
            return "planet_opposition"
        if "элонгации" in text:
            return "planet_elongation"
        if "движения" in text:
            return "planet_station"
        if "максимальном блеске" in text:
            return "planet_brilliancy"
        return "planet_conjunction"

    if category == "visibility":
        return "planet_visibility"

    if category == "jupiter_moons":
        return "jupiter_moons"
    if category == "jupiter_phenomena":
        return "jupiter_phenomena"
    if category == "saturn_moons":
        return "titan"

    if category.startswith("comet"):
        return "comet"

    if category == "asteroid":
        return "neo" if meta.get("distance_km") else "asteroid"

    if category == "meteors":
        return "meteors"

    if category == "iss":
        return "css" if meta.get("station") == "ККС" else "iss"

    if category == "spaceflight":
        return "launch"

    if category == "lunar_feature":
        return "libration" if "либрация" in text else "lunar_feature"

    if category == "season":
        return "season"

    return "other"


def title_of(key: str) -> str:
    kind = BY_KEY.get(key)
    return kind.title if kind else key


def grouped_kinds() -> dict[str, list[Kind]]:
    result: dict[str, list[Kind]] = {group: [] for group in GROUPS}
    for kind in KINDS:
        result[kind.group].append(kind)
    return result
