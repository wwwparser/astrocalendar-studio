"""Каталоги и справочники: имена звёзд, типы объектов, геометрия."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal.catalogs import (STAR_NAMES_RU, angular_distance_deg,   # noqa: E402
                               bright_stars, deep_sky)
from astrocal.geo import RU_REGIONS, WORLD_REGIONS, make_grid, region_coverage  # noqa: E402

# Опорные звёзды: HIP, русское имя, блеск (Hipparcos), допуск по блеску
REFERENCE_STARS = [
    (32349, "Сириус", -1.44), (69673, "Арктур", -0.05), (91262, "Вега", 0.03),
    (24608, "Капелла", 0.08), (24436, "Ригель", 0.18), (37279, "Процион", 0.40),
    (27989, "Бетельгейзе", 0.45), (21421, "Альдебаран", 0.87),
    (65474, "Спика", 0.98), (80763, "Антарес", 1.06), (49669, "Регул", 1.36),
    (102098, "Денеб", 1.25), (97649, "Альтаир", 0.76), (11767, "Полярная", 1.97),
    (63125, "Сердце Карла", 2.89), (9487, "Альриша", 3.82), (73555, "Неккар", 3.49),
]


@pytest.mark.parametrize("hip, name, mag", REFERENCE_STARS)
def test_star_names_point_at_the_right_star(hip, name, mag):
    """Русское имя должно стоять у той звезды, у которой ожидается по блеску."""
    assert STAR_NAMES_RU[hip] == name
    catalog = bright_stars(mag_limit=8.0).set_index("hip")
    assert hip in catalog.index
    assert abs(float(catalog.loc[hip].magnitude) - mag) < 0.05


def test_no_star_name_duplicates():
    names = list(STAR_NAMES_RU.values())
    assert len(names) == len(set(names)), "одно имя присвоено двум звёздам"


def test_catalog_has_no_missing_coordinates():
    stars = bright_stars(mag_limit=8.0)
    assert np.isfinite(stars.ra_degrees).all()
    assert np.isfinite(stars.dec_degrees).all()


def test_ngc246_is_a_planetary_nebula_in_cetus():
    dso = deep_sky(mag_limit=12.0)
    row = dso[dso.Name == "NGC0246"].iloc[0]
    assert row.type_ru == "планетарная туманность"
    assert row.Const == "Cet"
    assert abs(row.mag - 10.9) < 0.1


def test_messier_numbers_are_labelled():
    dso = deep_sky(mag_limit=12.0)
    m22 = dso[dso.Name == "NGC6656"].iloc[0]
    assert m22.messier == "M22"


def test_angular_distance_known_values():
    assert angular_distance_deg(0, 0, 0, 90) == pytest.approx(90.0, abs=1e-9)
    assert angular_distance_deg(0, 0, 180, 0) == pytest.approx(180.0, abs=1e-6)
    assert angular_distance_deg(10, 20, 10, 20) == pytest.approx(0.0, abs=1e-9)


def test_region_boxes_do_not_overlap_pathologically():
    """Каждый регион должен содержать узлы сетки — иначе прямоугольник задан неверно."""
    lat, lon = make_grid(2.0)
    for entry in RU_REGIONS + WORLD_REGIONS:
        if len(entry) == 6:
            name, _, la, lb, lo, hi = entry
        else:
            name, la, lb, lo, hi = entry
        inside = (lat >= la) & (lat <= lb) & (lon >= lo) & (lon <= hi)
        assert inside.any(), f"регион «{name}» не покрывает ни одного узла сетки"


def test_region_coverage_reports_full_and_partial():
    lat, lon = make_grid(2.0)
    everything = np.ones(len(lat), dtype=bool)
    coverage = region_coverage(lat, lon, everything, RU_REGIONS)
    assert len(coverage) == len(RU_REGIONS)
    assert all(share == pytest.approx(1.0) for _, _, share in coverage)

    nothing = np.zeros(len(lat), dtype=bool)
    assert region_coverage(lat, lon, nothing, RU_REGIONS) == []
