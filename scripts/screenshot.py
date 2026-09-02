"""Снимок главного окна для документации.

Запускает интерфейс без участия человека, наполняет его настоящим выпуском и
сохраняет PNG. Используется в README и как грубая проверка того, что окно
собирается и наполняется данными.

    python scripts/screenshot.py 2026 9 docs/screenshot.png
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# На Windows окно рисуется настоящим бэкендом — иначе в снимке не будет
# кириллических шрифтов. Offscreen оставляем как запасной вариант.
if os.environ.get("ASTUDIO_OFFSCREEN"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer                       # noqa: E402

from astrocal_app import service, workspace             # noqa: E402
from astrocal_studio import theme                       # noqa: E402
from astrocal_studio.app import create_application      # noqa: E402
from astrocal_studio.main_window import MainWindow      # noqa: E402


def main(argv: list[str]) -> int:
    year = int(argv[0]) if argv else 2026
    month = int(argv[1]) if len(argv) > 1 else 9
    target = Path(argv[2]) if len(argv) > 2 else Path("docs/screenshot.png")
    theme_name = argv[3] if len(argv) > 3 else "dark"

    print(f"Считаю выпуск {month:02d}.{year}…")
    issue = service.compute_issue(year, month, use_horizons=False,
                                  progress=lambda stage, percent:
                                  print(f"  {percent:3d}% {stage}", flush=True))
    workspace.load_into(issue)

    application = create_application([])
    application.setStyleSheet(theme.stylesheet(theme_name))
    window = MainWindow(theme_name)
    window.resize(1680, 980)
    # снимок должен показывать раскладку по умолчанию, а не ту, что осталась
    # в настройках от предыдущих запусков
    window.splitter.setSizes([290, 900, 470])
    window.show()

    window.issue = issue
    window.parameters.set_period(year, month)
    window.parameters.set_enabled_kinds(issue.enabled_kinds)
    window.parameters.set_enabled_ranks(issue.enabled_ranks)
    window.apply_filters()
    window.qa_panel.show_issue(issue)
    if window.table.model.rowCount():
        window.table.view.selectRow(0)

    target.parent.mkdir(parents=True, exist_ok=True)

    def grab() -> None:
        window.grab().save(str(target))
        print(f"Снимок сохранён: {target}")
        application.quit()

    QTimer.singleShot(700, grab)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
