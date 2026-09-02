"""Сближения астероидов: перевод единиц, отбор, устойчивые идентификаторы.

Сеть не трогается: ответ CNEOS подставляется заранее подготовленным.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import config as cfg                                  # noqa: E402
from astrocal.events import close_approaches as ca                  # noqa: E402

FIELDS = ["des", "orbit_id", "jd", "cd", "dist", "dist_min", "dist_max",
          "v_rel", "v_inf", "t_sigma_f", "h", "diameter", "fullname"]


def row(des, cd, dist_au, v_rel, h, diameter=None, fullname=None):
    return [des, "1", "2461000.5", cd, str(dist_au), str(dist_au * 0.99),
            str(dist_au * 1.01), str(v_rel), str(v_rel), "00:01", str(h),
            diameter, fullname or f"({des})"]


def payload(rows):
    return {"signature": {"source": "NASA/JPL"}, "count": len(rows),
            "fields": FIELDS, "data": rows}


# 0.00257 а.е. ≈ 1 LD; 0.01 а.е. ≈ 3.9 LD
SAMPLE = payload([
    row("2026 AA", "2026-Sep-10 05:12", 0.0015, 12.8, 22.0),       # 0.58 LD
    row("2026 BB", "2026-Sep-12 18:40", 0.0100, 9.4, 22.5),        # 3.9 LD, 55 м
    row("2026 CC", "2026-Sep-15 03:00", 0.0100, 9.4, 30.0),        # 3.9 LD, 2 м
    row("2026 DD", "2026-Sep-20 11:00", 0.0400, 18.0, 20.0),       # 15.6 LD, 340 м
    row("2026 EE", "2026-Sep-25 11:00", 0.0400, 18.0, 27.0),       # 15.6 LD, 14 м
])


def approaches():
    return ca.parse_payload(SAMPLE, "2026-09-02T10:00:00+00:00")


# ------------------------------------------------------------------ разбор


def test_parses_all_rows():
    assert len(approaches()) == 5


def test_kilometres_and_lunar_distances_agree():
    for item in approaches():
        assert abs(item.distance_km / cfg.LUNAR_DISTANCE_KM
                   - item.distance_ld) < 1e-9
        assert abs(item.distance_au * ca.AU_KM - item.distance_km) < 1.0


def test_one_lunar_distance_is_384400_km():
    item = approaches()[0]
    assert abs(item.distance_ld - item.distance_km / 384400.0) < 1e-9


def test_diameter_bounds_bracket_the_estimate():
    for item in approaches():
        assert item.diameter_min < item.diameter_estimate < item.diameter_max


def test_diameter_from_h_matches_reference():
    # H=20 при альбедо 0.14 даёт примерно 340 м — общеизвестное значение
    assert 0.30 < ca.diameter_km(20.0) < 0.36


def test_times_are_moscow():
    for item in approaches():
        assert item.close_approach_datetime.utcoffset() == dt.timedelta(hours=3)


# ------------------------------------------------------------------ отбор


def test_closer_than_the_moon_is_a_must():
    item = next(a for a in approaches() if a.designation == "2026 AA")
    assert ca.rank_of(item) == "must"


def test_small_but_close_object_is_interesting():
    item = next(a for a in approaches() if a.designation == "2026 BB")
    assert ca.rank_of(item) == "interesting"


def test_tiny_rock_nearby_is_only_optional():
    """Двухметровый камень в четырёх лунных расстояниях — не событие."""
    item = next(a for a in approaches() if a.designation == "2026 CC")
    assert ca.rank_of(item) == "optional"


def test_large_object_is_interesting_even_farther():
    item = next(a for a in approaches() if a.designation == "2026 DD")
    assert ca.rank_of(item) == "interesting"


def test_small_object_far_away_is_filtered_out():
    item = next(a for a in approaches() if a.designation == "2026 EE")
    assert ca.rank_of(item) == "optional"
    assert item not in ca.significant(approaches())


def test_significant_keeps_only_publishable():
    chosen = {a.designation for a in ca.significant(approaches())}
    assert chosen == {"2026 AA", "2026 BB", "2026 DD"}


# ------------------------------------------------------------------ события


def test_stable_identifier_survives_reparsing():
    first = {a.live_id for a in approaches()}
    second = {a.live_id for a in ca.parse_payload(SAMPLE)}
    assert first == second
    assert len(first) == 5, "идентификаторы должны быть уникальными"


def test_identifier_names_object_and_moment():
    item = next(a for a in approaches() if a.designation == "2026 AA")
    assert item.live_id.startswith("neo:2026AA:2026-09-10T")


def test_event_text_mentions_distance_and_size():
    item = next(a for a in approaches() if a.designation == "2026 DD")
    item.rank = ca.rank_of(item)
    event = ca.to_event(item)
    assert "от Земли" in event.text
    assert "расстояния Земля—Луна" in event.text
    assert event.rank == "interesting"


def test_event_records_that_diameter_is_an_estimate():
    """Оценка размера по H не должна выглядеть как измерение."""
    event = ca.to_event(approaches()[0])
    assert "оценка по H" in event.provenance["diameter_provenance"]
    assert event.text.count("d≈") == 1


def test_measured_diameter_is_marked_differently():
    rows = [row("433", "2026-Sep-10 05:12", 0.0015, 12.8, 11.2, "16.84", "433 Eros")]
    item = ca.parse_payload(payload(rows))[0]
    assert item.diameter_measured == 16.84
    assert item.diameter_text.startswith("d=")
    assert ca.to_event(item).provenance["diameter_provenance"] == "измерен"


def test_qa_catches_broken_lunar_distance_conversion():
    from astrocal import qa

    item = approaches()[0]
    event = ca.to_event(item)
    event.meta["distance_ld"] = item.distance_ld * 10      # порча значения
    event.flags = []
    qa.check_close_approach(event)
    assert any(flag.check == "neo_ld" for flag in event.flags)
