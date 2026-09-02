"""Генерация карт для выпуска из командной строки.

    python scripts/generate_maps.py 2026 9
    python scripts/generate_maps.py 2026 9 --city krasnodar
    python scripts/generate_maps.py 2026 9 --stations
    python scripts/generate_maps.py 2026 9 --top-events 10
    python scripts/generate_maps.py 2026 9 --all-must

Карты складываются в out/maps/. Тот же код использует интерфейс — карта,
построенная здесь и в приложении, будет одинаковой.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg                       # noqa: E402
from astrocal.cities import all_cities, by_key           # noqa: E402
from astrocal.render import event_map, satellite_map     # noqa: E402
from astrocal_app import service                         # noqa: E402

MAPS = cfg.OUT / "maps"


def _flag_value(argv: list[str], name: str, default=None):
    if name not in argv:
        return default
    index = argv.index(name)
    return argv[index + 1] if index + 1 < len(argv) else default


def station_maps(city, hours: float = 72.0) -> list[Path]:
    """Карты ближайших пролётов МКС и китайской станции."""
    from astrocal.events.iss import STATIONS

    start = dt.datetime.now(cfg.MSK)
    end = start + dt.timedelta(hours=hours)
    produced = []
    for catnr in STATIONS:
        passes = satellite_map.passes_for_station(catnr, city, start, end)
        if not passes:
            print(f"  {STATIONS[catnr]['label']}: видимых пролётов нет")
            continue
        best = max(passes, key=lambda item: item.max_altitude_deg)
        path = MAPS / (f"pass_{STATIONS[catnr]['label']}_{best.start:%Y%m%d_%H%M}"
                       f"_{city.key}.png")
        satellite_map.render(best, path)
        produced.append(path)
        print(f"  {STATIONS[catnr]['label']}: {best.start:%d.%m %H:%M}, "
              f"до {best.max_altitude_deg:.0f}° → {path.name}")
    return produced


def event_maps(issue, city, limit: int | None, only_must: bool) -> list[Path]:
    items = issue.published()
    if only_must:
        items = [item for item in items if item.rank == "must"]
    if limit:
        items = items[:limit]

    produced = []
    for item in items:
        path = MAPS / f"{item.event_id}_sky.png"
        try:
            result = event_map.for_event(item.event, city, path)
        except Exception as error:            # noqa: BLE001
            print(f"  {item.when:%d.%m} {item.calculated_text[:50]}: "
                  f"карта не построена ({error})")
            continue
        if result is None:
            print(f"  {item.when:%d.%m} {item.calculated_text[:50]}: "
                  f"карта для этого типа не требуется")
            continue
        produced.append(result)
        print(f"  {item.when:%d.%m} {item.calculated_text[:50]} → {result.name}")
    return produced


def main(argv: list[str]) -> int:
    positional = [a for a in argv if not a.startswith("--")
                  and not (argv.index(a) > 0 and argv[argv.index(a) - 1]
                           in ("--city", "--top-events"))]
    year = int(positional[0]) if positional else cfg.YEAR
    month = int(positional[1]) if len(positional) > 1 else cfg.MONTH

    city_key = _flag_value(argv, "--city", "москва")
    city = by_key(city_key) or by_key("москва")
    if city is None:
        print("Город не найден. Доступны: "
              + ", ".join(c.key for c in all_cities()))
        return 1

    MAPS.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []

    if "--stations" in argv:
        print(f"Карты пролётов станций для города {city.name}:")
        produced += station_maps(city)

    wants_events = ("--stations" not in argv or "--all-must" in argv
                    or "--top-events" in argv)
    if wants_events:
        limit = _flag_value(argv, "--top-events")
        print(f"Считаю выпуск {month:02d}.{year}…")
        issue = service.compute_issue(
            year, month, use_horizons=False, with_circumstances=False,
            progress=lambda stage, percent: print(f"  {percent:3d}% {stage}",
                                                  flush=True))
        print(f"Карты событий для города {city.name}:")
        produced += event_maps(issue, city, int(limit) if limit else None,
                               "--all-must" in argv)

    print(f"\nГотово. Карт построено: {len(produced)} → {MAPS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
