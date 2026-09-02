"""Обновление живой ленты из командной строки.

    python scripts/refresh_live.py                 # все источники
    python scripts/refresh_live.py --neo
    python scripts/refresh_live.py --comets
    python scripts/refresh_live.py --transients
    python scripts/refresh_live.py --occultations
    python scripts/refresh_live.py --json          # машинный вывод

Нужно ровно для того же, для чего кнопка «Обновить сейчас» в программе, но без
интерфейса: так удобно отлаживать источники, гонять обновление по расписанию и
видеть, что именно поменялось.

Состояние ленты общее с приложением: объект, объявленный новым здесь, в
программе новым уже не будет.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal.live import discovery_service          # noqa: E402
from astrocal.live.state import LiveState            # noqa: E402
from astrocal import qa_live                         # noqa: E402


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Обновление AstroCalendar Live")
    parser.add_argument("--neo", action="store_true",
                        help="сближения астероидов с Землёй (CNEOS)")
    parser.add_argument("--comets", action="store_true",
                        help="новые кометы (MPC)")
    parser.add_argument("--transients", action="store_true",
                        help="новые и сверхновые (TNS)")
    parser.add_argument("--occultations", action="store_true",
                        help="покрытия звёзд астероидами (IOTA + JPL)")
    parser.add_argument("--days", type=float, default=30.0,
                        help="горизонт прогноза в сутках (по умолчанию 30)")
    parser.add_argument("--no-cache", action="store_true",
                        help="не использовать кэш сетевых ответов")
    parser.add_argument("--no-observability", action="store_true",
                        help="не считать наблюдаемость (быстрее, без Horizons)")
    parser.add_argument("--json", action="store_true",
                        help="вывести результат в JSON")
    parser.add_argument("--state", type=Path, default=None,
                        help="каталог состояния ленты (по умолчанию data/live)")
    return parser.parse_args(argv)


def selected(arguments: argparse.Namespace) -> tuple:
    chosen = tuple(kind for kind, flag in (
        ("occultations", arguments.occultations), ("neo", arguments.neo),
        ("comets", arguments.comets), ("transients", arguments.transients))
        if flag)
    return chosen or discovery_service.KINDS


def report(result, records) -> str:
    lines = [result.summary_text(), ""]
    for key, summary in result.sources.items():
        title = summary.get("title", key)
        status = summary.get("status", "ок")
        extra = summary.get("error") or summary.get("note") or ""
        lines.append(f"  {title}: {status}" + (f" — {extra}" if extra else ""))

    fresh = [item for item in records
             if item.status in ("NEW", "UPDATED")]
    if fresh:
        lines.append("")
        lines.append("Изменения:")
        for item in fresh:
            when = f"{item.moment:%d.%m %H:%M}" if item.moment else "—"
            level = qa_live.qa_level(item)
            lines.append(f"  [{item.status}] {when} {item.kind_title}: "
                         f"{item.title} ({item.rank}, QA {level})")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    arguments = parse(argv)
    state = LiveState(arguments.state)
    result = discovery_service.refresh(
        selected(arguments), state=state, days=arguments.days,
        use_cache=not arguments.no_cache,
        with_observability=not arguments.no_observability)
    qa_live.run(result.records)

    if arguments.json:
        payload = result.as_dict()
        payload["qa"] = {item.live_id: [
            {"level": flag.level, "check": flag.check, "message": flag.message}
            for flag in (item.state or {}).get("qa", [])]
            for item in result.records}
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(report(result, result.records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
