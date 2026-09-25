"""Взаимные явления галилеевых спутников.

Наблюдатель спросил, учитываются ли они. Не учитывались — модуль считал только
явления спутник–планета. Сезон 2026–2027 как раз подходящий, поэтому проверки
идут и на геометрию, и на то, что вне сезона список честно пуст.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg                                # noqa: E402
from astrocal.events import jupiter_mutual as jm                  # noqa: E402


# ------------------------------------------------------------------ геометрия


def test_no_overlap_when_discs_are_apart():
    assert jm.overlap_fraction(10.0, 2.0, 3.0) == 0.0


def test_full_overlap_when_the_front_disc_is_larger():
    """Ганимед крупнее Ио и закрывает его целиком."""
    assert jm.overlap_fraction(0.0, 3.0, 2.0) == 1.0


def test_partial_overlap_when_the_front_disc_is_smaller():
    """Ио меньше Ганимеда: даже по центру закроет только часть."""
    fraction = jm.overlap_fraction(0.0, 2.0, 3.0)
    assert abs(fraction - (2.0 / 3.0) ** 2) < 1e-9


def test_half_overlap_at_touching_centres():
    fraction = jm.overlap_fraction(2.0, 2.0, 2.0)
    assert 0.3 < fraction < 0.5


def test_overlap_grows_as_discs_converge():
    far = jm.overlap_fraction(3.5, 2.0, 2.0)
    near = jm.overlap_fraction(1.0, 2.0, 2.0)
    assert near > far


def test_overlap_never_exceeds_one():
    assert jm.overlap_fraction(0.0, 100.0, 1.0) == 1.0


# ------------------------------------------------------------------ поиск


@pytest.fixture(scope="module")
def october():
    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 10, 8, tzinfo=cfg.MSK)
    return jm.find(start, end)


def test_season_of_2026_has_mutual_events(october):
    assert october, "в сезон явления обязаны быть"


def test_both_kinds_are_found(october):
    kinds = {item.kind for item in october}
    assert kinds == {"occultation", "eclipse"}


def test_durations_are_minutes_not_hours(october):
    for item in october:
        assert 0 < item.duration_minutes < 120


def test_events_are_ordered_in_time(october):
    moments = [item.middle for item in october]
    assert moments == sorted(moments)


def test_participants_are_different_moons(october):
    for item in october:
        assert item.front != item.back


def test_times_are_moscow(october):
    for item in october:
        assert item.middle.utcoffset() == dt.timedelta(hours=3)


def test_middle_lies_inside_the_event(october):
    for item in october:
        assert item.start <= item.middle <= item.end


def test_out_of_season_there_are_no_events():
    """Плоскость орбит наклонена — явлений не бывает, и это не сбой."""
    start = dt.datetime(2024, 6, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2024, 6, 8, tzinfo=cfg.MSK)
    assert jm.find(start, end) == []


# ------------------------------------------------------------------ отбор


def make(obscuration: float, minutes: float, observable: bool) -> jm.MutualEvent:
    start = dt.datetime(2026, 10, 5, 3, 0, tzinfo=cfg.MSK)
    return jm.MutualEvent(
        kind="occultation", front="io", back="ganymede",
        start=start, middle=start + dt.timedelta(minutes=minutes / 2),
        end=start + dt.timedelta(minutes=minutes),
        min_separation_arcsec=0.4, obscuration=obscuration,
        observable=observable)


def test_faint_touch_is_not_published():
    assert jm.significant([make(0.03, 6.0, True)]) == []


def test_unobservable_event_is_not_published():
    assert jm.significant([make(0.9, 6.0, False)]) == []


def test_too_short_event_is_not_published():
    assert jm.significant([make(0.9, 0.5, True)]) == []


def test_good_event_is_published():
    assert len(jm.significant([make(0.9, 6.0, True)])) == 1


def test_calendar_is_capped_and_keeps_the_deepest():
    many = [make(0.30 + index * 0.01, 6.0, True) for index in range(20)]
    chosen = jm.significant(many)
    assert len(chosen) == cfg.JUPITER_MUTUAL_MAX_IN_CALENDAR
    assert min(item.obscuration for item in chosen) > 0.40


# ------------------------------------------------------------------ события


def test_event_text_names_both_moons_and_the_depth():
    event = jm.to_event(make(0.68, 4.0, True))
    assert "Ио" in event.text and "Ганимед" in event.text
    assert "68 %" in event.text
    assert event.category == "jupiter_mutual"


def test_eclipse_mentions_the_penumbra_caveat():
    item = make(0.68, 4.0, True)
    item.kind = "eclipse"
    assert "полутеневая" in jm.to_event(item).computed


def test_occultation_has_no_penumbra_caveat():
    assert "полутеневая" not in jm.to_event(make(0.68, 4.0, True)).computed


def test_rank_depends_on_observability():
    assert jm.to_event(make(0.68, 4.0, True)).rank == "interesting"
    assert jm.to_event(make(0.68, 4.0, False)).rank == "optional"


def test_event_is_classified_and_ranked():
    from astrocal.rating import rank_event
    from astrocal.taxonomy import classify

    event = jm.to_event(make(0.68, 4.0, True))
    assert classify(event) == "jupiter_mutual"
    assert rank_event(event) == "interesting"


def test_all_events_returns_calendar_and_full_list():
    start = dt.datetime(2026, 10, 1, tzinfo=cfg.MSK)
    end = dt.datetime(2026, 10, 8, tzinfo=cfg.MSK)
    calendar, every = jm.all_events(start, end)
    assert len(every) > len(calendar)
    assert all(event.category == "jupiter_mutual" for event in calendar)
