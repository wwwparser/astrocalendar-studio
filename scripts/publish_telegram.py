"""Публикация готового календаря в Telegram-канал.

Запуск:
    python scripts/publish_telegram.py 2026 9            # показать, что будет отправлено
    python scripts/publish_telegram.py 2026 9 --send     # отправить

Без флага --send скрипт ничего не отправляет: публикация в канал необратима,
и подтверждать её должен человек. Токен и канал берутся из .env
(см. .env.example), в код они не попадают.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg          # noqa: E402

API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_LIMIT = 4096


def load_env(path: Path = None) -> None:
    """Минимальный разбор .env — без зависимости от python-dotenv."""
    path = path or cfg.ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Режем по строкам: обрывать строку календаря посередине нельзя."""
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit and current:
            chunks.append(current.rstrip("\n"))
            current = ""
        current += line
    if current.strip():
        chunks.append(current.rstrip("\n"))
    return chunks


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    send = "--send" in argv
    year = int(args[0]) if args else cfg.YEAR
    month = int(args[1]) if len(args) > 1 else cfg.MONTH

    source = cfg.OUT / f"calendar_{year:04d}-{month:02d}.txt"
    if not source.exists():
        print(f"Нет файла {source}. Сначала: python scripts/build_calendar.py "
              f"{year} {month}")
        return 1
    text = source.read_text(encoding="utf-8")
    parts = split_message(text)

    print(f"{source}: {len(text.splitlines())} строк, {len(parts)} сообщение(й).")
    if not send:
        print("\n--- предпросмотр ---\n")
        print(text)
        print("--- конец ---\n")
        print("Ничего не отправлено. Для публикации добавьте флаг --send.")
        return 0

    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Нет TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID. "
              "Заполните .env по образцу .env.example.")
        return 1

    for i, chunk in enumerate(parts, 1):
        response = requests.post(API.format(token=token), timeout=30, json={
            "chat_id": chat, "text": chunk, "disable_web_page_preview": True})
        payload = response.json()
        if not payload.get("ok"):
            print(f"Ошибка на части {i}/{len(parts)}: {payload}")
            return 1
        print(f"Отправлено {i}/{len(parts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
