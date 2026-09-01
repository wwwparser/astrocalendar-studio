"""Точные времена пролётов МКС и китайской станции по свежему TLE.

Месячный календарь называет только период видимости: элементы орбиты стареют,
и обещать минуту за три недели вперёд нельзя. Этот скрипт запускается за
2–3 суток до события, скачивает актуальный TLE и печатает точные пролёты —
их можно отправить в канал отдельным сообщением.

    python scripts/refresh_passes.py            # ближайшие 3 суток
    python scripts/refresh_passes.py 5          # ближайшие 5 суток
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg                      # noqa: E402
from astrocal.core import to_msk                        # noqa: E402
from astrocal.events.iss import (EXACT_TIME_MAX_AGE_DAYS, STATIONS,  # noqa: E402
                                 load_tle, visible_passes)


def main(argv: list[str]) -> int:
    days = float(argv[0]) if argv else 3.0
    start = dt.datetime.now(cfg.MSK).replace(minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=days)
    print(f"Пролёты с {start:%d.%m %H:%M} по {end:%d.%m %H:%M} МСК\n")

    for catnr, station in STATIONS.items():
        sat = load_tle(catnr, max_age_hours=6.0)
        if sat is None:
            print(f"{station['label']}: TLE недоступен")
            continue
        epoch = to_msk(sat.epoch)
        age = abs((start - epoch).days)
        status = ("свежий" if age <= EXACT_TIME_MAX_AGE_DAYS
                  else f"устарел на {age} сут — время ориентировочное")
        print(f"{station['label']} ({station['where']}), TLE от {epoch:%d.%m %H:%M} "
              f"МСК — {status}")
        passes = visible_passes(sat, start, end, station["lat"], station["lon"],
                                station["min_alt"])
        if not passes:
            print("  видимых пролётов нет\n")
            continue
        for when, alt in passes:
            print(f"  ▪️{when:%d.%m}, {when:%H:%M} — пролёт {station['label']}, "
                  f"максимальная высота {alt:.0f}°")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
