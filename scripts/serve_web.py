"""Запуск веб-версии.

    python scripts/serve_web.py                  # 127.0.0.1:8120
    python scripts/serve_web.py --host 0.0.0.0 --port 8120
    python scripts/serve_web.py --dev            # без HTTPS-куки, с перезагрузкой

По умолчанию слушает только локальный адрес: наружу сайт смотрит через
обратный прокси, который держит сертификат. Открывать порт приложения в
интернет напрямую не нужно.

Перед первым запуском нужны две вещи: ключ подписи сессий в `.env`
(`ASTROCAL_WEB_SECRET`) и хотя бы один пользователь
(`python scripts/web_user.py add <имя>`).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Веб-версия AstroCalendar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8120)
    parser.add_argument("--dev", action="store_true",
                        help="разработка: кука без требования HTTPS")
    arguments = parser.parse_args(argv)

    if arguments.dev:
        # Без этого браузер не сохранит сессионную куку на http://localhost
        os.environ["ASTROCAL_WEB_INSECURE"] = "1"

    from astrocal_web.auth import AuthError, UserStore

    try:
        from astrocal_web.app import create_app
        application = create_app()
    except AuthError as error:
        print(f"Не могу запуститься: {error}")
        return 1

    if not UserStore().names():
        print("Внимание: пользователей нет, войти будет некому.")
        print("Заведите: python scripts/web_user.py add <имя>")

    import uvicorn

    print(f"AstroCalendar: http://{arguments.host}:{arguments.port}")
    uvicorn.run(application, host=arguments.host, port=arguments.port,
                proxy_headers=True, forwarded_allow_ips="*",
                log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
