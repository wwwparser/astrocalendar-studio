"""Сквозная проверка Binocular Sky по сценарию MVP.

Прогоняет тот же путь, что и человек: открыть, выбрать ночь, посчитать «что
посмотреть», выбрать объект, посмотреть поле бинокля, построить траекторию,
добавить в план, сохранить и перечитать профиль. В конце снимает окно.

Запуск:
    python scripts/smoke_binocular_sky.py [--screenshot out/binocular_sky.png]

По умолчанию используется отдельный каталог профиля, чтобы не трогать настоящий.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot",
                        default=str(ROOT / "out" / "binocular_sky.png"))
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--home", default="")
    parser.add_argument("--date", default="")
    options = parser.parse_args()

    os.environ["BINOCULAR_SKY_HOME"] = options.home or os.path.join(
        tempfile.gettempdir(), "BinocularSkySmoke")
    if options.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from binocular_sky.app import configure_webengine
    configure_webengine()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from binocular_sky import storage
    from binocular_sky.main_window import MainWindow

    app = QApplication([])
    settings = storage.load()
    settings.wizard_done = True
    # проверяем на демонстрационном участке: на нём есть дом и деревья, то есть
    # проверяется именно перекрытие неба, а не пустая площадка
    settings.active_observer = next(
        (i for i, o in enumerate(settings.observers) if o.is_demo), 0)

    window = MainWindow(settings)
    window.show()

    console: list[str] = []
    window.sky_view.console_message.connect(console.append)

    date = dt.date.fromisoformat(options.date) if options.date else dt.date.today()
    report: list[str] = []
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        report.append(("OK     " if condition else "ПРОВАЛ ") + message)
        if not condition:
            failures.append(message)

    # ---------------------------------------------------------------- шаги

    def step_start() -> None:
        window.set_date(date)
        check(window.night is not None, f"ночь на {date} рассчитана")
        check(window.horizon.max_altitude_deg > 5,
              f"маска участка построена, максимум "
              f"{window.horizon.max_altitude_deg:.0f}°")
        window.compute_tonight()

    def step_tonight(recommendations) -> None:
        check(len(recommendations) >= 5,
              f"«что посмотреть сегодня» вернуло {len(recommendations)} объектов")
        for item in recommendations[:8]:
            report.append(f"        {item.stars_text} {item.score:3d} "
                          f"{item.target.name} — {item.window_text}")
        if not recommendations:
            finish()
            return
        window.select_target(recommendations[0].target.id)
        QTimer.singleShot(2500, step_object)

    def step_object() -> None:
        current = window.current
        check(current is not None, "карточка объекта заполнена")
        if current is None:
            finish()
            return
        report.append(f"        выбран: {current.target.name}, "
                      f"аз. {current.azimuth_deg:.0f}°, "
                      f"выс. {current.altitude_deg:.0f}°")

        blocked = find_blocked()
        check(blocked is not None,
              "найден объект, закрытый домом или деревьями"
              + (f": {blocked}" if blocked else ""))

        window.binocular_action.setChecked(True)
        check(window.binocular_mode, "режим «вид в бинокль» включён")

        from binocular_sky.services import scene_service
        field = scene_service.binocular_field(
            window.observer, window.binocular, current.target,
            window.timeline.moment)
        check(abs(field["fov_deg"] - window.binocular.field_of_view_deg) < 1e-6,
              f"поле зрения в виде бинокля равно {field['fov_deg']}°")
        check(len(field["stars"]) > 0,
              f"в поле бинокля {len(field['stars'])} звёзд")

        window.show_track()
        window.add_to_plan(current.target.id)
        window.optimise_plan()
        check(len(window.settings.plan_for(window.date).items) == 1,
              "объект добавлен в план и упорядочен")

        window.save()
        restored = storage.load()
        check(restored.observer.name == window.observer.name
              and window.date.isoformat() in restored.plans,
              "профиль и план сохраняются и перечитываются")

        QTimer.singleShot(1500, step_shot_binocular)

    def find_blocked() -> str | None:
        from binocular_sky.services import astronomy_service as astro
        for target in astro.solar_targets(window.timeline.moment):
            try:
                altitude, azimuth = astro.altaz_at(window.observer, target,
                                                   window.timeline.moment)
            except Exception:
                continue
            floor = window.horizon.altitude_at(azimuth)
            if 0 < altitude <= floor:
                return (f"{target.name} на высоте {altitude:.0f}° "
                        f"при горизонте участка {floor:.0f}°")
        return None

    # ---------------------------------------------------------------- снимки

    def step_shot_binocular() -> None:
        base = Path(options.screenshot)
        capture(base.with_name(base.stem + "_binocular" + base.suffix),
                then=step_shot_sky)

    def step_shot_sky() -> None:
        window.binocular_action.setChecked(False)
        QTimer.singleShot(1200,
                          lambda: capture(Path(options.screenshot), then=finish))

    def capture(path: Path, then=None) -> None:
        """Снять сцену.

        Снимается именно холст 3D-вида, а не экран: `QWidget.grab()` не
        забирает содержимое QWebEngineView (оно рисуется отдельным
        композитором), а снимок всего экрана захватил бы посторонние окна.
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        def save(image) -> None:
            ok = bool(image is not None and image.save(str(path)))
            check(ok, f"снимок сцены сохранён: {path}")
            if then is not None:
                QTimer.singleShot(300, then)

        window.sky_view.capture_image(save)

    # ---------------------------------------------------------------- итог

    def finish() -> None:
        errors = [line for line in console if "rror" in line]
        check(not errors,
              "в консоли 3D-сцены нет ошибок" + (f": {errors[:3]}" if errors else ""))
        for line in console[:8]:
            report.append(f"        консоль: {line}")
        print("\n".join(report))
        print("\nИТОГ:", "всё прошло" if not failures
              else f"провалов {len(failures)}")
        app.exit(1 if failures else 0)

    window.tonight_runner.finished.connect(step_tonight)
    window.tonight_runner.failed.connect(
        lambda message: (check(False, "расчёт ночи: "
                               + message.strip().splitlines()[-1]), finish()))
    for runner in (window.snapshot_runner, window.detail_runner):
        runner.failed.connect(
            lambda message: check(False, "фоновая задача: "
                                  + message.strip().splitlines()[-1]))

    QTimer.singleShot(2500, step_start)
    QTimer.singleShot(150000, finish)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
