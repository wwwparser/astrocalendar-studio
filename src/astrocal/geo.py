"""География: регионы России и мира прямоугольниками широта/долгота.

Полигоны границ здесь избыточны: календарю нужна фраза «видимое на Юге
Европейской части России», а не точный контур области. Прямоугольники дают
такую формулировку честно — по доле узлов сетки региона, попавших в полосу.
"""
from __future__ import annotations

import numpy as np

# name, предложный падеж для фразы "видимое на/в …", lat_min, lat_max, lon_min, lon_max
RU_REGIONS = [
    ("Калининградская область", "в Калининградской области", 54.3, 55.4, 19.6, 22.9),
    ("Северо-Запад России", "на Северо-Западе России", 55.5, 70.0, 27.0, 45.0),
    ("Центр Европейской части России", "в Центре Европейской части России",
     51.5, 59.0, 30.0, 47.0),
    ("Юг Европейской части России", "на Юге Европейской части России",
     44.0, 51.5, 36.0, 48.0),
    ("Кавказ", "на Кавказе", 41.0, 45.0, 37.0, 48.5),
    ("Поволжье", "в Поволжье", 46.0, 58.0, 45.0, 54.0),
    ("Урал", "на Урале", 51.0, 68.0, 54.0, 66.0),
    ("Западная Сибирь", "в Западной Сибири", 50.0, 72.0, 66.0, 90.0),
    ("Восточная Сибирь", "в Восточной Сибири", 50.0, 71.0, 90.0, 113.0),
    ("Таймыр", "на Таймыре", 71.0, 78.0, 82.0, 113.0),
    ("Новая Земля и Арктика России", "на Новой Земле и в российской Арктике",
     70.0, 82.0, 45.0, 82.0),
    ("Якутия", "в Якутии", 55.0, 73.0, 113.0, 142.0),
    ("Дальний Восток", "на Дальнем Востоке", 42.0, 62.0, 130.0, 163.0),
    ("Камчатка и Чукотка", "на Камчатке и Чукотке", 51.0, 71.0, 156.0, 180.0),
]

WORLD_REGIONS = [
    ("Европа", 36.0, 60.0, -10.0, 30.0),
    ("Северная Африка и Ближний Восток", 15.0, 36.0, -15.0, 60.0),
    ("Центральная Азия", 35.0, 50.0, 55.0, 80.0),
    ("Индия и Южная Азия", 5.0, 35.0, 65.0, 92.0),
    ("Китай и Восточная Азия", 20.0, 50.0, 100.0, 145.0),
    ("Юго-Восточная Азия", -10.0, 20.0, 92.0, 130.0),
    ("Австралия и Новая Зеландия", -47.0, -10.0, 112.0, 179.0),
    ("Тропическая и Южная Африка", -35.0, 15.0, -18.0, 52.0),
    ("Северная Америка", 25.0, 60.0, -125.0, -60.0),
    ("Аляска и север Канады", 55.0, 75.0, -170.0, -95.0),
    ("Гренландия и Исландия", 60.0, 84.0, -60.0, -13.0),
    ("Южная Америка", -55.0, 13.0, -82.0, -34.0),
    ("Атлантический океан", -50.0, 55.0, -50.0, -12.0),
    ("Тихий океан", -50.0, 55.0, -180.0, -100.0),
    ("Арктика", 75.0, 90.0, -180.0, 180.0),
    ("Антарктика", -90.0, -60.0, -180.0, 180.0),
]


def make_grid(step_deg: float = 2.0, lat_limit: float = 85.0):
    """Регулярная сетка узлов по поверхности Земли."""
    lats = np.arange(-lat_limit, lat_limit + step_deg / 2, step_deg)
    lons = np.arange(-180.0, 180.0, step_deg)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    return lat_grid.ravel(), lon_grid.ravel()


def region_coverage(lat, lon, mask, regions, min_fraction: float = 0.12):
    """Какие регионы попали в полосу и насколько.

    Возвращает список (имя, предложная форма, доля покрытых узлов), отсортированный
    по убыванию доли. Регионы с долей ниже min_fraction отбрасываются: одиночный
    узел на краю прямоугольника — это шум, а не «видно в Сибири».
    """
    out = []
    for entry in regions:
        if len(entry) == 6:
            name, phrase, lat_lo, lat_hi, lon_lo, lon_hi = entry
        else:
            name, lat_lo, lat_hi, lon_lo, lon_hi = entry
            phrase = f"в регионе «{name}»"
        inside = ((lat >= lat_lo) & (lat <= lat_hi) &
                  (lon >= lon_lo) & (lon <= lon_hi))
        total = int(inside.sum())
        if not total:
            continue
        share = float((inside & mask).sum()) / total
        if share >= min_fraction:
            out.append((name, phrase, share))
    return sorted(out, key=lambda r: -r[2])


def describe(coverage) -> str:
    """Человеческая фраза из результата region_coverage."""
    if not coverage:
        return ""
    parts = []
    for name, phrase, share in coverage:
        parts.append(phrase if share > 0.6 else f"{phrase} (частично)")
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " и " + parts[-1]


EARTH_A_KM = 6378.137
EARTH_F = 1.0 / 298.257223563
EARTH_B_KM = EARTH_A_KM * (1.0 - EARTH_F)


def itrs_to_geodetic(point_km):
    """Прямоугольные ITRS-координаты (км) → широта и долгота, градусы."""
    x, y, z = point_km
    e2 = EARTH_F * (2.0 - EARTH_F)
    lon = np.degrees(np.arctan2(y, x))
    r = np.hypot(x, y)
    lat = np.arctan2(z, r * (1.0 - e2))
    for _ in range(8):                      # итерации Боуринга сходятся за 3–4 шага
        n = EARTH_A_KM / np.sqrt(1.0 - e2 * np.sin(lat) ** 2)
        height = r / np.cos(lat) - n
        lat = np.arctan2(z, r * (1.0 - e2 * n / (n + height)))
    return float(np.degrees(lat)), float(lon)


def ray_ellipsoid_intersection(origin_km, direction):
    """Ближняя точка пересечения луча origin + s·direction с эллипсоидом Земли.

    Возвращает None, если луч проходит мимо. Растягиваем ось z так, чтобы
    эллипсоид стал сферой, — тогда задача сводится к обычному квадратному
    уравнению.
    """
    scale = np.array([1.0, 1.0, EARTH_A_KM / EARTH_B_KM])
    o, d = scale * np.asarray(origin_km), scale * np.asarray(direction)
    a = float(np.dot(d, d))
    b = -2.0 * float(np.dot(o, d))
    c = float(np.dot(o, o)) - EARTH_A_KM ** 2
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    s = (-b - np.sqrt(disc)) / (2.0 * a)
    return np.asarray(origin_km) - s * np.asarray(direction)


def point_in_russia(lat: float, lon: float) -> str | None:
    """Имя региона России, в чей прямоугольник попала точка.

    Прямоугольники местами перекрываются (Северо-Запад и Центр ЕЧР, например),
    поэтому выбираем самый узкий из подходящих — он точнее описывает место.
    """
    best, best_area = None, float("inf")
    for name, _phrase, lat_lo, lat_hi, lon_lo, lon_hi in RU_REGIONS:
        if lat_lo <= lat <= lat_hi and lon_lo <= lon <= lon_hi:
            area = (lat_hi - lat_lo) * (lon_hi - lon_lo)
            if area < best_area:
                best, best_area = name, area
    return best


def bounds(lat, lon, mask) -> dict:
    """Габариты полосы: диапазон широт и долгот покрытых узлов."""
    if not mask.any():
        return {}
    return {"lat_min": float(lat[mask].min()), "lat_max": float(lat[mask].max()),
            "lon_min": float(lon[mask].min()), "lon_max": float(lon[mask].max()),
            "points": int(mask.sum())}
