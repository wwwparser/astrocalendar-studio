"""Интерфейс живой ленты: карточки, фильтры, перенос в выпуск.

Сеть и расчёты подменены: лента наполняется готовыми записями, а проверяется
поведение окна — что карточки рисуются, фильтры работают, счётчик считает и
запись попадает в выпуск с сохранённым происхождением.
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

from astrocal.config import MSK                                    # noqa: E402
from astrocal.live.model import (DiscoveryEvent, LiveUpdate,       # noqa: E402
                                 ScheduledEvent)
from astrocal.live.state import LiveState                          # noqa: E402
from astrocal_app.models import Issue                              # noqa: E402


@pytest.fixture(scope="module")
def application():
    from astrocal_studio import theme
    from astrocal_studio.app import create_application

    app = create_application([])
    app.setStyleSheet(theme.stylesheet("dark"))
    return app


def records() -> list:
    neo = ScheduledEvent(
        live_id="neo:2026XX:2026-09-17T05:12", kind="neo",
        title="2026 XX — 1,7 LD", summary="Астероид 2026 XX пролетает у Земли",
        lines=["Размер: ≈315 м", "До Земли: 1.7 LD", "Скорость: 12,8 км/с"],
        when=dt.datetime(2026, 9, 17, 8, 12, tzinfo=MSK), rank="must", stars=4,
        magnitude=10.8,
        payload={"designation": "2026 XX", "distance_ld": 1.7,
                 "distance_km": 653480.0, "velocity_km_s": 12.8,
                 "absolute_magnitude_H": 21.0, "ra": 45.0, "dec": 20.0},
        sources=["CNEOS"],
        provenance={"source": "CNEOS", "source_updated_at": "2026-09-02T10:00:00",
                    "diameter_provenance": "оценка по H=21.0"},
        observability={"visible": True, "city": "Москва", "stars": 4})
    comet = DiscoveryEvent(
        live_id="comet:C/2026 X1", kind="comet", title="Новая комета C/2026 X1",
        summary="Открыта комета C/2026 X1",
        lines=["Сейчас: ~+15,8m", "Ожидаемый максимум: ~+8,0m"],
        discovered_at=dt.datetime(2026, 9, 1, 12, 0, tzinfo=MSK),
        rank="interesting", stars=3, magnitude=15.8,
        payload={"peak_magnitude": 8.0, "perihelion_distance_au": 1.2,
                 "eccentricity": 1.0, "inclination_deg": 62.0,
                 "magnitude_model": "m = g + 5 lg D", "magnitude_uncertainty": 2.0,
                 "constellation": "Лебедь", "ra": 300.0, "dec": 40.0},
        sources=["MPC"],
        provenance={"source": "MPC", "source_updated_at": "2026-09-02T10:00:00"})
    transient = DiscoveryEvent(
        live_id="tns:2026abc", kind="transient", title="Сверхновая SN 2026abc",
        summary="Сверхновая SN 2026abc в созвездии Лебедь",
        lines=["Тип: SN Ia", "Блеск при открытии: +11,8m"],
        discovered_at=dt.datetime(2026, 9, 12, 20, 14, tzinfo=MSK),
        rank="interesting", stars=3, magnitude=11.8,
        payload={"name": "SN 2026abc", "type": "SN Ia", "ra": 310.5,
                 "dec": 41.2, "discovery_mag": 11.8, "source_id": "152341",
                 "discovery_date": "2026-09-12T20:14:00+03:00",
                 "type_group": "supernova", "constellation": "Лебедь"},
        sources=["TNS"],
        provenance={"source": "TNS", "source_updated_at": "2026-09-12T21:00:00"},
        observability={"visible": True, "city": "Москва", "stars": 3,
                       "sun_altitude_deg": -18.0})
    shift = LiveUpdate(
        live_id="astocc:40999:HIP1:2026-09-19T15:50Z:shift", kind="occultation",
        title="Полоса покрытия сдвинулась на 34 км",
        summary="Полоса покрытия сдвинулась на 34 км",
        lines=["Сдвиг: 34 км"], when=dt.datetime(2026, 9, 19, 18, 50, tzinfo=MSK),
        rank="interesting", target_id="astocc:40999:HIP1:2026-09-19T15:50Z",
        payload={"shift_km": 34.0},
        provenance={"source": "IOTA", "source_updated_at": "2026-09-02T00:00:00"})
    return [neo, comet, transient, shift]


@pytest.fixture
def window(application, tmp_path, monkeypatch):
    from astrocal_app import workspace
    from astrocal_studio.main_window import MainWindow

    monkeypatch.setattr(workspace, "WORKSPACE_DIR", tmp_path)
    window = MainWindow("dark")
    window.feed.state = LiveState(tmp_path / "live")
    window.feed.records = records()
    window.feed.state.observe_all(window.feed.records)
    from astrocal import qa_live
    window.feed.qa = qa_live.run(window.feed.records)
    window.apply_feed_filters()
    return window


# ------------------------------------------------------------------ вкладка


def test_live_tab_exists(window):
    titles = [window.right_tabs.tabText(i)
              for i in range(window.right_tabs.count())]
    assert any(title.startswith("LIVE") for title in titles)


def test_cards_are_rendered(window):
    assert window.feed_panel.cards_layout.count() - 1 == 4


def test_card_shows_status_and_stars(window):
    card = window.feed_panel.cards_layout.itemAt(0).widget()
    assert "НОВОЕ" in card._status_text()
    assert card.record.stars >= 3


def test_badge_counts_unread(window):
    index = window.live_tab_index
    assert window.right_tabs.tabText(index) == "LIVE (4)"


def test_opening_a_card_marks_it_read(window):
    card = window.feed_panel.cards_layout.itemAt(0).widget()
    card.toggle()
    window.apply_feed_filters()
    assert window.right_tabs.tabText(window.live_tab_index) == "LIVE (3)"


def test_expanded_card_shows_all_lines(window):
    card = window.feed_panel.cards_layout.itemAt(0).widget()
    card.toggle()
    assert card.body.text().count("\n") >= 2


# ------------------------------------------------------------------ фильтры


def test_kind_filter_hides_records(window):
    window.feed_panel.kind_boxes["transient"].setChecked(False)
    window.apply_feed_filters()
    kinds = {record.kind for record in window.feed_panel.records}
    assert "transient" not in kinds


def test_brightness_filter_hides_faint_transients(window):
    window.feed_panel.magnitude_spin.setValue(10.0)
    window.apply_feed_filters()
    assert not [r for r in window.feed_panel.records if r.kind == "transient"]


def test_show_all_returns_hidden_records(window):
    window.feed_panel.magnitude_spin.setValue(10.0)
    window.feed_panel.show_all_box.setChecked(True)
    window.apply_feed_filters()
    assert [r for r in window.feed_panel.records if r.kind == "transient"]


def test_ignoring_removes_record_from_feed(window):
    record = window.feed.by_id("tns:2026abc")
    window.ignore_live(record)
    assert record.live_id not in {r.live_id for r in window.feed_panel.records}


def test_ignored_record_returns_with_show_all(window):
    record = window.feed.by_id("tns:2026abc")
    window.ignore_live(record)
    window.feed_panel.show_all_box.setChecked(True)
    window.apply_feed_filters()
    assert record.live_id in {r.live_id for r in window.feed_panel.records}


# ------------------------------------------------------------------ выпуск


def test_adding_to_issue_keeps_origin(window):
    window.issue = Issue(year=2026, month=9)
    record = window.feed.by_id("neo:2026XX:2026-09-17T05:12")
    window.add_live_to_issue(record)
    item = window.issue.events[-1]
    assert item.event.provenance["origin"] == "live"
    assert item.event.provenance["source_event_id"] == record.live_id
    assert item.kind == "live_neo"


def test_adding_enables_the_live_category(window):
    window.issue = Issue(year=2026, month=9)
    window.add_live_to_issue(window.feed.by_id("comet:C/2026 X1"))
    assert "live_comet" in window.issue.enabled_kinds
    assert window.issue.published(), "запись должна быть видна в выпуске"


def test_adding_twice_does_not_duplicate(window):
    window.issue = Issue(year=2026, month=9)
    record = window.feed.by_id("tns:2026abc")
    window.add_live_to_issue(record)
    window.add_live_to_issue(record)
    assert len(window.issue.events) == 1


def test_added_record_is_remembered(window):
    window.issue = Issue(year=2026, month=9)
    record = window.feed.by_id("tns:2026abc")
    window.add_live_to_issue(record)
    assert window.feed.state.entry(record.live_id)["added_to_workspace"]


def test_source_change_is_detected_but_text_is_kept(window):
    window.issue = Issue(year=2026, month=9)
    record = window.feed.by_id("neo:2026XX:2026-09-17T05:12")
    item = window.feed.add_to_issue(window.issue, record)
    item.editor_text = "Моя формулировка"

    record.payload["distance_ld"] = 2.4          # источник уточнил расстояние
    changes = window.feed.source_changes(window.issue)
    assert changes and changes[0][0] is item

    window.feed.apply_source_update(item, record)
    assert item.editor_text == "Моя формулировка"
    assert item.text == "Моя формулировка"
    # расчётная часть пересобрана по свежим данным источника
    assert item.event.provenance["payload_hash"] == record.payload_hash()
    assert not window.feed.source_changes(window.issue)


def test_post_preview_is_built_from_the_record(window):
    text = window.feed.post_text(window.feed.by_id("tns:2026abc"))
    assert "SN 2026abc" in text
    assert "TNS" in text


def test_live_events_survive_a_saved_workspace(window, tmp_path):
    from astrocal_app import workspace

    window.issue = Issue(year=2026, month=9)
    record = window.feed.by_id("comet:C/2026 X1")
    window.add_live_to_issue(record)
    workspace.save(window.issue, tmp_path)

    fresh = Issue(year=2026, month=9)
    restored = workspace.load_into(fresh, tmp_path)
    assert restored["manual"] == 1
    assert fresh.events[0].event.provenance["origin"] == "live"
    assert fresh.events[0].event.category == "live_comet"
