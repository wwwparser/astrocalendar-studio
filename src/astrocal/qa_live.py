"""Проверки записей живой ленты.

Проверки календаря (`qa`) смотрят на готовую строку: формат, часовой пояс,
физическую правдоподобность чисел. У живой ленты другая природа ошибок: данные
приходят из сети, в чужом формате, и ломаются они иначе — расстояние в других
единицах, координаты за пределами сферы, дата открытия в будущем, оценка блеска
выданная за измерение, устаревший прогноз полосы.

Отдельно проверяется происхождение. Любая запись, полученная по сети, обязана
нести источник и время получения: без них невозможно ни воспроизвести
результат, ни объяснить читателю, откуда взялось число.

Уровни те же, что в календарном QA: REVIEW — публиковать нельзя не глядя,
WARN — стоит посмотреть, INFO — к сведению.
"""
from __future__ import annotations

import datetime as dt

from . import config as cfg
from .qa import Flag

LD_KM = cfg.LUNAR_DISTANCE_KM


def _flag(flags: list, level: str, check: str, message: str) -> None:
    flags.append(Flag(level, check, message))


# ------------------------------------------------------------------ общее


def check_provenance(record, flags: list) -> None:
    """Сетевое событие без источника и времени получения непубликуемо."""
    provenance = record.provenance or {}
    if not provenance.get("source"):
        _flag(flags, "REVIEW", "provenance", "не указан источник данных")
    if not provenance.get("source_updated_at"):
        _flag(flags, "WARN", "provenance",
              "не указано время получения данных от источника")


# ------------------------------------------------------------------ NEO


def check_bright_neo(record, flags: list) -> None:
    """Прогноз блеска яркого объекта года: это не карточка пролёта.

    Ни скорости, ни точного момента сближения у такой записи нет и быть не
    должно — источник говорит только о блеске. Требовать от неё полей
    карточки сближения бессмысленно, проверять есть что другое.
    """
    payload = record.payload or {}
    peak = payload.get("peak_magnitude")
    if peak is None or not (-5.0 <= peak <= 20.0):
        _flag(flags, "REVIEW", "neo_magnitude",
              f"прогноз максимума блеска {peak!r} вне разумных пределов")
    distance_ld = payload.get("distance_ld")
    if distance_ld is not None and not (0.0 < distance_ld < 2000.0):
        _flag(flags, "REVIEW", "neo_distance",
              f"расстояние {distance_ld} лунных расстояний неправдоподобно")


def check_neo(record, flags: list) -> None:
    payload = record.payload or {}
    if payload.get("bright_of_year"):
        check_bright_neo(record, flags)
        return
    distance_km = payload.get("distance_km")
    distance_ld = payload.get("distance_ld")

    if not distance_km or distance_km <= 0:
        _flag(flags, "REVIEW", "neo_distance",
              f"расстояние {distance_km!r} не положительно")
    elif distance_ld is not None:
        expected = distance_km / LD_KM
        if abs(expected - distance_ld) > 0.01 * max(expected, 1e-6):
            _flag(flags, "REVIEW", "neo_ld",
                  f"перевод в лунные расстояния не сходится: {distance_ld:.3f} LD "
                  f"против {expected:.3f} LD по расстоянию в километрах")

    velocity = payload.get("velocity_km_s")
    if velocity is None or not (0.5 <= velocity <= 80.0):
        _flag(flags, "WARN", "neo_velocity",
              f"относительная скорость {velocity!r} км/с вне разумных пределов "
              f"0,5…80 км/с")

    ours = payload.get("magnitude_computed")
    theirs = payload.get("feed_magnitude")
    if ours is not None and theirs is not None:
        difference = abs(float(ours) - float(theirs))
        if difference > 1.5:
            _flag(flags, "REVIEW", "neo_magnitude",
                  f"наш расчёт блеска {ours:+.1f}m расходится с независимым "
                  f"источником ({theirs:+.1f}m) на {difference:.1f}m")
        elif difference > 0.5:
            _flag(flags, "WARN", "neo_magnitude",
                  f"блеск расходится с независимым источником на "
                  f"{difference:.1f}m: {ours:+.1f}m против {theirs:+.1f}m")

    if payload.get("diameter_measured") is None:
        if payload.get("absolute_magnitude_H") is None:
            _flag(flags, "WARN", "neo_diameter",
                  "размер не измерен и не выводится: нет ни диаметра, ни H")
        elif "оценка" not in str((record.provenance or {}).get(
                "diameter_provenance", "")):
            _flag(flags, "REVIEW", "neo_diameter",
                  "диаметр получен из H, но в происхождении это не отмечено — "
                  "оценка не должна выдаваться за измерение")


# ------------------------------------------------------------------ покрытия


def check_occultation(record, flags: list) -> None:
    payload = record.payload or {}

    if not payload.get("star_id"):
        _flag(flags, "REVIEW", "occ_star", "не указана покрываемая звезда")
    star_mag = payload.get("star_mag")
    if star_mag is None or not (-2.0 <= star_mag <= 16.0):
        _flag(flags, "WARN", "occ_star",
              f"блеск звезды {star_mag!r} вне разумных пределов")

    if not payload.get("orbit_epoch"):
        _flag(flags, "WARN", "occ_orbit",
              "неизвестна дата решения орбиты астероида — свежесть прогноза "
              "проверить нечем")

    age = (record.provenance or {}).get("prediction_age_days")
    if age is not None and record.when is not None:
        days_left = (record.when - dt.datetime.now(cfg.MSK)).total_seconds() / 86400.0
        if age > cfg.OCC_PREDICTION_STALE_DAYS and 0 <= days_left <= 60:
            _flag(flags, "REVIEW", "occ_freshness",
                  f"прогноз рассчитан {age:.0f} дн назад, а событие через "
                  f"{days_left:.0f} дн — полосу нужно пересчитать")

    if payload.get("uncertainty_km") is None:
        _flag(flags, "WARN", "occ_uncertainty",
              "неизвестна неопределённость положения полосы")

    path = payload.get("central_path_sample") or []
    if not path:
        _flag(flags, "REVIEW", "occ_path", "полоса покрытия пуста")
    for point in path:
        try:
            latitude, longitude = float(point["lat"]), float(point["lon"])
        except (KeyError, TypeError, ValueError):
            _flag(flags, "REVIEW", "occ_path", f"негодная точка полосы: {point!r}")
            continue
        if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
            _flag(flags, "REVIEW", "occ_path",
                  f"точка полосы вне Земли: {latitude}, {longitude}")

    star_altitude = payload.get("star_altitude_deg")
    sun_altitude = payload.get("sun_altitude_deg")
    if star_altitude is not None and star_altitude < 0:
        _flag(flags, "REVIEW", "occ_visibility",
              f"звезда под горизонтом ({star_altitude:.0f}°) — покрытие "
              f"наблюдать неоткуда")
    if sun_altitude is not None and sun_altitude > 0:
        _flag(flags, "WARN", "occ_visibility",
              f"на полосе день, Солнце {sun_altitude:.0f}° над горизонтом")


# ------------------------------------------------------------------ кометы


def check_comet(record, flags: list) -> None:
    payload = record.payload or {}

    q = payload.get("perihelion_distance_au")
    if q is None or not (0.0 < q < 100.0):
        _flag(flags, "REVIEW", "comet_elements",
              f"перигелийное расстояние {q!r} а.е. неправдоподобно")
    eccentricity = payload.get("eccentricity")
    if eccentricity is None or eccentricity < 0:
        _flag(flags, "REVIEW", "comet_elements",
              f"эксцентриситет {eccentricity!r} недопустим")
    inclination = payload.get("inclination_deg")
    if inclination is not None and not (0.0 <= inclination <= 180.0):
        _flag(flags, "REVIEW", "comet_elements",
              f"наклонение {inclination} вне 0…180°")

    if not payload.get("magnitude_model"):
        _flag(flags, "REVIEW", "comet_magnitude",
              "не указана модель, по которой получен блеск")
    if payload.get("magnitude_uncertainty") is None:
        _flag(flags, "REVIEW", "comet_magnitude",
              "оценка блеска дана без неопределённости — так её легко принять "
              "за измеренную величину")

    peak = payload.get("peak_magnitude")
    if peak is not None and not (-10.0 <= peak <= 30.0):
        _flag(flags, "WARN", "comet_magnitude",
              f"прогноз максимума {peak} вне разумных пределов")


# ------------------------------------------------------------------ транзиенты


def check_transient(record, flags: list) -> None:
    payload = record.payload or {}

    ra, dec = payload.get("ra"), payload.get("dec")
    if ra is None or not (0.0 <= ra < 360.0):
        _flag(flags, "REVIEW", "tns_coordinates", f"прямое восхождение {ra!r} вне 0…360°")
    if dec is None or not (-90.0 <= dec <= 90.0):
        _flag(flags, "REVIEW", "tns_coordinates", f"склонение {dec!r} вне −90…+90°")

    discovery = payload.get("discovery_date")
    if not discovery:
        _flag(flags, "WARN", "tns_time", "не указана дата открытия")
    else:
        try:
            stamp = dt.datetime.fromisoformat(discovery)
        except ValueError:
            _flag(flags, "REVIEW", "tns_time", f"дата открытия не разобрана: {discovery}")
        else:
            if stamp > dt.datetime.now(cfg.MSK) + dt.timedelta(days=1):
                _flag(flags, "REVIEW", "tns_time",
                      f"дата открытия в будущем: {discovery}")

    magnitude = payload.get("discovery_mag")
    if magnitude is None:
        _flag(flags, "WARN", "tns_magnitude", "не указан блеск при открытии")
    elif not (-5.0 <= magnitude <= 30.0):
        _flag(flags, "REVIEW", "tns_magnitude",
              f"блеск при открытии {magnitude} вне разумных пределов")

    if not payload.get("type"):
        _flag(flags, "WARN", "tns_classification",
              "классификация объекта ещё не опубликована")
    if not payload.get("source_id"):
        _flag(flags, "REVIEW", "tns_source", "нет идентификатора записи в источнике")


# ------------------------------------------------------------------ прогон


CHECKS = {"neo": check_neo, "occultation": check_occultation,
          "comet": check_comet, "transient": check_transient}


def check(record) -> list:
    """Проверки одной записи ленты. Возвращает список флагов."""
    flags: list = []
    check_provenance(record, flags)
    handler = CHECKS.get(record.kind)
    if handler is not None and record.semantic != "update":
        handler(record, flags)
    return flags


def run(records: list) -> dict:
    """Проверить всю ленту. Флаги кладутся в `record.state['qa']`."""
    review, warn = [], []
    for record in records:
        flags = check(record)
        record.state = dict(record.state or {})
        record.state["qa"] = flags
        levels = {flag.level for flag in flags}
        if "REVIEW" in levels:
            review.append(record)
        elif "WARN" in levels:
            warn.append(record)
    return {"total": len(records), "review": review, "warn": warn,
            "clean": len(records) - len(review) - len(warn)}


def qa_level(record) -> str:
    levels = {flag.level for flag in (record.state or {}).get("qa", [])}
    if "REVIEW" in levels:
        return "REVIEW"
    if "WARN" in levels:
        return "WARN"
    return "OK"
