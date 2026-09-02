"""Отправка публикации в Telegram.

Общий код для GUI и командной строки: токен читается из `.env`, в репозиторий
он не попадает. Отправка намеренно вынесена в отдельный модуль — так её видно
и легко проверить, а случайно вызвать из расчётного кода нельзя.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from astrocal import config as cfg
from astrocal.telegram import Publication

API = "https://api.telegram.org/bot{token}/sendMessage"


def load_env(path: Path | None = None) -> None:
    """Минимальный разбор .env без внешних зависимостей."""
    target = path or cfg.ROOT / ".env"
    if not target.exists():
        return
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def credentials() -> tuple[str | None, str | None]:
    load_env()
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


def send(publication: Publication) -> str:
    """Отправить все части публикации. Действие необратимо."""
    token, chat = credentials()
    if not token or not chat:
        raise RuntimeError(
            "В .env нет TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID "
            "(шаблон — .env.example)")
    for part in publication.parts:
        response = requests.post(API.format(token=token), timeout=30, json={
            "chat_id": chat, "text": part.text, "disable_web_page_preview": True})
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram отклонил часть {part.index}: {payload}")
    return f"Отправлено сообщений: {len(publication.parts)}"
