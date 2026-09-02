"""Точка сборки приложения: QApplication, тема, главное окно."""
from __future__ import annotations

import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from . import theme
from .main_window import APPLICATION, ORGANISATION, MainWindow


def create_application(argv: list[str] | None = None) -> QApplication:
    """QApplication с настройками, общими для всех запусков."""
    existing = QApplication.instance()
    if existing is not None:
        return existing
    # Windows масштабирует интерфейс на 125/150/200%: округление до целых
    # пикселей делает шрифты чёткими и не ломает разметку
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    application = QApplication(argv if argv is not None else sys.argv)
    application.setOrganizationName(ORGANISATION)
    application.setApplicationName(APPLICATION)
    application.setWindowIcon(QIcon())
    # Явный шрифт: у Qt на Windows подбор по умолчанию иногда даёт гарнитуру
    # без кириллицы, и интерфейс превращается в квадраты
    font = QFont("Segoe UI", 9)
    font.setStyleHint(QFont.SansSerif)
    application.setFont(font)
    return application


def main(argv: list[str] | None = None) -> int:
    application = create_application(argv)
    settings = QSettings(ORGANISATION, APPLICATION)
    theme_name = str(settings.value("theme", "dark"))
    application.setStyleSheet(theme.stylesheet(theme_name))
    window = MainWindow(theme_name)
    window.show()
    return application.exec()
