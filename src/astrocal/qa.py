"""Автоматические проверки календаря перед публикацией.

Задача этого модуля — не пересчитать события заново, а поймать то, что ломается
в подобных генераторах на практике: перепутанный часовой пояс, сдвиг на сутки,
физически невозможное расстояние, блеск планеты вне разумных пределов, созвездие
не то, дубликаты, сорванное форматирование.

Проверки делятся на три вида:

* **sanity** — физика и здравый смысл, считаются из самого события;
* **cross** — сверка с независимым источником (JPL Horizons);
* **format** — соответствие строки формату календаря.

Каждая непройденная проверка добавляется в `event.flags`. Флаг уровня `REVIEW`
означает, что событие нельзя публиковать не глядя.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .core import Event, body, earth, timescale
from .fmt import CONSTELLATIONS_RU, MONTHS_GEN

LINE_PATTERN = re.compile(r"^▪️\d{2} [а-яё]+, \d{2}:\d{2} — .+$")
MAGNITUDE_PATTERN = re.compile(r"V=[+-]\d+,\d+m")
ANGLE_PATTERN = re.compile(r"(\d+\.\d+°|0°\d+′|\d+″)")

# Разумные пределы блеска планет — выход за них означает ошибку модели
MAG_LIMITS = {
    "меркури": (-2.5, 7.5), "венер": (-4.9, -3.0), "марс": (-3.0, 2.0),
    "юпитер": (-3.0, -1.2), "сатурн": (-0.6, 1.5), "уран": (5.3, 6.1),
    "нептун": (7.5, 8.1),
}
MOON_DISTANCE_KM = (356000, 407000)


@dataclass
class Flag:
    level: str          # REVIEW | WARN | INFO
    check: str
    message: str


def _add(event: Event, level: str, check: str, message: str) -> None:
    event.flags.append(Flag(level, check, message))


# ------------------------------------------------------------------ формат


def check_format(event: Event) -> None:
    line = event.line()
    if not LINE_PATTERN.match(line):
        _add(event, "REVIEW", "format", f"строка не соответствует формату: {line!r}")
    if "." in line.split("—", 1)[-1] and "V=" in line:
        for token in re.findall(r"V=[^\s)]+", line):
            if not MAGNITUDE_PATTERN.fullmatch(token.rstrip(",);")):
                _add(event, "WARN", "format",
                     f"звёздная величина оформлена не по стандарту: {token}")
    month_word = line.split()[1] if len(line.split()) > 1 else ""
    if month_word.rstrip(",") not in MONTHS_GEN.values():
        _add(event, "REVIEW", "format", f"месяц записан неверно: {month_word!r}")


# ------------------------------------------------------------------ здравый смысл


def check_timezone(event: Event, start: dt.datetime, end: dt.datetime) -> None:
    if event.when.tzinfo is None:
        _add(event, "REVIEW", "timezone", "время без часового пояса")
        return
    offset = event.when.utcoffset()
    if offset != dt.timedelta(hours=3):
        _add(event, "REVIEW", "timezone",
             f"смещение {offset}, а календарь ведётся в МСК (UTC+3)")
    if not (start <= event.when < end):
        _add(event, "REVIEW", "range",
             f"событие вне месяца: {event.when:%Y-%m-%d %H:%M}")


def check_moon_distance(event: Event) -> None:
    if "перигее" not in event.text and "апогее" not in event.text:
        return
    numbers = re.findall(r"(\d{6})\s*км", event.text)
    if not numbers:
        _add(event, "REVIEW", "moon_distance", "не найдено расстояние до Луны")
        return
    km = int(numbers[0])
    low, high = MOON_DISTANCE_KM
    if not (low <= km <= high):
        _add(event, "REVIEW", "moon_distance",
             f"{km} км вне диапазона орбиты Луны {low}–{high} км")
    if "перигее" in event.text and km > 371000:
        _add(event, "REVIEW", "moon_distance", f"перигей не может быть {km} км")
    if "апогее" in event.text and km < 391000:
        _add(event, "REVIEW", "moon_distance", f"апогей не может быть {km} км")


def check_moon_distance_matches_ephemeris(event: Event,
                                          tolerance_km: float = 100.0) -> None:
    """Сверить расстояние в тексте с пересчётом на тот же момент.

    Проверка диапазона ловит только физически невозможное. Число может быть
    вполне правдоподобным перигеем — и при этом не тем, что был в эту дату:
    именно так выглядела ошибка «359 077 км» в чужом августовском календаре
    при истинных 363 265 км.
    """
    if "перигее" not in event.text and "апогее" not in event.text:
        return
    numbers = re.findall(r"(\d{6})\s*км", event.text)
    if not numbers:
        return
    stated = float(numbers[0])
    t = timescale().from_datetime(event.when)
    actual = float(earth().at(t).observe(body("moon")).distance().km)
    if abs(stated - actual) > tolerance_km:
        _add(event, "REVIEW", "moon_distance_ephemeris",
             f"в строке {stated:.0f} км, пересчёт на тот же момент "
             f"{actual:.0f} км, расхождение {abs(stated - actual):.0f} км")


def check_phase_notation(event: Event) -> None:
    for token in re.findall(r"Ф=([+-])(\d,\d\d)", event.text):
        sign, value = token
        fraction = float(value.replace(",", "."))
        if not (0.0 <= fraction <= 0.99):
            _add(event, "REVIEW", "phase", f"фаза Ф={sign}{value} вне 0–0,99")
    if "полнолуние" in event.text and "Ф=" in event.text:
        _add(event, "WARN", "phase", "у полнолуния фазу обычно не указывают")


def check_magnitudes(event: Event) -> None:
    text = event.text.lower()
    if "V=" not in event.text:
        return          # у стояний и соединений блеск не указывают — это норма
    for marker, (low, high) in MAG_LIMITS.items():
        if marker not in text:
            continue
        for token in re.findall(r"V=([+-]\d+,\d+)m", event.text):
            value = float(token.replace(",", "."))
            if low - 0.4 <= value <= high + 0.4:
                break
        else:
            _add(event, "WARN", "magnitude",
                 f"для «{marker}» ожидается блеск {low}…{high}m, "
                 f"в строке этого значения нет")


def check_constellation(event: Event) -> None:
    match = re.search(r"в созвездии ([А-ЯЁ][а-яё]+(?: [А-ЯЁ][а-яё]+)?)", event.text)
    if not match:
        return
    if match.group(1) not in CONSTELLATIONS_RU.values():
        _add(event, "REVIEW", "constellation",
             f"неизвестное созвездие: {match.group(1)!r}")


def check_angles(event: Event) -> None:
    for token in re.findall(r"проходит в ([^\s]+)", event.text):
        if not ANGLE_PATTERN.fullmatch(token):
            _add(event, "WARN", "angle", f"угловое расстояние оформлено странно: {token}")


def check_close_approach(event: Event) -> None:
    """Сближение NEO: расстояние, перевод в лунные расстояния, скорость.

    Ошибка в этих трёх числах — самая заметная для читателя: «в 25 км от Земли»
    вместо «в 25 млн км» выглядит как конец света, а не как рядовой пролёт.
    """
    from . import config as cfg

    meta = event.meta or {}
    distance_km = meta.get("distance_km")
    if not distance_km:
        return
    if distance_km <= 0:
        _add(event, "REVIEW", "neo_distance",
             f"расстояние {distance_km} км не положительно")
        return
    distance_ld = meta.get("distance_ld")
    if distance_ld is not None:
        expected = distance_km / cfg.LUNAR_DISTANCE_KM
        if abs(expected - distance_ld) > 0.01 * expected:
            _add(event, "REVIEW", "neo_ld",
                 f"в лунных расстояниях {distance_ld:.2f}, а по километрам "
                 f"{expected:.2f}")
    velocity = meta.get("velocity_km_s")
    if velocity is not None and not (0.5 <= velocity <= 80.0):
        _add(event, "WARN", "neo_velocity",
             f"относительная скорость {velocity} км/с вне пределов 0,5…80 км/с")
    if meta.get("diameter_km") and not (event.provenance or {}).get(
            "diameter_provenance"):
        _add(event, "WARN", "neo_diameter",
             "указан размер, но не указано, измерен он или оценён по H")


def check_duplicates(events: list[Event]) -> None:
    seen: dict[tuple, Event] = {}
    for event in events:
        key = (event.text, event.display_time.strftime("%d %H"))
        if key in seen:
            _add(event, "REVIEW", "duplicate",
                 f"дубликат события {seen[key].display_time:%d.%m %H:%M}")
        seen[key] = event


# ------------------------------------------------------------------ второй источник


def check_against_horizons(event: Event, tolerance_arcsec: float = 1.0) -> None:
    """Сверка положения участвующих тел с JPL Horizons."""
    from .verify import compare

    bodies = {"луна": "moon", "меркури": "mercury", "венер": "venus", "марс": "mars",
              "юпитер": "jupiter", "сатурн": "saturn", "уран": "uranus",
              "нептун": "neptune"}
    text = event.text.lower()
    targets = [code for marker, code in bodies.items() if marker in text]
    if not targets:
        return
    for name in targets[:2]:
        try:
            result = compare(name, event.when)
        except Exception as exc:
            _add(event, "WARN", "horizons", f"сверка {name} не выполнена: {exc}")
            continue
        delta = result["delta_arcsec"]
        event.provenance.setdefault("horizons", {})[name] = round(delta, 3)
        if delta > tolerance_arcsec:
            _add(event, "REVIEW", "horizons",
                 f"положение {name} расходится с Horizons на {delta:.1f}″ "
                 f"при допуске {tolerance_arcsec:.0f}″")


# ------------------------------------------------------------------ provenance


def stamp_provenance(events: list[Event], sources: dict) -> None:
    """Проставить каждому событию источник данных, версию и время расчёта."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for event in events:
        event.provenance.setdefault("computed_at_utc", now)
        event.provenance.setdefault("ephemeris", sources.get("ephemeris"))
        event.provenance.setdefault("catalogs", sources.get("catalogs"))
        event.provenance.setdefault("timescale", "UTC → МСК (UTC+3), без перехода")
        if event.category == "iss":
            event.provenance["tle_age_days"] = event.meta.get("tle_age_days")


# ------------------------------------------------------------------ прогон


def run(events: list[Event], start: dt.datetime, end: dt.datetime,
        use_horizons: bool = True) -> dict:
    for event in events:
        event.flags = []
        check_format(event)
        check_timezone(event, start, end)
        check_moon_distance(event)
        check_moon_distance_matches_ephemeris(event)
        check_phase_notation(event)
        check_magnitudes(event)
        check_constellation(event)
        check_angles(event)
        check_close_approach(event)
    check_duplicates(events)
    if use_horizons:
        for event in events:
            check_against_horizons(event)

    review = [e for e in events if any(f.level == "REVIEW" for f in e.flags)]
    warn = [e for e in events if any(f.level == "WARN" for f in e.flags)
            and e not in review]
    return {"total": len(events), "review": review, "warn": warn,
            "clean": len(events) - len(review) - len(warn)}


def sanity_summary(events: list[Event]) -> list[str]:
    """Короткие итоги по физическим величинам — для отчёта."""
    ts = timescale()
    lines = []
    for event in events:
        if "перигее" in event.text or "апогее" in event.text:
            km = int(re.findall(r"(\d{6})\s*км", event.text)[0])
            t = ts.from_datetime(event.when)
            actual = float(earth().at(t).observe(body("moon")).distance().km)
            lines.append(f"{event.display_time:%d.%m} расстояние до Луны в строке "
                         f"{km} км, пересчёт на тот же момент {actual:.0f} км, "
                         f"расхождение {abs(km - actual):.0f} км")
    return lines
