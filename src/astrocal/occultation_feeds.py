"""Ленты предсказаний покрытий звёзд астероидами.

Своя астрометрия здесь неуместна: полоса такого покрытия бывает шириной в
десяток километров, и её положение определяется орбитой астероида с точностью
до десятков угловых миллисекунд. Это работа специализированных сервисов —
IOTA/OccultWatcher, Lucky Star. Мы берём у них **список кандидатов** (какой
астероид, какую звезду и примерно когда покрывает), а полосу пересчитываем сами
по актуальной орбите JPL и проверяем, проходит ли она через Россию.

Источник ленты — occelmnt-файлы Стива Престона на asteroidoccultation.com,
единственные публично скачиваемые машиночитаемые предсказания на год вперёд.
У них есть важная особенность: файл считается один раз (для 2026 года — в июне
2026 по орбитам конца 2024-го) и потом не обновляется. Для астероидов со слабой
астрометрией предсказание к моменту события успевает уехать на часы — именно
поэтому наш пересчёт по свежей орбите обязателен, а не факультативен.

OccultWatcher Cloud публикует уточнённые предсказания за ~60 суток до события,
но открытого API без авторизации у него нет: страницы отдаются как SPA.
Если у вас есть доступ, подключить его нужно первым приоритетом — структура
`Candidate` под это готова.
"""
from __future__ import annotations

import datetime as dt
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree

import requests

from . import config as cfg

BASE = "https://www.asteroidoccultation.com/{year}/"
IOTA_FILE = "{year}-iota.zip"
RAW_FILE = "{year}-raw-generic.zip"


@dataclass
class Candidate:
    """Кандидат в покрытие: что, кого и примерно когда."""
    asteroid_number: int
    asteroid_name: str
    asteroid_mag: float
    diameter_km: float
    distance_au: float
    star_id: str
    star_ra_deg: float          # J2000
    star_dec_deg: float         # J2000
    star_mag: float
    magnitude_drop: float
    max_duration_s: float
    predicted_utc: dt.datetime
    sigma_km: float
    feed: str
    orbit_solution: str
    provenance: dict = field(default_factory=dict)


def _download(year: int, name: str):
    path = cfg.CACHE / name.format(year=year).replace(f"{year}-", f"occ{year}-")
    if path.exists():
        return path
    url = BASE.format(year=year) + name.format(year=year)
    response = requests.get(url, timeout=600)
    response.raise_for_status()
    path.write_bytes(response.content)
    return path


def _float(value: str, default=float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_events(xml_bytes: bytes, feed: str) -> list[Candidate]:
    root = ElementTree.fromstring(xml_bytes.decode("utf-8", "replace"))
    out = []
    for node in root.findall("Event"):
        elements = (node.findtext("Elements") or "").split(",")
        star = (node.findtext("Star") or "").split(",")
        obj = (node.findtext("Object") or "").split(",")
        errors = (node.findtext("Errors") or "").split(",")
        if len(elements) < 5 or len(star) < 12 or len(obj) < 5:
            continue
        try:
            hour = float(elements[1])
            year, month, day = int(elements[2]), int(elements[3]), int(elements[4])
            when = (dt.datetime(year, month, day, tzinfo=dt.timezone.utc)
                    + dt.timedelta(hours=hour))
            number = int(obj[0])
        except (ValueError, IndexError):
            continue
        out.append(Candidate(
            asteroid_number=number,
            asteroid_name=obj[1].strip(),
            asteroid_mag=_float(obj[2]),
            diameter_km=_float(obj[3]),
            distance_au=_float(obj[4]),
            star_id=star[0].strip(),
            star_ra_deg=_float(star[1]) * 15.0,
            star_dec_deg=_float(star[2]),
            star_mag=_float(star[4]),
            magnitude_drop=_float(star[11]),
            max_duration_s=_float(obj[10] if len(obj) > 10 else "nan"),
            predicted_utc=when,
            sigma_km=_float(errors[3] if len(errors) > 3 else "nan"),
            feed=feed,
            orbit_solution=elements[0].strip(),
            provenance={"feed_file": feed, "elements": ",".join(elements[:5])},
        ))
    return out


def candidates(year: int, month: int, star_mag_limit: float = 7.0,
               use_raw: bool = True) -> list[Candidate]:
    """Кандидаты месяца ярче star_mag_limit.

    Отфильтрованный набор IOTA содержит лучшие по статистике события, но он
    неполон: покрытие HIP 20901 астероидом (14717) 29 августа 2026 в него не
    попало и нашлось только в «сыром» наборе. Поэтому по умолчанию читаем оба.
    """
    found: dict[tuple, Candidate] = {}

    iota_zip = _download(year, IOTA_FILE)
    with zipfile.ZipFile(iota_zip) as archive:
        for name in archive.namelist():
            for c in _parse_events(archive.read(name), f"IOTA {name}"):
                if c.predicted_utc.month == month and c.star_mag <= star_mag_limit:
                    found[(c.asteroid_number, c.star_id)] = c

    if use_raw:
        raw_zip = _download(year, RAW_FILE)
        with zipfile.ZipFile(raw_zip) as archive:
            name = f"{year}-{month:02d}.xml"
            if name in archive.namelist():
                for c in _parse_events(archive.read(name), f"raw {name}"):
                    key = (c.asteroid_number, c.star_id)
                    if c.star_mag <= star_mag_limit and key not in found:
                        found[key] = c

    return sorted(found.values(), key=lambda c: c.predicted_utc)
