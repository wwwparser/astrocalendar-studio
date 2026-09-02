"""Слежение за покрытиями звёзд астероидами.

У этого класса событий есть свойство, которого нет у затмений и соединений:
прогноз стареет. Годовой файл предсказаний считается один раз по орбитам
позапрошлого года, а орбита астероида уточняется каждым новым наблюдением.
Для объекта со слабой астрометрией полоса за полгода уезжает на сотни
километров, а момент — на часы. Опубликовать такой прогноз как окончательный
значит отправить наблюдателей не в ту ночь и не в тот регион.

Поэтому здесь две задачи.

**Свежесть.** У каждого события известны возраст предсказания и возраст
решения орбиты. Если прогноз стар, а событие уже близко, запись помечается как
требующая пересчёта.

**Сдвиг полосы.** Центральная линия при каждом пересчёте сравнивается с
сохранённой. Если она сдвинулась больше порога (по умолчанию 20 км), в ленту
попадает `LiveUpdate` с прежней и новой полосой и величиной сдвига. При этом
редакторский текст события в выпуске не трогается: меняются расчётные данные,
а не формулировка человека.
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from .. import config as cfg
from ..events import asteroid_occultations as occ
from ..fmt import number
from ..geo import path_shift_km
from .model import KIND_OCCULTATION, LiveUpdate, ScheduledEvent

SOURCE = "IOTA / asteroidoccultation.com + JPL Horizons"
PATH_SAMPLE = "central_path_sample"
SAMPLE_POINTS = 9


def sample_path(path: list, points: int = SAMPLE_POINTS) -> list[dict]:
    """Сжатая центральная линия для хранения между запусками.

    Полная полоса — это сотни точек, и держать её в файле состояния незачем:
    для оценки сдвига хватает девяти опорных точек.
    """
    if not path:
        return []
    step = max(1, len(path) // points)
    return [{"lat": round(p["lat"], 3), "lon": round(p["lon"], 3),
             "utc": p["utc"].isoformat()} for p in path[::step]][:points]


def _restore(sample: list) -> list[dict]:
    restored = []
    for point in sample or []:
        try:
            restored.append({"lat": float(point["lat"]), "lon": float(point["lon"]),
                             "utc": dt.datetime.fromisoformat(point["utc"])})
        except (KeyError, TypeError, ValueError):
            continue
    return restored


def describe(record: occ.Occultation, analysis: dict | None = None) -> ScheduledEvent:
    """Карточка покрытия для живой ленты."""
    star = f"{record.star_name or record.star_id}"
    lines = [
        f"({record.asteroid_number}) {record.asteroid_name} покрывает {star}",
        f"Звезда: {number(record.star_mag, 1, sign=True)}m",
    ]
    if np.isfinite(record.magnitude_drop):
        lines.append(f"Падение блеска: {number(record.magnitude_drop)}m")
    if np.isfinite(record.duration_sec):
        lines.append(f"Макс. длительность: {number(record.duration_sec)} с")
    if record.path_width_km:
        lines.append(f"Ширина полосы: {record.path_width_km:.0f} км")
    if record.regions:
        lines.append("Полоса: " + " → ".join(record.regions[:4]))
    if record.star_altitude_deg is not None:
        lines.append(f"Высота звезды: {record.star_altitude_deg:.0f}°")
    if record.sun_altitude_deg is not None:
        lines.append(f"Солнце: {record.sun_altitude_deg:.0f}° ({record.sky_state})")
    if np.isfinite(record.uncertainty_km):
        lines.append(f"Неопределённость полосы: ±{record.uncertainty_km:.0f} км")
    if record.freshness_note:
        lines.append(record.freshness_note)

    inside = [item["city"] for item in record.cities_visible if item["inside"]]
    if inside:
        lines.append("Города в полосе: " + ", ".join(inside))

    payload = {
        "asteroid_number": record.asteroid_number,
        "asteroid_name": record.asteroid_name,
        "star_id": record.star_id,
        "star_name": record.star_name,
        "star_ra_dec": [record.star_ra_deg, record.star_dec_deg],
        "star_mag": record.star_mag,
        "asteroid_mag": record.asteroid_mag,
        "magnitude_drop": _finite(record.magnitude_drop),
        "event_utc": record.event_utc.isoformat(),
        "event_local": record.event_local.isoformat(),
        "duration_sec": _finite(record.duration_sec),
        "asteroid_diameter_km": _finite(record.asteroid_diameter_km),
        "path_width_km": _finite(record.path_width_km),
        "prediction_epoch": (record.prediction_epoch.isoformat()
                             if record.prediction_epoch else None),
        "orbit_epoch": record.orbit_epoch,
        "orbit_solution": record.orbit_solution,
        "uncertainty_km": _finite(record.uncertainty_km),
        "regions": record.regions,
        "cities_visible": inside,
        "sun_altitude_deg": record.sun_altitude_deg,
        "star_altitude_deg": record.star_altitude_deg,
        "sky_state": record.sky_state,
        PATH_SAMPLE: sample_path(record.central_path),
    }
    return ScheduledEvent(
        live_id=record.event_id,
        kind=KIND_OCCULTATION,
        title=(f"({record.asteroid_number}) {record.asteroid_name} покрывает "
               f"{star}"),
        summary=(f"Астероид ({record.asteroid_number}) {record.asteroid_name} "
                 f"покрывает звезду {star}, полоса проходит через "
                 + ", ".join(record.regions[:3])),
        lines=lines,
        when=record.event_local,
        magnitude=record.star_mag,
        rank=("interesting" if record.regions and record.confidence != "низкая"
              else "optional"),
        stars=record.stars,
        payload=payload,
        sources=[record.source, "JPL Horizons (актуальная орбита)"],
        provenance={"source": record.source,
                    "source_updated_at": record.source_updated_at,
                    "orbit_epoch": record.orbit_epoch,
                    "orbit_solution": record.orbit_solution,
                    "prediction_age_days": record.prediction_age_days,
                    "orbit_age_days": record.orbit_age_days},
        retain=(PATH_SAMPLE,),
        # полная полоса нужна для карты и в отпечаток не входит
        extra={"analysis": analysis} if analysis else {},
    )


def _finite(value) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None


def shift_update(record: ScheduledEvent,
                 threshold_km: float | None = None) -> LiveUpdate | None:
    """Сообщение о сдвиге полосы, если он существенный.

    Сравнивается прежняя сохранённая центральная линия с новой. Порог берётся
    из конфигурации: сдвиг в пару километров — это шум пересчёта, сдвиг в
    десятки километров означает, что регион наблюдения изменился.
    """
    limit = cfg.OCC_PATH_SHIFT_ALERT_KM if threshold_km is None else threshold_km
    previous = _restore(record.previous.get(PATH_SAMPLE))
    current = _restore(record.payload.get(PATH_SAMPLE))
    if not previous or not current:
        return None
    shift = path_shift_km(previous, current)
    if shift is None or shift < limit:
        return None

    def corner(points: list[dict]) -> str:
        first, last = points[0], points[-1]
        return (f"{first['lat']:.1f}°, {first['lon']:.1f}° → "
                f"{last['lat']:.1f}°, {last['lon']:.1f}°")

    return LiveUpdate(
        live_id=f"{record.live_id}:shift",
        kind=KIND_OCCULTATION,
        title=f"Полоса покрытия сдвинулась на {shift:.0f} км",
        summary=(f"{record.title}: полоса покрытия сдвинулась на {shift:.0f} км "
                 f"относительно прошлого расчёта"),
        lines=[f"Предыдущая полоса: {corner(previous)}",
               f"Новая полоса: {corner(current)}",
               f"Сдвиг: {shift:.0f} км",
               "Редакторский текст события не изменён — обновились только "
               "расчётные данные"],
        when=record.when,
        rank="interesting",
        payload={"target": record.live_id, "shift_km": round(shift, 1),
                 "previous": record.previous.get(PATH_SAMPLE),
                 "current": record.payload.get(PATH_SAMPLE)},
        sources=record.sources,
        provenance=dict(record.provenance),
        target_id=record.live_id,
        changes=[f"центральная линия сдвинулась на {shift:.0f} км"],
    )


# ------------------------------------------------------------------ прогон


def check(days: float = 45.0, cities=None, star_mag_limit: float | None = None,
          only_russia: bool = True, max_candidates: int = 40, progress=None,
          state=None) -> tuple[list, dict]:
    """Покрытия ближайших `days` суток, пересчитанные по свежей орбите.

    Пересчёт одного кандидата — это два обращения к Horizons, и лента за месяц
    вперёд содержит сотни кандидатов: считать все означало бы держать редактора
    у прогресс-бара десятки минут. Поэтому берутся самые яркие звёзды —
    именно они и интересны наблюдателю, — а число разбираемых кандидатов
    ограничено `max_candidates`. Сколько осталось за границей, видно в сводке.
    """
    if progress:
        progress("Покрытия звёзд астероидами", 5)
    now = dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(days=days)
    limit = cfg.OCC_STAR_MAG_LIMIT if star_mag_limit is None else star_mag_limit

    months = {(now.year, now.month), (horizon.year, horizon.month)}
    candidates = []
    errors: list[str] = []
    try:
        from ..occultation_feeds import candidates as feed_candidates
        for year, month in sorted(months):
            candidates += [c for c in feed_candidates(year, month, limit)
                           if now <= c.predicted_utc <= horizon]
    except Exception as error:                   # noqa: BLE001
        return [], {"source": SOURCE, "status": "недоступен", "error": str(error),
                    "new": 0, "total": 0}

    # звёзды поярче — вперёд: их покрытия и заметнее, и надёжнее предсказаны
    candidates.sort(key=lambda c: (c.star_mag, c.predicted_utc))
    total = len(candidates)
    skipped = max(0, total - max_candidates)
    candidates = candidates[:max_candidates]

    records: list = []
    for index, candidate in enumerate(candidates):
        if progress:
            progress(f"Пересчёт полосы ({candidate.asteroid_number})",
                     10 + int(80 * index / max(1, len(candidates))))
        if not occ.star_above_russia(candidate.predicted_utc,
                                     candidate.star_ra_deg, candidate.star_dec_deg):
            continue
        try:
            result = occ.analyse(candidate)
        except Exception as error:               # noqa: BLE001
            errors.append(f"({candidate.asteroid_number}): {error}")
            continue
        if not result or not result.get("path"):
            continue
        if only_russia and not result.get("regions"):
            continue
        record = occ.record_for(candidate, result, cities)
        entry = describe(record, result)
        if state is not None:
            # прежняя полоса нужна до обновления состояния, поэтому здесь
            # только чтение: запись состояния делает вызывающий слой
            state.prepare(entry)
            update = shift_update(entry)
            if update is not None:
                records.append(update)
        records.append(entry)

    summary = {"source": SOURCE, "status": "ок", "total": total,
               "analysed": len(candidates), "new": len(records),
               "errors": errors}
    if skipped:
        summary["note"] = (f"разобрано {len(candidates)} кандидатов из {total}: "
                           f"остальные — покрытия более слабых звёзд")
    return records, summary
