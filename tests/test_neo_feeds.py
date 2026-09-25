"""Таблицы блеска околоземных астероидов: разбор, сопоставление, сверка.

Сеть не трогается: страницы подставляются фрагментами настоящей разметки,
включая её особенность — на странице ярких объектов строки `<tr>` не закрыты.
Именно на этом разбор и ломался, поэтому фрагмент сохранён как есть.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import neo_feeds as nf                              # noqa: E402
from astrocal.events import close_approaches as ca                # noqa: E402

# Строки таблицы ярких объектов не закрыты — так отдаёт сам сайт
BRIGHT_HTML = """
<table><thead>
<tr><th colspan="3">NEO</th><th colspan="2">Today</th>
    <th colspan="3">Closest Approach</th><th colspan="2">Brightest</th></tr>
<tr><th>designation</th><th>H&#8320;</th><th>diameter est.</th>
    <th>magn</th><th>delta (LD)</th>
    <th>date</th><th>delta (LD)</th><th>magn</th>
    <th>date</th><th>magn</th></tr>
</thead><tbody>
<tr><td><a href='#'>(137108) 1999 AN10</a></td><td>18.1</td><td>650 - 1460 m</td>
    <td>21.4</td><td>900.0 LD</td><td>7 Aug 2027</td><td>1.0 LD</td><td>7.8</td>
    <td>7 Aug 2027</td><td>7.6</td>
<tr><td><a href='#'>(217628) Lugh</a></td><td>16.7</td><td>1 - 3 km</td>
    <td>18.6</td><td>321.0 LD</td><td>28 Nov 2026</td><td>27.5 LD</td><td>14.0</td>
    <td>23 Nov 2026</td><td>13.4</td>
</tbody></table>
"""

APPROACH_HTML = """
<table><thead>
<tr><th colspan="2">NEO</th><th colspan="3">Today</th>
    <th colspan="6">Closest Approach</th></tr>
<tr><th>designation</th><th>diameter</th>
    <th>magn</th><th>delta (AU)</th><th>delta (LD)</th>
    <th>date</th><th>ra</th><th>dec</th><th>magn</th>
    <th>delta (AU)</th><th>delta (LD)</th></tr>
</thead><tbody>
<tr><td><a href='#'>2026 RZ1</a></td><td>30 - 60 m</td><td>20.1</td>
    <td>0.030 AU</td><td>11.7 LD</td><td>22 Sep 2026</td><td>03h45m</td>
    <td>-03&#176;11'</td><td>19.1</td><td>0.027 AU</td><td>10.4 LD</td></tr>
<tr><td><a href='#'>(2019 AS2)</a></td><td>37 - 82 m</td><td>20.9</td>
    <td>0.020 AU</td><td>7.8 LD</td><td>2 Oct 2026</td><td>22h10m</td>
    <td>+45&#176;30'</td><td>19.7</td><td>0.011 AU</td><td>4.5 LD</td></tr>
</tbody></table>
"""


def feed(monkeypatch, bright=BRIGHT_HTML, approach=APPROACH_HTML):
    """Подменить сетевой слой заранее заготовленными страницами."""
    class FakeResponse:
        def __init__(self, body):
            self.body = body
            self.fetched_at = dt.datetime(2026, 9, 25, 10, 0,
                                          tzinfo=dt.timezone.utc)

    def fake_fetch(url, **kwargs):
        return FakeResponse(bright if url == nf.BRIGHT_URL else approach)

    monkeypatch.setattr(nf, "fetch", fake_fetch)


# ------------------------------------------------------------------ разбор


def test_unclosed_rows_are_still_parsed(monkeypatch):
    """На странице ярких объектов <tr> не закрыты — строки терялись молча."""
    feed(monkeypatch)
    entries = nf.bright()
    assert len(entries) == 2


def test_bright_fields(monkeypatch):
    feed(monkeypatch)
    an10 = nf.bright()[0]
    assert an10.designation == "(137108) 1999 AN10"
    assert an10.absolute_magnitude == 18.1
    assert an10.diameter_text == "650 - 1460 m"
    assert an10.brightest_magnitude == 7.6
    assert an10.closest_ld == 1.0


def test_approach_fields(monkeypatch):
    feed(monkeypatch)
    entry = nf.approaches()[0]
    assert entry.designation == "2026 RZ1"
    assert entry.closest_magnitude == 19.1
    assert entry.closest_ld == 10.4
    assert entry.closest_date.day == 22 and entry.closest_date.month == 9


def test_coordinates_are_converted_to_degrees(monkeypatch):
    feed(monkeypatch)
    entry = nf.approaches()[0]
    assert abs(entry.ra_deg - 56.25) < 0.01          # 03h45m
    assert abs(entry.dec_deg + 3.183) < 0.01         # -03°11'


def test_positive_declination(monkeypatch):
    feed(monkeypatch)
    entry = nf.approaches()[1]
    assert abs(entry.dec_deg - 45.5) < 0.01


def test_changed_table_structure_is_an_error(monkeypatch):
    """Лучше явная ошибка, чем тихо разъехавшиеся колонки."""
    broken = APPROACH_HTML.replace("<th>diameter</th>", "<th>size</th>")
    feed(monkeypatch, approach=broken)
    try:
        nf.approaches()
    except ValueError as error:
        assert "структура таблицы" in str(error)
    else:
        raise AssertionError("изменение колонок осталось незамеченным")


def test_peak_magnitude_prefers_the_brightest_column(monkeypatch):
    feed(monkeypatch)
    lugh = nf.bright()[1]
    assert lugh.closest_magnitude == 14.0
    assert lugh.peak_magnitude == 13.4
    assert lugh.peak_when.day == 23


# ------------------------------------------------------------------ ключи


def test_designation_keys_split_number_and_name():
    keys = nf.designation_keys("(363790) 2005 JE46")
    assert "363790" in keys
    assert "2005JE46" in keys


def test_designation_keys_for_named_object():
    keys = nf.designation_keys("(217628) Lugh")
    assert "217628" in keys and "LUGH" in keys


def test_designation_keys_for_provisional():
    assert nf.designation_keys("2026 RZ1") == {"2026RZ1"}


def test_index_finds_by_either_form(monkeypatch):
    feed(monkeypatch)
    index = nf.load()
    assert index.find("1999 AN10") is not None
    assert index.find("137108") is not None
    assert index.find("2026 RZ1") is not None
    assert index.find("2026 ZZ99") is None


def test_broken_source_does_not_raise(monkeypatch):
    def explode(url, **kwargs):
        raise RuntimeError("сайт недоступен")

    monkeypatch.setattr(nf, "fetch", explode)
    index = nf.load()
    assert not index.available
    assert len(index.errors) == 2


# ------------------------------------------------------------------ сверка


def approach_record(magnitude: float | None):
    from astrocal.live.model import ScheduledEvent

    return ScheduledEvent(
        live_id="neo:X", kind="neo", title="X",
        payload={"distance_km": 1.7e6, "distance_ld": 4.42,
                 "velocity_km_s": 7.3, "absolute_magnitude_H": 24.3,
                 "diameter_estimate": 0.049,
                 "magnitude_computed": 19.1, "feed_magnitude": magnitude},
        provenance={"source": "CNEOS", "source_updated_at": "2026-09-25T10:00:00",
                    "diameter_provenance": "оценка по H=24.3"})


def test_close_magnitudes_pass_quietly():
    from astrocal import qa_live

    flags = qa_live.check(approach_record(19.3))
    assert not [f for f in flags if f.check == "neo_magnitude"]


def test_moderate_disagreement_is_a_warning():
    from astrocal import qa_live

    flags = qa_live.check(approach_record(19.7))
    warning = [f for f in flags if f.check == "neo_magnitude"]
    assert warning and warning[0].level == "WARN"


def test_large_disagreement_needs_review():
    from astrocal import qa_live

    flags = qa_live.check(approach_record(22.0))
    review = [f for f in flags if f.check == "neo_magnitude"]
    assert review and review[0].level == "REVIEW"


def test_missing_second_source_is_not_an_error():
    from astrocal import qa_live

    flags = qa_live.check(approach_record(None))
    assert not [f for f in flags if f.check == "neo_magnitude"]


def test_feed_magnitude_is_attached_to_approaches(monkeypatch):
    feed(monkeypatch)
    item = ca.CloseApproach(
        designation="2019 AS2", fullname="(2019 AS2)",
        close_approach_datetime=dt.datetime(2026, 10, 2, tzinfo=dt.timezone.utc),
        distance_au=0.011, distance_km=1.7e6, distance_ld=4.5,
        velocity_km_s=7.3, absolute_magnitude_H=24.3,
        diameter_min=0.037, diameter_max=0.082, diameter_estimate=0.049)
    ca.attach_feed([item], nf.load())
    assert item.feed_magnitude == 19.7
    assert "vanbuitenen" in item.feed_source
    item.observability = {"magnitude": 19.1}
    assert abs(item.magnitude_difference + 0.6) < 0.01


# ------------------------------------------------------------------ яркие за год


def test_bright_of_year_is_sorted_by_magnitude(monkeypatch):
    feed(monkeypatch)
    entries = ca.bright_of_year()
    assert [e.peak_magnitude for e in entries] == [7.6, 13.4]


def test_bright_rank_by_brightness():
    class Entry:
        peak_magnitude = 7.6
    assert ca.bright_rank(Entry()) == "must"
    Entry.peak_magnitude = 12.0
    assert ca.bright_rank(Entry()) == "interesting"
    Entry.peak_magnitude = 14.0
    assert ca.bright_rank(Entry()) == "optional"


def test_bright_event_text(monkeypatch):
    feed(monkeypatch)
    event = ca.bright_to_event(ca.bright_of_year()[0])
    assert "1999 AN10" in event.text
    assert "+7,6m" in event.text
    assert event.category == "neo_bright"
    assert event.rank == "must"


def test_bright_event_is_classified_and_ranked(monkeypatch):
    from astrocal.taxonomy import classify
    from astrocal.rating import rank_event

    feed(monkeypatch)
    event = ca.bright_to_event(ca.bright_of_year()[0])
    assert classify(event) == "bright_neo"
    assert rank_event(event) == "must"


def test_only_maxima_inside_the_month_become_events(monkeypatch):
    from astrocal import config as cfg

    feed(monkeypatch)
    start, end = cfg.month_bounds(2027, 8)
    events = ca.bright_events(start, end)
    assert len(events) == 1 and "1999 AN10" in events[0].text

    start, end = cfg.month_bounds(2027, 9)
    assert ca.bright_events(start, end) == []
