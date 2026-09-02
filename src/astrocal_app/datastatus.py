"""Состояние внешних источников данных.

Половина ошибок в таких системах — не в формулах, а в устаревших данных: TLE
недельной давности, орбита кометы прошлого года, расписание пусков, снятое до
переноса. Панель показывает возраст каждого источника, а обновление можно
запустить точечно: качать гигабайты ради одной строки незачем.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from astrocal import config as cfg


@dataclass
class Source:
    key: str
    title: str
    path: Path | None
    fresh_hours: float | None      # None — не устаревает
    refreshable: bool = True
    note: str = ""

    @property
    def exists(self) -> bool:
        return bool(self.path and self.path.exists())

    @property
    def updated(self) -> dt.datetime | None:
        if not self.exists:
            return None
        return dt.datetime.fromtimestamp(self.path.stat().st_mtime, tz=cfg.MSK)

    @property
    def age_hours(self) -> float | None:
        updated = self.updated
        if updated is None:
            return None
        return (dt.datetime.now(cfg.MSK) - updated).total_seconds() / 3600.0

    @property
    def status(self) -> str:
        if not self.exists:
            return "нет данных"
        if self.fresh_hours is None:
            return "локальный"
        age = self.age_hours or 0.0
        if age <= self.fresh_hours:
            return "актуально"
        if age <= self.fresh_hours * 4:
            return "стареет"
        return "устарело"

    @property
    def age_text(self) -> str:
        if not self.exists:
            return "—"
        if self.fresh_hours is None:
            return "локально"
        age = self.age_hours or 0.0
        if age < 1:
            return f"{age * 60:.0f} мин назад"
        if age < 48:
            return f"{age:.0f} ч назад"
        return f"{age / 24:.0f} дн назад"


def sources() -> list[Source]:
    cache = cfg.CACHE
    return [
        Source("de440", "JPL DE440s (планеты и Луна)", cfg.DATA / "de440s.bsp",
               None, refreshable=False, note="эфемериды до 2150 года"),
        Source("jup380", "JPL jup380s (галилеевы спутники)",
               cfg.DATA / "jup380s.bsp", None, refreshable=False),
        Source("hipparcos", "Hipparcos (звёзды)", cache / "hip_bright.parquet",
               None, refreshable=False),
        Source("openngc", "OpenNGC (объекты каталогов)", cache / "NGC.csv",
               24 * 90),
        Source("mpc", "MPC CometEls (кометы)", cache / "CometEls.txt", 24 * 7),
        Source("iota", "IOTA (покрытия звёзд астероидами)",
               cache / "occ2026-iota.zip", 24 * 30),
        Source("cneos", "CNEOS (сближения NEO)", _latest(cache, "cad_*.json"),
               24 * 7),
        Source("tle_iss", "TLE МКС", cache / "iss_tle.txt", 24),
        Source("tle_css", "TLE ККС", cache / "css_tle.txt", 24),
        Source("launches", "Launch Library 2 (пуски)",
               _latest(cache, "ll2_*.json"), 12),
        Source("constellations", "Линии созвездий",
               cache / "constellationship.fab", None, refreshable=False),
    ]


def _latest(directory: Path, pattern: str) -> Path | None:
    matches = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime,
                     reverse=True)
    return matches[0] if matches else None


# ------------------------------------------------------------------ обновление


def refresh_tle(progress=None) -> str:
    from astrocal.events.iss import STATIONS, load_tle

    updated = []
    for catnr in STATIONS:
        if progress:
            progress(f"TLE {STATIONS[catnr]['label']}", 50)
        satellite = load_tle(catnr, max_age_hours=0.0)
        if satellite is not None:
            updated.append(STATIONS[catnr]["label"])
    return "Обновлены элементы: " + (", ".join(updated) or "ничего")


def refresh_comets(progress=None) -> str:
    import requests
    from skyfield.data import mpc

    if progress:
        progress("Элементы комет MPC", 30)
    response = requests.get(mpc.COMET_URL, timeout=180)
    response.raise_for_status()
    (cfg.CACHE / "CometEls.txt").write_bytes(response.content)
    return f"Загружено {len(response.content) // 1024} КБ элементов комет"


def refresh_launches(year: int, month: int, progress=None) -> str:
    from astrocal.launches import fetch

    if progress:
        progress("Расписание пусков", 40)
    start, end = cfg.month_bounds(year, month)
    records = fetch(start, end, use_cache=False)
    return f"Получено пусков: {len(records)}"


def refresh_neo(year: int, month: int, progress=None) -> str:
    from astrocal.events.asteroids import close_approaches

    if progress:
        progress("Сближения NEO", 60)
    start, end = cfg.month_bounds(year, month)
    cache = cfg.CACHE / f"cad_{start:%Y%m}.json"
    if cache.exists():
        cache.unlink()
    events = close_approaches(start, end)
    return f"Получено сближений: {len(events)}"


def refresh_all(year: int, month: int, progress=None) -> str:
    """Обновить то, что действительно стареет, и ничего больше."""
    steps = [
        ("TLE станций", lambda: refresh_tle()),
        ("Расписание пусков", lambda: refresh_launches(year, month)),
        ("Сближения NEO", lambda: refresh_neo(year, month)),
        ("Элементы комет", lambda: refresh_comets()),
    ]
    messages = []
    for index, (name, action) in enumerate(steps):
        if progress:
            progress(name, int(100 * index / len(steps)))
        try:
            messages.append(f"{name}: {action()}")
        except Exception as error:               # noqa: BLE001
            messages.append(f"{name}: не удалось — {error}")
    if progress:
        progress("Готово", 100)
    return "\n".join(messages)
