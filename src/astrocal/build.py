"""Сборка календаря: собрать события из всех модулей, отрендерить пост и протокол."""
from __future__ import annotations

import datetime as dt
import json

from . import config as cfg
from .core import Event
from .events import (asteroid_occultations, asteroids, comets, eclipses, iss,
                     jupiter_moons, jupiter_phenomena, lunar_features, meteors,
                     moon, occultations, planets, seasons, spaceflight, titan,
                     visibility)
from .fmt import MONTHS_NOM_CAP, date_time_msk

HEADER = "АСТРОНОМИЧЕСКИЕ СОБЫТИЯ {month} {year} года (время московское)✨"


def collect(start: dt.datetime, end: dt.datetime) -> tuple[list[Event], dict]:
    """Все события месяца + вспомогательные данные для протокола."""
    extra: dict = {}
    events: list[Event] = []

    events += moon.all_events(start, end)

    occ_events, occ_report = occultations.build(start, end)
    star_occ_events, star_occ_report = occultations.build_stars(start, end)
    events += occ_events + star_occ_events
    extra["occultations"] = occ_report + star_occ_report

    eclipse_events, eclipse_report = eclipses.all_events(start, end)
    events += eclipse_events
    extra["eclipses"] = eclipse_report

    events += planets.all_events(start, end)
    events += seasons.all_events(start, end)
    events += jupiter_moons.all_events(start, end)
    events += meteors.all_events(start, end)

    try:
        events += jupiter_phenomena.all_events(start, end)
    except Exception as exc:
        extra["jupiter_phenomena_error"] = str(exc)

    try:
        events += lunar_features.all_events(start, end)
    except Exception as exc:                       # нужны ядра ориентации Луны
        extra["lunar_features_error"] = str(exc)
    events += visibility.all_events(start, end)

    try:
        events += asteroids.all_events(start, end)
    except Exception as exc:                       # CNEOS/Horizons могут не ответить
        extra["asteroids_error"] = str(exc)

    try:
        occultation_events, occultation_report = asteroid_occultations.build(start, end)
        events += occultation_events
        extra["asteroid_occultations"] = occultation_report
    except Exception as exc:                       # лента предсказаний может не скачаться
        extra["asteroid_occultations_error"] = str(exc)

    try:
        events += titan.all_events(start, end)
    except Exception as exc:                       # Horizons может быть недоступен
        extra["titan_error"] = str(exc)

    comet_cal, comet_all, comet_table = comets.all_events(start, end)
    events += comet_cal
    try:
        events += comets.milestones(start, end)
    except Exception as exc:
        extra["comet_milestones_error"] = str(exc)
    extra["comets_all"] = comet_all
    extra["comets_table"] = comet_table

    sf_events, sf_rejected = spaceflight.all_events(start, end)
    events += sf_events
    extra["spaceflight_rejected"] = sf_rejected

    try:
        events += iss.all_events(start, end)
    except Exception as exc:
        extra["iss_error"] = str(exc)

    events = [e for e in events if start <= e.when < end]
    events.sort(key=lambda e: (e.display_time, e.text))
    return events, extra


def render_post(events: list[Event], year: int, month: int) -> str:
    head = HEADER.format(month=MONTHS_NOM_CAP[month], year=year)
    return head + "\n\n" + "\n".join(e.line() for e in events) + "\n"


def load_source_list(year: int, month: int) -> list[dict]:
    path = cfg.DATA / f"source_list_{year:04d}-{month:02d}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def _source_day(item: dict) -> int | None:
    """День месяца из префикса 'DD.MM' контрольной строки."""
    head = item["text"].split()[0]
    try:
        return int(head.split(".")[0])
    except (ValueError, IndexError):
        return None


def match_source_list(events: list[Event], source_items: list[dict],
                      day_tolerance: int = 3) -> list[dict]:
    """Сопоставление контрольного списка с пересчитанным календарём.

    Совпадением считается событие, у которого сходятся ключевые слова И дата
    отличается не больше чем на day_tolerance суток: иначе одна строка
    «Титан севернее Сатурна» цепляет все четыре прохождения Титана за месяц.
    """
    result = []
    used: set[int] = set()
    for item in source_items:
        keys = [k.lower() for k in item["keywords"]]
        day = _source_day(item)
        hits = [e for e in events if all(k in e.text.lower() for k in keys)]
        if day is not None:
            hits = [e for e in hits
                    if abs(e.display_time.day - day) <= day_tolerance]
            hits.sort(key=lambda e: abs(e.display_time.day - day))
        best = hits[:1]
        used.update(id(e) for e in best)
        result.append({"source": item, "matches": best,
                       "candidates": len(hits)})
    return result, used


def render_protocol(events: list[Event], extra: dict, year: int, month: int,
                    checks: list[dict] | None = None) -> str:
    lines = [f"# Протокол проверки — календарь на {MONTHS_NOM_CAP[month]} {year}",
             "",
             "Технический документ, не для публикации. Каждая строка календаря "
             "сопровождается расчётом, источниками и уровнем уверенности.",
             "",
             "## 1. Построчный разбор", ""]
    for e in events:
        lines += [f"### ▪️{date_time_msk(e.display_time)} — {e.text}",
                  f"- категория: `{e.category}`",
                  f"- расчёт: {e.computed}",
                  f"- источники: {'; '.join(e.sources) if e.sources else '—'}",
                  f"- уверенность: {e.confidence}"]
        if e.notes:
            lines.append(f"- примечание: {e.notes}")
        lines.append("")

    if checks:
        lines += ["## 2. Независимая сверка с JPL Horizons", "",
                  "| момент | тела | Skyfield | Horizons | расхождение |",
                  "|---|---|---|---|---|"]
        for c in checks:
            lines.append(
                f"| {c['when']} | {c['pair']} | {c['skyfield_deg']:.5f}° | "
                f"{c['horizons_deg']:.5f}° | {c['diff_arcsec']:.2f}″ |")
        lines.append("")

    matched, used = match_source_list(events, load_source_list(year, month))
    if matched:
        lines += ["## 3. Проверка исходного списка", "",
                  "| исходная строка | результат пересчёта |", "|---|---|"]
        for row in matched:
            src = row["source"]
            if row["matches"]:
                got = "; ".join(f"{date_time_msk(m.display_time)} — {m.text}"
                                for m in row["matches"])
            else:
                got = "**не подтверждено расчётом**"
            lines.append(f"| {src['text']} | {got} |")
        lines.append("")

        missing = [row for row in matched if not row["matches"]]
        if missing:
            lines += ["### Найденные ошибки исходного календаря", ""]
            for row in missing:
                lines.append(f"- {row['source']['text']} — расчётом не подтверждено")
            lines.append("")

        added = [e for e in events if id(e) not in used]
        if added:
            lines += ["### Дополнительные события, которых не было в исходном списке", ""]
            for e in added:
                lines.append(f"- {date_time_msk(e.display_time)} — {e.text}")
            lines.append("")

    lines += ["## 4. Кометы: отбор", ""]
    table = extra.get("comets_table")
    if table is not None and len(table):
        lines += ["| комета | минимальный расчётный блеск за месяц |", "|---|---|"]
        for _, r in table.iterrows():
            lines.append(f"| {r['designation']} | {r['mag_min']:.1f}m |")
        lines.append("")
    lines += [f"Всего найдено сближений (включая ненаблюдаемые из Москвы): "
              f"{len(extra.get('comets_all', []))}.", ""]

    rejected = extra.get("spaceflight_rejected", [])
    if rejected:
        lines += ["## 5. Космонавтика: что НЕ вошло в календарь", ""]
        for e in rejected:
            lines += [f"- **{date_time_msk(e.when)} — {e.text}** — "
                      f"уверенность {e.confidence}. {e.notes}",
                      f"  Источники: {'; '.join(e.sources)}"]
        lines.append("")

    occ = extra.get("occultations", [])
    if occ:
        lines += ["## 6. Покрытия: полосы видимости", ""]
        for rec in occ:
            ru = ", ".join(f"{n} ({sh:.0%})" for n, _, sh in rec["ru"]) or "нет"
            world = ", ".join(f"{n} ({sh:.0%})" for n, _, sh in rec["world"]) or "нет"
            lines += [f"### {rec['planet']}, {rec['when']:%d.%m %H:%M} МСК, "
                      f"геоцентрическое расстояние {rec['geo_sep']:.3f}°",
                      f"- регионы РФ в полосе: {ru}",
                      f"- мировые регионы: {world}",
                      f"- габариты полосы: {rec['extent']}",
                      f"- дневное небо: {'да' if rec['daytime'] else 'нет'}", ""]

    notes = cfg.DATA / f"notes_{year:04d}-{month:02d}.md"
    if notes.exists():
        lines += ["## 7. Разбор расхождений (написано вручную)", "",
                  notes.read_text(encoding="utf-8"), ""]

    eclipse_report = extra.get("eclipses", [])
    if eclipse_report:
        lines += ["## 6б. Затмения: полосы", ""]
        for rec in eclipse_report:
            lines += [f"### {rec['kind']}, {rec['when']:%d.%m %H:%M} МСК",
                      "- полная фаза, регионы РФ: " +
                      (", ".join(f"{n} ({sh:.0%})" for n, _, sh in rec["central_ru"])
                       or "нет"),
                      "- полная фаза, мир: " +
                      (", ".join(f"{n} ({sh:.0%})" for n, _, sh in rec["central_world"])
                       or "нет"),
                      "- частные фазы, регионы РФ: " +
                      (", ".join(f"{n} ({sh:.0%})" for n, _, sh in rec["partial_ru"])
                       or "нет"),
                      f"- габариты полосы полной фазы: {rec['central_extent']}", ""]

    for key in ("titan_error", "iss_error", "asteroids_error"):
        if key in extra:
            lines += [f"> Модуль `{key.split('_')[0]}` не отработал: {extra[key]}", ""]
    return "\n".join(lines)


VERIFICATION_MATRIX = [
    ("Фазы Луны, перигей/апогей", "Skyfield + DE440s",
     "JPL Horizons: координаты и расстояние в момент события"),
    ("Равноденствия и солнцестояния", "Skyfield almanac",
     "опубликованные эфемеридные значения"),
    ("Сближения Луны с планетами и звёздами",
     "минимум геоцентрического расстояния по DE440s", "JPL Horizons"),
    ("Покрытия планет и звёзд Луной", "геометрия на сетке ITRS по всей Земле",
     "JPL Horizons: расстояние в максимуме"),
    ("Затмения Солнца и Луны", "та же геометрия + skyfield.eclipselib",
     "опубликованный момент наибольшего затмения"),
    ("Стояния, противостояния, соединения",
     "нули разности видимых эклиптических долгот", "JPL Horizons, выборка по времени"),
    ("Конфигурации галилеевых спутников", "JPL jup380s.bsp", "—"),
    ("Титан", "JPL Horizons", "Skyfield: положение Сатурна и условия видимости"),
    ("Метеорные потоки", "момент достижения табличной λ☉", "рабочий список IMO"),
    ("Кометы", "элементы MPC, кросс-матч с Hipparcos и OpenNGC",
     "JPL Horizons: T-mag и координаты"),
    ("Яркие астероиды", "JPL Horizons", "—"),
    ("Сближения NEO", "NASA/JPL CNEOS Close Approach API", "—"),
    ("Покрытия звёзд астероидами", "лента IOTA + собственный пересчёт полосы",
     "актуальная орбита JPL Horizons против орбиты, по которой считалась лента"),
    ("Пуски", "Launch Library 2, статус Go/TBC/TBD",
     "новости и Википедия, ручное подтверждение"),
    ("Пролёты станций", "Celestrak TLE + SGP4",
     "срок годности элементов, см. раздел про данные с истекающим сроком"),
]


def render_qa_report(events, published, extra, result, year, month) -> str:
    """QA-отчёт: на чём основано доверие к числам в этом календаре."""
    from collections import Counter

    from .qa import sanity_summary

    lines = [f"# QA-отчёт: календарь на {MONTHS_NOM_CAP[month]} {year}", "",
             f"Составлен {dt.datetime.now(cfg.MSK):%Y-%m-%d %H:%M} МСК. Документ "
             "отвечает не на вопрос «что происходит в этом месяце», а на вопрос "
             "«почему этим числам можно верить».", "",
             "## 1. Сводка", "",
             f"- событий рассчитано: **{len(events)}**",
             f"- отобрано в публикацию: **{len(published)}**",
             f"- без замечаний: **{result['clean']}**",
             f"- с флагом REVIEW (публиковать только после просмотра): "
             f"**{len(result['review'])}**",
             f"- с предупреждением WARN: **{len(result['warn'])}**", ""]

    ranks = Counter(e.rank for e in events)
    lines += ["| ранг значимости | рассчитано | в публикации |", "|---|---|---|"]
    for rank in ("must", "interesting", "optional", "technical"):
        in_post = sum(1 for e in published if e.rank == rank)
        lines.append(f"| {rank} | {ranks.get(rank, 0)} | {in_post} |")
    lines.append("")

    lines += ["## 2. Первичный расчёт и независимая проверка по типам событий", "",
              "| категория | чем считается | чем проверяется |", "|---|---|---|"]
    for category, primary, secondary in VERIFICATION_MATRIX:
        lines.append(f"| {category} | {primary} | {secondary} |")
    lines.append("")

    lines += ["## 3. События с флагом REVIEW", ""]
    if result["review"]:
        for event in result["review"]:
            lines.append(f"### {date_time_msk(event.display_time)} — {event.text}")
            for flag in event.flags:
                if flag.level == "REVIEW":
                    lines.append(f"- **{flag.check}**: {flag.message}")
            lines.append("")
    else:
        lines += ["Ни одного.", ""]

    lines += ["## 4. Предупреждения", ""]
    if result["warn"]:
        for event in result["warn"]:
            messages = "; ".join(f.message for f in event.flags if f.level == "WARN")
            lines.append(f"- {date_time_msk(event.display_time)} — {event.text} "
                         f"→ {messages}")
        lines.append("")
    else:
        lines += ["Нет.", ""]

    lines += ["## 5. Сверка с JPL Horizons", "",
              "| момент | тело | расхождение, ″ |", "|---|---|---|"]
    worst, rows = 0.0, 0
    for event in events:
        for name, delta in (event.provenance.get("horizons") or {}).items():
            lines.append(f"| {date_time_msk(event.display_time)} | {name} | {delta} |")
            worst = max(worst, float(delta))
            rows += 1
    if not rows:
        lines.append("| — | сверка не выполнялась | — |")
    lines += ["", f"Наибольшее расхождение: **{worst:.2f}″** при допуске 1″.", ""]

    checks = sanity_summary(events)
    lines += ["## 6. Физические проверки", ""]
    lines += ([f"- {line}" for line in checks] if checks
              else ["Проверяемых величин в этом месяце не оказалось."])
    lines.append("")

    lines += ["## 7. Provenance", "",
              "Источник эфемерид, каталоги и время расчёта проставлены каждому "
              "событию. Общие для месяца значения:", ""]
    sample = events[0].provenance if events else {}
    for key in ("ephemeris", "catalogs", "timescale", "computed_at_utc"):
        if sample.get(key):
            lines.append(f"- **{key}**: {sample[key]}")
    lines.append("")

    tle_events = [e for e in events if e.category == "iss"]
    if tle_events:
        lines += ["## 8. Данные с истекающим сроком годности", "",
                  "| событие | возраст TLE, сут | точное время опубликовано |",
                  "|---|---|---|"]
        for event in tle_events:
            station = event.meta.get("station", "")
            published_exact = event.provenance.get("exact_time_published")
            lines.append(f"| {date_time_msk(event.display_time)} {station} "
                         f"| {event.provenance.get('tle_age_days')} "
                         f"| {'да' if published_exact else 'нет'} |")
        lines += ["", "Точное время пролёта публикуется только при возрасте "
                  "элементов не больше 3 суток. Иначе календарь называет период, "
                  "а минуты выдаёт `scripts/refresh_passes.py` за 2–3 дня до "
                  "события.", ""]

    occ = extra.get("asteroid_occultations", [])
    if occ:
        analysed = [r for r in occ if "candidate" in r and "error" not in r]
        shifted = [r for r in analysed
                   if r.get("feed_shift_hours") and abs(r["feed_shift_hours"]) > 1]
        lines += ["## 9. Покрытия звёзд астероидами: расхождение с лентой", "",
                  f"Разобрано кандидатов: {len(analysed)}. У "
                  f"{len(shifted)} из них момент по годовой ленте IOTA расходится с "
                  "пересчётом по актуальной орбите больше чем на час — это и есть "
                  "причина, по которой ленту нельзя публиковать напрямую.", ""]
        for record in sorted(analysed,
                             key=lambda r: -abs(r.get("feed_shift_hours") or 0))[:10]:
            candidate = record["candidate"]
            shift = record.get("feed_shift_hours")
            lines.append(
                f"- ({candidate.asteroid_number}) {candidate.asteroid_name} × "
                f"{candidate.star_id}: сдвиг "
                f"{shift:+.1f} ч, ось тени в {record['axis_miss_km']:.0f} км от "
                f"центра Земли, регионы: "
                f"{', '.join(record['regions']) if record['regions'] else 'мимо России'}")
        lines.append("")

    external, rows = absence_check(events, year, month)
    if rows:
        found = [r for r in rows if r["match"]]
        missing = [r for r in rows if not r["match"]
                   and not r["item"].get("expected_missing")]
        excluded = [r for r in rows if not r["match"]
                    and r["item"].get("expected_missing")]
        lines += ["## 10. Проверка на пропуски", "",
                  f"Внешний источник: {external.get('source', '—')} "
                  f"(получен {external.get('fetched', '—')}). Сверка отвечает на "
                  "вопрос «чего у нас нет, хотя оно есть у других».", "",
                  f"- совпало: **{len(found)}** из {len(rows)}",
                  f"- отсутствует у нас без объяснения: **{len(missing)}**",
                  f"- сознательно не публикуется: **{len(excluded)}**", "",
                  "| внешний источник | наш календарь |", "|---|---|"]
        for row in rows:
            item = row["item"]
            if row["match"]:
                event = row["match"]
                ours = f"{date_time_msk(event.display_time)} — {event.text}"
            elif item.get("expected_missing"):
                ours = f"*не публикуется: {item['expected_missing']}*"
            else:
                ours = "**отсутствует**"
            lines.append(f"| {item['external']} | {ours} |")
        lines.append("")
        if missing:
            lines += ["### Пропуски, требующие решения", ""]
            for row in missing:
                lines.append(f"- {row['item']['external']}")
            lines.append("")

    dropped = [e for e in events if e not in published]
    lines += ["## 11. Рассчитано, но не пошло в публикацию", ""]
    if dropped:
        for event in sorted(dropped, key=lambda e: e.when):
            lines.append(f"- [{event.rank}] {date_time_msk(event.display_time)} — "
                         f"{event.text}")
        lines.append("")
    else:
        lines += ["Всё рассчитанное вошло в публикацию.", ""]
    return "\n".join(lines)


def load_external(year: int, month: int) -> dict:
    """Внешний календарь для проверки на пропуски."""
    path = cfg.DATA / f"external_{year:04d}-{month:02d}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def absence_check(events, year: int, month: int, day_tolerance: int = 2):
    """Чего нет у нас, но есть во внешнем источнике.

    Проверка «я ничего не пропустил» — вторая половина доверия к календарю.
    Первая («то, что я нашёл, посчитано верно») закрывается сверкой с Horizons,
    но она ничего не говорит о полноте.
    """
    external = load_external(year, month)
    rows = []
    for item in external.get("items", []):
        keys = [k.lower() for k in item["keywords"]]
        day = item.get("day")
        hits = [e for e in events if all(k in e.text.lower() for k in keys)]
        if day is not None:
            hits = [e for e in hits
                    if abs(e.display_time.day - day) <= day_tolerance]
            hits.sort(key=lambda e: abs(e.display_time.day - day))
        rows.append({"item": item, "match": hits[0] if hits else None})
    return external, rows
