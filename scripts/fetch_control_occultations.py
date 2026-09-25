"""Сбор контрольного списка покрытий с astrovert.ru.

    python scripts/fetch_control_occultations.py 2026

Список ведут наблюдатели: яркие покрытия (звезда ярче +7m, астероид крупнее
10 км, длительность больше секунды), видимые с территории России. Для нас это
не источник данных, а **эталон полноты**: свои события мы считаем сами, а по
этому списку проверяем, не потеряли ли что-то заметное.

Результат кладётся в `data/control_occultations_<год>.json` вместе со ссылкой
и датой снятия — чтобы через полгода было видно, с чем именно сверялись.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg                      # noqa: E402
from astrocal.net import fetch                          # noqa: E402

URL = "https://astrovert.ru/journal/events/pokrytiya-asteroidami-v-{year}-godu/"

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11,
    "декабря": 12,
    # на странице есть опечатка «3 аперля» — узнаём и её, иначе событие
    # молча выпадет из эталона
    "аперля": 4,
}

START = re.compile(r"^\d{1,2}\s+[А-Яа-яё]+,\s*\d{1,2}:\d{2}\s*[—–-]\s*астероид")

LINE = re.compile(
    r"(\d{1,2})\s+([А-Яа-яё]+),\s*(\d{1,2}):(\d{2})\s*[—–-]\s*"
    r"астероид\s*\((\d+)\)\s*(.+?)\s+покрывает\s+звезду\s+(.+?)\s*"
    r"\(\+?(\d+)m\)\s*,\s*видимость:\s*([^(]+?)\s*(?:\(([^)]*)\))?\s*$")

DIAMETER = re.compile(r"\(\s*d\s*=\s*(\d+)\s*км\s*\)")


def _record(line: str) -> dict | None:
    """Разобрать одну строку события. None — строка ещё не собралась."""
    match = LINE.match(line)
    if not match:
        return None
    (day, month_word, hour, minute, number, name, star, star_mag,
     regions, note) = match.groups()
    month = MONTHS.get(month_word.lower())
    if month is None:
        return None

    # у части объектов в скобках указан диаметр: «Lucina (d=137км)»
    diameter = None
    size = DIAMETER.search(name)
    if size:
        diameter = int(size.group(1))
        name = name[:size.start()].strip()

    return {
        "date": f"{month:02d}-{int(day):02d}",
        "time_msk": f"{int(hour):02d}:{minute}",
        "asteroid_number": int(number),
        "asteroid_name": name.strip(),
        "asteroid_diameter_km": diameter,
        "star": star.strip(),
        "star_magnitude": int(star_mag),
        "regions": [part.strip() for part in regions.split(",") if part.strip()],
        "note": (note or "").strip(),
        "source_line": line,
    }


def parse(html: str) -> list[dict]:
    """События со страницы.

    Строка события может быть перенесена разметкой, поэтому разбор идёт не
    построчно: строки накапливаются, пока не соберётся целое событие. Иначе
    один перенос в исходнике тихо съедает событие.
    """
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = text.replace("&nbsp;", " ").replace("&mdash;", "—")

    events: list[dict] = []
    unparsed: list[str] = []
    buffer = ""

    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if START.match(line):
            if buffer:
                unparsed.append(buffer)
            buffer = line
        elif buffer:
            buffer = f"{buffer} {line}"
        else:
            continue

        record = _record(buffer)
        if record is not None:
            events.append(record)
            buffer = ""

    if buffer:
        unparsed.append(buffer)
    if unparsed:
        print(f"Не разобрано строк: {len(unparsed)}")
        for line in unparsed:
            print("  ", line[:160])
    return events


def main(argv: list[str]) -> int:
    year = int(argv[0]) if argv else cfg.YEAR
    url = URL.format(year=year)
    response = fetch(url, ttl_hours=24.0)
    events = parse(response.body)
    if not events:
        print("Ни одного события не разобрано — проверьте разметку страницы")
        return 1

    payload = {
        "year": year,
        "source": "astrovert.ru",
        "url": url,
        "fetched_at": response.fetched_at.isoformat(),
        "criteria": ("звёзды ярче +7m, астероиды крупнее 10 км, длительность "
                     "больше 1 секунды, полоса над территорией России"),
        "purpose": ("контрольный список для проверки полноты нашего расчёта; "
                    "источником данных не является"),
        "events": events,
    }
    path = cfg.DATA / f"control_occultations_{year}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"Событий: {len(events)} → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
