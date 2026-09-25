"""Проверка полноты расчёта покрытий по контрольному списку наблюдателей.

    python scripts/check_occultations.py 2026 9      # один месяц
    python scripts/check_occultations.py 2026        # весь год, помесячно

Отвечает на единственный вопрос: находим ли мы то, что видят наблюдатели.
Контрольный список (astrovert.ru) собирается отдельной командой
`fetch_control_occultations.py` и в расчёте не участвует — мы считаем полосу
сами по свежей орбите JPL, а список нужен, чтобы заметить пропажу.

Расчёт небыстрый: на каждого кандидата уходит два обращения к Horizons.
Месяц считается минутами, год — десятками минут.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg                                   # noqa: E402
from astrocal.events import asteroid_occultations as occ             # noqa: E402


def check_month(year: int, month: int, star_mag_limit: float = 8.0) -> dict:
    start, end = cfg.month_bounds(year, month)
    events, _report = occ.build(start, end, star_mag_limit=star_mag_limit)
    return occ.compare_with_control(events, year, month)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    year = int(argv[0])
    months = [int(argv[1])] if len(argv) > 1 else list(range(1, 13))

    control = occ.control_list(year)
    if not control.get("events"):
        print("Контрольного списка нет. Соберите его:")
        print(f"    python scripts/fetch_control_occultations.py {year}")
        return 1
    print(f"Контрольный список: {control.get('url', '')}")
    print(f"Снят: {control.get('fetched_at', 'неизвестно')}")
    print(f"Критерий отбора: {control.get('criteria', '')}\n")

    total_expected = total_matched = 0
    for month in months:
        expected = [e for e in control["events"] if int(e["date"][:2]) == month]
        if not expected:
            continue
        print(f"=== {month:02d}.{year} ===")
        try:
            result = check_month(year, month)
        except Exception as error:                   # noqa: BLE001
            print(f"  расчёт не выполнен: {error}\n")
            continue
        print(occ.describe_comparison(result))
        print()
        total_expected += result["expected"]
        total_matched += len(result["matched"])

    if total_expected:
        print(f"Итого: {total_matched} из {total_expected} "
              f"({100 * total_matched / total_expected:.0f} %)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
