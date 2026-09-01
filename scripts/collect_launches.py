"""Черновик расписания космонавтики на месяц из Launch Library 2.

Запуск:
    python scripts/collect_launches.py 2026 9

Скрипт НЕ трогает существующий data/spaceflight_YYYY-MM.json — он кладёт рядом
файл с суффиксом `.auto.json`. Человек переносит нужные строки руками, правит
русские формулировки и ставит include=true. Так автоматика экономит время, но
не может сама протащить в календарь непроверенный пуск.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg          # noqa: E402
from astrocal.events.spaceflight import data_path, load   # noqa: E402
from astrocal.launches import drafts        # noqa: E402


def main(argv: list[str]) -> int:
    year = int(argv[0]) if argv else cfg.YEAR
    month = int(argv[1]) if len(argv) > 1 else cfg.MONTH
    start, end = cfg.month_bounds(year, month)

    records = drafts(start, end)
    existing = {rec["text"] for rec in load(year, month)}
    fresh = [r for r in records if r["text"] not in existing]

    target = data_path(year, month).with_suffix(".auto.json")
    target.write_text(json.dumps({"events": fresh}, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    print(f"Launch Library 2 вернул {len(records)} подходящих пусков, "
          f"новых для этого месяца — {len(fresh)}.")
    for rec in fresh:
        flag = "в календарь" if rec["include"] else "ТРЕБУЕТ ПРОВЕРКИ"
        print(f"  {rec['when_msk']} — {rec['text']}  [{rec['_ll2_status']}, {flag}]")
    print(f"\nЧерновик: {target}")
    print("Перенесите нужные строки в основной файл, поправив формулировки.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
