"""Короткий пост об открытии для Telegram.

Отдельная новость живёт по другим законам, чем строка календаря: у неё есть
заголовок, два-три абзаца и понятный вывод «во сколько и чем смотреть».

Главное ограничение — текст собирается только из полей записи. Ни одного
утверждения, которого нет в данных: если тип объекта не опубликован, пост
говорит «классификация ещё не опубликована», а не придумывает её; если
наблюдаемость не посчиталась, пост об этом молчит, а не обещает высоту над
горизонтом. Это не стилистическое предпочтение, а условие: пост уходит в
канал, и выдуманное число там уже не исправить.
"""
from __future__ import annotations

from ..fmt import number
from .model import (KIND_COMET, KIND_NEO, KIND_OCCULTATION, KIND_TRANSIENT,
                    LiveRecord)


def _magnitude(value) -> str:
    return f"{number(float(value), 1, sign=True)}m"


def _instrument_phrase(instrument: str) -> str:
    return {
        "Невооружённым глазом": "Объект доступен невооружённым глазом.",
        "Бинокль": "Для наблюдения достаточно бинокля.",
        "Телескоп": "Для наблюдения потребуется телескоп.",
    }.get(instrument, "")


def _observing_paragraph(record: LiveRecord) -> list[str]:
    sky = record.observability or {}
    if not sky.get("visible"):
        note = sky.get("note")
        return [f"Условия наблюдения: {note}." if note else ""]
    lines = []
    if sky.get("best_time"):
        lines.append(f"Из города {sky['city']} объект лучше всего наблюдать "
                     f"{sky['best_time']:%d.%m около %H:%M} МСК.")
    if sky.get("max_altitude_deg") is not None:
        lines.append(f"Максимальная высота над горизонтом — "
                     f"{sky['max_altitude_deg']:.0f}°.")
    elif sky.get("altitude_deg") is not None:
        lines.append(f"Высота над горизонтом — {sky['altitude_deg']:.0f}°"
                     + (f", направление {sky['direction']}."
                        if sky.get("direction") else "."))
    phrase = _instrument_phrase(sky.get("instrument", ""))
    if phrase:
        lines.append(phrase)
    return [line for line in lines if line]


def _transient(record: LiveRecord) -> list[str]:
    payload = record.payload
    kind = payload.get("type") or ""
    head = f"🆕 {record.title}"
    body = []
    name = payload.get("name") or record.title
    host = payload.get("host_name")
    where = f" в галактике {host}" if host else ""
    if payload.get("discovery_mag") is not None:
        body.append(f"{name} обнаружен{where}. Блеск при открытии — "
                    f"{_magnitude(payload['discovery_mag'])}.")
    else:
        body.append(f"{name} обнаружен{where}.")
    if payload.get("constellation"):
        body.append(f"Объект находится в созвездии "
                    f"{payload['constellation']}.")
    body.append(f"Классификация: {kind}." if kind
                else "Классификация ещё не опубликована.")
    return [head, ""] + body


def _comet(record: LiveRecord) -> list[str]:
    payload = record.payload
    head = f"🆕 {record.title}"
    body = []
    current = payload.get("current_magnitude")
    if current is not None:
        body.append(f"Сейчас комета оценивается примерно в "
                    f"{_magnitude(current)}.")
    peak = payload.get("peak_magnitude")
    if peak is not None and payload.get("peak_when"):
        body.append(f"По элементам орбиты MPC ожидаемый максимум блеска — около "
                    f"{_magnitude(peak)}; это оценка модели, "
                    f"а не измерение.")
    if payload.get("perihelion"):
        body.append(f"Перигелий: {payload['perihelion'][:10]}"
                    + (f", на расстоянии "
                       f"{number(payload['perihelion_distance_au'], 2)} а.е. "
                       f"от Солнца."
                       if payload.get("perihelion_distance_au") else "."))
    if payload.get("closest_delta_au"):
        body.append(f"Минимальное расстояние от Земли — "
                    f"{number(payload['closest_delta_au'], 2)} а.е.")
    if payload.get("constellation"):
        body.append(f"Сейчас комета в созвездии {payload['constellation']}.")
    return [head, ""] + body


def _neo(record: LiveRecord) -> list[str]:
    payload = record.payload
    head = f"☄ Близкий пролёт астероида {payload.get('fullname') or ''}".strip()
    body = [record.summary + "."]
    if payload.get("velocity_km_s"):
        body.append("Относительная скорость — "
                    f"{number(payload['velocity_km_s'])} км/с.")
    if payload.get("absolute_magnitude_H") is not None:
        body.append("Размер оценён по абсолютной величине "
                    f"H={number(payload['absolute_magnitude_H'])}m "
                    f"и потому приблизителен.")
    return [head, ""] + body


def _occultation(record: LiveRecord) -> list[str]:
    payload = record.payload
    head = f"★ {record.title}"
    body = [record.summary + "."]
    if payload.get("event_local"):
        body.append(f"Момент: {payload['event_local'][11:16]} МСК "
                    f"{payload['event_local'][8:10]}.{payload['event_local'][5:7]}.")
    if payload.get("duration_sec"):
        body.append("Максимальная длительность — "
                    f"{number(payload['duration_sec'])} с.")
    if payload.get("path_width_km"):
        body.append(f"Ширина полосы — {payload['path_width_km']:.0f} км.")
    if payload.get("uncertainty_km"):
        body.append(f"Заявленная неопределённость положения полосы — "
                    f"±{payload['uncertainty_km']:.0f} км: точное место стоит "
                    f"уточнить ближе к дате.")
    return [head, ""] + body


BUILDERS = {KIND_TRANSIENT: _transient, KIND_COMET: _comet,
            KIND_NEO: _neo, KIND_OCCULTATION: _occultation}


def build(record: LiveRecord) -> str:
    """Готовый текст поста об одной записи ленты."""
    builder = BUILDERS.get(record.kind)
    lines = builder(record) if builder else [record.title, "", record.summary]
    observing = _observing_paragraph(record)
    if observing:
        lines += [""] + observing
    sources = [s for s in record.sources if s]
    if sources:
        lines += ["", "Источник: " + ", ".join(sources[:2])]
    text = "\n".join(lines).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text + "\n"
