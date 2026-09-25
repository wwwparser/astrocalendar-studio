"""Наблюдённый блеск комет: COBS и таблица ван Бёйтенена.

Формула MPC `m = g + 5·lg Δ + k·lg r` даёт не блеск, а прикидку по двум
параметрам, взятым из архива. Для комет, которые давно не наблюдались или
изменили активность, она ошибается катастрофически: 65P/Gunn по MPC выходит
+10,5ᵐ, а по наблюдениям COBS — 18,8ᵐ, то есть в десять тысяч раз слабее.
116P/Wild: +11,8ᵐ по модели против 21,7ᵐ по наблюдениям. Публиковать такое
нельзя, а понять это по одной лишь модели невозможно.

Поэтому блеск берём из наблюдений:

* **COBS** (cobs.si) — база визуальных и ПЗС-оценок, отдаёт текущий блеск,
  блеск в максимуме и признак «объект реально наблюдается». Это основной
  источник.
* **astro.vanbuitenen.nl/comets** — расчётный прогноз того же автора, чьи
  таблицы по астероидам мы уже используем. Второе мнение и запасной вариант.

Модель MPC остаётся, но в новой роли: она задаёт **форму кривой блеска** во
времени, а её уровень калибруется по наблюдению. Сдвиг Δm = наблюдение минус
модель на сегодня применяется ко всей кривой. Так сохраняется зависимость от
расстояний r и Δ, но уходит систематическая ошибка параметров.

Если кометы нет ни в одном источнике, блеск остаётся модельным — и событие
помечается как ненадёжное, а не выдаётся за измерение.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .net import fetch

COBS_URL = "https://cobs.si/api/comet_list.api"
VANBUITENEN_URL = "https://astro.vanbuitenen.nl/comets"
COBS_SOURCE = "COBS (Comet OBServation database)"
VB_SOURCE = "astro.vanbuitenen.nl (G. van Buitenen)"


def designation_keys(designation: str) -> set[str]:
    """Варианты обозначения кометы для сопоставления источников.

    MPC пишет «161P/Hartley-IRAS», COBS — «161P» плюс полное имя, ван Бёйтенен
    может добавить первооткрывателя в скобках. Ключами считаем и короткое
    обозначение, и полное.
    """
    text = (designation or "").strip()
    if not text:
        return set()
    keys = {text.upper()}
    without_discoverer = text.split("(")[0].strip()
    keys.add(without_discoverer.upper())
    if "/" in without_discoverer:
        head, tail = without_discoverer.split("/", 1)
        head = head.strip().upper()
        # «161P/Hartley-IRAS» → «161P»; но у C/2024 J3 голова не информативна
        if re.fullmatch(r"\d+[PDCI]", head):
            keys.add(head)
        else:
            keys.add(f"{head}/{tail.strip()}".upper())
    return {re.sub(r"\s+", " ", key).strip() for key in keys if key}


@dataclass
class CometBrightness:
    """Что источник знает о блеске кометы."""
    designation: str
    fullname: str = ""
    current_magnitude: float | None = None
    peak_magnitude: float | None = None
    peak_date: dt.datetime | None = None
    perihelion_magnitude: float | None = None
    observed: bool = False
    source: str = ""
    source_updated_at: str = ""

    @property
    def keys(self) -> set[str]:
        return designation_keys(self.designation) | designation_keys(self.fullname)

    def provenance(self) -> dict:
        return {"magnitude_source": self.source,
                "source_updated_at": self.source_updated_at,
                "observed": self.observed,
                "current_magnitude": self.current_magnitude}


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value) -> dt.datetime | None:
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(str(value).strip(), pattern).replace(
                tzinfo=dt.timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


# ------------------------------------------------------------------ источники


def cobs(use_cache: bool = True, ttl_hours: float = 12.0) -> list[CometBrightness]:
    """Список комет COBS с наблюдённым блеском."""
    response = fetch(COBS_URL, ttl_hours=ttl_hours, use_cache=use_cache,
                     timeout=120.0)
    payload = response.json()
    out = []
    for item in payload.get("objects") or []:
        out.append(CometBrightness(
            designation=str(item.get("name") or "").strip(),
            fullname=str(item.get("fullname") or "").strip(),
            current_magnitude=_float(item.get("current_mag")),
            peak_magnitude=_float(item.get("peak_mag")),
            peak_date=_date(item.get("peak_mag_date")),
            perihelion_magnitude=_float(item.get("perihelion_mag")),
            observed=bool(item.get("is_observed")),
            source=COBS_SOURCE,
            source_updated_at=response.fetched_at.isoformat()))
    return out


VB_COLUMNS = ["designation", "magn", "delta", "radius", "date", "magn",
              "radius", "date", "magn", "delta"]


def vanbuitenen(use_cache: bool = True,
                ttl_hours: float = 12.0) -> list[CometBrightness]:
    """Прогноз блеска комет с astro.vanbuitenen.nl."""
    from .neo_feeds import _normalise_header, parse_table

    response = fetch(VANBUITENEN_URL, ttl_hours=ttl_hours, use_cache=use_cache,
                     timeout=60.0)
    headers, rows = parse_table(response.body)
    actual = [_normalise_header(name) for name in headers]
    if actual != VB_COLUMNS:
        raise ValueError(f"структура таблицы {VANBUITENEN_URL} изменилась: "
                         f"ожидались {VB_COLUMNS}, получены {actual}")
    if not rows:
        raise ValueError(f"на странице {VANBUITENEN_URL} разобран заголовок, "
                         f"но ни одной строки данных не найдено")
    out = []
    for row in rows:
        if len(row) < len(VB_COLUMNS):
            continue
        out.append(CometBrightness(
            designation=row[0].strip(),
            fullname=row[0].strip(),
            current_magnitude=_float(row[1]),
            perihelion_magnitude=_float(row[5]),
            peak_magnitude=_float(row[5]),
            peak_date=_date(row[4]),
            observed=False,
            source=VB_SOURCE,
            source_updated_at=response.fetched_at.isoformat()))
    return out


# ------------------------------------------------------------------ поиск


@dataclass
class BrightnessIndex:
    """Наблюдения по всем источникам, разложенные по обозначениям."""
    entries: list[CometBrightness] = field(default_factory=list)
    by_key: dict[str, CometBrightness] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def find(self, designation: str) -> CometBrightness | None:
        for key in designation_keys(designation):
            entry = self.by_key.get(key)
            if entry is not None:
                return entry
        return None

    @property
    def available(self) -> bool:
        return bool(self.entries)


def load(use_cache: bool = True, sources=("cobs", "vanbuitenen")) -> BrightnessIndex:
    """Собрать индекс блеска. Недоступность источника не мешает расчёту.

    Порядок важен: COBS идёт первым, потому что это наблюдения, а не прогноз.
    Запись из более раннего источника не перезаписывается более поздним.
    """
    index = BrightnessIndex()
    loaders = {"cobs": cobs, "vanbuitenen": vanbuitenen}
    for name in sources:
        try:
            entries = loaders[name](use_cache=use_cache)
        except Exception as error:               # noqa: BLE001
            index.errors.append(f"{name}: {error}")
            continue
        index.entries += entries
        for entry in entries:
            for key in entry.keys:
                index.by_key.setdefault(key, entry)
    return index
