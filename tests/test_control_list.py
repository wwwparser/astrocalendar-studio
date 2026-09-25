"""Контрольный список покрытий: разбор страницы и проверка полноты.

Список наблюдателей — эталон, а не источник: он отвечает на вопрос «не
потеряли ли мы заметное событие». Сеть здесь не нужна, разбирается сохранённый
фрагмент страницы со всеми её особенностями, включая опечатку в названии
месяца.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from astrocal import config as cfg                                  # noqa: E402
from astrocal.core import Event                                     # noqa: E402
from astrocal.events import asteroid_occultations as occ            # noqa: E402


def load_script():
    """Скрипт сбора лежит в scripts/ и пакетом не является."""
    path = ROOT / "scripts" / "fetch_control_occultations.py"
    spec = importlib.util.spec_from_file_location("fetch_control", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PAGE = """
<div>
<p>29 августа, 00:18 — астероид (14717) 2000 CJ82 покрывает звезду HIP 20901
(+5m), видимость: ЕЧР, Урал, З. Сибирь</p>
<p>3 аперля, 14:34 — астероид (28387) 1999 JE79 покрывает звезду HIP 61719
(+6m), видимость: Д. Восток</p>
<p>3 мая, 16:40 — астероид (146) Lucina (d=137км) покрывает звезду HIP 34693
(+4m), видимость: Китай, Монголия, Алтай (длительность до 5 сек!)</p>
<p>Вернуться к списку новостей</p>
</div>
"""


@pytest.fixture(scope="module")
def parsed():
    return load_script().parse(PAGE)


# ------------------------------------------------------------------ разбор


def test_all_events_are_parsed(parsed):
    assert len(parsed) == 3


def test_fields_of_an_event(parsed):
    event = parsed[0]
    assert event["date"] == "08-29"
    assert event["time_msk"] == "00:18"
    assert event["asteroid_number"] == 14717
    assert event["asteroid_name"] == "2000 CJ82"
    assert event["star"] == "HIP 20901"
    assert event["star_magnitude"] == 5
    assert event["regions"] == ["ЕЧР", "Урал", "З. Сибирь"]


def test_typo_in_the_month_does_not_lose_an_event(parsed):
    """На странице написано «3 аперля» — событие не должно пропасть."""
    april = [e for e in parsed if e["date"].startswith("04")]
    assert len(april) == 1
    assert april[0]["asteroid_number"] == 28387


def test_diameter_is_separated_from_the_name(parsed):
    lucina = [e for e in parsed if e["asteroid_number"] == 146][0]
    assert lucina["asteroid_name"] == "Lucina"
    assert lucina["asteroid_diameter_km"] == 137
    assert "длительность" in lucina["note"]


def test_unrelated_lines_are_ignored(parsed):
    assert all("Вернуться" not in e["source_line"] for e in parsed)


# ------------------------------------------------------------------ сверка


@pytest.fixture
def control(tmp_path, monkeypatch, parsed):
    """Подменить каталог данных временным с нашим списком."""
    payload = {"year": 2026, "url": "https://example/list",
               "fetched_at": "2026-09-25T10:00:00+00:00",
               "criteria": "яркие покрытия", "events": parsed}
    (tmp_path / "control_occultations_2026.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cfg, "DATA", tmp_path)
    return payload


def our_event(number: int, when: dt.datetime) -> Event:
    return Event(when=when, text="покрытие", category="asteroid_occultation",
                 meta={"asteroid": number})


def test_control_list_is_loaded(control):
    assert len(occ.control_list(2026)["events"]) == 3


def test_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA", tmp_path)
    assert occ.control_list(2026)["events"] == []


def test_matching_event_is_found(control):
    ours = [our_event(14717, dt.datetime(2026, 8, 29, 0, 18, tzinfo=cfg.MSK))]
    result = occ.compare_with_control(ours, 2026, 8)
    assert result["expected"] == 1
    assert len(result["matched"]) == 1 and not result["missing"]


def test_shifted_by_hours_still_matches(control):
    """Пересчёт по свежей орбите законно сдвигает момент — это то же событие."""
    ours = [our_event(14717, dt.datetime(2026, 8, 29, 21, 40, tzinfo=cfg.MSK))]
    assert len(occ.compare_with_control(ours, 2026, 8)["matched"]) == 1


def test_shifted_by_a_week_does_not_match(control):
    ours = [our_event(14717, dt.datetime(2026, 8, 22, 0, 18, tzinfo=cfg.MSK))]
    result = occ.compare_with_control(ours, 2026, 8)
    assert not result["matched"] and len(result["missing"]) == 1


def test_absent_event_is_reported(control):
    result = occ.compare_with_control([], 2026, 8)
    assert len(result["missing"]) == 1
    assert result["missing"][0]["asteroid_number"] == 14717
    assert result["coverage"] == 0.0


def test_our_extra_events_are_counted_separately(control):
    ours = [our_event(14717, dt.datetime(2026, 8, 29, 0, 18, tzinfo=cfg.MSK)),
            our_event(99999, dt.datetime(2026, 8, 5, 3, 0, tzinfo=cfg.MSK))]
    result = occ.compare_with_control(ours, 2026, 8)
    assert len(result["matched"]) == 1
    assert len(result["extra"]) == 1


def test_month_filter_limits_the_comparison(control):
    result = occ.compare_with_control([], 2026, 5)
    assert result["expected"] == 1
    assert result["missing"][0]["asteroid_number"] == 146


def test_whole_year_without_month(control):
    assert occ.compare_with_control([], 2026)["expected"] == 3


def test_full_coverage(control):
    ours = [our_event(14717, dt.datetime(2026, 8, 29, tzinfo=cfg.MSK)),
            our_event(28387, dt.datetime(2026, 4, 3, tzinfo=cfg.MSK)),
            our_event(146, dt.datetime(2026, 5, 3, tzinfo=cfg.MSK))]
    result = occ.compare_with_control(ours, 2026)
    assert result["coverage"] == 1.0


def test_description_names_what_is_missing(control):
    text = occ.describe_comparison(occ.compare_with_control([], 2026, 8))
    assert "не найдено 1" in text
    assert "14717" in text and "HIP 20901" in text


def test_occultation_record_is_matched_by_its_own_field(control):
    """Сверка работает и с полной карточкой покрытия, не только со строкой."""
    record = occ.Occultation(
        event_id="astocc:14717", asteroid_number=14717,
        asteroid_name="2000 CJ82", star_id="HIP 20901", star_name="",
        star_ra_deg=67.0, star_dec_deg=15.0, star_mag=5.0, asteroid_mag=15.0,
        magnitude_drop=10.0,
        event_utc=dt.datetime(2026, 8, 28, 21, 18, tzinfo=dt.timezone.utc),
        event_local=dt.datetime(2026, 8, 29, 0, 18, tzinfo=cfg.MSK),
        duration_sec=2.0, asteroid_diameter_km=20.0, path_width_km=20.0)
    result = occ.compare_with_control([record], 2026, 8)
    assert len(result["matched"]) == 1
