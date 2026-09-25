"""Видимые размеры и фазы тел на конкретный момент.

Наблюдателю мало знать, что событие с участием Луны состоится: важно, какой
она будет в этот вечер — тонким серпом двадцати девяти угловых минут или
почти полным диском в тридцать три. То же с планетами: Марс в противостоянии
показывает диск 25″, а в соединении — 4″, и это разные объекты для телескопа.

Модуль считает три величины и больше ничего:

* видимый угловой диаметр (по экваториальному радиусу и расстоянию);
* освещённую долю диска — для Меркурия и Венеры, у которых фаза заметна;
* то и другое в виде готовой подписи для строки календаря.

Радиусы — экваториальные, из IAU Working Group on Cartographic Coordinates.
Для колец Сатурна и сплюснутости Юпитера поправок нет: в календаре указывается
диаметр диска, как это принято в наблюдательных изданиях.
"""
from __future__ import annotations

import numpy as np
from skyfield import almanac

from .core import body, earth, planets, timescale

# Экваториальные радиусы, км (IAU 2015)
RADIUS_KM = {
    "mercury": 2439.7, "venus": 6051.8, "mars": 3396.2, "jupiter": 71492.0,
    "saturn": 60268.0, "uranus": 25559.0, "neptune": 24764.0,
    "moon": 1737.4, "sun": 695700.0,
}

# Планеты, у которых фаза видна в любительский инструмент и потому уместна
# в календаре. У внешних планет освещённая доля почти всегда больше 0,99.
PHASE_SHOWN = ("mercury", "venus")


def angular_diameter_arcsec(name: str, t) -> float:
    """Видимый угловой диаметр тела, угловые секунды."""
    radius = RADIUS_KM[name]
    distance = float(earth().at(t).observe(body(name)).apparent().distance().km)
    return float(np.degrees(2.0 * np.arcsin(radius / distance)) * 3600.0)


def illuminated_fraction(name: str, t) -> float:
    """Освещённая доля диска, 0…1."""
    return float(almanac.fraction_illuminated(planets(), name, t))


def format_diameter(arcsec: float) -> str:
    """31′28″ для Луны и Солнца, 3,7″ для всего остального.

    Луна и Солнце — единственные тела, у которых диаметр измеряется минутами;
    писать «1888″» вместо «31′28″» формально верно, но читателю бесполезно.
    """
    if arcsec >= 60.0:
        minutes = int(arcsec // 60)
        seconds = arcsec - minutes * 60
        return f"{minutes}′{seconds:.0f}″"
    from .fmt import number
    return f"{number(arcsec)}″"


def moon_label(t, illum: float, waxing: bool) -> str:
    """«Ф=+0,31, D=31′28″» — подпись Луны для строки календаря."""
    from .fmt import phase_fraction

    diameter = angular_diameter_arcsec("moon", t)
    return f"{phase_fraction(illum, waxing)}, D={format_diameter(diameter)}"


def planet_label(name: str, t, magnitude_value: float | None = None) -> str:
    """«V=-4,5m, D=37,1″, Ф=0,27» — подпись планеты.

    Фаза добавляется только Меркурию и Венере: у остальных она неотличима от
    единицы и только удлиняет строку.
    """
    from .fmt import magnitude, number

    parts = []
    if magnitude_value is None:
        from .magnitudes import planet_magnitude
        magnitude_value = planet_magnitude(name, t)
    parts.append(magnitude(magnitude_value))
    parts.append(f"D={format_diameter(angular_diameter_arcsec(name, t))}")
    if name in PHASE_SHOWN:
        fraction = illuminated_fraction(name, t)
        parts.append(f"Ф={number(fraction, 2)}")
    return ", ".join(parts)


def moon_label_at(when, illum: float, waxing: bool) -> str:
    """То же, что `moon_label`, но от обычного datetime."""
    return moon_label(timescale().from_datetime(when), illum, waxing)
