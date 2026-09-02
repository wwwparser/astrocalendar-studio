"""Сетевой слой с кэшем, паузами между запросами и понятной ошибкой.

Живые источники (CNEOS, MPC, TNS, IOTA) опрашиваются из интерфейса, и без
общего слоя это быстро превращается в проблему: каждая перерисовка карточки
дёргает API, сервис отвечает 429, программа падает. Здесь один вход для всех
внешних запросов и три правила:

* **кэш на диске** с явным сроком годности — переход по карточкам ничего не
  запрашивает, обновление данных происходит только по кнопке «Обновить»;
* **пауза между обращениями к одному хосту** — чтобы не выглядеть как атака;
* **выдержка при 429 и 5xx** с ограниченным числом попыток, после чего
  возвращается понятный статус, а не исключение посреди расчёта.

Ответ всегда сопровождается временем получения: без него невозможно ни
показать возраст источника, ни записать provenance в QA-отчёт.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

from . import config as cfg

USER_AGENT = "AstroCalendarStudio/1.0 (+https://github.com/wwwparser/astrocalendar-studio)"

_last_request: dict[str, float] = {}


class NetworkError(RuntimeError):
    """Источник недоступен. Ловится вызывающим кодом, программу не роняет."""


class RateLimited(NetworkError):
    """Источник ограничил частоту запросов."""


@dataclass
class Response:
    """Ответ источника плюс всё, что нужно для provenance."""
    url: str
    body: str
    fetched_at: dt.datetime
    from_cache: bool = False
    status: int = 200
    headers: dict = field(default_factory=dict)

    @property
    def age_hours(self) -> float:
        return (dt.datetime.now(dt.timezone.utc)
                - self.fetched_at).total_seconds() / 3600.0

    def json(self):
        return json.loads(self.body)

    def provenance(self, name: str) -> dict:
        return {"source": name, "url": self.url,
                "source_updated_at": self.fetched_at.isoformat(),
                "from_cache": self.from_cache}


def _key(url: str, params: dict | None, data: dict | None) -> str:
    raw = json.dumps([url, params or {}, sorted((data or {}).keys())],
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _cache_path(key: str):
    cfg.NET_CACHE.mkdir(parents=True, exist_ok=True)
    return cfg.NET_CACHE / f"{key}.json"


def read_cache(key: str, ttl_hours: float | None) -> Response | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched = dt.datetime.fromisoformat(payload["fetched_at"])
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None
    age = (dt.datetime.now(dt.timezone.utc) - fetched).total_seconds() / 3600.0
    if ttl_hours is not None and age > ttl_hours:
        return None
    return Response(url=payload.get("url", ""), body=payload["body"],
                    fetched_at=fetched, from_cache=True,
                    status=payload.get("status", 200))


def write_cache(key: str, response: Response) -> None:
    try:
        _cache_path(key).write_text(json.dumps({
            "url": response.url, "status": response.status,
            "fetched_at": response.fetched_at.isoformat(),
            "body": response.body}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass          # кэш — удобство, а не условие работы


def _throttle(url: str) -> None:
    host = urlparse(url).netloc
    previous = _last_request.get(host)
    now = time.monotonic()
    if previous is not None:
        wait = cfg.NET_MIN_INTERVAL_S - (now - previous)
        if wait > 0:
            time.sleep(wait)
    _last_request[host] = time.monotonic()


def fetch(url: str, *, params: dict | None = None, data: dict | None = None,
          headers: dict | None = None, method: str = "GET",
          ttl_hours: float | None = 6.0, timeout: float = 60.0,
          retries: int | None = None, use_cache: bool = True) -> Response:
    """Запрос к внешнему источнику. Кэш, пауза, выдержка при 429.

    `ttl_hours=None` означает «кэш годен всегда» — так читаются файлы, которые
    обновляются вручную. `use_cache=False` заставляет сходить в сеть.
    """
    key = _key(url, params, data)
    if use_cache:
        cached = read_cache(key, ttl_hours)
        if cached is not None:
            return cached

    attempts = cfg.NET_RETRIES if retries is None else retries
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_error: Exception | None = None

    for attempt in range(max(1, attempts)):
        _throttle(url)
        try:
            if method.upper() == "POST":
                raw = requests.post(url, params=params, data=data,
                                    headers=request_headers, timeout=timeout)
            else:
                raw = requests.get(url, params=params, headers=request_headers,
                                   timeout=timeout)
        except requests.RequestException as error:
            last_error = error
            time.sleep(2 ** attempt)
            continue

        if raw.status_code == 429 or raw.status_code >= 500:
            # выдержка растёт, но не бесконечно: пользователь ждёт ответа
            wait = float(raw.headers.get("Retry-After") or 2 ** (attempt + 1))
            last_error = RateLimited(
                f"{urlparse(url).netloc} ответил {raw.status_code}")
            if attempt + 1 < attempts:
                time.sleep(min(wait, 30.0))
                continue
            break

        if raw.status_code >= 400:
            raise NetworkError(f"{urlparse(url).netloc} ответил "
                               f"{raw.status_code}: {raw.text[:200]}")

        response = Response(url=raw.url, body=raw.text,
                            fetched_at=dt.datetime.now(dt.timezone.utc),
                            status=raw.status_code, headers=dict(raw.headers))
        if use_cache:
            write_cache(key, response)
        return response

    # Сеть не отдала свежие данные. Если на диске есть просроченный ответ,
    # он лучше пустоты: устаревшие данные с честным возрастом — это данные,
    # а исключение посреди обновления Live обрушивает всю панель.
    stale = read_cache(key, None) if use_cache else None
    if stale is not None:
        return stale
    if isinstance(last_error, NetworkError):
        raise last_error
    raise NetworkError(f"{urlparse(url).netloc} недоступен: {last_error}")


def cached_age_hours(url: str, params: dict | None = None,
                     data: dict | None = None) -> float | None:
    """Возраст кэша для источника — для панели состояния данных."""
    cached = read_cache(_key(url, params, data), None)
    return cached.age_hours if cached else None
