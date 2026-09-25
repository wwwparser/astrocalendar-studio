"""Блеск комет: наблюдения вместо формулы из архива.

Замечание с разбора октябрьского выпуска: 65P/Gunn ушла в пост с +10,6ᵐ при
наблюдаемых 18,8ᵐ — ошибка в десять тысяч раз по потоку света. Здесь
зафиксировано поведение, которое этого больше не допустит.

Сеть не трогается: ответы COBS и таблица ван Бёйтенена подставляются.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import comet_feeds as cf                             # noqa: E402

COBS_JSON = json.dumps({
    "info": {"recordsTotal": 3},
    "objects": [
        {"id": 1, "name": "65P", "fullname": "65P/Gunn", "current_mag": "18.8",
         "peak_mag": "16.1", "peak_mag_date": "2025-06-28",
         "perihelion_mag": "16.3", "is_observed": True, "is_active": True},
        {"id": 2, "name": "10P", "fullname": "10P/Tempel", "current_mag": "9.4",
         "peak_mag": "8.2", "peak_mag_date": "2026-08-03",
         "perihelion_mag": "8.2", "is_observed": True, "is_active": True},
        {"id": 3, "name": "C/2026 X1", "fullname": "C/2026 X1 (Test)",
         "current_mag": None, "peak_mag": None, "peak_mag_date": None,
         "perihelion_mag": None, "is_observed": False, "is_active": True},
    ]})

# У таблицы комет нет ни одного <tr>: ячейки идут подряд, строка закрывается
# одним </tr>. Разметка сохранена как на сайте — на ней разбор и ломался.
VB_HTML = """
<table><thead>
<tr><th colspan="1">Comet(s)</th><th colspan="3">Today</th>
    <th colspan="3">Perihelion</th><th colspan="3">Nearest approach</th></tr>
<tr><th>designation</th><th>magn</th><th>delta</th><th>radius</th>
    <th>date</th><th>magn</th><th>radius</th>
    <th>date</th><th>magn</th><th>delta</th></tr>
</thead><tbody>
<td><a href='#'>10P/Tempel</a></td><td>9.4</td><td>0.62 AU</td><td>1.53 AU</td>
<td>2 Aug 2026</td><td>8.2</td><td>1.42 AU</td><td>3 Aug 2026</td><td>8.2</td>
<td>0.41 AU</td></tr>
<td><a href='#'>161P/Hartley-IRAS</a></td><td>11.8</td><td>0.54 AU</td>
<td>1.53 AU</td><td>27 Nov 2026</td><td>12.3</td><td>1.27 AU</td>
<td>2 Oct 2026</td><td>11.4</td><td>0.50 AU</td></tr>
</tbody></table>
"""


@pytest.fixture
def feeds(monkeypatch):
    class FakeResponse:
        def __init__(self, body):
            self.body = body
            self.fetched_at = dt.datetime(2026, 9, 25, 12, 0,
                                          tzinfo=dt.timezone.utc)

        def json(self):
            return json.loads(self.body)

    def fake_fetch(url, **kwargs):
        return FakeResponse(COBS_JSON if url == cf.COBS_URL else VB_HTML)

    monkeypatch.setattr(cf, "fetch", fake_fetch)
    from astrocal import neo_feeds
    monkeypatch.setattr(neo_feeds, "fetch", fake_fetch)


# ------------------------------------------------------------------ разбор


def test_cobs_is_parsed(feeds):
    entries = cf.cobs()
    assert len(entries) == 3
    gunn = entries[0]
    assert gunn.current_magnitude == 18.8
    assert gunn.observed is True


def test_vanbuitenen_table_without_row_tags(feeds):
    """В таблице комет нет <tr> — ячейки открывают строку сами."""
    entries = cf.vanbuitenen()
    assert len(entries) == 2
    assert entries[0].designation == "10P/Tempel"
    assert entries[0].current_magnitude == 9.4


def test_empty_table_is_an_error(monkeypatch):
    """Заголовок разобран, строк нет — это отказ разбора, а не пустая таблица."""
    from astrocal import neo_feeds

    empty = VB_HTML[:VB_HTML.index("<tbody>")] + "<tbody></tbody></table>"

    class FakeResponse:
        body = empty
        fetched_at = dt.datetime(2026, 9, 25, tzinfo=dt.timezone.utc)

    monkeypatch.setattr(cf, "fetch", lambda url, **kw: FakeResponse())
    monkeypatch.setattr(neo_feeds, "fetch", lambda url, **kw: FakeResponse())
    with pytest.raises(ValueError, match="ни одной строки"):
        cf.vanbuitenen()


# ------------------------------------------------------------------ ключи


def test_periodic_comet_keys():
    keys = cf.designation_keys("161P/Hartley-IRAS")
    assert "161P" in keys and "161P/HARTLEY-IRAS" in keys


def test_long_period_comet_keys():
    keys = cf.designation_keys("C/2024 J3 (ATLAS)")
    assert "C/2024 J3" in keys


def test_index_finds_by_short_and_full_name(feeds):
    index = cf.load()
    assert index.find("65P/Gunn").current_magnitude == 18.8
    assert index.find("65P").current_magnitude == 18.8
    assert index.find("999P/Nobody") is None


def test_observations_win_over_forecast(feeds):
    """COBS — наблюдения, ван Бёйтенен — прогноз; приоритет у наблюдений."""
    index = cf.load()
    assert index.find("10P/Tempel").source == cf.COBS_SOURCE


def test_broken_source_does_not_raise(monkeypatch):
    def explode(url, **kwargs):
        raise RuntimeError("источник недоступен")

    monkeypatch.setattr(cf, "fetch", explode)
    index = cf.load()
    assert not index.available and len(index.errors) == 2


# ------------------------------------------------------------------ калибровка


def test_offset_brings_model_to_observation(feeds, monkeypatch):
    """Сдвиг модели равен разнице между наблюдением и моделью на сегодня."""
    from astrocal.events import comets

    comets.brightness_index.cache_clear()
    monkeypatch.setattr(comets, "brightness_index", lambda: cf.load())

    row = {"designation": "65P/Gunn", "magnitude_g": 6.0, "magnitude_k": 10.0}
    monkeypatch.setattr(comets, "model_magnitude_now", lambda r: 10.5)

    offset, entry = comets.calibrate(row)
    assert entry.current_magnitude == 18.8
    assert abs(offset - 8.3) < 0.01


def test_no_offset_when_model_cannot_be_evaluated(feeds, monkeypatch):
    """Орбита не считается — блеск остаётся наблюдённым, модель не выдумываем."""
    from astrocal.events import comets

    comets.brightness_index.cache_clear()
    monkeypatch.setattr(comets, "brightness_index", lambda: cf.load())
    monkeypatch.setattr(comets, "model_magnitude_now", lambda r: None)
    offset, entry = comets.calibrate({"designation": "65P/Gunn"})
    assert offset == 0.0 and entry is not None


def test_unknown_comet_gets_no_calibration(feeds, monkeypatch):
    from astrocal.events import comets

    comets.brightness_index.cache_clear()
    monkeypatch.setattr(comets, "brightness_index", lambda: cf.load())
    offset, entry = comets.calibrate({"designation": "999P/Nobody"})
    assert offset == 0.0 and entry is None


def test_magnitude_note_names_the_source(feeds):
    from astrocal.events.comets import magnitude_note

    entry = cf.load().find("65P")
    note = magnitude_note(entry, 8.3)
    assert "COBS" in note and "18.8" in note


def test_magnitude_note_admits_when_there_is_no_observation():
    from astrocal.events.comets import magnitude_note

    note = magnitude_note(None, 0.0)
    assert "наблюдений" in note and "ненадёжно" in note


# ------------------------------------------------------------------ публикация


def base_meta(**extra) -> dict:
    meta = {"visible": True, "sep_deg": 0.3, "object_mag": 3.9, "kind": "star",
            "magnitude_observed": True}
    meta.update(extra)
    return meta


def test_observed_comet_can_be_published():
    from astrocal.events.comets import interesting

    assert interesting(base_meta())


def test_comet_without_observations_is_not_published():
    """Главный урок разбора: неподтверждённый блеск в пост не идёт."""
    from astrocal.events.comets import interesting

    assert not interesting(base_meta(magnitude_observed=False))


def test_invisible_comet_is_not_published():
    from astrocal.events.comets import interesting

    assert not interesting(base_meta(visible=False))
