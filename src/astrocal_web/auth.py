"""Вход по логину и паролю.

Сайт закрыт целиком: без входа не отдаётся ни одна страница, кроме самой формы
входа. Пользователей немного и заводит их администратор — регистрации нет,
восстановления пароля нет. Это осознанно: чем меньше путей внутрь, тем меньше
способов туда попасть постороннему.

Пароли хранятся как scrypt-хэш с индивидуальной солью. scrypt взят из
стандартной библиотеки: он требует памяти, а не только процессора, поэтому
перебор на видеокартах даётся дорого, и лишней зависимости в проект не
приходит. Сам пароль не хранится нигде и не пишется в логи.

Защита от подбора — задержка после неудачных попыток по паре «логин + адрес».
Пять ошибок подряд закрывают вход на пятнадцать минут. Ответ при неверном
логине и при неверном пароле одинаковый: иначе форма подсказывает, какие
логины существуют.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from astrocal import config as cfg

USERS_FILE = cfg.DATA / "web_users.json"

# Параметры scrypt: N=2^15 при r=8 требует около 32 МБ памяти на проверку.
# Для входа раз в день это незаметно, для перебора — существенно.
SCRYPT_N = 1 << 15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LENGTH = 32
SALT_BYTES = 16
# OpenSSL по умолчанию не даёт scrypt больше 32 МБ, а N=2^15 при r=8 требует
# ровно столько. Предел поднимаем явно, иначе вызов падает.
SCRYPT_MAXMEM = 96 * 1024 * 1024

MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class AuthError(RuntimeError):
    """Вход невозможен. Текст предназначен пользователю."""


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Соль и хэш пароля в шестнадцатеричном виде."""
    if not password or len(password) < 8:
        raise AuthError("пароль короче восьми символов")
    salt = salt or secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            dklen=KEY_LENGTH, maxmem=SCRYPT_MAXMEM)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    """Сравнение за постоянное время: иначе по задержке ответа подбирают хэш."""
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            dklen=KEY_LENGTH, maxmem=SCRYPT_MAXMEM)
    return hmac.compare_digest(digest.hex(), hash_hex)


@dataclass
class User:
    name: str
    salt: str
    digest: str
    created_at: str = ""
    last_login: str = ""
    comment: str = ""

    def as_dict(self) -> dict:
        return {"salt": self.salt, "hash": self.digest,
                "created_at": self.created_at, "last_login": self.last_login,
                "comment": self.comment}


@dataclass
class UserStore:
    """Файл с пользователями. Права на него — только у владельца."""
    path: Path = field(default_factory=lambda: USERS_FILE)

    def load(self) -> dict[str, User]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return {name: User(name=name, salt=record.get("salt", ""),
                           digest=record.get("hash", ""),
                           created_at=record.get("created_at", ""),
                           last_login=record.get("last_login", ""),
                           comment=record.get("comment", ""))
                for name, record in (payload.get("users") or {}).items()}

    def save(self, users: dict[str, User]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": 1,
                   "users": {name: user.as_dict()
                             for name, user in sorted(users.items())}}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        try:                                   # файл с хэшами — не для всех
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------ операции

    def add(self, name: str, password: str, comment: str = "") -> User:
        name = name.strip().lower()
        if not name:
            raise AuthError("пустое имя пользователя")
        users = self.load()
        if name in users:
            raise AuthError(f"пользователь «{name}» уже существует")
        salt, digest = hash_password(password)
        user = User(name=name, salt=salt, digest=digest,
                    created_at=dt.datetime.now(cfg.MSK).isoformat(),
                    comment=comment)
        users[name] = user
        self.save(users)
        return user

    def set_password(self, name: str, password: str) -> None:
        name = name.strip().lower()
        users = self.load()
        if name not in users:
            raise AuthError(f"пользователя «{name}» нет")
        salt, digest = hash_password(password)
        users[name].salt = salt
        users[name].digest = digest
        self.save(users)

    def remove(self, name: str) -> bool:
        users = self.load()
        if name.strip().lower() not in users:
            return False
        users.pop(name.strip().lower())
        self.save(users)
        return True

    def names(self) -> list[str]:
        return sorted(self.load())

    def mark_login(self, name: str) -> None:
        users = self.load()
        user = users.get(name)
        if user is None:
            return
        user.last_login = dt.datetime.now(cfg.MSK).isoformat()
        self.save(users)


# ------------------------------------------------------------------ попытки


@dataclass
class Attempts:
    """Счётчик неудачных попыток входа, в памяти процесса."""
    failures: dict = field(default_factory=dict)

    def key(self, name: str, address: str) -> str:
        return f"{name.strip().lower()}@{address}"

    def locked_for(self, name: str, address: str) -> float:
        record = self.failures.get(self.key(name, address))
        if not record or record["count"] < MAX_ATTEMPTS:
            return 0.0
        passed = (dt.datetime.now(dt.timezone.utc)
                  - record["last"]).total_seconds()
        left = LOCKOUT_MINUTES * 60 - passed
        return max(0.0, left)

    def note_failure(self, name: str, address: str) -> None:
        key = self.key(name, address)
        record = self.failures.setdefault(
            key, {"count": 0, "last": dt.datetime.now(dt.timezone.utc)})
        # после истечения блокировки счётчик начинается заново
        if (record["count"] >= MAX_ATTEMPTS
                and self.locked_for(name, address) <= 0):
            record["count"] = 0
        record["count"] += 1
        record["last"] = dt.datetime.now(dt.timezone.utc)

    def reset(self, name: str, address: str) -> None:
        self.failures.pop(self.key(name, address), None)


ATTEMPTS = Attempts()


def authenticate(name: str, password: str, address: str = "",
                 store: UserStore | None = None) -> User:
    """Проверить логин и пароль. Бросает AuthError с текстом для человека."""
    store = store or UserStore()
    name = (name or "").strip().lower()

    left = ATTEMPTS.locked_for(name, address)
    if left > 0:
        raise AuthError(f"слишком много неудачных попыток, "
                        f"подождите {left / 60:.0f} мин")

    users = store.load()
    user = users.get(name)
    # Проверку выполняем даже для несуществующего логина: иначе по времени
    # ответа видно, какие имена заведены.
    salt = user.salt if user else secrets.token_bytes(SALT_BYTES).hex()
    digest = user.digest if user else "0" * (KEY_LENGTH * 2)
    correct = verify_password(password or "", salt, digest)

    if not user or not correct:
        ATTEMPTS.note_failure(name, address)
        raise AuthError("неверный логин или пароль")

    ATTEMPTS.reset(name, address)
    store.mark_login(name)
    return user


def session_secret() -> str:
    """Ключ подписи сессионной куки.

    Берётся из окружения. Если его нет, приложение не стартует: со случайным
    ключом каждый перезапуск разлогинивал бы всех, а с постоянным значением в
    коде подделать куку смог бы кто угодно.
    """
    from astrocal.secrets import get, load_env

    load_env()
    value = get("ASTROCAL_WEB_SECRET") or os.environ.get("ASTROCAL_WEB_SECRET")
    if not value or len(value) < 32:
        raise AuthError(
            "не задан ASTROCAL_WEB_SECRET (не короче 32 символов). "
            "Сгенерируйте: python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\" и впишите в .env")
    return value
