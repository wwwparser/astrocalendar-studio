"""Наблюдатель за новыми кометами (Minor Planet Center).

Открытие кометы предсказать нельзя, поэтому в месячном календаре его быть не
может. Зато можно поймать момент, когда комета впервые появилась в списке
орбитальных элементов MPC, — и рассказать о ней в тот же день.

Ключевая тонкость — что считать открытием. Файл `CometEls.txt` содержит
тысячи объектов, из них подавляющее большинство известны десятилетиями.
«Новой» комета считается только тогда, когда её обозначения не было в
предыдущем снимке источника (см. `state.Snapshot`), а не тогда, когда она
впервые попала в наш локальный кэш.

Вторая тонкость — отбор по яркости. Отбрасывать комету потому, что сейчас она
+17-й величины, нельзя: как раз такие объекты за полгода до перигелия и
оказываются главным событием года. Поэтому считается не текущий блеск, а
прогноз до перигелия, и решение принимается по ожидаемому максимуму.

Блеск кометы — оценка, а не измерение. Формула MPC m = g + 5·lg Δ + k·lg r для
только что открытого объекта опирается на предварительные g и k и легко
ошибается на пару величин. Мы храним и модель, и её неопределённость, и не
выдаём результат за точное значение.
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from .. import config as cfg
from ..core import body, constellation_at, earth, timescale, to_msk, ts_range
from ..fmt import number, ru_constellation
from .model import KIND_COMET, DiscoveryEvent
from .state import Snapshot

SOURCE = "Minor Planet Center, CometEls.txt"
SNAPSHOT = "mpc_comets"

# Погрешность модели блеска для свежеоткрытой кометы: параметры g и k
# определяются по нескольким первым наблюдениям и потом заметно уточняются
MAGNITUDE_UNCERTAINTY = 2.0
MODEL = "m = g + 5·lg Δ + k·lg r (параметры g, k из MPC)"


def designation_key(designation: str) -> str:
    """Обозначение без имени первооткрывателя: «C/2026 X1»."""
    return designation.split("(")[0].strip().rstrip(")").strip()


def perihelion_date(row) -> dt.datetime | None:
    try:
        year = int(row["perihelion_year"])
        month = int(row["perihelion_month"])
        day = float(row["perihelion_day"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        base = dt.datetime(year, month, 1, tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return base + dt.timedelta(days=day - 1)


def current_designations(use_cache: bool = True) -> tuple[list[str], object, str]:
    """Обозначения всех комет из файла MPC плюс сама таблица элементов."""
    from io import BytesIO

    from skyfield.data import mpc

    from ..net import fetch

    response = fetch(mpc.COMET_URL, ttl_hours=0.0 if not use_cache else 24.0,
                     timeout=180.0, use_cache=True)
    frame = mpc.load_comets_dataframe(BytesIO(response.body.encode("utf-8")))
    keys = [designation_key(str(name)) for name in frame["designation"]]
    return keys, frame, response.fetched_at.isoformat()


# ------------------------------------------------------------------ обогащение


def forecast(row, horizon_days: float = 900.0, step_days: float = 5.0) -> dict:
    """Ход блеска и расстояний кометы от сегодняшнего дня до перигелия и после.

    Считается по элементам MPC на сетке в несколько суток: точнее не нужно,
    потому что сама модель блеска грубее любого шага.
    """
    from ..events.comets import _orbit, estimate_magnitude

    now = dt.datetime.now(dt.timezone.utc)
    perihelion = perihelion_date(row)
    end = now + dt.timedelta(days=horizon_days)
    if perihelion is not None:
        end = max(end, perihelion + dt.timedelta(days=180))
        end = min(end, now + dt.timedelta(days=1500))

    grid = ts_range(now, end, step_days * 24 * 60)
    comet = _orbit(row)
    astro = earth().at(grid).observe(comet)
    delta = astro.distance().au
    r = body("sun").at(grid).observe(comet).distance().au
    magnitude = np.asarray(estimate_magnitude(row, r, delta), dtype=float)

    finite = np.isfinite(magnitude)
    if not finite.any():
        return {"perihelion": perihelion, "current_magnitude": None,
                "peak_magnitude": None, "peak_when": None,
                "current_r_au": float(r[0]), "current_delta_au": float(delta[0]),
                "closest_delta_au": float(np.nanmin(delta)),
                "closest_when": to_msk(grid[int(np.nanargmin(delta))])}

    peak = int(np.nanargmin(np.where(finite, magnitude, np.inf)))
    closest = int(np.nanargmin(delta))
    return {
        "perihelion": perihelion,
        "current_magnitude": float(magnitude[0]),
        "peak_magnitude": float(magnitude[peak]),
        "peak_when": to_msk(grid[peak]),
        "current_r_au": float(r[0]),
        "current_delta_au": float(delta[0]),
        "closest_delta_au": float(delta[closest]),
        "closest_when": to_msk(grid[closest]),
        "perihelion_distance_au": float(row.get("perihelion_distance_au", np.nan)),
        "eccentricity": float(row.get("eccentricity", np.nan)),
        "inclination_deg": float(row.get("inclination_degrees", np.nan)),
        "magnitude_g": float(row.get("magnitude_g", np.nan)),
        "magnitude_k": float(row.get("magnitude_k", np.nan)),
    }


def constellation_now(row) -> tuple[str, float, float]:
    """Созвездие и текущие экваториальные координаты кометы."""
    from ..events.comets import _orbit

    t = timescale().from_datetime(dt.datetime.now(dt.timezone.utc))
    position = earth().at(t).observe(_orbit(row)).apparent()
    ra, dec, _distance = position.radec()
    return (ru_constellation(constellation_at()(position)),
            float(ra.degrees), float(dec.degrees))


def rank_of(data: dict) -> str:
    """Значимость открытия. Пороги — в `config`, не в коде правила."""
    peak = data.get("peak_magnitude")
    if peak is not None and peak <= cfg.COMET_DISCOVERY_MUST_MAG:
        return "must"
    if peak is not None and peak <= cfg.COMET_DISCOVERY_INTERESTING_MAG:
        return "interesting"
    closest = data.get("closest_delta_au")
    q = data.get("perihelion_distance_au")
    if closest is not None and closest <= cfg.COMET_DISCOVERY_CLOSE_EARTH_AU:
        return "interesting"
    if q is not None and np.isfinite(q) and q <= cfg.COMET_DISCOVERY_SMALL_Q_AU:
        return "interesting"
    return "optional"


def observability(row, when: dt.datetime, cities=None) -> dict:
    """Наблюдаемость кометы из городов на момент ожидаемого максимума."""
    from ..cities import all_cities
    from ..events.comets import _orbit
    from ..observing import circumstances

    best = None
    for city in (cities or all_cities()):
        try:
            result = circumstances(_orbit(row), city, when)
        except Exception:                       # noqa: BLE001 — один город не критичен
            continue
        if result.visible and (best is None or result.score > best.score):
            best = result
    if best is None:
        return {"visible": False,
                "note": "из выбранных городов комета не наблюдается"}
    return {"visible": True, "city": best.city.name, "stars": best.stars,
            "score": best.score, "best_time": best.best_time,
            "altitude_deg": best.altitude_deg, "direction": best.direction,
            "window_start": best.window_start, "window_end": best.window_end,
            "instrument": best.instrument_ru, "note": best.note}


def _magnitude_text(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "оценка недоступна"
    return f"~{number(value, 1, sign=True)}m"


def describe(designation: str, row, data: dict, sky: dict,
             source_updated_at: str) -> DiscoveryEvent:
    """Собрать карточку открытия."""
    name = str(row["designation"]).strip()
    lines = [f"Обозначение: {name}"]
    if data.get("perihelion"):
        lines.append(f"Перигелий: {data['perihelion'].astimezone(cfg.MSK):%d.%m.%Y}"
                     + (f", q = {data['perihelion_distance_au']:.3f} а.е."
                        if np.isfinite(data.get("perihelion_distance_au", np.nan))
                        else ""))
    lines.append(f"Сейчас: {_magnitude_text(data.get('current_magnitude'))}, "
                 f"r = {data['current_r_au']:.2f} а.е., "
                 f"Δ = {data['current_delta_au']:.2f} а.е.")
    if data.get("peak_magnitude") is not None:
        lines.append(f"Ожидаемый максимум: "
                     f"{_magnitude_text(data['peak_magnitude'])} "
                     f"около {data['peak_when']:%d.%m.%Y} "
                     f"(±{MAGNITUDE_UNCERTAINTY:.0f}m, модель MPC)")
    lines.append(f"Минимальное расстояние от Земли: "
                 f"{data['closest_delta_au']:.2f} а.е. "
                 f"({data['closest_when']:%d.%m.%Y})")
    if data.get("constellation"):
        lines.append(f"Созвездие: {data['constellation']}")
    if sky.get("visible"):
        lines.append(f"Лучшее окно: {sky['window_start']:%d.%m %H:%M}–"
                     f"{sky['window_end']:%H:%M} МСК из города {sky['city']}, "
                     f"высота {sky['altitude_deg']:.0f}° ({sky['direction']})")
        lines.append(f"Инструмент: {sky['instrument']}")
    else:
        lines.append(f"Наблюдаемость: {sky.get('note', 'не определена')}")

    peak = data.get("peak_magnitude")
    summary = (f"Открыта комета {name}"
               + (f", ожидаемый максимум блеска {_magnitude_text(peak)} "
                  f"около {data['peak_when']:%d.%m.%Y}" if peak is not None else ""))

    rank = rank_of(data)
    payload = {
        "designation": designation, "full_designation": name,
        "perihelion": (data["perihelion"].isoformat()
                       if data.get("perihelion") else None),
        "perihelion_distance_au": data.get("perihelion_distance_au"),
        "eccentricity": data.get("eccentricity"),
        "inclination_deg": data.get("inclination_deg"),
        "current_magnitude": data.get("current_magnitude"),
        "peak_magnitude": peak,
        "peak_when": (data["peak_when"].isoformat()
                      if data.get("peak_when") else None),
        "current_r_au": data.get("current_r_au"),
        "current_delta_au": data.get("current_delta_au"),
        "closest_delta_au": data.get("closest_delta_au"),
        "magnitude_model": MODEL,
        "magnitude_uncertainty": MAGNITUDE_UNCERTAINTY,
        "constellation": data.get("constellation"),
        "ra": data.get("ra"), "dec": data.get("dec"),
    }
    return DiscoveryEvent(
        live_id=f"comet:{designation}",
        kind=KIND_COMET,
        title=f"Новая комета {name}",
        summary=summary,
        lines=lines,
        discovered_at=dt.datetime.now(cfg.MSK),
        magnitude=data.get("current_magnitude"),
        rank=rank,
        stars=sky.get("stars", 0),
        payload=payload,
        sources=[SOURCE],
        provenance={"source": SOURCE, "source_updated_at": source_updated_at,
                    "magnitude_model": MODEL,
                    "magnitude_uncertainty": MAGNITUDE_UNCERTAINTY,
                    "elements_epoch": str(row.get("epoch_year", ""))},
        observability=sky,
    )


# ------------------------------------------------------------------ прогон


def check(directory=None, cities=None, use_cache: bool = True,
          progress=None) -> tuple[list[DiscoveryEvent], dict]:
    """Сравнить текущий список комет MPC со снимком и описать новые.

    Возвращает найденные открытия и сводку по источнику.
    """
    if progress:
        progress("Элементы комет MPC", 10)
    keys, frame, updated_at = current_designations(use_cache)
    snapshot = Snapshot(SNAPSHOT, directory)
    first_run = snapshot.first_run
    new_keys = snapshot.difference(keys)

    discoveries: list[DiscoveryEvent] = []
    errors: list[str] = []
    for index, key in enumerate(new_keys):
        if progress:
            progress(f"Новая комета {key}",
                     20 + int(70 * index / max(1, len(new_keys))))
        matches = [row for _, row in frame.iterrows()
                   if designation_key(str(row["designation"])) == key]
        if not matches:
            continue
        row = matches[0]
        try:
            data = forecast(row)
            (data["constellation"], data["ra"],
             data["dec"]) = constellation_now(row)
            when = data.get("peak_when") or dt.datetime.now(cfg.MSK)
            sky = observability(row, when, cities)
            discoveries.append(describe(key, row, data, sky, updated_at))
        except Exception as error:              # noqa: BLE001
            errors.append(f"{key}: {error}")

    snapshot.update(keys)
    summary = {"source": SOURCE, "total": len(keys), "new": len(new_keys),
               "first_run": first_run, "errors": errors,
               "source_updated_at": updated_at}
    if first_run:
        summary["note"] = ("сформирован базовый снимок источника: "
                           f"{len(keys)} комет, открытиями они не считаются")
    return discoveries, summary
