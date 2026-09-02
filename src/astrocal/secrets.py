"""Доступ к учётным данным внешних сервисов.

Правило одно: ключи живут в `.env` рядом с проектом, `.env` в репозиторий не
попадает, а шаблон `.env.example` показывает, какие переменные нужны. В коде
ключей нет и быть не может.

Второе правило — про сообщения об ошибках. Отсутствие ключа должно приводить к
понятному тексту («в .env нет TNS_API_KEY»), а не к загадочному отказу
сервиса; и ни ключ, ни его часть никогда не попадают ни в текст ошибки, ни в
provenance, ни в QA-отчёт.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import config as cfg

_loaded = False


def load_env(path: Path | None = None, force: bool = False) -> None:
    """Минимальный разбор .env без внешних зависимостей."""
    global _loaded
    if _loaded and not force and path is None:
        return
    target = path or cfg.ROOT / ".env"
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    if path is None:
        _loaded = True


class MissingCredentials(RuntimeError):
    """Нужных ключей нет. Не ошибка сети и не повод падать — повод сказать."""

    def __init__(self, service: str, names: list[str]):
        self.service = service
        self.names = names
        super().__init__(
            f"{service}: в .env не заданы {', '.join(names)}. "
            f"Скопируйте .env.example в .env и впишите значения — "
            f"без них этот источник не опрашивается.")


def get(name: str) -> str | None:
    load_env()
    value = os.environ.get(name)
    return value.strip() if value else None


def require(service: str, *names: str) -> dict[str, str]:
    """Вернуть значения переменных или сказать, каких именно не хватает."""
    load_env()
    values, missing = {}, []
    for name in names:
        value = get(name)
        if not value:
            missing.append(name)
        else:
            values[name] = value
    if missing:
        raise MissingCredentials(service, missing)
    return values


def available(*names: str) -> bool:
    load_env()
    return all(get(name) for name in names)
