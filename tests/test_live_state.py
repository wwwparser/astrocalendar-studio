"""Состояние живой ленты: NEW → UPDATED → UNCHANGED и память между запусками.

Это самая ответственная часть Live: если состояние не переживает перезапуск,
лента при каждом старте объявляет открытием всё, что видит.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal.config import MSK                                    # noqa: E402
from astrocal.live.model import (DiscoveryEvent, LiveUpdate,       # noqa: E402
                                 ScheduledEvent, STATUS_NEW,
                                 STATUS_UNCHANGED, STATUS_UPDATED)
from astrocal.live.state import LiveState, Snapshot                # noqa: E402


def record(live_id="neo:X:2026-09-10T05:12", magnitude=12.0, rank="interesting"):
    return ScheduledEvent(
        live_id=live_id, kind="neo", title="Тестовое сближение",
        summary="Астероид X пролетает мимо Земли",
        when=dt.datetime(2026, 9, 10, 8, 12, tzinfo=MSK),
        rank=rank, magnitude=magnitude,
        payload={"designation": "X", "distance_ld": 1.5, "magnitude": magnitude})


# ------------------------------------------------------------------ статусы


def test_first_sighting_is_new(tmp_path):
    state = LiveState(tmp_path)
    assert state.observe(record()) == STATUS_NEW


def test_second_sighting_of_same_data_is_unchanged(tmp_path):
    state = LiveState(tmp_path)
    state.observe(record())
    assert state.observe(record()) == STATUS_UNCHANGED


def test_changed_payload_is_an_update(tmp_path):
    state = LiveState(tmp_path)
    state.observe(record())
    assert state.observe(record(magnitude=9.5)) == STATUS_UPDATED


def test_update_remembers_previous_hash(tmp_path):
    state = LiveState(tmp_path)
    first = record()
    state.observe(first)
    state.observe(record(magnitude=9.5))
    entry = state.entry(first.live_id)
    assert entry["previous_payload_hash"] == first.payload_hash()
    assert entry["current_payload_hash"] != entry["previous_payload_hash"]


def test_state_survives_restart(tmp_path):
    """Перезапуск программы не превращает известное в открытие."""
    LiveState(tmp_path).observe_all([record()])
    assert LiveState(tmp_path).observe(record()) == STATUS_UNCHANGED


def test_counts_are_reported(tmp_path):
    state = LiveState(tmp_path)
    counts = state.observe_all([record(), record("neo:Y:2026-09-11T00:00")])
    assert counts == {STATUS_NEW: 2, STATUS_UPDATED: 0, STATUS_UNCHANGED: 0}


# ------------------------------------------------------------------ прочитано


def test_new_record_is_unread(tmp_path):
    state = LiveState(tmp_path)
    item = record()
    state.observe(item)
    assert item.unread


def test_marking_read_persists(tmp_path):
    state = LiveState(tmp_path)
    item = record()
    state.observe(item)
    state.mark_read(item.live_id)
    fresh = record()
    LiveState(tmp_path).observe(fresh)
    assert not fresh.unread


def test_updated_record_becomes_unread_again(tmp_path):
    """Изменившиеся данные снова требуют внимания редактора."""
    state = LiveState(tmp_path)
    state.observe(record())
    state.mark_read(record().live_id)
    changed = record(magnitude=9.5)
    state.observe(changed)
    assert changed.unread


def test_ignored_record_is_marked(tmp_path):
    state = LiveState(tmp_path)
    item = record()
    state.observe(item)
    state.mark_ignored(item.live_id)
    again = record()
    LiveState(tmp_path).observe(again)
    assert again.ignored


def test_badge_counts_only_significant_unread(tmp_path):
    state = LiveState(tmp_path)
    state.observe_all([record("neo:A:1", rank="must"),
                       record("neo:B:2", rank="optional")])
    assert state.unread_count() == 1


def test_badge_drops_after_reading(tmp_path):
    state = LiveState(tmp_path)
    state.observe_all([record("neo:A:1", rank="must")])
    state.mark_read("neo:A:1")
    assert state.unread_count() == 0


def test_added_to_workspace_is_remembered(tmp_path):
    state = LiveState(tmp_path)
    state.observe(record())
    state.mark_added(record().live_id, "2026-09")
    entry = LiveState(tmp_path).entry(record().live_id)
    assert entry["added_to_workspace"] and entry["workspace_reference"] == "2026-09"


# ------------------------------------------------------------------ снимки


def test_first_run_declares_nothing_new(tmp_path):
    """Первый опрос источника не объявляет открытием весь его каталог."""
    snapshot = Snapshot("tns", tmp_path)
    assert snapshot.first_run
    assert snapshot.difference(["a", "b", "c"]) == []


def test_difference_after_snapshot(tmp_path):
    snapshot = Snapshot("tns", tmp_path)
    snapshot.update(["a", "b"])
    assert Snapshot("tns", tmp_path).difference(["a", "b", "c"]) == ["c"]


def test_snapshot_survives_restart(tmp_path):
    Snapshot("mpc", tmp_path).update(["1P", "2P"])
    again = Snapshot("mpc", tmp_path)
    assert not again.first_run
    assert again.difference(["1P", "2P"]) == []


def test_retained_fields_expose_previous_value(tmp_path):
    """По сохранённому полю видно, что именно изменилось."""
    state = LiveState(tmp_path)
    first = ScheduledEvent(live_id="astocc:1", kind="occultation", title="Покрытие",
                           payload={"path": [1, 2]}, retain=("path",))
    state.observe(first)
    second = ScheduledEvent(live_id="astocc:1", kind="occultation", title="Покрытие",
                            payload={"path": [3, 4]}, retain=("path",))
    assert state.observe(second) == STATUS_UPDATED
    assert second.previous["path"] == [1, 2]


def test_prepare_reads_without_writing(tmp_path):
    state = LiveState(tmp_path)
    first = ScheduledEvent(live_id="astocc:1", kind="occultation", title="Покрытие",
                           payload={"path": [1]}, retain=("path",))
    state.observe(first)
    second = ScheduledEvent(live_id="astocc:1", kind="occultation", title="Покрытие",
                            payload={"path": [2]}, retain=("path",))
    state.prepare(second)
    assert second.previous["path"] == [1]
    assert state.entry("astocc:1")["retained"]["path"] == [1], \
        "prepare не должна менять состояние"


def test_prune_removes_forgotten_records(tmp_path):
    state = LiveState(tmp_path)
    state.observe(record())
    state.records[record().live_id]["last_seen_at"] = "2020-01-01T00:00:00+00:00"
    assert state.prune(older_than_days=30) == 1
    assert not state.records


# ------------------------------------------------------------------ семантика


def test_scheduled_and_discovery_are_different_types():
    """Предсказанное событие и открытие нельзя путать."""
    scheduled = ScheduledEvent(live_id="a", kind="neo", title="Пролёт",
                               when=dt.datetime(2026, 9, 10, tzinfo=MSK))
    discovery = DiscoveryEvent(live_id="b", kind="transient", title="Сверхновая",
                               discovered_at=dt.datetime(2026, 9, 12, tzinfo=MSK))
    assert scheduled.semantic == "scheduled"
    assert discovery.semantic == "discovery"
    assert scheduled.moment == scheduled.when
    assert discovery.moment == discovery.discovered_at


def test_update_points_at_its_target():
    update = LiveUpdate(live_id="a:shift", kind="occultation",
                        title="Полоса сдвинулась", target_id="a",
                        changes=["сдвиг 34 км"])
    assert update.semantic == "update"
    assert update.target_id == "a"


def test_event_from_live_record_keeps_origin():
    discovery = DiscoveryEvent(
        live_id="tns:2026abc", kind="transient", title="Сверхновая SN 2026abc",
        summary="Сверхновая SN 2026abc", discovered_at=dt.datetime(
            2026, 9, 12, 20, 0, tzinfo=MSK), sources=["TNS"])
    event = discovery.to_event()
    assert event.provenance["origin"] == "live"
    assert event.provenance["source_event_id"] == "tns:2026abc"
    assert event.provenance["semantic"] == "discovery"
    assert event.category == "live_transient"
