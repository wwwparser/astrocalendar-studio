"""Независимый источник №2 — JPL Horizons (observer-эфемериды, кэш на диске)."""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Iterable

import requests

from . import config as cfg

API = "https://ssd.jpl.nasa.gov/api/horizons.api"

# Коды тел в Horizons
CODES = {
    "mercury": "199", "venus": "299", "mars": "499", "jupiter": "599",
    "saturn": "699", "uranus": "799", "neptune": "899",
    "moon": "301", "sun": "10", "titan": "606",
    "io": "501", "europa": "502", "ganymede": "503", "callisto": "504",
}


def _cache_path(params: dict):
    key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
    return cfg.CACHE / f"horizons_{key}.txt"


def query(command: str, start: str, stop: str, step: str,
          quantities: str = "1,31", center: str = "500@399",
          timeout: int = 60, retries: int = 3) -> str:
    """Сырой текст ответа Horizons. Результат кэшируется в data/cache."""
    params = {
        "format": "text", "COMMAND": f"'{command}'", "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'", "EPHEM_TYPE": "'OBSERVER'", "CENTER": f"'{center}'",
        "START_TIME": f"'{start}'", "STOP_TIME": f"'{stop}'", "STEP_SIZE": f"'{step}'",
        "QUANTITIES": f"'{quantities}'", "ANG_FORMAT": "'DEG'", "CSV_FORMAT": "'YES'",
        "TIME_DIGITS": "'MINUTES'", "APPARENT": "'AIRLESS'",
    }
    path = _cache_path(params)
    if path.exists():
        return path.read_text(encoding="utf-8")
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(API, params=params, timeout=timeout)
            r.raise_for_status()
            path.write_text(r.text, encoding="utf-8")
            return r.text
        except Exception as exc:      # сеть/лимиты — пробуем ещё раз
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Horizons недоступен: {last}")


ROW = re.compile(r"^\s*(\d{4}-\w{3}-\d{2} \d{2}:\d{2}),")


def rows(text: str) -> Iterable[list[str]]:
    """Строки между $$SOE и $$EOE, разобранные по запятым."""
    inside = False
    for line in text.splitlines():
        if line.startswith("$$SOE"):
            inside = True
            continue
        if line.startswith("$$EOE"):
            break
        if inside and line.strip():
            yield [c.strip() for c in line.split(",")]
