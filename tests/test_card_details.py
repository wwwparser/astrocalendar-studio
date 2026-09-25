"""Полнота карточек: видимые размеры, фазы, значки, названия объектов.

Замечания наблюдателя: около Луны нужны фаза и угловой диаметр, около планет —
блеск и диаметр, у Меркурия и Венеры ещё фаза, у покрытий астероидами — блеск
астероида, созвездие, ширина полосы и длительность, у Титана — расстояние до
края диска, а не до центра.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal import apparent, icons                              # noqa: E402
from astrocal.catalogs import dso_common_name                     # noqa: E402
from astrocal.config import MSK                                   # noqa: E402
from astrocal.core import Event, timescale                        # noqa: E402


@pytest.fixture(scope="module")
def moment():
    return timescale().from_datetime(dt.datetime(2026, 10, 2, tzinfo=MSK))


# ------------------------------------------------------------------ размеры


def test_moon_diameter_is_about_half_a_degree(moment):
    arcsec = apparent.angular_diameter_arcsec("moon", moment)
    assert 1750 < arcsec < 2020          # 29,2′…33,7′ — крайние значения орбиты


def test_moon_is_larger_at_perigee():
    perigee = timescale().from_datetime(dt.datetime(2026, 10, 2, tzinfo=MSK))
    apogee = timescale().from_datetime(dt.datetime(2026, 10, 17, tzinfo=MSK))
    assert (apparent.angular_diameter_arcsec("moon", perigee)
            > apparent.angular_diameter_arcsec("moon", apogee))


def test_planet_diameters_are_plausible(moment):
    jupiter = apparent.angular_diameter_arcsec("jupiter", moment)
    neptune = apparent.angular_diameter_arcsec("neptune", moment)
    assert 29 < jupiter < 51             # Юпитер от соединения до противостояния
    assert 2.0 < neptune < 2.5
    assert jupiter > neptune


def test_diameter_format_switches_to_minutes():
    assert apparent.format_diameter(1941.0) == "32′21″"
    assert apparent.format_diameter(19.7) == "19,7″"


def test_moon_label_has_phase_and_diameter(moment):
    label = apparent.moon_label(moment, 0.69, False)
    assert label.startswith("Ф=-0,69")
    assert "D=" in label and "′" in label


def test_planet_label_has_magnitude_and_diameter(moment):
    label = apparent.planet_label("saturn", moment)
    assert label.startswith("V=")
    assert "D=" in label


def test_phase_is_shown_only_for_inner_planets(moment):
    assert "Ф=" in apparent.planet_label("venus", moment)
    assert "Ф=" in apparent.planet_label("mercury", moment)
    assert "Ф=" not in apparent.planet_label("jupiter", moment)


def test_venus_phase_is_a_crescent_before_conjunction(moment):
    """24 октября нижнее соединение — в начале месяца Венера узкий серп."""
    fraction = apparent.illuminated_fraction("venus", moment)
    assert 0.0 < fraction < 0.3


# ------------------------------------------------------------------ названия


def test_russian_name_for_famous_cluster():
    assert dso_common_name("M44", "NGC2632", "Beehive") == "«Ясли»"


def test_russian_name_wins_over_english():
    assert dso_common_name("M45", "Mel22", "Pleiades") == "«Плеяды»"


def test_english_name_is_kept_when_there_is_no_russian():
    assert dso_common_name("M105", "NGC3379", "Some Name") == "«Some Name»"


def test_no_name_gives_empty_string():
    assert dso_common_name(None, "NGC1234", "") == ""


def test_guillemets_are_used_not_straight_quotes():
    assert '"' not in dso_common_name("M8", "NGC6523", "Lagoon Nebula")


# ------------------------------------------------------------------ значки


def event(text: str, category: str = "planet") -> Event:
    return Event(when=dt.datetime(2026, 10, 4, 21, 0, tzinfo=MSK),
                 text=text, category=category)


def test_each_planet_has_its_own_icon():
    symbols = {icons.PLANET_ICONS[name] for name in
               ("mercury", "venus", "mars", "jupiter", "saturn",
                "uranus", "neptune")}
    assert len(symbols) == 7, "значки планет должны различаться"


def test_planet_event_gets_the_planet_icon():
    assert icons.icon_for(event("Сатурн в противостоянии с Солнцем")) == "🪐"
    assert icons.icon_for(event("Венера переходит к попятному движению")) == "⚪"


def test_moon_phase_icons_follow_the_phase():
    assert icons.icon_for(event("Луна в фазе полнолуние", "moon")) == "🌕"
    assert icons.icon_for(event("Луна в фазе новолуние", "moon")) == "🌑"


def test_pair_of_planets_keeps_the_neutral_icon():
    """Выбирать между двумя планетами произвольно нельзя."""
    assert icons.planet_in("Венера в 2° севернее Марса") is None


def test_meteor_and_comet_icons():
    assert icons.icon_for(event("Максимум активности потока Дракониды",
                                "meteors")) == "🌠"
    assert icons.icon_for(event("Комета 10P/Tempel проходит рядом со звездой",
                                "comet_star")) == "☄️"


def test_decorate_replaces_the_marker():
    item = event("Сатурн в противостоянии с Солнцем")
    line = icons.decorate(item.line(), item)
    assert line.startswith("🪐")
    assert "▪️" not in line


def test_decorate_touches_only_the_first_marker():
    item = event("Сатурн ▪️ в противостоянии")
    assert icons.decorate(item.line(), item).count("▪️") == 1


def test_unknown_category_keeps_the_default_marker():
    item = event("Нечто небывалое", "unknown")
    assert icons.decorate(item.line(), item).startswith("▪️")


# ------------------------------------------------------------------ Титан


def test_titan_distance_is_measured_from_the_limb(moment):
    from astrocal.events.titan import limb_text, saturn_radius_arcsec

    radius = saturn_radius_arcsec(moment)
    assert 8.0 < radius < 11.0           # диск Сатурна около 20″ в поперечнике
    assert "от края диска" in limb_text(29.0, moment)


def test_titan_projected_on_the_disc(moment):
    from astrocal.events.titan import limb_text

    assert "проекции на диск" in limb_text(3.0, moment)


# ------------------------------------------------------------------ выпуск


def test_issue_lines_can_use_icons():
    from astrocal_app.models import EditableEvent, Issue

    issue = Issue(year=2026, month=10, enabled_kinds=set())
    issue.events = [EditableEvent(event=event("Сатурн в противостоянии"))]
    assert issue.lines()[0].startswith("▪️")
    issue.icons = True
    assert issue.lines()[0].startswith("🪐")


def test_render_post_accepts_the_icons_flag():
    """Флаг CLI --icons должен доходить до рендера, а не падать на вызове."""
    from astrocal.build import render_post

    item = event("Сатурн в противостоянии с Солнцем")
    plain = render_post([item], 2026, 10)
    fancy = render_post([item], 2026, 10, icons=True)
    assert "▪️" in plain
    assert "🪐" in fancy and "▪️" not in fancy
