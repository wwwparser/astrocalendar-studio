"""Круговая карта неба в горизонтальных координатах.

Внешняя окружность — горизонт, центр — зенит, радиус растёт как r = 90° − h.
Север сверху, восток слева: карта показывает небо так, как его видит человек,
запрокинувший голову, а не вид на глобус сверху.

Модуль ничего не знает про интерфейс: на вход — время, место и что рисовать,
на выходе — файл PNG.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

from ..cities import City, topos
from ..constellations import (CONSTELLATION_FILE, CONSTELLATION_URL,
                              constellation_lines)
from ..core import body, timescale
from ..fmt import ru_constellation
from . import styles

__all__ = ["constellation_lines", "CONSTELLATION_FILE", "CONSTELLATION_URL",
           "altaz_of", "project", "base_figure", "clip", "draw_stars",
           "draw_object", "save", "sky_at", "planet_highlights", "LABELLED"]

# Созвездия, чьи названия подписываем: остальные превращают карту в кашу
LABELLED = {"UMa", "UMi", "Cas", "Cyg", "Lyr", "Aql", "Boo", "Vir", "Leo", "Ori",
            "Tau", "Gem", "Cnc", "Sco", "Sgr", "Peg", "And", "Per", "Aur", "CMa",
            "Cap", "Aqr", "Psc", "Ari", "Dra", "Her", "Oph", "Cet", "Eri"}


@lru_cache(maxsize=4)
def _star_table(mag_limit: float):
    from ..catalogs import bright_stars
    frame = bright_stars(mag_limit=mag_limit)
    return (frame.hip.to_numpy(), frame.magnitude.to_numpy(),
            frame.ra_degrees.to_numpy(), frame.dec_degrees.to_numpy())


def altaz_of(ra_deg, dec_deg, city: City, when: dt.datetime):
    """Высота и азимут набора точек с экваториальными координатами."""
    from skyfield.api import Star

    site = topos(city)
    t = timescale().from_datetime(when)
    star = Star(ra_hours=np.asarray(ra_deg, dtype=float) / 15.0,
                dec_degrees=np.asarray(dec_deg, dtype=float))
    altitude, azimuth, _ = site.at(t).observe(star).apparent().altaz()
    return altitude.degrees, azimuth.degrees


def project(altitude_deg, azimuth_deg):
    """Горизонтальные координаты → координаты на круге карты.

    Север сверху, восток слева: смотрим вверх, а не на карту местности.
    """
    radius = (90.0 - np.asarray(altitude_deg, dtype=float)) / 90.0
    angle = np.radians(np.asarray(azimuth_deg, dtype=float))
    return -radius * np.sin(angle), radius * np.cos(angle)


def base_figure(title: str, subtitle: str = "", theme: str = "dark",
                size: float = 7.2):
    """Пустая карта: горизонт, сетка высот, стороны света."""
    styles.apply_defaults()
    colors = styles.palette(theme)
    figure = Figure(figsize=(size, size * 1.1), facecolor=colors.background)
    axes = figure.add_axes([0.04, 0.04, 0.92, 0.86])
    axes.set_facecolor(colors.background)
    axes.set_xlim(-1.12, 1.12)
    axes.set_ylim(-1.12, 1.12)
    axes.set_aspect("equal")
    axes.axis("off")

    # диск неба и круги равных высот
    horizon = _circle(1.0, colors.sky, colors.horizon, 1.6, zorder=0)
    axes.add_artist(horizon)
    axes.horizon_patch = horizon      # по нему обрезается всё, что за горизонтом
    for altitude in (30, 60):
        radius = (90 - altitude) / 90.0
        axes.add_artist(_circle(radius, "none", colors.grid, 0.7, zorder=1))
        axes.text(-0.02, radius, f"{altitude}°", color=colors.muted, fontsize=7,
                  ha="right", va="bottom", zorder=2)

    # лучи азимута
    for azimuth in range(0, 360, 30):
        x, y = project([0], [azimuth])
        axes.plot([0, x[0]], [0, y[0]], color=colors.grid, linewidth=0.5,
                  zorder=1)

    for azimuth, label in ((0, "С"), (90, "В"), (180, "Ю"), (270, "З")):
        x, y = project([-7], [azimuth])
        axes.text(x[0], y[0], label, color=colors.text, fontsize=13,
                  fontweight="bold", ha="center", va="center", zorder=5)

    figure.text(0.5, 0.965, title, color=colors.text, fontsize=13,
                fontweight="bold", ha="center", va="top")
    if subtitle:
        figure.text(0.5, 0.925, subtitle, color=colors.muted, fontsize=9.5,
                    ha="center", va="top")
    return figure, axes, colors


def _circle(radius, facecolor, edgecolor, linewidth, zorder=0):
    from matplotlib.patches import Circle
    return Circle((0, 0), radius, facecolor=facecolor, edgecolor=edgecolor,
                  linewidth=linewidth, zorder=zorder)


def clip(axes, *artists) -> None:
    """Обрезать рисунок по кругу горизонта.

    Линия созвездия, у которой одна звезда над горизонтом, а вторая под ним,
    иначе уезжает за пределы карты.
    """
    patch = getattr(axes, "horizon_patch", None)
    if patch is None:
        return
    for artist in artists:
        for item in (artist if isinstance(artist, (list, tuple)) else [artist]):
            try:
                item.set_clip_path(patch)
            except AttributeError:
                pass


def draw_stars(axes, colors, city: City, when: dt.datetime,
               mag_limit: float = 5.4, with_lines: bool = True,
               with_labels: bool = True) -> None:
    """Звёзды, линии и подписи созвездий над горизонтом."""
    hip, magnitude, ra, dec = _star_table(mag_limit)
    altitude, azimuth = altaz_of(ra, dec, city, when)
    above = altitude > -1.0
    if not above.any():
        return

    if with_lines:
        position = {int(h): (altitude[i], azimuth[i]) for i, h in enumerate(hip)}
        for abbreviation, pairs in constellation_lines():
            segments = []
            for start, finish in pairs:
                if start not in position or finish not in position:
                    continue
                a, b = position[start], position[finish]
                if a[0] < 0 and b[0] < 0:
                    continue
                x, y = project([a[0], b[0]], [a[1], b[1]])
                segments.append(((x[0], y[0]), (x[1], y[1])))
            for (x0, y0), (x1, y1) in segments:
                clip(axes, axes.plot([x0, x1], [y0, y1], color=colors.constellation,
                                     linewidth=0.8, zorder=2, alpha=0.85))
            if with_labels and segments and abbreviation in LABELLED:
                cx = float(np.mean([p[0] for segment in segments for p in segment]))
                cy = float(np.mean([p[1] for segment in segments for p in segment]))
                if cx * cx + cy * cy < 0.95:
                    axes.text(cx, cy, ru_constellation(abbreviation),
                              color=colors.constellation, fontsize=7.5,
                              ha="center", va="center", zorder=3, alpha=0.9)

    x, y = project(altitude[above], azimuth[above])
    sizes = [styles.star_marker_size(m, mag_limit) for m in magnitude[above]]
    clip(axes, axes.scatter(x, y, s=sizes, c=colors.star, linewidths=0, zorder=4))


def draw_object(axes, colors, altitude_deg: float, azimuth_deg: float,
                label: str, color: str | None = None, marker: str = "o",
                size: float = 90.0) -> None:
    x, y = project([altitude_deg], [azimuth_deg])
    axes.scatter(x, y, s=size, facecolors="none",
                 edgecolors=color or colors.highlight, linewidths=1.8, zorder=6,
                 marker=marker)
    axes.text(x[0], y[0] - 0.045, label, color=color or colors.highlight,
              fontsize=9.5, ha="center", va="top", zorder=6, fontweight="bold")


def save(figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, facecolor=figure.get_facecolor())
    return path


def sky_at(city: City, when: dt.datetime, path: Path, theme: str = "dark",
           highlights: list[dict] | None = None, title: str | None = None) -> Path:
    """Обзорная карта неба с необязательными отметками объектов."""
    subtitle = f"{city.name} · {when:%d.%m.%Y %H:%M} МСК"
    figure, axes, colors = base_figure(title or "Карта неба", subtitle, theme)
    draw_stars(axes, colors, city, when)

    for item in highlights or []:
        target = item.get("target")
        if target is None:
            continue
        site = topos(city)
        t = timescale().from_datetime(when)
        altitude, azimuth, _ = site.at(t).observe(target).apparent().altaz()
        if altitude.degrees < -2:
            continue
        draw_object(axes, colors, float(altitude.degrees), float(azimuth.degrees),
                    item.get("label", ""), item.get("color"))
    return save(figure, path)


def planet_highlights(names: list[str], labels: dict[str, str] | None = None):
    labels = labels or {}
    return [{"target": body(name), "label": labels.get(name, name)}
            for name in names]
