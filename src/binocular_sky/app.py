"""Запуск приложения Binocular Sky."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Приложение должно работать и из исходников, и из собранного дистрибутива,
# где `src` в путь не попадает автоматически.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def configure_webengine() -> None:
    """Флаги Chromium до создания QApplication.

    Отключаем сетевые сервисы: сцена целиком локальная, и попытки браузерного
    движка ходить в интернет на даче с плохой связью только тормозят запуск.
    """
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    extra = "--disable-background-networking --disable-component-update"
    if extra not in flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{flags} {extra}".strip()


def main(argv: list[str] | None = None) -> int:
    configure_webengine()

    from PySide6.QtWidgets import QApplication

    from . import APP_NAME, storage
    from .main_window import MainWindow

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("BinocularSky")

    settings = storage.load()
    window = MainWindow(settings)
    window.show()

    if not settings.wizard_done:
        # первый запуск: спрашиваем место и прибор, участок можно пропустить
        window.run_wizard()

    return app.exec()
