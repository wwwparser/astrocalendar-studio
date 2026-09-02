"""Дымовые тесты интерфейса.

Тесты не требуют ни одного ручного клика: окно создаётся в offscreen-режиме,
наполняется заранее собранным выпуском и проверяется через публичные методы
виджетов. Астрономия здесь не считается — иначе тесты шли бы минутами.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from astrocal.config import MSK                            # noqa: E402
from astrocal.core import Event                            # noqa: E402
from astrocal_app.models import EditableEvent, Issue       # noqa: E402
from astrocal_app.service import add_manual_event, publication   # noqa: E402


@pytest.fixture(scope="module")
def application():
    from astrocal_studio.app import create_application
    from astrocal_studio import theme

    app = create_application([])
    app.setStyleSheet(theme.stylesheet("dark"))
    return app


@pytest.fixture
def issue() -> Issue:
    def event(day: int, text: str, category: str = "moon",
              rank: str = "must") -> Event:
        return Event(when=dt.datetime(2026, 9, day, 21, 0, tzinfo=MSK),
                     text=text, category=category, rank=rank,
                     computed="тестовый расчёт", sources=["тест"])

    issue = Issue(year=2026, month=9,
                  enabled_kinds={"moon_phase", "moon_planet", "comet", "manual"})
    events = [
        event(4, "Луна в фазе последней четверти в созвездии Телец"),
        event(6, "Луна проходит в 3.0° севернее Марса (V=+1,2m)"),
        event(16, "Комета 161P/Hartley-IRAS (V=+13,1m) проходит в 0°29′ западнее "
                  "звезды HIP 8102", category="comet_star", rank="interesting"),
    ]
    issue.events = [EditableEvent(event=item, order=index)
                    for index, item in enumerate(events)]
    return issue


@pytest.fixture
def window(application, issue, tmp_path, monkeypatch):
    from astrocal_app import workspace
    from astrocal_studio.main_window import MainWindow

    monkeypatch.setattr(workspace, "WORKSPACE_DIR", tmp_path)
    window = MainWindow("dark")
    window.issue = issue
    window.parameters.set_enabled_kinds(issue.enabled_kinds)
    window.parameters.set_enabled_ranks(issue.enabled_ranks)
    window.apply_filters()
    return window


# ------------------------------------------------------------------ сборка


def test_window_builds_with_all_panels(window):
    titles = [window.right_tabs.tabText(i)
              for i in range(window.right_tabs.count())]
    assert titles == ["Публикация", "Проверка", "Данные", "Live"]
    assert window.table.model.rowCount() == 3


def test_categories_cover_the_taxonomy(window):
    from astrocal.taxonomy import KINDS
    assert len(window.parameters._kind_boxes) == len(KINDS)


# ------------------------------------------------------------------ поведение


def test_unchecking_event_removes_it_from_preview(window, issue):
    before = publication(issue).length
    issue.events[0].selected = False
    window.update_preview()
    after = publication(issue).length
    assert after < before
    assert issue.events[0].text not in publication(issue).plain_text


def test_editing_text_changes_preview(window, issue):
    window._save_text(issue.events[1], "Полностью переписанная формулировка")
    assert "Полностью переписанная формулировка" in publication(issue).plain_text
    assert issue.events[1].calculated_text.startswith("Луна проходит")


def test_reverting_text_restores_calculated(window, issue):
    window._save_text(issue.events[1], "Временный текст")
    window._revert_text(issue.events[1])
    assert issue.events[1].text == issue.events[1].calculated_text


def test_reordering_changes_publication_order(window, issue):
    issue.move(issue.events[2].event_id, -2)
    window.apply_filters()
    lines = publication(issue).plain_text.splitlines()
    events = [line for line in lines if line.startswith("▪️")]
    assert "161P" in events[0]


def test_filter_by_rank_hides_events(window, issue):
    window.parameters.set_enabled_ranks({"must"})
    window.apply_filters()
    assert window.table.model.rowCount() == 2


def test_counter_shows_limit(window):
    assert "/ 4096" in window.preview.counter.text()


def test_manual_event_appears_in_table(window, issue):
    add_manual_event(issue, dt.datetime(2026, 9, 9, 20, 0, tzinfo=MSK),
                     "Ручное событие")
    window.apply_filters()
    assert window.table.model.rowCount() == 4


def test_details_panel_shows_selected_event(window, issue):
    window.details.show_event(issue.events[0])
    assert issue.events[0].calculated_text in \
        window.details.calculated_view.toPlainText()
    assert "тестовый расчёт" in window.details.info.toPlainText()


def test_band_tab_explains_when_map_is_not_needed(window, issue):
    window.details.show_event(issue.events[1])          # соединение, не покрытие
    assert "не требуется" in window.details.band_view.label.text()


def test_qa_panel_summarises_issue(window, issue):
    window.qa_panel.show_issue(issue)
    text = window.qa_panel.summary.toPlainText()
    assert "Horizons" in text
    assert "REVIEW" in text


def test_data_panel_lists_sources(window):
    assert window.data_panel.tree.topLevelItemCount() > 5


def test_data_panel_has_download_button(window):
    assert window.data_panel.download_button.text() == "Скачать недостающее"
    assert window.data_panel.missing_label.text()


def test_download_button_offers_missing_data(window, monkeypatch):
    """Когда данных нет, кнопка активна и говорит, сколько качать."""
    from astrocal_app import bootstrap

    fake = [bootstrap.Download("de440s", "Эфемериды", "http://example/e",
                               Path("nowhere/de440s.bsp"), 31.2, True)]
    monkeypatch.setattr(bootstrap, "catalogue", lambda: fake)
    window.data_panel.reload()
    assert window.data_panel.download_button.isEnabled()
    assert "31.2 МБ" in window.data_panel.missing_label.text()


def test_calculation_asks_to_download_when_data_is_absent(window, monkeypatch):
    """Расчёт без данных не падает с непонятной ошибкой, а предлагает скачать."""
    from astrocal_app import bootstrap
    from astrocal_studio import main_window as module

    fake = [bootstrap.Download("de440s", "Эфемериды", "http://example/e",
                               Path("nowhere/de440s.bsp"), 31.2, True)]
    monkeypatch.setattr(bootstrap, "catalogue", lambda: fake)

    asked = {"value": False}
    monkeypatch.setattr(module.QMessageBox, "question",
                        lambda *args, **kwargs: (asked.update(value=True)
                                                 or module.QMessageBox.No))
    submitted = []
    monkeypatch.setattr(window.runner, "submit",
                        lambda *args, **kwargs: submitted.append(args))

    window.calculate()
    assert asked["value"], "не предложено скачать данные"
    assert not submitted, "расчёт запустился без данных"


def test_window_state_is_saved_on_close(window, tmp_path, monkeypatch):
    from astrocal_app import workspace

    monkeypatch.setattr(workspace, "WORKSPACE_DIR", tmp_path)
    window.issue.events[0].selected = False
    window.close()
    saved = list(tmp_path.glob("*.astudio.json"))
    assert saved, "состояние выпуска не сохранилось при закрытии"


def test_settings_remember_period(window):
    window.parameters.set_period(2027, 3)
    assert window.parameters.year == 2027
    assert window.parameters.month == 3
