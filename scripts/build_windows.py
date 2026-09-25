"""Сборка Windows-приложения AstroCalendar Studio.

    python scripts/build_windows.py                 # one-folder (по умолчанию)
    python scripts/build_windows.py --onefile       # один exe
    python scripts/build_windows.py --clean

Собирается вариант «одна папка»: приложение работает с эфемеридами и кэшем
каталогов, а распаковка сотен мегабайт во временный каталог при каждом запуске
one-file сборки делает старт заметно медленнее. Вариант --onefile оставлен, но
не используется по умолчанию.

Данные (эфемериды, каталоги, кэш) в сборку НЕ включаются: их место — рядом с
приложением, чтобы обновление каталога не требовало пересборки. Пути к ним
приложение ищет относительно каталога с exe.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
NAME = "AstroCalendarStudio"

HIDDEN_IMPORTS = [
    "astrocal", "astrocal_app", "astrocal_studio",
    # наблюдатели живой ленты импортируются внутри функций — статический
    # анализ PyInstaller их видит, но лучше назвать явно
    "astrocal.live", "astrocal.live.neo_watch", "astrocal.live.new_comets",
    "astrocal.live.transients", "astrocal.live.occultation_watch",
    "astrocal.live.discovery_service", "astrocal.live.post",
    "astrocal.qa_live", "astrocal.tns", "astrocal.net", "astrocal.secrets",
    "astrocal.events.close_approaches", "astrocal_app.livefeed",
    "astrocal_studio.guide", "astrocal_studio.widgets.live_panel",
    "skyfield", "skyfield.data.hipparcos", "skyfield.data.mpc",
    "skyfield.data.stellarium", "skyfield.eclipselib", "skyfield.magnitudelib",
    "skyfield.framelib", "skyfield.planetarylib", "sgp4",
    "matplotlib.backends.backend_agg",
    "pandas", "numpy", "requests",
]

# skyfield нужен целиком (в нём есть файлы данных), matplotlib — ради шрифтов
COLLECT_ALL = ["skyfield", "matplotlib"]

# Виртуальное окружение может быть общим на несколько проектов, и PyInstaller
# честно тянет в сборку всё, до чего дотянется. Тяжёлые пакеты, которые
# приложению не нужны, исключаем явно — иначе дистрибутив разрастается на
# гигабайты за счёт torch и подобного.
EXCLUDES = [
    "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtMultimedia", "PySide6.QtQuick",
    "PySide6.QtQml", "PySide6.Qt3DRender",
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_tkagg",
    "matplotlib.backends.backend_webagg",
    "torch", "torchvision", "torchaudio", "scipy", "sklearn", "sympy",
    "numba", "llvmlite", "cv2", "PIL.ImageQt",
    "IPython", "jupyter", "notebook", "nbformat", "pytest", "sphinx",
    "playwright", "selenium", "transformers", "tensorflow",
    # оформление таблиц pandas тянет jinja2 и падает в изолированном хуке
    # PyInstaller; приложению стилизация DataFrame не нужна
    "pandas.io.formats.style", "jinja2",
]


def entry_point() -> Path:
    """Точка входа: тонкая обёртка, которую понимает PyInstaller."""
    launcher = BUILD / "astrocalendar_studio_main.py"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(
        '"""Точка входа собранного приложения."""\n'
        "import multiprocessing\n"
        "import sys\n\n"
        "from astrocal_studio.app import main\n\n"
        "if __name__ == '__main__':\n"
        "    multiprocessing.freeze_support()\n"
        "    sys.exit(main())\n",
        encoding="utf-8")
    return launcher


def command(onefile: bool) -> list[str]:
    arguments = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--windowed", "--name", NAME,
        "--paths", str(SRC),
        "--distpath", str(DIST), "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--onefile" if onefile else "--onedir",
    ]
    for module in HIDDEN_IMPORTS:
        arguments += ["--hidden-import", module]
    for package in COLLECT_ALL:
        arguments += ["--collect-all", package]
    for module in EXCLUDES:
        arguments += ["--exclude-module", module]
    icon = ROOT / "docs" / "icon.ico"
    if icon.exists():
        arguments += ["--icon", str(icon)]
    arguments.append(str(entry_point()))
    return arguments


def check_data_files() -> list[str]:
    """Предупредить о том, чего не хватит приложению при запуске."""
    expected = {
        "data/de440s.bsp": "эфемериды планет и Луны",
        "data/jup380s.bsp": "галилеевы спутники",
        "data/cache/hip_bright.parquet": "каталог звёзд Hipparcos",
        "data/cache/constellationship.fab": "линии созвездий",
    }
    missing = [f"{path} — {what}" for path, what in expected.items()
               if not (ROOT / path).exists()]
    return missing


def main(argv: list[str]) -> int:
    onefile = "--onefile" in argv
    if "--clean" in argv:
        for path in (DIST / NAME, BUILD):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        print("Каталоги сборки очищены")

    missing = check_data_files()
    if missing:
        print("Внимание: рядом с приложением не хватает данных —")
        for item in missing:
            print(f"  · {item}")
        print("Приложение скачает недостающее при первом запуске, кроме "
              "эфемерид: их нужно положить в data/ вручную.\n")

    print(f"Сборка {NAME} ({'один файл' if onefile else 'одна папка'})…")
    result = subprocess.run(command(onefile), cwd=ROOT)
    if result.returncode != 0:
        print("PyInstaller завершился с ошибкой")
        return result.returncode

    target = DIST / f"{NAME}.exe" if onefile else DIST / NAME / f"{NAME}.exe"
    print(f"\nГотово: {target}")
    if not onefile:
        print("Данные в сборку не входят: при первом запуске приложение "
              "предложит их скачать.")
        print("Для раздачи пользователям: запакуйте всю папку "
              f"{DIST / NAME} в zip — exe без соседних файлов не работает.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
