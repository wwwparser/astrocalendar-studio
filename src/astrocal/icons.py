"""Значки для строк календаря.

В канале все строки начинаются одним маркером ▪️. Читателю от этого не легче:
пост на полсотни строк выглядит однородной стеной, и найти в нём «где там про
Юпитер» можно только вычитыванием.

Значок решает ровно эту задачу — навигацию глазом. Поэтому правило простое:
если в событии участвует конкретная планета, значок её; иначе значок типа
события. Никакой декоративности: один значок на строку, и он всегда означает
одно и то же.

Набор символов собран в одном месте намеренно. Вкусы у редакций разные, и
менять их должно быть просто — здесь, а не поиском по коду.
"""
from __future__ import annotations

import re

# Планеты. Внешние — тёплые тона, внутренние — светлые, ледяные гиганты —
# холодные: так строка различается боковым зрением, ещё до чтения.
PLANET_ICONS = {
    "mercury": "⚪",
    "venus": "🟡",
    "mars": "🔴",
    "jupiter": "🟠",
    "saturn": "🪐",
    "uranus": "🔵",
    "neptune": "🔷",
    "sun": "☀️",
    "moon": "🌙",
}

# Названия в тексте события — по ним определяется планета
PLANET_WORDS = {
    "меркури": "mercury", "венер": "venus", "марс": "mars",
    "юпитер": "jupiter", "сатурн": "saturn", "уран": "uranus",
    "нептун": "neptune", "солнц": "sun",
}

# Значок по редакторской категории события (см. taxonomy)
KIND_ICONS = {
    "moon_phase": "🌗", "moon_apsis": "🌙", "moon_planet": "🌙",
    "moon_star": "✨", "moon_dso": "✨", "occultation": "🌑",
    "solar_eclipse": "🌞", "lunar_eclipse": "🌘",
    "planet_opposition": "🪐", "planet_conjunction": "🪐",
    "planet_elongation": "🪐", "planet_station": "🪐",
    "planet_brilliancy": "🪐", "planet_visibility": "🪐",
    "jupiter_moons": "🔭", "jupiter_phenomena": "🔭", "titan": "🔭",
    "comet": "☄️", "asteroid": "💫", "neo": "☄", "bright_neo": "☄",
    "asteroid_occultation": "⭐",
    "meteors": "🌠",
    "iss": "🛰", "css": "🛰", "launch": "🚀",
    "lunar_feature": "🌓", "libration": "🌓", "season": "🍂",
    "manual": "📌", "other": "▪️",
    "live_neo": "☄", "live_occultation": "⭐", "live_comet": "🆕",
    "live_transient": "🆕",
}

DEFAULT = "▪️"


def planet_in(text: str) -> str | None:
    """Планета, о которой идёт речь в строке, если она одна.

    Если планет несколько — «Венера в 2° от Марса» — значок по планете не
    ставится: выбирать между ними произвольно неправильно.
    """
    lowered = (text or "").lower()
    found = {code for word, code in PLANET_WORDS.items() if word in lowered}
    found.discard("sun")
    if len(found) == 1:
        return next(iter(found))
    return None


MOON_PHASE_ICONS = {
    "новолуние": "🌑", "первой четверти": "🌓",
    "полнолуние": "🌕", "последней четверти": "🌗",
}


def icon_for(event, kind: str | None = None) -> str:
    """Значок строки календаря."""
    from .taxonomy import classify

    resolved = kind or classify(event)
    text = event.text or ""

    if resolved == "moon_phase":
        for phrase, symbol in MOON_PHASE_ICONS.items():
            if phrase in text:
                return symbol
        return KIND_ICONS["moon_phase"]

    # У событий Луны с планетой значок Луны нагляднее планетного: речь о том,
    # что видно рядом с Луной, а не о самой планете.
    if resolved.startswith("moon_") or resolved == "occultation":
        return KIND_ICONS.get(resolved, DEFAULT)

    planet = planet_in(text)
    if planet and resolved.startswith("planet"):
        return PLANET_ICONS[planet]
    if planet and resolved in ("jupiter_moons", "jupiter_phenomena", "titan"):
        return KIND_ICONS[resolved]
    if planet and resolved in ("visibility",):
        return PLANET_ICONS[planet]

    return KIND_ICONS.get(resolved, DEFAULT)


LINE = re.compile(r"^▪️")


def decorate(line: str, event, kind: str | None = None) -> str:
    """Заменить стандартный маркер строки на значок события."""
    return LINE.sub(icon_for(event, kind), line, count=1)
