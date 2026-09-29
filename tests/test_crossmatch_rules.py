"""Пороги отбора сближений малых тел с объектами каталогов.

Три правила задал Станислав Короткий; проверяем и что они пропускают то, что
должны, и что не пропускают лишнего, и что оба модуля — астероиды и кометы —
судят по одной мерке.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import crossmatch                                   # noqa: E402


# ------------------------------------------------------------------ Мессье


def test_faint_body_near_messier_passes():
    assert crossmatch.by_new_rules(18.5, "dso", 8.0, True, 0.9)


def test_body_fainter_than_limit_near_messier_rejected():
    assert not crossmatch.by_new_rules(19.5, "dso", 8.0, True, 0.9)


def test_messier_rule_stops_at_one_degree():
    assert not crossmatch.by_new_rules(12.0, "dso", 8.0, True, 1.2)


# ------------------------------------------------------------------ NGC/IC


def test_body_near_ngc_passes_at_thirteen():
    assert crossmatch.by_new_rules(12.9, "dso", 11.0, False, 0.9)


def test_ngc_rule_is_stricter_than_messier():
    """То же тело и то же расстояние: у Мессье проходит, у NGC — нет."""
    assert crossmatch.by_new_rules(15.0, "dso", 11.0, True, 0.8)
    assert not crossmatch.by_new_rules(15.0, "dso", 11.0, False, 0.8)


# ------------------------------------------------------------------ звёзды


def test_body_near_bright_star_passes():
    assert crossmatch.by_new_rules(12.5, "star", 6.5, False, 0.4)


def test_faint_star_does_not_trigger_the_rule():
    assert not crossmatch.by_new_rules(12.5, "star", 7.5, False, 0.4)


def test_star_rule_radius_is_one_degree():
    """Сначала порог был 0,5°, Станислав расширил его до градуса."""
    assert crossmatch.by_new_rules(12.5, "star", 6.5, False, 0.9)
    assert not crossmatch.by_new_rules(12.5, "star", 6.5, False, 1.2)


# ------------------------------------------------------------------ пределы


def test_search_limits_cover_every_rule():
    for limit, radius in (crossmatch.MESSIER, crossmatch.NGC_IC,
                          crossmatch.STAR):
        assert limit <= crossmatch.BODY_MAG_LIMIT
        assert radius <= crossmatch.SEARCH_RADIUS_DEG


def test_rule_name_explains_the_reason():
    text = crossmatch.rule_name(18.0, "dso", 8.0, True, 0.5)
    assert "Мессье" in text
    assert crossmatch.rule_name(5.0, "dso", 8.0, False, 2.0) == \
        "прежнее правило отбора"


# ------------------------------------------------------------- номер Мессье


def test_missing_messier_number_is_not_truthy():
    """В каталоге пропуск приходит как NaN, а `bool(nan)` истинно."""
    from astrocal.catalogs import is_messier

    assert is_messier("M42")
    assert not is_messier(float("nan"))
    assert not is_messier(None)
    assert not is_messier("")
    assert not is_messier("   ")


def test_catalogue_rows_agree_with_the_helper():
    from astrocal.catalogs import deep_sky, is_messier

    catalog = deep_sky()
    flagged = catalog[catalog.messier.map(is_messier)]
    assert 100 <= len(flagged) <= 110, "объектов Мессье около 110"
    assert all(name.startswith("M") for name in flagged.messier)


# ------------------------------------------------------- применение в модулях


def test_asteroid_near_messier_is_published_though_faint():
    """Прежний порог 10,5ᵐ такое событие отбрасывал."""
    from astrocal.events.asteroids import interesting

    assert interesting({"mag": 14.0, "kind": "dso", "object_mag": 8.0,
                        "messier": True, "sep_deg": 0.8})


def test_asteroid_old_wide_rule_still_works():
    """Яркая звезда в двух градусах: новое правило не проходит, прежнее — да."""
    from astrocal.events.asteroids import interesting

    assert not crossmatch.by_new_rules(9.0, "star", 3.5, False, 2.0)
    assert interesting({"mag": 9.0, "kind": "star", "object_mag": 3.5,
                        "messier": False, "sep_deg": 2.0})


def test_comet_near_messier_is_published_though_faint():
    from astrocal.events.comets import interesting

    assert interesting({"visible": True, "magnitude_observed": True,
                        "sep_deg": 0.8, "object_mag": 9.0, "kind": "dso",
                        "messier": True, "comet_mag": 16.0})


def test_comet_without_observed_brightness_still_blocked():
    """Новые правила не отменяют требования подтверждённого блеска."""
    from astrocal.events.comets import interesting

    assert not interesting({"visible": True, "magnitude_observed": False,
                            "sep_deg": 0.2, "object_mag": 9.0, "kind": "dso",
                            "messier": True, "comet_mag": 10.0})


def test_comet_without_known_magnitude_does_not_pass_new_rules():
    """Объект слабее прежнего порога 11,5ᵐ: пройти можно только по новым
    правилам, а они требуют блеска самой кометы."""
    from astrocal.events.comets import interesting

    base = {"visible": True, "magnitude_observed": True, "sep_deg": 0.8,
            "object_mag": 11.9, "kind": "dso", "messier": True}
    assert interesting({**base, "comet_mag": 16.0})
    assert not interesting(base)
