"""Управление пользователями веб-версии.

    python scripts/web_user.py list
    python scripts/web_user.py add stas
    python scripts/web_user.py passwd stas
    python scripts/web_user.py remove stas

Пароль спрашивается скрытым вводом. Передать его аргументом нельзя намеренно:
аргументы видны в списке процессов и остаются в истории оболочки.

Для развёртывания без терминала пароль можно передать через переменную
окружения ASTROCAL_WEB_PASSWORD — тогда он не попадёт ни в историю, ни в
список процессов.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal_web.auth import AuthError, UserStore      # noqa: E402


def ask_password(confirm: bool = True) -> str:
    from_env = os.environ.get("ASTROCAL_WEB_PASSWORD")
    if from_env:
        return from_env
    password = getpass.getpass("Пароль (не короче 8 символов): ")
    if confirm and password != getpass.getpass("Ещё раз: "):
        raise AuthError("пароли не совпали")
    return password


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, *rest = argv
    store = UserStore()

    if command == "list":
        users = store.load()
        if not users:
            print("Пользователей нет. Заведите: python scripts/web_user.py add <имя>")
            return 0
        for name, user in sorted(users.items()):
            last = user.last_login[:16].replace("T", " ") if user.last_login \
                else "ни разу"
            print(f"  {name:20} создан {user.created_at[:10]}  "
                  f"вход: {last}  {user.comment}")
        return 0

    if not rest:
        print("Не указано имя пользователя")
        return 2
    name = rest[0]
    comment = " ".join(rest[1:])

    try:
        if command == "add":
            store.add(name, ask_password(), comment)
            print(f"Пользователь «{name}» создан")
        elif command == "passwd":
            store.set_password(name, ask_password())
            print(f"Пароль пользователя «{name}» изменён")
        elif command == "remove":
            print(f"Пользователь «{name}» удалён" if store.remove(name)
                  else f"Пользователя «{name}» нет")
        else:
            print(f"Неизвестная команда: {command}")
            return 2
    except AuthError as error:
        print(f"Ошибка: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
