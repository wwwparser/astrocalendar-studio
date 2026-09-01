"""Проверки самих проверок: QA-слой должен ловить типовые поломки."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import qa, rating                        # noqa: E402
from astrocal.config import MSK                        # noqa: E402
from astrocal.core import Event                        # noqa: E402

START = dt.datetime(2026, 9, 1, tzinfo=MSK)
END = dt.datetime(2026, 10, 1, tzinfo=MSK)


def make(text: str, when=None, **kwargs) -> Event:
    return Event(when=when or dt.datetime(2026, 9, 10, 12, 0, tzinfo=MSK),
                 text=text, category=kwargs.pop("category", "moon"), **kwargs)


def levels(event: Event) -> set[str]:
    return {f.level for f in event.flags}


def checks(event: Event) -> set[str]:
    return {f.check for f in event.flags}


def test_wrong_timezone_is_review():
    event = make("Тест", when=dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc))
    qa.run([event], START, END, use_horizons=False)
    assert "timezone" in checks(event)
    assert "REVIEW" in levels(event)


def test_event_outside_month_is_review():
    event = make("Тест", when=dt.datetime(2026, 10, 5, 12, 0, tzinfo=MSK))
    qa.run([event], START, END, use_horizons=False)
    assert "range" in checks(event)


def test_physically_impossible_distance_is_caught():
    event = make("Луна (Ф=-0,22) в перигее своей орбиты на расстоянии 300000 км "
                 "от Земли")
    qa.run([event], START, END, use_horizons=False)
    assert "moon_distance" in checks(event)


def test_plausible_but_wrong_distance_is_caught_by_ephemeris():
    """359 077 км — нормальный перигей, но не тот, что был 10 августа 2026."""
    event = make("Луна (Ф=-0,07) в перигее своей орбиты на расстоянии 359077 км "
                 "от Земли",
                 when=dt.datetime(2026, 8, 10, 14, 10, tzinfo=MSK))
    qa.run([event], dt.datetime(2026, 8, 1, tzinfo=MSK),
           dt.datetime(2026, 9, 1, tzinfo=MSK), use_horizons=False)
    assert "moon_distance_ephemeris" in checks(event)
    assert "REVIEW" in levels(event)


def test_correct_distance_passes_ephemeris_check():
    event = make("Луна (Ф=-0,07) в перигее своей орбиты на расстоянии 363265 км "
                 "от Земли",
                 when=dt.datetime(2026, 8, 10, 14, 10, tzinfo=MSK))
    qa.run([event], dt.datetime(2026, 8, 1, tzinfo=MSK),
           dt.datetime(2026, 9, 1, tzinfo=MSK), use_horizons=False)
    assert event.flags == []


def test_apogee_distance_cannot_be_perigee_value():
    event = make("Луна (Ф=+0,53) в апогее своей орбиты на расстоянии 363265 км "
                 "от Земли")
    qa.run([event], START, END, use_horizons=False)
    assert "moon_distance" in checks(event)


def test_unknown_constellation_is_review():
    event = make("Луна проходит в 2.0° севернее Марса в созвездии Мордор")
    qa.run([event], START, END, use_horizons=False)
    assert "constellation" in checks(event)


def test_implausible_planet_magnitude_warns():
    event = make("Венера (V=+3,0m) в наибольшей восточной элонгации")
    qa.run([event], START, END, use_horizons=False)
    assert "magnitude" in checks(event)


def test_duplicates_are_flagged():
    first = make("Одинаковый текст")
    second = make("Одинаковый текст")
    qa.run([first, second], START, END, use_horizons=False)
    assert "duplicate" in checks(second)


def test_clean_event_has_no_flags():
    event = make("Луна (Ф=-0,22) проходит в 3.0° севернее Марса (V=+1,2m) "
                 "в созвездии Близнецы")
    result = qa.run([event], START, END, use_horizons=False)
    assert event.flags == []
    assert result["clean"] == 1


def test_provenance_is_stamped():
    event = make("Тест")
    qa.stamp_provenance([event], {"ephemeris": "DE440s", "catalogs": "Hipparcos"})
    assert event.provenance["ephemeris"] == "DE440s"
    assert "computed_at_utc" in event.provenance
    assert "МСК" in event.provenance["timescale"]


@pytest.mark.parametrize("text, category, expected", [
    ("Полное солнечное затмение", "eclipse", "must"),
    ("Луна в фазе новолуние в созвездии Лев", "moon", "must"),
    ("Покрытие Венеры Луной", "occultation", "must"),
    ("Нептун в противостоянии с Солнцем", "planet", "must"),
    ("Осеннее равноденствие", "season", "must"),
])
def test_headline_events_rank_must(text, category, expected):
    assert rating.rank_event(make(text, category=category)) == expected


def test_low_confidence_is_technical():
    event = make("Что-то ненадёжное", category="iss", confidence="низкая")
    assert rating.rank_event(event) == "technical"


def test_publication_filter_drops_optional_and_technical():
    events = [make("A", category="eclipse"),
              make("B", category="iss", confidence="низкая")]
    rating.apply(events)
    published = rating.for_publication(events)
    assert [e.text for e in published] == ["A"]
