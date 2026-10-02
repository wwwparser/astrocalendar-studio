"""Регрессии редакторской проверки октября: физика, видимость и отбор."""
import datetime as dt
from types import SimpleNamespace

import pytest

from astrocal import crossmatch
from astrocal.config import month_bounds
from astrocal.core import body, timescale
from astrocal.encounters import observing_time
from astrocal.events import moon, lunar_features, asteroid_occultations


@pytest.mark.parametrize("diameter,duration,mag,expected", [
    (17, 1.2, 4.8, True), (3, .4, 5.6, False), (6, .6, 4.3, False),
    (7, .6, 5.3, False), (10, 2, 5, False), (11, 1, 5, False),
    (11, 2, 7.1, False), (11, 2, 7, True), (float("nan"), 2, 5, False),
])
def test_occultation_editorial_thresholds(diameter, duration, mag, expected):
    candidate = SimpleNamespace(diameter_km=diameter, max_duration_s=duration, star_mag=mag)
    assert asteroid_occultations.publication_candidate(candidate) == expected


def test_longitude_and_latitude_match_nasa_svs_snapshot():
    # NASA SVS 5587 mooninfo_2026.json, 13 Oct 2026 21:00 UT.
    lon, lat = lunar_features.libration(timescale().utc(2026, 10, 13, 21))
    assert lon == pytest.approx(3.213, abs=.02)
    assert lat == pytest.approx(6.669, abs=.02)


def test_north_and_south_features_not_swapped():
    events = lunar_features.librations(*month_bounds(2026, 10))
    north = next(e for e in events if e.meta["edge"] == "северный")
    south = next(e for e in events if e.meta["edge"] == "южный")
    assert north.when.day == 14 and "Пири" in north.text
    assert south.when.day == 27 and "Шеклтон" in south.text


def test_phases_have_actual_diameter():
    assert all("D=" in e.text for e in moon.phases(*month_bounds(2026, 10)))


def test_spica_in_solar_glare_not_published():
    stars = moon.conjunctions_with_stars(*month_bounds(2026, 10))
    assert not any("Спика" in e.text for e in stars)
    assert any("Регул" in e.text for e in stars)
    assert not any("HIP 78401" in e.text or "HIP 93506" in e.text for e in stars)


def test_no_daylight_or_below_horizon_observing_time():
    result = observing_time(dt.datetime(2026, 10, 24, 12, tzinfo=dt.timezone.utc),
                            body("moon"), body("saturn"), 7.5)
    assert result is not None
    t, site, _ = result
    assert site.at(t).observe(body("moon")).apparent().altaz()[0].degrees >= 5
    assert site.at(t).observe(body("saturn")).apparent().altaz()[0].degrees >= 5
    assert site.at(t).observe(body("sun")).apparent().altaz()[0].degrees <= -6


def test_old_wide_star_rules_cannot_bypass_new_threshold():
    from astrocal.events.asteroids import interesting as asteroid
    from astrocal.events.comets import interesting as comet
    assert not asteroid(dict(mag=9, kind="star", object_mag=3, messier=False, sep_deg=.2))
    assert not comet(dict(visible=True, magnitude_observed=True, comet_mag=9,
                          kind="star", object_mag=3, messier=False, sep_deg=.2))
    assert crossmatch.by_new_rules(12, "star", 7, False, 9.9 / 60)


def test_rms_parser_reads_layout_from_header():
    from astrocal.planetary_occultation_catalog import parse
    fields = {"TARGET": (1, 8), "EVENTID": (10, 20), "UTC_CA": (22, 47),
              "STARID": (49, 68), "STARPOS": (70, 100), "GMAG": (102, 108),
              "KMAG": (110, 116), "SUMMARY_PDF": (118, 150)}
    header = "\n".join(f" {a}-{b} A1 --- {key} description" for key, (a, b) in fields.items())
    line = list(" " * 150)
    for key, value in {"TARGET": "Jupiter", "EVENTID": "J260001", "UTC_CA": "2026-10-01 12:30:00",
                       "STARID": "123456789", "STARPOS": "01 02 03 +04 05 06", "GMAG": "9.2",
                       "KMAG": "6.1", "SUMMARY_PDF": "SOM/events/test.pdf"}.items():
        a, _ = fields[key]
        line[a - 1:a - 1 + len(value)] = value
    records = parse(header + "\n" + "".join(line))
    assert records[0]["g_mag"] == 9.2 and records[0]["k_mag"] == 6.1
    assert records[0]["when"].tzinfo == dt.timezone.utc


def test_unconfirmed_external_prediction_is_review_not_publication():
    from astrocal.core import Event
    from astrocal import qa, rating
    event = Event(when=dt.datetime(2026, 10, 20, 19, tzinfo=dt.timezone.utc),
                  text="Неподтверждённый прогноз покрытия", category="asteroid_occultation",
                  confidence="низкая", meta={"requires_review": True})
    start, end = month_bounds(2026, 10)
    result = qa.run([event], start, end, use_horizons=False)
    assert event in result["review"]
    rating.apply([event])
    assert not rating.for_publication([event])


def test_distinct_asteroid_targets_do_not_get_lost_to_monthly_cap():
    from astrocal.core import Event
    from astrocal.events.asteroids import _deduplicate
    events = [Event(when=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc),
                    text=f"Проход у HIP {i}", category="asteroid",
                    meta={"number": 18, "object": f"HIP {i}", "sep_deg": .1})
              for i in range(5)]
    assert len(_deduplicate(events)) == 5


def test_control_comparison_does_not_count_planets_as_extra_occultations():
    from astrocal.core import Event
    event = Event(when=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc),
                  text="Событие Луны", category="moon")
    result = asteroid_occultations.compare_with_control([event], 2026, 10)
    assert not result["extra"]
