"""Трассировка расчёта: шаги, счётчики, отсев, обращения к источникам.

Смысл трассировки в том, чтобы объяснить готовый календарь. Поэтому тут
проверяется не только что она записывает, но и что без неё ничего не ломается:
командная строка и настольная программа работают как раньше.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import trace                                       # noqa: E402


# ------------------------------------------------------------------ запись


def test_records_stages_in_order():
    with trace.recording() as record:
        with trace.stage("a", "Первый"):
            pass
        with trace.stage("b", "Второй"):
            pass
    assert [stage.key for stage in record.stages] == ["a", "b"]


def test_stage_keeps_title_and_description():
    with trace.recording() as record:
        with trace.stage("moon", "Луна", "фазы и сближения"):
            pass
    assert record.stages[0].title == "Луна"
    assert record.stages[0].description == "фазы и сближения"


def test_counts_are_human_readable():
    with trace.recording() as record:
        with trace.stage("a", "Шаг"):
            trace.count(рассмотрено=50, отобрано=3)
    assert record.stages[0].counts == {"рассмотрено": 50, "отобрано": 3}


def test_underscores_become_spaces():
    with trace.recording() as record:
        with trace.stage("a", "Шаг"):
            trace.count(найдено_явлений=7)
    assert "найдено явлений" in record.stages[0].counts


def test_notes_are_kept():
    with trace.recording() as record:
        with trace.stage("a", "Шаг"):
            trace.note("источник не ответил, взят кэш")
    assert record.stages[0].notes == ["источник не ответил, взят кэш"]


def test_rejects_keep_reason_and_total():
    with trace.recording() as record:
        with trace.stage("a", "Шаг"):
            for index in range(30):
                trace.reject(f"объект {index}", "полоса мимо России")
    stage = record.stages[0]
    assert stage.rejected_total == 30
    assert len(stage.rejects) == trace.MAX_REJECTS
    assert stage.rejects[0]["why"] == "полоса мимо России"


def test_notes_do_not_grow_without_limit():
    with trace.recording() as record:
        with trace.stage("a", "Шаг"):
            for index in range(200):
                trace.note(f"заметка {index}")
    assert len(record.stages[0].notes) == trace.MAX_NOTES


def test_fetches_are_recorded():
    with trace.recording() as record:
        with trace.stage("a", "Шаг"):
            trace.fetched("https://example.org/data", from_cache=False,
                          size_bytes=2048, seconds=0.4)
            trace.fetched("https://example.org/data", from_cache=True,
                          size_bytes=2048, seconds=0.01)
    stage = record.stages[0]
    assert len(stage.fetches) == 2
    assert stage.fresh_fetches == 1
    assert stage.fetches[0].host == "example.org"
    assert stage.fetches[0].size_text == "2 КБ"


def test_error_is_caught_and_reraised():
    with pytest.raises(ValueError):
        with trace.recording() as record:
            with trace.stage("a", "Шаг"):
                raise ValueError("сломалось")
    assert "ValueError" in record.stages[0].error
    assert not record.stages[0].ok


def test_timing_is_measured():
    import time

    with trace.recording() as record:
        with trace.stage("a", "Шаг"):
            time.sleep(0.05)
    assert record.stages[0].seconds >= 0.04
    assert record.total_seconds >= 0.04


def test_totals_across_stages():
    with trace.recording() as record:
        with trace.stage("a", "Раз"):
            trace.fetched("https://a.test/x", size_bytes=10, seconds=1.0)
        with trace.stage("b", "Два"):
            trace.fetched("https://b.test/y", size_bytes=10, seconds=2.0,
                          from_cache=True)
    assert record.fetch_count == 2
    assert record.fresh_fetch_count == 1
    assert abs(record.network_seconds - 3.0) < 0.01


def test_failed_stages_are_listed():
    with trace.recording() as record:
        with trace.stage("ok", "Хороший"):
            pass
        try:
            with trace.stage("bad", "Плохой"):
                raise RuntimeError("нет")
        except RuntimeError:
            pass
    assert [stage.key for stage in record.failed] == ["bad"]


# ------------------------------------------------------------------ без неё


def test_functions_are_silent_without_recording():
    """Модули зовут trace.note безусловно — вне расчёта это не должно падать."""
    trace.note("что-то")
    trace.count(отобрано=1)
    trace.reject("объект", "причина")
    trace.fetched("https://example.org/", size_bytes=1)
    assert trace.current() is None


def test_stage_outside_recording_is_a_plain_block():
    entered = False
    with trace.stage("a", "Шаг") as stage:
        entered = True
        assert stage is None
    assert entered


def test_recording_is_restored_after_nesting():
    with trace.recording() as outer:
        assert trace.current() is outer
    assert trace.current() is None


# ------------------------------------------------------------------ хранение


def test_round_trip_through_dict():
    with trace.recording() as record:
        with trace.stage("moon", "Луна", "фазы"):
            trace.count(отобрано=3)
            trace.note("замечание")
            trace.reject("объект", "причина")
            trace.fetched("https://example.org/x", size_bytes=100, seconds=0.2)

    restored = trace.Trace.from_dict(record.as_dict())
    stage = restored.stages[0]
    assert stage.title == "Луна"
    assert stage.description == "фазы"
    assert stage.counts["отобрано"] == 3
    assert stage.notes == ["замечание"]
    assert stage.rejects[0]["what"] == "объект"
    assert stage.fetches[0].size_bytes == 100
    assert restored.fetch_count == 1


def test_dict_is_json_serialisable():
    import json

    with trace.recording() as record:
        with trace.stage("a", "Шаг"):
            trace.count(отобрано=1)
    assert json.loads(json.dumps(record.as_dict(), ensure_ascii=False))


def test_empty_trace_restores_cleanly():
    restored = trace.Trace.from_dict({})
    assert restored.stages == []
    assert restored.fetch_count == 0


# ------------------------------------------------------------------ сборка


def test_every_step_of_the_pipeline_is_described():
    """Шаг без объяснения на сайте выглядит как пустая строка."""
    from astrocal.build import STEPS

    for key, (title, description) in STEPS.items():
        assert title, f"у шага {key} нет названия"
        assert len(description) > 40, f"шаг {key} описан слишком коротко"


def test_pipeline_steps_cover_event_categories():
    """Каждое событие должно уметь показать, какой шаг его посчитал."""
    from astrocal.build import STEPS
    from astrocal_web.app import STAGE_BY_CATEGORY

    unknown = set(STAGE_BY_CATEGORY.values()) - set(STEPS)
    assert not unknown, f"нет описания у шагов: {unknown}"
