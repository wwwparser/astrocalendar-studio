"""Наблюдатель за новыми и сверхновыми (Transient Name Server).

Сверхновая, вспыхнувшая 12 сентября, не могла попасть в календарь, свёрстанный
первого числа, — это событие открытия, и живёт оно только в Live.

TNS регистрирует тысячи объектов в год, и почти все они интересны
исключительно профессионалам: +19-я величина в далёкой галактике. Поэтому
поток фильтруется по блеску и по наличию классификации, а сырой список всегда
доступен отдельно — фильтр скрывает записи, но не выбрасывает их.

Что TNS даёт и что считаем мы. Источник отдаёт имя, координаты, дату
открытия, блеск, фильтр, тип, галактику-хозяина и красное смещение. Созвездие,
высота над горизонтом, доступность из России, лучшее время, помеха от Луны и
инструмент — наш расчёт по этим координатам; мы не выдумываем ничего, чего нет
в данных.
"""
from __future__ import annotations

import datetime as dt

from .. import config as cfg
from ..core import constellation_at, earth, timescale
from ..fmt import number, ru_constellation
from ..secrets import MissingCredentials
from .model import KIND_TRANSIENT, DiscoveryEvent
from .state import Snapshot

SOURCE = "Transient Name Server (TNS)"
SNAPSHOT = "tns_transients"

TYPE_NOVA = "nova"
TYPE_SUPERNOVA = "supernova"
TYPE_OTHER = "other"

TYPE_TITLES = {TYPE_NOVA: "Новая звезда", TYPE_SUPERNOVA: "Сверхновая",
               TYPE_OTHER: "Транзиент"}


def classify_type(record: dict) -> str:
    """Новая, сверхновая или прочий транзиент."""
    raw = record.get("object_type")
    name = ""
    if isinstance(raw, dict):
        name = str(raw.get("name") or "")
    elif raw:
        name = str(raw)
    lowered = name.strip().lower()
    if not lowered:
        return TYPE_OTHER
    if lowered.startswith("nova") or "classical nova" in lowered:
        return TYPE_NOVA
    if lowered.startswith("sn") or "supernova" in lowered:
        return TYPE_SUPERNOVA
    return TYPE_OTHER


def brightness_stars(magnitude: float | None) -> int:
    """Рейтинг по блеску: шкала из спецификации, а не оценка «на глаз»."""
    if magnitude is None:
        return 1
    limits = cfg.TRANSIENT_STAR_LIMITS
    for index, limit in enumerate(limits):
        if magnitude <= limit:
            return 5 - index
    return 1


def rank_of(magnitude: float | None, kind: str) -> str:
    if magnitude is None:
        return "technical"
    if magnitude <= cfg.TRANSIENT_MUST_MAG:
        return "must"
    if magnitude <= cfg.TRANSIENT_MAG_LIMIT:
        return "interesting"
    if kind == TYPE_OTHER:
        return "technical"
    return "optional"


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _group(record: dict, key: str) -> str:
    raw = record.get(key)
    if isinstance(raw, dict):
        return str(raw.get("group_name") or raw.get("name") or "")
    return str(raw or "")


def _discovery_date(record: dict) -> dt.datetime | None:
    raw = record.get("discoverydate") or record.get("discovery_date")
    if not raw:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(str(raw), pattern).replace(
                tzinfo=dt.timezone.utc).astimezone(cfg.MSK)
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ обогащение


def constellation_of(ra_deg: float, dec_deg: float) -> str:
    from skyfield.api import Star

    t = timescale().from_datetime(dt.datetime.now(dt.timezone.utc))
    star = Star(ra_hours=ra_deg / 15.0, dec_degrees=dec_deg)
    return ru_constellation(constellation_at()(earth().at(t).observe(star).apparent()))


def observability(ra_deg: float, dec_deg: float, magnitude: float | None,
                  when: dt.datetime | None = None, cities=None) -> dict:
    """Где, когда и чем смотреть объект с этими координатами."""
    from skyfield.api import Star

    from ..cities import all_cities
    from ..observing import circumstances

    star = Star(ra_hours=ra_deg / 15.0, dec_degrees=dec_deg)
    moment = when or dt.datetime.now(cfg.MSK)
    # Смотреть транзиент будут ближайшей ночью, а не в момент открытия
    tonight = moment.replace(hour=23, minute=0, second=0, microsecond=0)
    if tonight < dt.datetime.now(cfg.MSK):
        tonight += dt.timedelta(days=1)

    best = None
    for city in (cities or all_cities()):
        try:
            result = circumstances(star, city, tonight, magnitude)
        except Exception:                        # noqa: BLE001
            continue
        if result.visible and (best is None or result.score > best.score):
            best = result
    if best is None:
        return {"visible": False, "note": "из выбранных городов объект не виден"}
    return {"visible": True, "city": best.city.name, "score": best.score,
            "stars": best.stars, "best_time": best.best_time,
            "altitude_deg": best.altitude_deg, "azimuth_deg": best.azimuth_deg,
            "direction": best.direction,
            "sun_altitude_deg": best.sun_altitude_deg,
            "moon_altitude_deg": best.moon_altitude_deg,
            "moon_separation_deg": best.moon_separation_deg,
            "window_start": best.window_start, "window_end": best.window_end,
            "instrument": best.instrument_ru, "note": best.note}


def describe(record: dict, source_updated_at: str,
             cities=None) -> DiscoveryEvent | None:
    """Собрать карточку открытия по карточке TNS."""
    from ..tns import name_of

    ra = _float(record.get("radeg"))
    dec = _float(record.get("decdeg"))
    if ra is None or dec is None:
        return None

    name = name_of(record)
    kind = classify_type(record)
    magnitude = _float(record.get("discoverymag"))
    discovered = _discovery_date(record)
    filter_name = ""
    if isinstance(record.get("discmagfilter"), dict):
        filter_name = str(record["discmagfilter"].get("name") or "")

    constellation = constellation_of(ra, dec)
    sky = observability(ra, dec, magnitude, discovered, cities)

    type_raw = record.get("object_type")
    type_name = (type_raw.get("name") if isinstance(type_raw, dict) else type_raw) or ""
    redshift = _float(record.get("redshift"))
    host = str(record.get("hostname") or "")

    lines = [f"Тип: {type_name or 'классификация не опубликована'}"]
    if discovered:
        lines.append(f"Открыт: {discovered:%d.%m.%Y %H:%M} МСК")
    if magnitude is not None:
        lines.append(f"Блеск при открытии: {number(magnitude, 1, sign=True)}m"
                     + (f" ({filter_name})" if filter_name else ""))
    if host:
        lines.append(f"Галактика: {host}"
                     + (f", z = {redshift:.4f}" if redshift is not None else ""))
    lines.append(f"Созвездие: {constellation}")
    discovery_group = _group(record, "discovery_data_source")
    reporting_group = _group(record, "reporting_group")
    if discovery_group or reporting_group:
        lines.append("Открытие: " + (discovery_group or reporting_group))
    if sky.get("visible"):
        lines.append(f"Лучшее время: {sky['best_time']:%d.%m %H:%M} МСК из города "
                     f"{sky['city']}, высота {sky['altitude_deg']:.0f}° "
                     f"({sky['direction']})")
        lines.append(f"Окно: {sky['window_start']:%H:%M}–{sky['window_end']:%H:%M}, "
                     f"инструмент: {sky['instrument']}")
        lines.append(f"Помехи: {sky['note']}")
    else:
        lines.append(f"Наблюдаемость: {sky.get('note', 'не определена')}")

    magnitude_text = (f"{number(magnitude, 1, sign=True)}m"
                      if magnitude is not None else "блеск не указан")
    summary = (f"{TYPE_TITLES.get(kind, 'Транзиент')} {name} "
               f"в созвездии {constellation}, {magnitude_text}")

    payload = {
        "name": name,
        "objname": str(record.get("objname") or ""),
        "internal_name": str(record.get("internal_names") or
                             record.get("internal_name") or ""),
        "ra": ra, "dec": dec,
        "discovery_date": discovered.isoformat() if discovered else None,
        "discovery_mag": magnitude,
        "filter": filter_name,
        "type": type_name,
        "type_group": kind,
        "host_name": host,
        "redshift": redshift,
        "discovery_group": discovery_group,
        "reporting_group": reporting_group,
        "constellation": constellation,
        "source_id": str(record.get("objid") or record.get("objname") or ""),
        "source_url": f"https://www.wis-tns.org/object/{record.get('objname', '')}",
    }
    return DiscoveryEvent(
        live_id=f"tns:{str(record.get('objname') or name).strip().replace(' ', '')}",
        kind=KIND_TRANSIENT,
        title=f"{TYPE_TITLES.get(kind, 'Транзиент')} {name}",
        summary=summary,
        lines=lines,
        discovered_at=discovered or dt.datetime.now(cfg.MSK),
        magnitude=magnitude,
        rank=rank_of(magnitude, kind),
        stars=brightness_stars(magnitude),
        payload=payload,
        sources=[SOURCE, payload["source_url"]],
        provenance={"source": SOURCE, "source_updated_at": source_updated_at,
                    "source_id": payload["source_id"],
                    "classification": type_name or "не опубликована"},
        observability=sky,
    )


# ------------------------------------------------------------------ фильтры


def passes(record: DiscoveryEvent, *, novae: bool = True, supernovae: bool = True,
           confirmed_only: bool | None = None,
           magnitude_limit: float | None = None,
           only_visible: bool = True, only_at_night: bool = True) -> bool:
    """Показывать ли запись в основной ленте. «Показать все» обходит фильтр."""
    payload = record.payload
    kind = payload.get("type_group")
    if kind == TYPE_NOVA and not novae:
        return False
    if kind == TYPE_SUPERNOVA and not supernovae:
        return False
    if kind == TYPE_OTHER:
        # неклассифицированные объекты автоматически не публикуются
        return False

    confirmed = cfg.TRANSIENT_CONFIRMED_ONLY if confirmed_only is None \
        else confirmed_only
    if confirmed and not payload.get("type"):
        return False

    limit = cfg.TRANSIENT_MAG_LIMIT if magnitude_limit is None else magnitude_limit
    magnitude = payload.get("discovery_mag")
    if magnitude is None or magnitude > limit:
        return False

    if only_visible and not record.observability.get("visible"):
        return False
    if only_at_night and record.observability.get("visible"):
        sun = record.observability.get("sun_altitude_deg")
        if sun is not None and sun > -6.0:
            return False
    return True


# ------------------------------------------------------------------ прогон


def check(directory=None, cities=None, use_cache: bool = True,
          limit: int = 60, progress=None) -> tuple[list[DiscoveryEvent], dict]:
    """Опросить TNS и описать объекты, которых не было в прошлом снимке."""
    from .. import tns

    if progress:
        progress("Transient Name Server", 10)
    snapshot = Snapshot(SNAPSHOT, directory)
    first_run = snapshot.first_run

    try:
        since = None
        if snapshot.updated_at:
            try:
                since = dt.datetime.fromisoformat(snapshot.updated_at) \
                    - dt.timedelta(days=1)
            except ValueError:
                since = None
        records, updated_at = tns.search(since=since, limit=limit,
                                         use_cache=use_cache)
    except MissingCredentials as error:
        return [], {"source": SOURCE, "status": "нет ключей", "error": str(error),
                    "new": 0, "total": 0, "first_run": first_run}
    except Exception as error:                   # noqa: BLE001 — источник недоступен
        return [], {"source": SOURCE, "status": "недоступен", "error": str(error),
                    "new": 0, "total": 0, "first_run": first_run}

    keys = [str(item.get("objname") or "").strip()
            for item in records if item.get("objname")]
    known = set(snapshot.keys)
    new_keys = [key for key in keys if key not in known] if not first_run else []

    discoveries: list[DiscoveryEvent] = []
    errors: list[str] = []
    for index, key in enumerate(new_keys):
        if progress:
            progress(f"Транзиент {key}",
                     20 + int(70 * index / max(1, len(new_keys))))
        try:
            record = tns.details(key, use_cache=use_cache)
            if not record:
                continue
            entry = describe(record, updated_at, cities)
            if entry is not None:
                discoveries.append(entry)
        except Exception as error:               # noqa: BLE001
            errors.append(f"{key}: {error}")

    # снимок пополняем, а не заменяем: инкрементальный запрос отдаёт только
    # свежие объекты, и заменой мы бы «забыли» всё, что видели раньше
    snapshot.update(known | set(keys))
    summary = {"source": SOURCE, "status": "ок", "total": len(keys),
               "new": len(new_keys), "first_run": first_run, "errors": errors,
               "source_updated_at": updated_at}
    if first_run:
        summary["note"] = (f"сформирован базовый снимок TNS: {len(keys)} объектов, "
                           f"открытиями они не считаются")
    return discoveries, summary
