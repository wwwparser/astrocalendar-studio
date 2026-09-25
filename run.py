"""Запуск AstroCalendar Studio из исходников: python run.py

Этот файл существует ради одного: чтобы программа запускалась сразу после
распаковки архива с кодом, без установки пакета и без настройки путей.

Пакеты лежат в `src/`, поэтому из корня репозитория `python -m astrocal_studio`
сам по себе не работает — Python там ничего не находит. Установка
(`pip install -e .`) это чинит, но требовать её от человека, которому нужно
просто посмотреть программу, неправильно. Здесь каталог `src` добавляется в
пути импорта явно.

Если чего-то не хватает, скрипт говорит об этом человеческим языком, а не
роняет traceback: «нет PySide6 — выполните pip install -r requirements.txt».
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

REQUIRED = {
    "PySide6": "PySide6 — библиотека интерфейса",
    "skyfield": "skyfield — расчёт положений небесных тел",
    "numpy": "numpy — вычисления",
    "pandas": "pandas — работа с каталогами",
    "matplotlib": "matplotlib — построение карт",
    "requests": "requests — загрузка данных",
}


def missing_packages() -> list[str]:
    from importlib.util import find_spec

    absent = []
    for module, description in REQUIRED.items():
        if find_spec(module) is None:
            absent.append(description)
    return absent


def main() -> int:
    if not SRC.is_dir():
        print("Рядом с run.py нет каталога src — похоже, архив распакован "
              "не полностью.")
        return 2

    sys.path.insert(0, str(SRC))

    absent = missing_packages()
    if absent:
        print("Не хватает библиотек:\n")
        for item in absent:
            print(f"  · {item}")
        print("\nУстановите их одной командой:\n")
        print("    pip install -r requirements.txt\n")
        print("Если команда pip не найдена, попробуйте:\n")
        print("    python -m pip install -r requirements.txt\n")
        return 1

    from astrocal_studio.app import main as run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
