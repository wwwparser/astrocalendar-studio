import datetime as dt
from types import SimpleNamespace
import pytest
from astrocal import crossmatch, config
from astrocal.core import Event, timescale
from astrocal.events import lunar_features as lunar, iss, close_approaches as neo
from astrocal.events.planetary_stellar_occultations import parse_position


def test_exact_ten_arcminutes_is_excluded():
    assert not crossmatch.by_new_rules(10, "star", 6, False, 10/60)
    assert crossmatch.by_new_rules(10, "star", 6, False, 9.99/60)


def test_lunar_x_is_visible_in_far_east_and_has_parameters():
    events = lunar.clair_obscur(*config.month_bounds(2026, 10))
    x = next(e for e in events if "Lunar X" in e.text)
    assert "Ф=" in x.text and "D=" in x.text
    assert any(s["city"] == "Петропавловск-Камчатский" for s in x.meta["observing_sites"])
    assert "из России в этот момент Луна низко" not in x.text


def test_terrain_events_match_defined_low_sun_geometry():
    events = lunar.terrain_windows(*config.month_bounds(2026, 10))
    assert {e.meta["feature"] for e in events} == {x[0] for x in lunar.TERRAIN}
    for event in events:
        height = lunar.feature_sun_altitude(timescale().from_datetime(event.when),
                                           event.meta["feature_lat"], event.meta["feature_lon"])
        assert float(height) == pytest.approx(3, abs=.001)
        assert "не расчёт теней" in event.computed


def test_stations_use_sochi_and_distinct_start_end(monkeypatch):
    start, end = config.month_bounds(2026, 10)
    epoch = start + dt.timedelta(days=2)
    sat = SimpleNamespace(epoch=timescale().from_datetime(epoch))
    monkeypatch.setattr(iss, "load_tle", lambda number: sat)
    passes = [(start + dt.timedelta(days=1, hours=5), 40),
              (start + dt.timedelta(days=3, hours=5), 50)]
    monkeypatch.setattr(iss, "visible_passes", lambda *args, **kwargs: passes)
    events = iss.all_events(start, end)
    css = [e for e in events if e.meta["station"] == "ККС"]
    assert {e.meta["boundary"] for e in css} == {"start", "end"}
    assert all(e.meta["site"] == "Сочи" for e in css)


def test_station_boundary_in_previous_month_not_fabricated(monkeypatch):
    start, end = config.month_bounds(2026, 10)
    sat = SimpleNamespace(epoch=timescale().from_datetime(start))
    monkeypatch.setattr(iss, "load_tle", lambda number: sat)
    monkeypatch.setattr(iss, "visible_passes", lambda *a, **kw: [
        (start-dt.timedelta(days=2)+dt.timedelta(hours=5), 40),
        (start+dt.timedelta(days=1, hours=5), 40)])
    events = iss.all_events(start, end)
    assert events and all(e.meta["boundary"] == "end" for e in events)


def test_expired_tle_does_not_print_precise_clock(monkeypatch):
    start, end = config.month_bounds(2026, 10)
    sat = SimpleNamespace(epoch=timescale().from_datetime(start))
    monkeypatch.setattr(iss, "load_tle", lambda number: sat)
    monkeypatch.setattr(iss, "visible_passes", lambda *a, **kw: [
        (start+dt.timedelta(days=5, hours=5, minutes=17), 40),
        (start+dt.timedelta(days=6, hours=5, minutes=13), 40)])
    events = iss.all_events(start, end)
    assert all(e.precision == "day" and not e.provenance["exact_time_published"] for e in events)
    assert all("05:17" not in e.line() and "05:13" not in e.line() for e in events)
    from astrocal.qa import check_format
    for event in events:
        check_format(event)
        assert not event.flags


def test_neo_peak_not_h_and_coordinates_at_encounter(monkeypatch):
    from astrocal import horizons
    centre = dt.datetime(2026,10,5,tzinfo=dt.timezone.utc)
    item = SimpleNamespace(designation="2026 XX",close_approach_datetime=centre)
    monkeypatch.setattr(horizons,"query", lambda *a, **k: "fixture")
    monkeypatch.setattr(horizons,"table", lambda text: [
        {"_time":"2026-Oct-04 00:00", "APmag":"10.1", "R.A.":"10", "DEC":"20", "S-O-T":"80"},
        {"_time":"2026-Oct-05 00:00", "APmag":"12.0", "R.A.":"30", "DEC":"40", "S-O-T":"90"}])
    monkeypatch.setattr(horizons,"column_named", lambda row, key: row.get(key))
    result = neo.magnitude_peak(item)
    assert result["peak_magnitude"] == 10.1
    assert result["ra_deg"] == 30 and result["dec_deg"] == 40
    assert result["peak_at_window_boundary"]


def test_neo_missing_apmag_is_unknown(monkeypatch):
    from astrocal import horizons
    monkeypatch.setattr(horizons,"query", lambda *a, **k: "fixture")
    monkeypatch.setattr(horizons,"table", lambda text: [])
    item = SimpleNamespace(designation="2026 XX",close_approach_datetime=dt.datetime.now(dt.timezone.utc))
    assert neo.magnitude_peak(item)["peak_magnitude"] is None


@pytest.mark.parametrize("text, expected", [
    ("09 30 00.0 +15 30 00.0", (142.5, 15.5)),
    ("00 00 00.0 -00 30 00.0", (0, -.5)),
])
def test_rms_sexagesimal_preserves_declination_sign(text, expected):
    assert parse_position(text) == pytest.approx(expected)


def test_solar_context_preserves_event_identity():
    from astrocal.solar_context import enrich
    event = Event(when=config.month_bounds(2026,10)[0], text="Луна", category="moon")
    previous = event.event_id
    assert enrich(event)
    assert event.event_id == previous
    assert 0 <= event.meta["elongation_deg"] <= 180


def test_custom_emoji_export_escapes_editor_text():
    from astrocal.custom_emoji import telegram_html
    result = telegram_html('⚫ Меркурий <test> & "строка"')
    assert 'emoji-id="5192845129945202024"' in result
    assert "&lt;test&gt;" in result and "&amp;" in result


def test_rms_missing_horizons_is_reported_not_published(monkeypatch):
    from astrocal.events import planetary_stellar_occultations as module
    def fail(item):
        raise RuntimeError("offline")
    monkeypatch.setattr(module,"local_contacts",fail)
    report={"events":[{"g_mag":9,"target":"Titan"}]}
    assert module.build(report) == []
    assert report["events"][0]["local_status"] == "error"


def test_rms_g_not_fabricated_as_v(monkeypatch):
    from astrocal.events import planetary_stellar_occultations as module
    monkeypatch.setattr(module,"local_contacts",lambda item: [
        {"city":"Москва","start":"2026-10-05T01:00:00+03:00","end":"2026-10-05T01:02:00+03:00"}])
    report={"events":[{"g_mag":9,"target":"Titan","star_position":"09 30 00 +15 30 00",
                       "source_id":"T1","gaia_id":"123","source_url":"https://pds-rings.seti.org/", "provenance":{"source":"RMS"}}]}
    event = module.build(report)[0]
    assert "G=+9.0m" in event.text and "V=" not in event.text
    assert event.meta["requires_review"]
