"""Место наблюдения: точка на земле, с которой человек реально смотрит вверх."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass
class ObserverProfile:
    """Площадка наблюдения.

    `eye_height_m` — высота глаз над землёй. На небесные координаты она влияет
    пренебрежимо, но именно она задаёт, из какой точки видно поверх крыши и
    забора, поэтому хранится отдельно от высоты площадки над уровнем моря.
    """

    name: str = "Площадка"
    latitude: float = 55.7558
    longitude: float = 37.6173
    elevation_m: float = 150.0
    eye_height_m: float = 1.75
    timezone: str = "Europe/Moscow"
    bortle: int = 4
    is_demo: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        self.latitude = _clamp(float(self.latitude), -90.0, 90.0)
        self.longitude = ((float(self.longitude) + 180.0) % 360.0) - 180.0
        self.elevation_m = float(self.elevation_m)
        self.eye_height_m = max(0.0, float(self.eye_height_m))
        self.bortle = int(_clamp(int(self.bortle), 1, 9))

    # ------------------------------------------------------------ время

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    def now(self) -> dt.datetime:
        return dt.datetime.now(tz=self.tz)

    def localize(self, when: dt.datetime) -> dt.datetime:
        """Привести момент к местному поясу площадки (naive считается местным)."""
        if when.tzinfo is None:
            return when.replace(tzinfo=self.tz)
        return when.astimezone(self.tz)

    # ------------------------------------------------------------ Skyfield

    def topos(self):
        """Топоцентрический наблюдатель Skyfield для этой площадки."""
        from skyfield.api import wgs84

        from astrocal.core import planets
        return planets()["earth"] + wgs84.latlon(
            self.latitude, self.longitude, self.elevation_m + self.eye_height_m)

    # ------------------------------------------------------------ сериализация

    @property
    def key(self) -> str:
        slug = re.sub(r"[^\w]+", "-", self.name.lower(), flags=re.UNICODE)
        return slug.strip("-") or "site"

    def to_dict(self) -> dict:
        return {
            "name": self.name, "latitude": self.latitude,
            "longitude": self.longitude, "elevation_m": self.elevation_m,
            "eye_height_m": self.eye_height_m, "timezone": self.timezone,
            "bortle": self.bortle, "is_demo": self.is_demo, "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ObserverProfile":
        known = {f.name for f in field_names(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})

    def describe(self) -> str:
        lat = f"{abs(self.latitude):.4f}°{'N' if self.latitude >= 0 else 'S'}"
        lon = f"{abs(self.longitude):.4f}°{'E' if self.longitude >= 0 else 'W'}"
        return f"{self.name}: {lat} {lon}, {self.elevation_m:.0f} м, {self.timezone}"


def field_names(cls):
    from dataclasses import fields
    return fields(cls)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------- разбор ввода

_COORD = re.compile(
    r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*[,; ]\s*([-+]?\d+(?:[.,]\d+)?)\s*$")


def parse_latlon(text: str) -> tuple[float, float] | None:
    """Разобрать «55.7558, 37.6173» — то, что копируют из карт.

    Возвращает None, если строка не похожа на пару координат: молчаливая
    подстановка нулей увела бы наблюдателя в Гвинейский залив.
    """
    match = _COORD.match(text or "")
    if not match:
        return None
    try:
        lat = float(match.group(1).replace(",", "."))
        lon = float(match.group(2).replace(",", "."))
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


# ---------------------------------------------------------------- демо-площадка

def demo_observer() -> ObserverProfile:
    """Условная дача в Московской области.

    Координаты выдуманы и помечены DEMO: это не настоящий участок пользователя.
    """
    return ObserverProfile(
        name="DEMO — дача (Московская обл.)",
        latitude=55.9200, longitude=37.8200, elevation_m=170.0,
        eye_height_m=1.75, timezone="Europe/Moscow", bortle=4, is_demo=True,
        notes="Демонстрационная площадка. Замените на свои GPS-координаты.")
