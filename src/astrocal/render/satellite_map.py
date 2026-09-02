"""Карты пролётов МКС и китайской станции.

Пролёт — это не точка, а траектория: наблюдателю нужно знать, откуда станция
выйдет, где будет выше всего и где погаснет, войдя в тень Земли. Поэтому на
карте рисуется дуга со стрелкой направления и подписями времени, а рядом —
обстоятельства пролёта.

Видимость определяется тремя условиями сразу: станция над горизонтом, станция
освещена Солнцем и у наблюдателя достаточно тёмно. Пролёт, где станция входит
в тень Земли, обрывается — это видно на карте.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..cities import City, topos
from ..core import body, planets, to_msk, ts_range
from ..observing import compass_direction
from . import skymap


@dataclass
class Pass:
    """Один видимый пролёт станции."""
    station: str
    city: City
    start: dt.datetime
    peak: dt.datetime
    end: dt.datetime
    max_altitude_deg: float
    start_azimuth_deg: float
    peak_azimuth_deg: float
    end_azimuth_deg: float
    sun_altitude_deg: float
    enters_shadow: bool
    tle_epoch: dt.datetime
    tle_age_days: float
    samples: list = field(default_factory=list)

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0

    @property
    def quality(self) -> str:
        if self.max_altitude_deg >= 60:
            return "отличные"
        if self.max_altitude_deg >= 35:
            return "хорошие"
        if self.max_altitude_deg >= 20:
            return "средние"
        return "низкий пролёт"

    @property
    def tle_status(self) -> str:
        if self.tle_age_days <= 3:
            return "HIGH — время достоверно"
        if self.tle_age_days <= 7:
            return "WARNING — время может сместиться на минуты"
        return "точное время публиковать нельзя"

    def summary(self) -> list[str]:
        return [
            f"{self.station} · {self.city.name} · {self.start:%d.%m.%Y}",
            f"Начало:    {self.start:%H:%M:%S}  азимут {self.start_azimuth_deg:.0f}° "
            f"({compass_direction(self.start_azimuth_deg)})",
            f"Максимум:  {self.peak:%H:%M:%S}  высота {self.max_altitude_deg:.0f}°, "
            f"азимут {self.peak_azimuth_deg:.0f}° "
            f"({compass_direction(self.peak_azimuth_deg)})",
            f"Конец:     {self.end:%H:%M:%S}  азимут {self.end_azimuth_deg:.0f}° "
            f"({compass_direction(self.end_azimuth_deg)})",
            f"Длительность: {self.duration_minutes:.1f} мин",
            "Освещена Солнцем: да"
            + (", уходит в тень Земли" if self.enters_shadow else ""),
            f"Высота Солнца: {self.sun_altitude_deg:.0f}°",
            f"Условия наблюдений: {self.quality}",
            f"Возраст TLE: {self.tle_age_days:.1f} сут — {self.tle_status}",
        ]


def find_passes(satellite, city: City, start: dt.datetime, end: dt.datetime,
                min_altitude_deg: float = 10.0, step_seconds: int = 10,
                station: str = "МКС") -> list[Pass]:
    """Видимые пролёты станции над городом.

    Шаг 10 секунд: станция проходит небо за минуты, и на минутной сетке
    момент максимума смазывается.
    """
    site = topos(city)
    grid = ts_range(start, end, step_seconds / 60.0)
    topocentric = (satellite - _site_only(city)).at(grid)
    altitude, azimuth, _ = topocentric.altaz()
    altitude = altitude.degrees
    azimuth = azimuth.degrees
    sunlit = satellite.at(grid).is_sunlit(planets())
    sun_altitude = site.at(grid).observe(body("sun")).apparent().altaz()[0].degrees

    visible = (altitude > min_altitude_deg) & sunlit & (sun_altitude < -6.0)
    epoch = to_msk(satellite.epoch)

    results: list[Pass] = []
    index = 0
    while index < len(visible):
        if not visible[index]:
            index += 1
            continue
        finish = index
        while finish + 1 < len(visible) and visible[finish + 1]:
            finish += 1
        window = np.arange(index, finish + 1)
        peak = int(window[np.argmax(altitude[window])])

        # уходит ли станция в тень, не опустившись к горизонту
        shadow = bool(finish + 1 < len(visible)
                      and altitude[finish + 1] > min_altitude_deg
                      and not sunlit[finish + 1])

        samples = [{"time": to_msk(grid[k]), "altitude": float(altitude[k]),
                    "azimuth": float(azimuth[k])} for k in window]
        results.append(Pass(
            station=station, city=city,
            start=to_msk(grid[index]), peak=to_msk(grid[peak]),
            end=to_msk(grid[finish]),
            max_altitude_deg=float(altitude[peak]),
            start_azimuth_deg=float(azimuth[index]),
            peak_azimuth_deg=float(azimuth[peak]),
            end_azimuth_deg=float(azimuth[finish]),
            sun_altitude_deg=float(sun_altitude[peak]),
            enters_shadow=shadow,
            tle_epoch=epoch,
            tle_age_days=abs((to_msk(grid[peak]) - epoch).total_seconds()) / 86400.0,
            samples=samples,
        ))
        index = finish + 1
    return results


def _site_only(city: City):
    from skyfield.api import wgs84
    return wgs84.latlon(city.lat, city.lon, city.elevation_m)


def render(pass_: Pass, path: Path, theme: str = "dark") -> Path:
    """Карта одного пролёта: дуга, направление, метки времени."""
    subtitle = (f"{pass_.city.name} · {pass_.start:%d.%m.%Y} · "
                f"{pass_.start:%H:%M}–{pass_.end:%H:%M} МСК")
    figure, axes, colors = skymap.base_figure(
        f"Пролёт {pass_.station}", subtitle, theme)
    skymap.draw_stars(axes, colors, pass_.city, pass_.peak, mag_limit=4.6,
                      with_labels=False)

    altitudes = [s["altitude"] for s in pass_.samples]
    azimuths = [s["azimuth"] for s in pass_.samples]
    x, y = skymap.project(altitudes, azimuths)
    skymap.clip(axes, axes.plot(x, y, color=colors.track, linewidth=2.6,
                                zorder=7, solid_capstyle="round"))

    # стрелка направления движения — в середине дуги
    middle = len(x) // 2
    if len(x) > 4:
        axes.annotate("", xy=(x[middle + 2], y[middle + 2]),
                      xytext=(x[middle - 2], y[middle - 2]),
                      arrowprops=dict(arrowstyle="-|>", color=colors.track,
                                      linewidth=2.2, mutation_scale=18),
                      zorder=8)

    for point, label, color in (
            (pass_.samples[0], f"начало {pass_.start:%H:%M:%S}", colors.accent),
            (pass_.samples[len(pass_.samples) // 2],
             f"максимум {pass_.peak:%H:%M:%S}, {pass_.max_altitude_deg:.0f}°",
             colors.track),
            (pass_.samples[-1],
             ("вход в тень " if pass_.enters_shadow else "конец ")
             + f"{pass_.end:%H:%M:%S}", colors.highlight)):
        px, py = skymap.project([point["altitude"]], [point["azimuth"]])
        axes.scatter(px, py, s=70, color=color, zorder=9, edgecolors="none")
        axes.text(px[0], py[0] + 0.05, label, color=color, fontsize=8.5,
                  ha="center", va="bottom", zorder=9, fontweight="bold")

    footer = (f"макс. высота {pass_.max_altitude_deg:.0f}° · "
              f"{pass_.duration_minutes:.1f} мин · условия: {pass_.quality} · "
              f"TLE {pass_.tle_age_days:.1f} сут")
    figure.text(0.5, 0.018, footer, color=colors.muted, fontsize=8.5,
                ha="center", va="bottom")
    return skymap.save(figure, path)


def passes_for_station(catnr: int, city: City, start: dt.datetime,
                       end: dt.datetime) -> list[Pass]:
    """Пролёты станции по свежему TLE с Celestrak."""
    from ..events.iss import STATIONS, load_tle

    station = STATIONS[catnr]
    satellite = load_tle(catnr)
    if satellite is None:
        return []
    return find_passes(satellite, city, start, end,
                       min_altitude_deg=station["min_alt"],
                       station=station["label"])
