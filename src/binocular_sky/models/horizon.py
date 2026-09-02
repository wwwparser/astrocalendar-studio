"""Маска местного горизонта: минимальная высота, с которой объект виден.

Математический горизонт — идеальная плоскость. Реальный участок так не устроен:
на юго-западе крыша поднимает горизонт до 19°, на востоке берёза до 27°, а на
открытом западе остаётся полтора градуса. Эта разница и решает, увидит человек
объект или простоит полчаса, глядя в стену.

Профиль хранится как значения на равномерной сетке азимутов и интерполируется
по кругу: 359.7° и 0.3° — соседи, а не края таблицы.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

GRID_STEP_DEG = 0.5


@dataclass
class HorizonProfile:
    """Азимут → минимальная видимая высота, градусы."""

    altitudes: np.ndarray          # значения на сетке 0..360 с шагом step_deg
    step_deg: float = GRID_STEP_DEG

    @property
    def azimuths(self) -> np.ndarray:
        return np.arange(len(self.altitudes)) * self.step_deg

    def altitude_at(self, azimuth_deg):
        """Высота горизонта на данном азимуте. Линейная интерполяция по кругу."""
        values = np.asarray(self.altitudes, dtype=float)
        position = (np.asarray(azimuth_deg, dtype=float) % 360.0) / self.step_deg
        low = np.floor(position).astype(int) % len(values)
        high = (low + 1) % len(values)
        weight = position - np.floor(position)
        result = values[low] * (1.0 - weight) + values[high] * weight
        return float(result) if np.isscalar(azimuth_deg) or result.ndim == 0 else result

    def is_visible(self, azimuth_deg, altitude_deg):
        """Виден ли объект: выше маски на своём азимуте."""
        return np.asarray(altitude_deg, dtype=float) > self.altitude_at(azimuth_deg)

    def clearance(self, azimuth_deg, altitude_deg):
        """Запас по высоте над препятствием; отрицательный — объект закрыт."""
        return np.asarray(altitude_deg, dtype=float) - self.altitude_at(azimuth_deg)

    def to_list(self) -> list[list[float]]:
        """[[азимут, высота], ...] — то, что уходит в 3D-сцену."""
        return [[float(a), float(h)]
                for a, h in zip(self.azimuths, self.altitudes)]

    @property
    def max_altitude_deg(self) -> float:
        return float(np.max(self.altitudes)) if len(self.altitudes) else 0.0


def build(landscape, eye_height_m: float,
          step_deg: float = GRID_STEP_DEG) -> HorizonProfile:
    """Собрать маску: естественный горизонт плюс верхняя огибающая препятствий.

    Каждое препятствие даёт облако точек силуэта. Точки раскладываются по ячейкам
    сетки азимутов, в ячейке берётся максимум. Пустые ячейки внутри препятствия
    (силуэт дал точки не в каждую) заполняются интерполяцией между соседними
    занятыми — иначе в крыше появлялись бы щели шириной в полградуса, сквозь
    которые «просвечивали» бы планеты.
    """
    count = int(round(360.0 / step_deg))
    base = float(getattr(landscape, "natural_horizon_deg", 0.0))
    mask = np.full(count, base, dtype=float)

    for obstacle in getattr(landscape, "obstacles", []):
        azimuth, altitude = obstacle.silhouette(eye_height_m)
        if len(azimuth) == 0:
            continue
        bins = (np.round(np.asarray(azimuth) / step_deg).astype(int)) % count
        local = np.full(count, -np.inf)
        np.maximum.at(local, bins, np.asarray(altitude, dtype=float))
        local = _fill_gaps(local)
        mask = np.maximum(mask, local)

    return HorizonProfile(altitudes=mask, step_deg=step_deg)


def _fill_gaps(values: np.ndarray) -> np.ndarray:
    """Заполнить пустые ячейки внутри занятого сектора линейной интерполяцией."""
    filled = np.asarray(values, dtype=float)
    known = np.isfinite(filled)
    if not known.any() or known.all():
        return np.where(known, filled, -np.inf)

    indices = np.where(known)[0]
    # сектор считается сплошным, если разрыв между соседними точками невелик;
    # большие разрывы — это промежутки между разными краями препятствия
    result = np.full_like(filled, -np.inf)
    result[known] = filled[known]
    max_gap = max(6, len(filled) // 60)          # около 3° при шаге 0.5°
    for start, finish in zip(indices, np.roll(indices, -1)):
        gap = (finish - start) % len(filled)
        if gap <= 1 or gap > max_gap:
            continue
        for offset in range(1, gap):
            weight = offset / gap
            position = (start + offset) % len(filled)
            result[position] = filled[start] * (1 - weight) + filled[finish] * weight
    return result


def flat(altitude_deg: float = 0.0, step_deg: float = GRID_STEP_DEG) -> HorizonProfile:
    """Ровный горизонт без препятствий — для тестов и площадки без модели участка."""
    count = int(round(360.0 / step_deg))
    return HorizonProfile(altitudes=np.full(count, float(altitude_deg)),
                          step_deg=step_deg)
