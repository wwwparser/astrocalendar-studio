"""Открытия: новые кометы, транзиенты TNS, сдвиг полосы покрытия, посты.

Ни один тест не ходит в сеть: MPC, TNS и Horizons подменяются заглушками.
Проверяется наша логика — сравнение со снимком, пороги значимости, фильтры и
то, что в текст поста не попадает ничего, чего нет в данных.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg, qa_live                        # noqa: E402
from astrocal.live import (discovery_service, new_comets,          # noqa: E402
                           occultation_watch, post, transients)
from astrocal.live.model import DiscoveryEvent, ScheduledEvent     # noqa: E402
from astrocal.live.state import LiveState                          # noqa: E402


# ------------------------------------------------------------------ кометы


def comet_row(designation="C/2026 X1 (PANSTARRS)", q=1.2, g=8.0, k=10.0):
    return {"designation": designation, "perihelion_year": 2027,
            "perihelion_month": 1, "perihelion_day": 4.5,
            "perihelion_distance_au": q, "eccentricity": 1.0,
            "inclination_degrees": 62.0, "magnitude_g": g, "magnitude_k": k}


def comet_frame(designations):
    return pd.DataFrame([comet_row(name) for name in designations])


def stub_comets(monkeypatch, designations, peak=8.0):
    frame = comet_frame(designations)
    monkeypatch.setattr(new_comets, "current_designations",
                        lambda use_cache=True: (
                            [new_comets.designation_key(n) for n in designations],
                            frame, "2026-09-02T10:00:00+00:00"))
    monkeypatch.setattr(new_comets, "forecast", lambda row, **kwargs: {
        "perihelion": dt.datetime(2027, 1, 4, tzinfo=dt.timezone.utc),
        "current_magnitude": 15.8, "peak_magnitude": peak,
        "peak_when": dt.datetime(2027, 1, 10, tzinfo=cfg.MSK),
        "current_r_au": 4.1, "current_delta_au": 4.4,
        "closest_delta_au": 1.1,
        "closest_when": dt.datetime(2027, 2, 1, tzinfo=cfg.MSK),
        "perihelion_distance_au": float(row["perihelion_distance_au"]),
        "eccentricity": 1.0, "inclination_deg": 62.0,
        "magnitude_g": 8.0, "magnitude_k": 10.0})
    monkeypatch.setattr(new_comets, "constellation_now",
                        lambda row: ("Лебедь", 300.0, 40.0))
    monkeypatch.setattr(new_comets, "observability", lambda *a, **k: {
        "visible": True, "city": "Москва", "stars": 3, "score": 61,
        "best_time": dt.datetime(2027, 1, 10, 22, 0, tzinfo=cfg.MSK),
        "altitude_deg": 41.0, "direction": "ЮВ",
        "window_start": dt.datetime(2027, 1, 10, 20, 0, tzinfo=cfg.MSK),
        "window_end": dt.datetime(2027, 1, 10, 23, 30, tzinfo=cfg.MSK),
        "instrument": "Телескоп", "note": "Луна не мешает"})


def test_first_run_records_snapshot_without_discoveries(tmp_path, monkeypatch):
    """Тысяча давно известных комет — не тысяча открытий."""
    stub_comets(monkeypatch, ["1P/Halley", "2P/Encke", "C/2020 F3 (NEOWISE)"])
    found, summary = new_comets.check(directory=tmp_path)
    assert found == []
    assert summary["first_run"] and summary["total"] == 3
    assert (tmp_path / "mpc_comets_state.json").exists()


def test_new_designation_is_a_discovery(tmp_path, monkeypatch):
    stub_comets(monkeypatch, ["1P/Halley"])
    new_comets.check(directory=tmp_path)

    stub_comets(monkeypatch, ["1P/Halley", "C/2026 X1 (PANSTARRS)"])
    found, summary = new_comets.check(directory=tmp_path)
    assert summary["new"] == 1
    assert len(found) == 1
    assert found[0].live_id == "comet:C/2026 X1"
    assert found[0].semantic == "discovery"


def test_second_run_does_not_repeat_the_discovery(tmp_path, monkeypatch):
    stub_comets(monkeypatch, ["1P/Halley"])
    new_comets.check(directory=tmp_path)
    stub_comets(monkeypatch, ["1P/Halley", "C/2026 X1 (PANSTARRS)"])
    new_comets.check(directory=tmp_path)
    found, summary = new_comets.check(directory=tmp_path)
    assert found == [] and summary["new"] == 0


def test_faint_comet_with_bright_forecast_is_significant(tmp_path, monkeypatch):
    """Сейчас +15,8m, но к перигелию +5m — это событие, а не мелочь."""
    stub_comets(monkeypatch, ["1P/Halley"])
    new_comets.check(directory=tmp_path)
    stub_comets(monkeypatch, ["1P/Halley", "C/2026 X1 (PANSTARRS)"], peak=5.0)
    found, _summary = new_comets.check(directory=tmp_path)
    assert found[0].rank == "must"
    assert found[0].magnitude == 15.8, "текущий блеск сохраняется как есть"


def test_rank_follows_thresholds():
    assert new_comets.rank_of({"peak_magnitude": 5.0}) == "must"
    assert new_comets.rank_of({"peak_magnitude": 9.0}) == "interesting"
    assert new_comets.rank_of({"peak_magnitude": 14.0}) == "optional"


def test_close_approach_makes_a_faint_comet_interesting():
    assert new_comets.rank_of({"peak_magnitude": 14.0,
                               "closest_delta_au": 0.2}) == "interesting"


def test_small_perihelion_makes_a_faint_comet_interesting():
    assert new_comets.rank_of({"peak_magnitude": 14.0,
                               "closest_delta_au": 3.0,
                               "perihelion_distance_au": 0.1}) == "interesting"


def test_designation_key_drops_the_discoverer():
    assert new_comets.designation_key("C/2026 X1 (PANSTARRS)") == "C/2026 X1"
    assert new_comets.designation_key("161P/Hartley-IRAS") == "161P/Hartley-IRAS"


def test_perihelion_date_is_read_from_elements():
    when = new_comets.perihelion_date(comet_row())
    assert when.year == 2027 and when.month == 1 and when.day == 4


def test_comet_card_keeps_magnitude_uncertainty(tmp_path, monkeypatch):
    stub_comets(monkeypatch, ["1P/Halley"])
    new_comets.check(directory=tmp_path)
    stub_comets(monkeypatch, ["1P/Halley", "C/2026 X1 (PANSTARRS)"])
    found, _ = new_comets.check(directory=tmp_path)
    payload = found[0].payload
    assert payload["magnitude_model"].startswith("m = g")
    assert payload["magnitude_uncertainty"] == new_comets.MAGNITUDE_UNCERTAINTY
    assert qa_live.qa_level(_checked(found[0])) != "REVIEW"


def _checked(record):
    record.state = {"qa": qa_live.check(record)}
    return record


# ------------------------------------------------------------------ TNS


TNS_RECORD = {
    "objname": "2026abc", "name_prefix": "SN", "radeg": 310.5, "decdeg": 41.2,
    "discoverydate": "2026-09-12 20:14:00", "discoverymag": 11.8,
    "discmagfilter": {"name": "r"}, "object_type": {"name": "SN Ia"},
    "hostname": "NGC 6946", "redshift": 0.0043,
    "discovery_data_source": {"group_name": "ZTF"},
    "reporting_group": {"group_name": "ZTF"}, "objid": 152341,
}


@pytest.fixture
def described(monkeypatch):
    monkeypatch.setattr(transients, "constellation_of",
                        lambda ra, dec: "Лебедь")
    monkeypatch.setattr(transients, "observability", lambda *a, **k: {
        "visible": True, "city": "Москва", "score": 66, "stars": 4,
        "best_time": dt.datetime(2026, 9, 12, 23, 30, tzinfo=cfg.MSK),
        "altitude_deg": 48.0, "azimuth_deg": 190.0, "direction": "Ю",
        "sun_altitude_deg": -18.0, "moon_altitude_deg": -20.0,
        "moon_separation_deg": 95.0,
        "window_start": dt.datetime(2026, 9, 12, 21, 0, tzinfo=cfg.MSK),
        "window_end": dt.datetime(2026, 9, 13, 3, 0, tzinfo=cfg.MSK),
        "instrument": "Телескоп", "note": "Луна под горизонтом"})

    def make(record=None):
        return transients.describe(record or dict(TNS_RECORD),
                                   "2026-09-12T21:00:00+00:00")
    return make


def test_transient_fields_are_extracted(described):
    entry = described()
    assert entry.live_id == "tns:2026abc"
    assert entry.payload["type"] == "SN Ia"
    assert entry.payload["host_name"] == "NGC 6946"
    assert entry.payload["redshift"] == 0.0043
    assert entry.payload["discovery_group"] == "ZTF"
    assert entry.discovered_at.day == 12


def test_transient_is_a_discovery_not_a_forecast(described):
    entry = described()
    assert entry.semantic == "discovery"
    assert entry.when is None and entry.discovered_at is not None


def test_observability_is_computed_by_us(described):
    entry = described()
    assert entry.payload["constellation"] == "Лебедь"
    assert entry.observability["altitude_deg"] == 48.0


def test_classification_of_types():
    assert transients.classify_type({"object_type": {"name": "SN II"}}) == "supernova"
    assert transients.classify_type({"object_type": {"name": "Nova"}}) == "nova"
    assert transients.classify_type({"object_type": {"name": "AGN"}}) == "other"
    assert transients.classify_type({}) == "other"


def test_brightness_scale():
    assert transients.brightness_stars(5.0) == 5
    assert transients.brightness_stars(9.0) == 4
    assert transients.brightness_stars(12.0) == 3
    assert transients.brightness_stars(14.0) == 2
    assert transients.brightness_stars(18.0) == 1


def test_bright_transient_is_a_must():
    assert transients.rank_of(6.0, "nova") == "must"
    assert transients.rank_of(11.8, "supernova") == "interesting"
    assert transients.rank_of(16.0, "supernova") == "optional"


def test_filter_keeps_bright_supernova(described):
    assert transients.passes(described())


def test_filter_drops_faint_transient(described):
    faint = dict(TNS_RECORD, discoverymag=18.5)
    assert not transients.passes(described(faint))


def test_filter_can_switch_off_supernovae(described):
    assert not transients.passes(described(), supernovae=False)


def test_unclassified_object_is_not_published(described):
    raw = dict(TNS_RECORD)
    raw["object_type"] = None
    assert not transients.passes(described(raw))


def test_daytime_object_is_filtered_out(described, monkeypatch):
    entry = described()
    entry.observability["sun_altitude_deg"] = 10.0
    assert not transients.passes(entry)
    assert transients.passes(entry, only_at_night=False)


def test_show_all_ignores_brightness_limit(described):
    faint = described(dict(TNS_RECORD, discoverymag=18.5))
    assert transients.passes(faint, magnitude_limit=25.0)


def test_transient_watcher_uses_snapshot(tmp_path, monkeypatch, described):
    from astrocal import tns

    monkeypatch.setattr(tns, "search",
                        lambda **kwargs: ([{"objname": "2026abc"}],
                                          "2026-09-12T21:00:00+00:00"))
    monkeypatch.setattr(tns, "details",
                        lambda name, **kwargs: dict(TNS_RECORD))

    first, summary = transients.check(directory=tmp_path)
    assert first == [] and summary["first_run"]

    monkeypatch.setattr(tns, "search",
                        lambda **kwargs: ([{"objname": "2026abc"},
                                           {"objname": "2026xyz"}],
                                          "2026-09-12T22:00:00+00:00"))
    second, summary = transients.check(directory=tmp_path)
    assert summary["new"] == 1 and len(second) == 1


def test_missing_credentials_do_not_break_anything(tmp_path, monkeypatch):
    from astrocal import tns
    from astrocal.secrets import MissingCredentials

    def explode(**kwargs):
        raise MissingCredentials("TNS", ["TNS_API_KEY"])

    monkeypatch.setattr(tns, "search", explode)
    records, summary = transients.check(directory=tmp_path)
    assert records == []
    assert summary["status"] == "нет ключей"
    assert "TNS_API_KEY" in summary["error"]


def test_credentials_never_leak_into_provenance(described):
    entry = described()
    text = repr(entry.provenance) + repr(entry.payload)
    assert "api_key" not in text.lower()
    assert "TNS_API_KEY" not in text


# ------------------------------------------------------------------ покрытия


def path_points(shift_deg=0.0):
    base = dt.datetime(2026, 9, 19, 15, 50, tzinfo=dt.timezone.utc)
    return [{"lat": 55.0 + shift_deg, "lon": 37.0 + index,
             "utc": (base + dt.timedelta(seconds=index * 10)).isoformat()}
            for index in range(5)]


def occultation_record(points):
    return ScheduledEvent(
        live_id="astocc:40999:HIP1:2026-09-19T15:50Z", kind="occultation",
        title="(40999) 1999 UU8 покрывает HIP 1",
        when=dt.datetime(2026, 9, 19, 18, 50, tzinfo=cfg.MSK),
        payload={"star_id": "HIP 1", "star_mag": 3.9,
                 "central_path_sample": points},
        retain=("central_path_sample",))


def test_no_message_when_the_band_barely_moves(tmp_path):
    state = LiveState(tmp_path)
    state.observe(occultation_record(path_points()))
    fresh = occultation_record(path_points(0.05))          # ~5 км
    state.prepare(fresh)
    assert occultation_watch.shift_update(fresh) is None


def test_significant_band_shift_produces_an_update(tmp_path):
    state = LiveState(tmp_path)
    state.observe(occultation_record(path_points()))
    fresh = occultation_record(path_points(0.5))           # ~55 км
    state.prepare(fresh)
    update = occultation_watch.shift_update(fresh)
    assert update is not None
    assert update.semantic == "update"
    assert update.target_id == fresh.live_id
    assert 40 <= update.payload["shift_km"] <= 70
    assert "не изменён" in " ".join(update.lines)


def test_shift_threshold_is_configurable(tmp_path):
    state = LiveState(tmp_path)
    state.observe(occultation_record(path_points()))
    fresh = occultation_record(path_points(0.1))           # ~11 км
    state.prepare(fresh)
    assert occultation_watch.shift_update(fresh) is None
    assert occultation_watch.shift_update(fresh, threshold_km=5.0) is not None


def test_first_sighting_has_nothing_to_compare(tmp_path):
    fresh = occultation_record(path_points())
    LiveState(tmp_path).prepare(fresh)
    assert occultation_watch.shift_update(fresh) is None


def test_path_sample_is_compact():
    long_path = [{"lat": 50.0 + i * 0.01, "lon": 30.0 + i * 0.01,
                  "utc": dt.datetime(2026, 9, 19, tzinfo=dt.timezone.utc)}
                 for i in range(400)]
    assert len(occultation_watch.sample_path(long_path)) == 9


def test_occultation_identifier_is_stable():
    from astrocal.events.asteroid_occultations import occultation_id

    when = dt.datetime(2026, 9, 19, 15, 50, 12, tzinfo=dt.timezone.utc)
    later = dt.datetime(2026, 9, 19, 15, 50, 48, tzinfo=dt.timezone.utc)
    assert occultation_id(40999, "HIP 1", when) == \
        occultation_id(40999, "HIP 1", later), \
        "уточнение на секунды не создаёт новое событие"


def test_freshness_flags_a_stale_prediction():
    from astrocal.events.asteroid_occultations import Occultation

    now = dt.datetime.now(dt.timezone.utc)
    record = Occultation(
        event_id="astocc:1", asteroid_number=1, asteroid_name="Церера",
        star_id="HIP 1", star_name="", star_ra_deg=0.0, star_dec_deg=0.0,
        star_mag=8.0, asteroid_mag=9.0, magnitude_drop=2.0,
        event_utc=now + dt.timedelta(days=10),
        event_local=(now + dt.timedelta(days=10)).astimezone(cfg.MSK),
        duration_sec=3.0, asteroid_diameter_km=900.0, path_width_km=900.0,
        prediction_epoch=now - dt.timedelta(days=120))
    assert record.needs_refresh
    assert "пересчёт" in record.freshness_note


def test_old_prediction_for_a_distant_event_is_not_urgent():
    from astrocal.events.asteroid_occultations import Occultation

    now = dt.datetime.now(dt.timezone.utc)
    record = Occultation(
        event_id="astocc:2", asteroid_number=1, asteroid_name="Церера",
        star_id="HIP 1", star_name="", star_ra_deg=0.0, star_dec_deg=0.0,
        star_mag=8.0, asteroid_mag=9.0, magnitude_drop=2.0,
        event_utc=now + dt.timedelta(days=300),
        event_local=(now + dt.timedelta(days=300)).astimezone(cfg.MSK),
        duration_sec=3.0, asteroid_diameter_km=900.0, path_width_km=900.0,
        prediction_epoch=now - dt.timedelta(days=120))
    assert not record.needs_refresh


# ------------------------------------------------------------------ посты


def test_post_uses_only_the_data_it_has(described):
    text = post.build(described())
    assert "SN 2026abc" in text
    assert "+11,8m" in text
    assert "NGC 6946" in text
    assert "SN Ia" in text
    assert "Источник: Transient Name Server (TNS)" in text


def test_post_says_when_classification_is_missing(described):
    raw = dict(TNS_RECORD)
    raw["object_type"] = None
    text = post.build(described(raw))
    assert "классификация ещё не опубликована" in text.lower()


def test_post_does_not_invent_observability():
    record = DiscoveryEvent(
        live_id="tns:x", kind="transient", title="Сверхновая SN X",
        summary="Сверхновая SN X",
        payload={"name": "SN X", "discovery_mag": 12.0},
        observability={"visible": False, "note": "объект не поднимается"})
    text = post.build(record)
    assert "высота" not in text.lower()
    assert "не поднимается" in text


def test_comet_post_marks_the_forecast_as_a_model():
    record = DiscoveryEvent(
        live_id="comet:C/2026 X1", kind="comet", title="Новая комета C/2026 X1",
        summary="Открыта комета C/2026 X1",
        payload={"peak_magnitude": 8.0, "peak_when": "2027-01-10T00:00:00",
                 "current_magnitude": 15.8, "perihelion": "2027-01-04T00:00:00",
                 "perihelion_distance_au": 1.2, "closest_delta_au": 1.1,
                 "constellation": "Лебедь"},
        sources=["Minor Planet Center"])
    text = post.build(record)
    assert "оценка модели" in text
    assert "не измерение" in text


# ------------------------------------------------------------------ устойчивость


def test_one_broken_source_does_not_stop_the_others(tmp_path, monkeypatch):
    """Недоступный TNS не должен ронять кометы и сближения."""
    monkeypatch.setattr(discovery_service, "KINDS", ("neo", "transients"))

    def broken(**kwargs):
        raise RuntimeError("сеть недоступна")

    from astrocal.live import neo_watch
    monkeypatch.setattr(neo_watch, "check", lambda **kwargs: (
        [ScheduledEvent(live_id="neo:A", kind="neo", title="Пролёт",
                        when=dt.datetime(2026, 9, 10, tzinfo=cfg.MSK))],
        {"status": "ок", "new": 1, "total": 1}))
    monkeypatch.setattr(transients, "check", broken)

    result = discovery_service.refresh(("neo", "transients"),
                                       state=LiveState(tmp_path))
    assert result.new == 1
    assert result.errors == 1
    assert result.sources["transients"]["status"] == "недоступен"
    assert "Новых: " not in result.summary_text()
    assert result.summary_text().startswith("New: 1")

def test_card_lines_keep_russian_abbreviations():
    """Десятичная запятая не должна превращать «Макс.» в «Макс,»."""
    from astrocal.events.asteroid_occultations import Occultation

    now = dt.datetime.now(dt.timezone.utc)
    record = Occultation(
        event_id="astocc:40999", asteroid_number=40999, asteroid_name="1999 UU8",
        star_id="J235918.60+065148.9", star_name="", star_ra_deg=359.8,
        star_dec_deg=6.9, star_mag=3.9, asteroid_mag=15.0, magnitude_drop=13.1,
        event_utc=now, event_local=now.astimezone(cfg.MSK), duration_sec=0.6,
        asteroid_diameter_km=6.0, path_width_km=6.0,
        regions=["Дальний Восток"], uncertainty_km=52.0)
    lines = occultation_watch.describe(record).lines
    assert any("Макс. длительность: 0,6 с" == line for line in lines)
    assert any("Звезда: +3,9m" == line for line in lines)
    assert not any(",  " in line for line in lines)


def test_neo_post_keeps_units_intact():
    record = ScheduledEvent(
        live_id="neo:X", kind="neo", title="2026 XX",
        summary="Астероид 2026 XX пролетает в 653 тыс. км от Земли",
        payload={"fullname": "(2026 XX)", "velocity_km_s": 12.8,
                 "absolute_magnitude_H": 21.0},
        sources=["CNEOS"])
    text = post.build(record)
    assert "12,8 км/с." in text
    assert "H=21,0m" in text
