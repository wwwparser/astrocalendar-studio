"""Клиент Transient Name Server (TNS).

TNS — официальный реестр новых и сверхновых: там объект получает имя (SN 2026xy)
и там же публикуется классификация. Открытый доступ есть, но только по ключу
бота: сервис требует api_key и заголовок с идентификатором бота, иначе отвечает
отказом. Ключи берутся из `.env` (`TNS_API_KEY`, `TNS_BOT_ID`, `TNS_BOT_NAME`)
и в репозиторий не попадают.

Опрос делается инкрементально: у поиска есть параметр `public_timestamp`, и
запрашиваются только объекты, опубликованные после прошлого обновления. Иначе
каждый раз пришлось бы выкачивать десятки тысяч записей.

Формат ответа у TNS менялся: в одних версиях `data` — это словарь с ключом
`reply`, в других сразу список. Разбор учитывает оба варианта.
"""
from __future__ import annotations

import datetime as dt
import json

from .net import NetworkError, fetch
from .secrets import MissingCredentials, require   # noqa: F401 — часть публичного API

BASE = "https://www.wis-tns.org/api/get"
SEARCH = f"{BASE}/search"
OBJECT = f"{BASE}/object"
SERVICE = "TNS"


def credentials() -> dict[str, str]:
    """Ключи TNS из .env. Бросает MissingCredentials, если их нет."""
    return require(SERVICE, "TNS_API_KEY", "TNS_BOT_ID", "TNS_BOT_NAME")


def configured() -> bool:
    try:
        credentials()
    except MissingCredentials:
        return False
    return True


def _headers(values: dict[str, str]) -> dict[str, str]:
    marker = json.dumps({"tns_id": values["TNS_BOT_ID"], "type": "bot",
                         "name": values["TNS_BOT_NAME"]})
    return {"User-Agent": f"tns_marker{marker}"}


def _reply(payload: dict):
    """Полезная часть ответа при любом из известных форматов."""
    data = payload.get("data")
    if isinstance(data, dict):
        return data.get("reply", data)
    return data


def _post(url: str, values: dict[str, str], data: dict,
          ttl_hours: float, use_cache: bool):
    body = {"api_key": values["TNS_API_KEY"],
            "data": json.dumps(data, ensure_ascii=False)}
    response = fetch(url, method="POST", data=body, headers=_headers(values),
                     ttl_hours=ttl_hours, use_cache=use_cache, timeout=90.0)
    try:
        payload = response.json()
    except json.JSONDecodeError as error:
        raise NetworkError(f"TNS вернул не JSON: {error}") from error
    code = (payload.get("id_code") or payload.get("id_message")
            or payload.get("status", 200))
    if isinstance(code, int) and code >= 400:
        raise NetworkError(f"TNS ответил кодом {code}")
    return _reply(payload), response


def search(since: dt.datetime | None = None, limit: int = 200,
           use_cache: bool = True, ttl_hours: float = 1.0) -> tuple[list[dict], str]:
    """Список объектов, опубликованных после `since`.

    Возвращает записи вида {"objname": "2026abc", "prefix": "SN"} и время
    получения ответа — для provenance и панели свежести данных.
    """
    values = credentials()
    data: dict = {"num_page": min(limit, 200)}
    if since is not None:
        data["public_timestamp"] = since.astimezone(
            dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    reply, response = _post(SEARCH, values, data, ttl_hours, use_cache)
    records = reply if isinstance(reply, list) else []
    return records, response.fetched_at.isoformat()


def details(objname: str, use_cache: bool = True,
            ttl_hours: float = 24.0) -> dict:
    """Полная карточка объекта TNS."""
    values = credentials()
    reply, _response = _post(OBJECT, values,
                             {"objname": objname, "photometry": "0",
                              "spectra": "0"}, ttl_hours, use_cache)
    return reply if isinstance(reply, dict) else {}


def name_of(record: dict) -> str:
    """Имя объекта с префиксом: «SN 2026abc»."""
    prefix = (record.get("prefix") or record.get("name_prefix") or "").strip()
    name = str(record.get("objname") or record.get("name") or "").strip()
    return f"{prefix} {name}".strip()
