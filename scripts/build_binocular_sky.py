"""Сборка Windows-приложения Binocular Sky.

    python scripts/build_binocular_sky.py            # одна папка (по умолчанию)
    python scripts/build_binocular_sky.py --clean
    python scripts/build_binocular_sky.py --onefile  # не рекомендуется

Собирается вариант «одна папка». Приложение тащит за собой Chromium из
QtWebEngine — это сотни мегабайт, и распаковывать их во временный каталог при
каждом запуске one-file сборки значит ждать старта минуту. Вариант --onefile
оставлен, но по умолчанию не используется.

Данные (эфемериды, каталоги, кэш) в сборку НЕ включаются: их место — каталог
`data/` рядом с exe, чтобы обновление каталога не требовало пересборки.
Ресурсы самой сцены (three.js, HTML, JS) наоборот включаются: без них
приложение не работает вовсе, а интернета на даче может не быть.
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
NAME = "BinocularSky"
WEB = SRC / "binocular_sky" / "web"

HIDDEN_IMPORTS = [
    "binocular_sky", "binocular_sky.app", "binocular_sky.main_window",
    "binocular_sky.storage", "binocular_sky.theme", "binocular_sky.workers",
    "binocular_sky.models", "binocular_sky.services",
    "binocular_sky.services.astronomy_service",
    "binocular_sky.services.catalog_service",
    "binocular_sky.services.horizon_service",
    "binocular_sky.services.observing_service",
    "binocular_sky.services.recommendation_service",
    "binocular_sky.services.scene_service",
    "binocular_sky.widgets.sky_view", "binocular_sky.widgets.timeline",
    "binocular_sky.widgets.tonight_panel", "binocular_sky.widgets.plan_panel",
    "binocular_sky.widgets.object_details",
    "binocular_sky.widgets.binocular_panel",
    "binocular_sky.widgets.settings_panel",
    # астрономическое ядро общего проекта
    "astrocal", "astrocal.core", "astrocal.catalogs", "astrocal.constellations",
    "astrocal.magnitudes", "astrocal.observing", "astrocal.config",
    "astrocal.events.comets", "astrocal.events.jupiter_moons",
    "skyfield", "skyfield.data.hipparcos", "skyfield.data.mpc",
    "skyfield.data.stellarium", "skyfield.magnitudelib", "skyfield.almanac",
    "pandas", "numpy", "requests", "pyarrow",
    # трёхмерная сцена живёт в QWebEngineView; без явного указания
    # PyInstaller не подхватит ни Chromium, ни мост QWebChannel
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
]

COLLECT_ALL = ["skyfield"]

# Из общего виртуального окружения PyInstaller тянет всё, до чего дотянется.
# Здесь перечислено то, что Binocular Sky заведомо не нужно: matplotlib нужен
# только календарным картам, остальное — чужие тяжёлые пакеты.
EXCLUDES = [
    "tkinter", "PyQt5", "PyQt6", "PySide2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
    "matplotlib", "astrocal_studio", "astrocal_app",
    "torch", "torchvision", "torchaudio", "scipy", "sklearn", "sympy",
    "numba", "llvmlite", "cv2", "IPython", "jupyter", "notebook", "nbformat",
    "pytest", "sphinx", "playwright", "selenium", "transformers", "tensorflow",
    "pandas.io.formats.style", "jinja2",
]


def entry_point() -> Path:
    launcher = BUILD / "binocular_sky_main.py"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(
        '"""Точка входа собранного приложения."""\n'
        "import multiprocessing\n"
        "import sys\n\n"
        "from binocular_sky.app import main\n\n"
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
        # ресурсы сцены кладутся туда же, где их ищет виджет
        "--add-data", f"{WEB}{';' if sys.platform == 'win32' else ':'}"
                      f"binocular_sky/web",
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


def check_resources() -> list[str]:
    """То, без чего собранное приложение не запустится или будет неполным."""
    problems = []
    for name in ("index.html", "app.js", "sky.js", "terrain.js", "objects.js",
                 "binocular.js", "labels.js", "styles.css",
                 "vendor/three.module.min.js"):
        if not (WEB / name).exists():
            problems.append(f"src/binocular_sky/web/{name} — ресурс 3D-сцены")
    for path, what in {
        "data/de440s.bsp": "эфемериды планет и Луны",
        "data/jup380s.bsp": "галилеевы спутники Юпитера",
        "data/cache/hip_bright.parquet": "каталог звёзд Hipparcos",
        "data/cache/NGC.csv": "каталог объектов OpenNGC",
        "data/cache/constellationship.fab": "фигуры созвездий",
    }.items():
        if not (ROOT / path).exists():
            problems.append(f"{path} — {what}")
    return problems


def main(argv: list[str]) -> int:
    onefile = "--onefile" in argv
    if "--clean" in argv:
        for path in (DIST / NAME, BUILD / "work"):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        print("Каталоги сборки очищены")

    problems = check_resources()
    fatal = [p for p in problems if p.startswith("src/")]
    if fatal:
        print("Не хватает ресурсов сцены — сборка бессмысленна:")
        for item in fatal:
            print(f"  · {item}")
        return 2
    for item in problems:
        print(f"Внимание: нет {item}")
    if problems:
        print("Каталоги данных положите рядом с exe: приложение ищет их "
              "относительно себя.\n")

    print(f"Сборка {NAME} ({'один файл' if onefile else 'одна папка'})…")
    result = subprocess.run(command(onefile), cwd=ROOT)
    if result.returncode != 0:
        print("PyInstaller завершился с ошибкой")
        return result.returncode

    target = DIST / f"{NAME}.exe" if onefile else DIST / NAME / f"{NAME}.exe"
    print(f"\nГотово: {target}")
    if not onefile:
        print("Рядом с exe положите каталог data/ (эфемериды и кэш каталогов).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
