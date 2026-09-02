"""Редакторский слой: фильтры, выбор, порядок, тексты, сохранение состояния."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal.config import MSK                          # noqa: E402
from astrocal.core import Event                          # noqa: E402
from astrocal_app import workspace                       # noqa: E402
from astrocal_app.models import EditableEvent, Issue     # noqa: E402
from astrocal_app.service import add_manual_event        # noqa: E402


def event(day: int, text: str, category: str = "moon",
          rank: str = "interesting") -> Event:
    return Event(when=dt.datetime(2026, 9, day, 21, 0, tzinfo=MSK), text=text,
                 category=category, rank=rank)


def issue_with(*events: Event) -> Issue:
    issue = Issue(year=2026, month=9,
                  enabled_kinds={"moon_phase", "moon_planet", "occultation",
                                 "manual", "meteors"})
    issue.events = [EditableEvent(event=item, order=index)
                    for index, item in enumerate(events)]
    return issue


# ------------------------------------------------------------------ тексты


def test_editor_text_does_not_destroy_calculated_text():
    item = EditableEvent(event=event(1, "Расчётная формулировка"))
    item.editor_text = "Редакторская формулировка"
    assert item.calculated_text == "Расчётная формулировка"
    assert item.text == "Редакторская формулировка"
    assert item.edited


def test_revert_returns_calculated_text():
    item = EditableEvent(event=event(1, "Расчётная формулировка"))
    item.editor_text = "Другое"
    item.revert()
    assert item.text == "Расчётная формулировка"
    assert not item.edited


def test_line_uses_editor_text():
    item = EditableEvent(event=event(3, "Исходный"))
    item.editor_text = "Изменённый"
    assert item.line().endswith("— Изменённый")


# ------------------------------------------------------------------ фильтры


def test_filters_by_kind():
    issue = issue_with(event(1, "Луна в фазе новолуние в созвездии Лев"),
                       event(2, "Максимум активности потока Ауригиды",
                             category="meteors"))
    issue.enabled_kinds = {"meteors"}
    assert [item.kind for item in issue.visible_events()] == ["meteors"]


def test_filters_by_rank():
    issue = issue_with(event(1, "Важное", rank="must"),
                       event(2, "Узкое", rank="optional"))
    issue.enabled_ranks = {"must"}
    assert [item.text for item in issue.visible_events()] == ["Важное"]


def test_unselected_event_leaves_the_post():
    issue = issue_with(event(1, "Первое"), event(2, "Второе"))
    assert len(issue.published()) == 2
    issue.events[0].selected = False
    published = issue.published()
    assert len(published) == 1
    assert published[0].text == "Второе"


def test_manual_events_pass_filters():
    issue = issue_with(event(1, "Обычное"))
    issue.enabled_kinds = {"meteors"}
    issue.enabled_ranks = {"must"}
    add_manual_event(issue, dt.datetime(2026, 9, 5, 20, 0, tzinfo=MSK),
                     "Лекция в планетарии")
    texts = [item.text for item in issue.visible_events()]
    assert "Лекция в планетарии" in texts


def test_manual_event_is_marked_as_manual():
    issue = issue_with()
    item = add_manual_event(issue, dt.datetime(2026, 9, 5, 20, 0, tzinfo=MSK),
                            "Своё событие")
    assert item.manual
    assert item.kind == "manual"
    assert "вручную" in item.event.computed


# ------------------------------------------------------------------ порядок


def test_sort_chronologically_undoes_manual_order():
    issue = issue_with(event(5, "Позже"), event(1, "Раньше"))
    assert [item.text for item in issue.ordered()] == ["Позже", "Раньше"]
    issue.sort_chronologically()
    assert [item.text for item in issue.ordered()] == ["Раньше", "Позже"]


def test_move_changes_order():
    issue = issue_with(event(1, "A"), event(2, "B"), event(3, "C"))
    issue.move(issue.events[2].event_id, -2)
    assert [item.text for item in issue.ordered()] == ["C", "A", "B"]


def test_reorder_by_explicit_list():
    issue = issue_with(event(1, "A"), event(2, "B"), event(3, "C"))
    ids = [item.event_id for item in issue.ordered()]
    issue.reorder([ids[2], ids[0], ids[1]])
    assert [item.text for item in issue.ordered()] == ["C", "A", "B"]


# ------------------------------------------------------------------ workspace


def test_workspace_round_trip_preserves_editor_work(tmp_path):
    issue = issue_with(event(1, "Первое"), event(2, "Второе"), event(3, "Третье"))
    issue.events[0].selected = False
    issue.events[1].editor_text = "Переписано редактором"
    issue.move(issue.events[2].event_id, -2)
    workspace.save(issue, tmp_path)

    # «пересчёт»: те же события, но состояние по умолчанию
    fresh = issue_with(event(1, "Первое"), event(2, "Второе"), event(3, "Третье"))
    report = workspace.load_into(fresh, tmp_path)

    assert report["restored"] == 3
    assert fresh.by_id(fresh.events[0].event_id).selected is False
    edited = [item for item in fresh.events if item.editor_text]
    assert edited and edited[0].editor_text == "Переписано редактором"
    assert [item.text for item in fresh.ordered()][0] == "Третье"


def test_workspace_flags_changed_source_data(tmp_path):
    issue = issue_with(event(1, "Луна проходит в 3.0° севернее Марса"))
    issue.events[0].editor_text = "Моя формулировка"
    workspace.save(issue, tmp_path)

    # пересчёт дал другое значение: идентификатор тот же, отпечаток другой
    fresh = issue_with(event(1, "Луна проходит в 3.4° севернее Марса"))
    report = workspace.load_into(fresh, tmp_path)

    assert report["changed"] == 1
    assert fresh.events[0].source_changed
    messages = workspace.describe_changes(fresh)
    assert messages and "изменились" in messages[0]


def test_workspace_restores_manual_events(tmp_path):
    issue = issue_with(event(1, "Обычное"))
    add_manual_event(issue, dt.datetime(2026, 9, 7, 19, 0, tzinfo=MSK),
                     "Ручная заметка")
    workspace.save(issue, tmp_path)

    fresh = issue_with(event(1, "Обычное"))
    report = workspace.load_into(fresh, tmp_path)
    assert report["manual"] == 1
    assert any(item.manual and item.text == "Ручная заметка"
               for item in fresh.events)


def test_missing_event_is_counted(tmp_path):
    issue = issue_with(event(1, "Первое"), event(2, "Исчезнет"))
    workspace.save(issue, tmp_path)
    fresh = issue_with(event(1, "Первое"))
    report = workspace.load_into(fresh, tmp_path)
    assert report["missing"] == 1


# ------------------------------------------------------------------ идентичность


def test_event_id_survives_value_changes():
    first = event(14, "Покрытие Венеры (V=-4,8m) Луной (Ф=+0,12)")
    second = event(14, "Покрытие Венеры (V=-4,9m) Луной (Ф=+0,13)")
    assert first.event_id == second.event_id


def test_event_id_differs_for_different_events():
    assert event(14, "Покрытие Венеры Луной").event_id != \
        event(14, "Покрытие Юпитера Луной").event_id


def test_fingerprint_changes_with_values():
    first = event(14, "Покрытие Венеры (V=-4,8m)")
    second = event(14, "Покрытие Венеры (V=-4,9m)")
    assert first.fingerprint() != second.fingerprint()


@pytest.mark.parametrize("category, text, expected", [
    ("moon", "Луна в фазе новолуние в созвездии Лев", "moon_phase"),
    ("moon", "Луна в перигее своей орбиты", "moon_apsis"),
    ("moon", "Луна проходит в 3.0° севернее Марса", "moon_planet"),
    ("eclipse", "Полное солнечное затмение", "solar_eclipse"),
    ("eclipse", "Частное лунное затмение", "lunar_eclipse"),
    ("planet", "Нептун в противостоянии с Солнцем", "planet_opposition"),
    ("planet", "Уран переходит от прямого движения к попятному", "planet_station"),
    ("spaceflight", "Запуск Прогресса", "launch"),
])
def test_taxonomy(category, text, expected):
    assert EditableEvent(event=event(1, text, category=category)).kind == expected
