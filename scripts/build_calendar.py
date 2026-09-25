"""Собрать календарь на месяц.

    python scripts/build_calendar.py                 # месяц из config.py
    python scripts/build_calendar.py 2026 9          # конкретный месяц
    python scripts/build_calendar.py 2026 9 --no-horizons   # без обращения к сети
    python scripts/build_calendar.py 2026 9 --all-ranks     # публиковать всё
    python scripts/build_calendar.py 2026 9 --icons         # значки вместо ▪️

На выходе три файла:

* `out/calendar_YYYY-MM.txt` — пост для Телеграма (только ранги must и interesting);
* `out/protocol_YYYY-MM.md` — построчный разбор расчётов и источников;
* `out/QA_REPORT_YYYY-MM.md` — можно ли доверять этому календарю: проверки,
  флаги REVIEW, сверка с Horizons, provenance, сроки годности данных.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg, qa, rating              # noqa: E402
from astrocal.build import (collect, render_post, render_protocol,   # noqa: E402
                            render_qa_report)

SOURCES = {
    "ephemeris": "JPL DE440s (планеты и Луна), jup380s (галилеевы спутники), "
                 "JPL Horizons (Титан, астероиды, сверка)",
    "catalogs": "Hipparcos (звёзды), OpenNGC (объекты глубокого космоса), "
                "MPC CometEls (кометы), IOTA/asteroidoccultation.com (покрытия), "
                "CNEOS CAD (сближения NEO), Celestrak (TLE), Launch Library 2 (пуски)",
}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    use_horizons = "--no-horizons" not in argv
    all_ranks = "--all-ranks" in argv
    icons = "--icons" in argv
    year = int(args[0]) if args else cfg.YEAR
    month = int(args[1]) if len(args) > 1 else cfg.MONTH

    start, end = cfg.month_bounds(year, month)
    print(f"Считаю события {start:%d.%m.%Y} — {end:%d.%m.%Y} (МСК)…")
    events, extra = collect(start, end)
    print(f"Рассчитано событий: {len(events)}")

    rating.apply(events)
    qa.stamp_provenance(events, SOURCES)

    print("Проверки" + (" и сверка с JPL Horizons…" if use_horizons else "…"))
    result = qa.run(events, start, end, use_horizons=use_horizons)
    print(f"  без замечаний: {result['clean']}, REVIEW: {len(result['review'])}, "
          f"WARN: {len(result['warn'])}")

    published = events if all_ranks else rating.for_publication(events)
    print(f"В публикацию отобрано: {len(published)}")

    checks = [{"when": f"{e.when:%d.%m %H:%M}", "pair": name,
               "skyfield_deg": 0.0, "horizons_deg": 0.0, "diff_arcsec": delta}
              for e in events
              for name, delta in (e.provenance.get("horizons") or {}).items()]

    out_post = cfg.OUT / f"calendar_{year:04d}-{month:02d}.txt"
    out_protocol = cfg.OUT / f"protocol_{year:04d}-{month:02d}.md"
    out_qa = cfg.OUT / f"QA_REPORT_{year:04d}-{month:02d}.md"

    out_post.write_text(render_post(published, year, month, icons=icons), encoding="utf-8")
    out_protocol.write_text(render_protocol(events, extra, year, month, checks),
                            encoding="utf-8")
    out_qa.write_text(render_qa_report(events, published, extra, result, year, month),
                      encoding="utf-8")

    print(f"\n{out_post}\n{out_protocol}\n{out_qa}")
    if result["review"]:
        print("\nВНИМАНИЕ: есть события с флагом REVIEW — смотрите QA-отчёт "
              "перед публикацией.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
