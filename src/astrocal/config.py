"""Общие настройки генератора календаря."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CACHE = DATA / "cache"
OUT = ROOT / "out"
for _p in (DATA, CACHE, OUT):
    _p.mkdir(parents=True, exist_ok=True)

MSK = ZoneInfo("Europe/Moscow")  # UTC+3 без перехода на летнее время

# Ядра эфемерид
EPH_PLANETS = DATA / "de440s.bsp"
EPH_JUPSAT = DATA / "jup380s.bsp"

# Целевой месяц (по умолчанию — сентябрь 2026)
YEAR = 2026
MONTH = 9

# Наблюдательная площадка по умолчанию: Москва
SITE_LAT = 55.7558
SITE_LON = 37.6173
SITE_ELEV_M = 156

# Вторая площадка — юг Европейской части России. Канал пишет для всей страны,
# а объекты южнее −20° по склонению из Москвы не поднимаются выше нескольких
# градусов: без южной точки они молча выпадают из календаря.
SOUTH_LAT = 45.04
SOUTH_LON = 38.98
SOUTH_ELEV_M = 25

# Пороги для автопоиска сближений кометы с объектами каталогов
COMET_MAG_LIMIT = 12.0          # рассматриваем кометы ярче этой величины
APPROACH_LIMIT_DEG = 1.0        # интересное сближение
APPROACH_TIGHT_DEG = 0.5        # особенно интересное
STAR_MAG_LIMIT = 8.0            # звёзды HIP ярче этой величины
DSO_MAG_LIMIT = 12.0            # NGC/IC/Messier ярче этой величины
COMET_STEP_MINUTES = 15         # шаг сетки для трассировки кометы


def month_bounds(year: int = YEAR, month: int = MONTH) -> tuple[dt.datetime, dt.datetime]:
    """Границы месяца в МСК: [01-е 00:00, 1-е следующего 00:00)."""
    start = dt.datetime(year, month, 1, tzinfo=MSK)
    end = dt.datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=MSK)
    return start, end
