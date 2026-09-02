"""Города наблюдения: обстоятельства события «на местности».

Одно и то же явление выглядит по-разному из Калининграда и из Владивостока —
где-то оно на тёмном небе высоко над горизонтом, где-то днём под горизонтом.
Календарь на всю страну обязан это различать, поэтому обстоятельства считаются
для набора опорных городов, а не для одной точки.

Пользовательские города добавляются в `data/cities.json` и подхватываются
автоматически.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from functools import lru_cache

from . import config as cfg


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    timezone: str
    elevation_m: float = 0.0

    @property
    def key(self) -> str:
        return self.name.lower().replace(" ", "-").replace("ё", "е")


DEFAULT_CITIES = [
    City("Москва", 55.7558, 37.6173, "Europe/Moscow", 156),
    City("Санкт-Петербург", 59.9386, 30.3141, "Europe/Moscow", 3),
    City("Калининград", 54.7104, 20.4522, "Europe/Kaliningrad", 20),
    City("Краснодар", 45.0355, 38.9753, "Europe/Moscow", 25),
    City("Екатеринбург", 56.8389, 60.6057, "Asia/Yekaterinburg", 255),
    City("Новосибирск", 55.0084, 82.9357, "Asia/Novosibirsk", 150),
    City("Владивосток", 43.1155, 131.8855, "Asia/Vladivostok", 30),
]

USER_CITIES_FILE = cfg.DATA / "cities.json"


@lru_cache(maxsize=1)
def all_cities() -> tuple[City, ...]:
    """Опорные города плюс пользовательские из data/cities.json."""
    cities = list(DEFAULT_CITIES)
    if USER_CITIES_FILE.exists():
        try:
            payload = json.loads(USER_CITIES_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return tuple(cities)
        known = {c.key for c in cities}
        for record in payload.get("cities", []):
            try:
                city = City(record["name"], float(record["lat"]), float(record["lon"]),
                            record.get("timezone", "Europe/Moscow"),
                            float(record.get("elevation_m", 0.0)))
            except (KeyError, TypeError, ValueError):
                continue
            if city.key not in known:
                cities.append(city)
                known.add(city.key)
    return tuple(cities)


def by_key(key: str) -> City | None:
    for city in all_cities():
        if city.key == key:
            return city
    return None


def save_user_cities(cities: list[City]) -> None:
    """Сохранить пользовательские города (стандартные не дублируются)."""
    default_keys = {c.key for c in DEFAULT_CITIES}
    extra = [asdict(c) for c in cities if c.key not in default_keys]
    USER_CITIES_FILE.write_text(
        json.dumps({"cities": extra}, ensure_ascii=False, indent=2), encoding="utf-8")
    all_cities.cache_clear()


def topos(city: City):
    """Skyfield-наблюдатель для города."""
    from skyfield.api import wgs84

    from .core import planets
    return planets()["earth"] + wgs84.latlon(city.lat, city.lon, city.elevation_m)
