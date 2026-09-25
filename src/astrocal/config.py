"""Общие настройки генератора календаря."""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo


def _root() -> Path:
    """Каталог, рядом с которым лежат данные, кэш и результаты.

    В собранном приложении `__file__` указывает внутрь дистрибутива, куда
    писать нельзя и где данных нет. Поэтому у замороженной сборки корнем
    считается каталог с исполняемым файлом — там же лежит `data/`.
    Переменная окружения ASTROCAL_HOME перекрывает выбор, если данные
    держат в другом месте.
    """
    override = os.environ.get("ASTROCAL_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


ROOT = _root()
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


# ------------------------------------------------------------------ малые тела

# Пороги редакционной значимости сближений околоземных астероидов.
# Вынесены сюда намеренно: это редакторские решения, а не физика, и менять их
# приходится чаще, чем код.
LUNAR_DISTANCE_KM = 384400.0    # 1 LD

NEO_SEARCH_RADIUS_AU = 0.05     # что вообще запрашиваем у CNEOS
NEO_MUST_LD = 1.0               # ближе Луны — событие месяца
NEO_INTERESTING_LD = 5.0
NEO_INTERESTING_DIAMETER_M = 20.0
NEO_LARGE_DIAMETER_M = 100.0
NEO_LARGE_LD = 20.0
NEO_MAX_IN_CALENDAR = 4         # иначе календарь превращается в поток мелких NEO
NEO_ALBEDO = 0.14               # для оценки диаметра по H

# Покрытия звёзд астероидами
OCC_STAR_MAG_LIMIT = 10.0       # предел блеска звезды для отбора кандидатов
OCC_MIN_DROP_MAG = 1.5          # падение блеска, ниже которого смотреть нечего
OCC_MAX_SUN_ALT_DEG = -6.0      # на дневном небе покрытие не наблюдают
OCC_PREDICTION_STALE_DAYS = 30.0    # прогноз старше — пересчитать перед публикацией
OCC_ORBIT_STALE_DAYS = 60.0         # орбита старше — предупредить
OCC_PATH_SHIFT_ALERT_KM = 20.0      # сдвиг полосы, о котором сообщаем редактору

# Взаимные явления галилеевых спутников. За месяц сезона их бывает под сотню,
# и почти все — касания на несколько процентов диска. В календарь идут те, что
# действительно видно: заметное перекрытие, наблюдаемое из России.
JUPITER_MUTUAL_MIN_OBSCURATION = 0.25
JUPITER_MUTUAL_MIN_MINUTES = 2.0
JUPITER_MUTUAL_MAX_IN_CALENDAR = 8

# Открытия новых комет
COMET_DISCOVERY_MUST_MAG = 6.0          # прогнозируемый максимум ярче — событие
COMET_DISCOVERY_INTERESTING_MAG = 10.0
COMET_DISCOVERY_CLOSE_EARTH_AU = 0.3    # необычно тесное сближение с Землёй
COMET_DISCOVERY_SMALL_Q_AU = 0.3        # околосолнечная комета

# Новые и сверхновые (TNS)
TRANSIENT_MAG_LIMIT = 13.0              # что показываем в основной ленте Live
TRANSIENT_MUST_MAG = 8.0                # ярче — событие, о котором пишут отдельно
TRANSIENT_CONFIRMED_ONLY = True         # только классифицированные объекты
TRANSIENT_STAR_LIMITS = (6.0, 10.0, 13.0, 15.0)   # границы ★★★★★…★

# Сетевой слой
NET_CACHE = CACHE / "net"
NET_MIN_INTERVAL_S = 1.0        # пауза между запросами к одному хосту
NET_RETRIES = 3
LIVE_DIR = DATA / "live"
