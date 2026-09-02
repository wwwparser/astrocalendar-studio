"""Карты конкретных событий: что и где искать на небе.

Для сближения важна не вся полусфера, а маленький участок неба, поэтому здесь
две формы подачи: обзорная круговая карта с отметкой объекта и «врезка» —
увеличенный фрагмент вокруг события, где видно взаимное расположение тел и
масштаб углового расстояния.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

from ..cities import City
from ..core import body, timescale
from . import skymap, styles

PLANET_MARKERS = {
    "mercury": ("Меркурий", "#c9c2b6"), "venus": ("Венера", "#ffe7a8"),
    "mars": ("Марс", "#ff8a6b"), "jupiter": ("Юпитер", "#ffd08a"),
    "saturn": ("Сатурн", "#e8dba6"), "uranus": ("Уран", "#9fe3e8"),
    "neptune": ("Нептун", "#8fb4ff"), "moon": ("Луна", "#f2f2f2"),
    "sun": ("Солнце", "#ffd24a"),
}


def _radec(target, when: dt.datetime):
    from ..core import earth
    t = timescale().from_datetime(when)
    ra, dec, _ = earth().at(t).observe(target).apparent().radec()
    return float(ra.degrees), float(dec.degrees)


def closeup(targets: list[dict], when: dt.datetime, city: City, path: Path,
            title: str, subtitle: str = "", theme: str = "dark",
            span_deg: float | None = None) -> Path:
    """Врезка: увеличенный участок неба вокруг события.

    `targets` — список словарей: {"target": объект Skyfield, "label": подпись,
    "color": цвет, "size": размер маркера}.
    """
    styles.apply_defaults()
    colors = styles.palette(theme)

    points = []
    for item in targets:
        ra, dec = _radec(item["target"], when)
        points.append({**item, "ra": ra, "dec": dec})
    if not points:
        raise ValueError("нечего рисовать")

    centre_dec = float(np.mean([p["dec"] for p in points]))
    reference_ra = points[0]["ra"]
    for point in points:
        point["dx"] = ((point["ra"] - reference_ra + 180) % 360 - 180) * \
            np.cos(np.radians(centre_dec))
        point["dy"] = point["dec"] - centre_dec
    centre_dx = float(np.mean([p["dx"] for p in points]))

    spread = max(
        max(abs(p["dx"] - centre_dx) for p in points),
        max(abs(p["dy"]) for p in points), 0.05)
    half = span_deg / 2 if span_deg else max(spread * 2.6, 0.35)

    figure = Figure(figsize=(6.4, 6.0), facecolor=colors.background)
    axes = figure.add_axes([0.09, 0.09, 0.86, 0.80])
    axes.set_facecolor(colors.sky)
    axes.set_xlim(centre_dx + half, centre_dx - half)     # восток слева
    axes.set_ylim(-half, half)
    axes.set_aspect("equal")
    for spine in axes.spines.values():
        spine.set_color(colors.grid)
    axes.tick_params(colors=colors.muted, labelsize=8)
    axes.grid(color=colors.grid, linewidth=0.5, alpha=0.6)
    axes.set_xlabel("← восток · Δα·cos δ, градусы · запад →", color=colors.muted,
                    fontsize=8.5)
    axes.set_ylabel("Δδ, градусы", color=colors.muted, fontsize=8.5)

    # звёзды фона
    from ..catalogs import bright_stars
    stars = bright_stars(mag_limit=8.0)
    dx = ((stars.ra_degrees - reference_ra + 180) % 360 - 180) * \
        np.cos(np.radians(centre_dec))
    dy = stars.dec_degrees - centre_dec
    near = (np.abs(dx - centre_dx) < half * 1.2) & (np.abs(dy) < half * 1.2)
    if near.any():
        sizes = [styles.star_marker_size(m, 8.0) * 1.6
                 for m in stars.magnitude[near]]
        axes.scatter(dx[near], dy[near], s=sizes, c=colors.star, linewidths=0,
                     zorder=2)

    for point in points:
        axes.scatter([point["dx"]], [point["dy"]],
                     s=point.get("size", 240),
                     facecolors=point.get("color", colors.highlight),
                     edgecolors=colors.background, linewidths=1.0, zorder=5)
        axes.text(point["dx"], point["dy"] - half * 0.09, point.get("label", ""),
                  color=colors.text, fontsize=10, ha="center", va="top",
                  zorder=6, fontweight="bold")

    # угловое расстояние между первыми двумя объектами
    if len(points) >= 2:
        a, b = points[0], points[1]
        axes.plot([a["dx"], b["dx"]], [a["dy"], b["dy"]], color=colors.accent,
                  linewidth=1.0, linestyle="--", zorder=4)
        separation = float(np.hypot(a["dx"] - b["dx"], a["dy"] - b["dy"]))
        text = (f"{separation:.2f}°" if separation >= 1
                else f"{separation * 60:.0f}′")
        axes.text((a["dx"] + b["dx"]) / 2, (a["dy"] + b["dy"]) / 2 + half * 0.04,
                  text, color=colors.accent, fontsize=9.5, ha="center",
                  va="bottom", zorder=6, fontweight="bold")

    figure.text(0.5, 0.965, title, color=colors.text, fontsize=13,
                fontweight="bold", ha="center", va="top")
    figure.text(0.5, 0.925, subtitle or f"{city.name} · {when:%d.%m.%Y %H:%M} МСК",
                color=colors.muted, fontsize=9.5, ha="center", va="top")
    return skymap.save(figure, path)


def for_event(event, city: City, path: Path, theme: str = "dark") -> Path | None:
    """Подобрать и построить карту, подходящую типу события."""
    from ..taxonomy import classify

    kind = classify(event)

    if kind in ("moon_planet", "occultation", "moon_star", "moon_dso"):
        return _moon_closeup(event, city, path, theme)
    if kind == "planet_conjunction":
        return _planet_pair(event, city, path, theme)
    if kind in ("comet", "asteroid", "asteroid_occultation", "neo"):
        return _sky_position(event, city, path, theme)
    if kind in ("meteors",):
        return _radiant(event, city, path, theme)
    if kind in ("planet_opposition", "planet_elongation", "planet_station",
                "planet_brilliancy", "planet_visibility", "jupiter_moons",
                "titan", "moon_phase", "moon_apsis", "season"):
        return _sky_position(event, city, path, theme)
    return None


def _mentioned_bodies(text: str) -> list[str]:
    markers = {"луна": "moon", "меркури": "mercury", "венер": "venus",
               "марс": "mars", "юпитер": "jupiter", "сатурн": "saturn",
               "уран": "uranus", "нептун": "neptune"}
    lowered = text.lower()
    found = [(lowered.index(marker), name)
             for marker, name in markers.items() if marker in lowered]
    return [name for _, name in sorted(found)]


def _moon_closeup(event, city, path, theme):
    names = _mentioned_bodies(event.text)
    targets = [{"target": body("moon"), "label": "Луна",
                "color": PLANET_MARKERS["moon"][1], "size": 320}]
    for name in names:
        if name == "moon":
            continue
        label, color = PLANET_MARKERS[name]
        targets.append({"target": body(name), "label": label, "color": color})
    if event.meta.get("ra_deg") is not None:
        from skyfield.api import Star
        targets.append({
            "target": Star(ra_hours=float(event.meta["ra_deg"]) / 15.0,
                           dec_degrees=float(event.meta["dec_deg"])),
            "label": event.meta.get("object_label", "объект"),
            "color": "#8fe388"})
    if len(targets) < 2:
        return _sky_position(event, city, path, theme)
    return closeup(targets, event.when, city, path, "Взаимное расположение",
                   f"{city.name} · {event.when:%d.%m.%Y %H:%M} МСК", theme)


def _planet_pair(event, city, path, theme):
    names = _mentioned_bodies(event.text)
    if len(names) < 2:
        return _sky_position(event, city, path, theme)
    targets = []
    for name in names[:2]:
        label, color = PLANET_MARKERS[name]
        targets.append({"target": body(name), "label": label, "color": color})
    return closeup(targets, event.when, city, path, "Сближение планет",
                   f"{city.name} · {event.when:%d.%m.%Y %H:%M} МСК", theme)


def _sky_position(event, city, path, theme):
    """Обзорная карта неба с отметкой участвующих объектов."""
    highlights = []
    for name in _mentioned_bodies(event.text):
        label, color = PLANET_MARKERS[name]
        highlights.append({"target": body(name), "label": label, "color": color})
    if event.meta.get("ra_deg") is not None:
        from skyfield.api import Star
        highlights.append({
            "target": Star(ra_hours=float(event.meta["ra_deg"]) / 15.0,
                           dec_degrees=float(event.meta["dec_deg"])),
            "label": event.meta.get("object_label", "объект"),
            "color": "#8fe388"})
    if not highlights:
        return None
    return skymap.sky_at(city, event.when, path, theme, highlights,
                         title="Положение на небе")


RADIANTS = {
    "ауригиды": (91.0, 39.0), "сентябрьские эпсилон-персеиды": (48.0, 40.0),
    "дневные секстантиды": (152.0, 0.0), "персеиды": (46.2, 57.4),
    "ориониды": (95.0, 16.0), "геминиды": (112.0, 33.0),
    "квадрантиды": (230.0, 49.0), "лириды": (271.0, 34.0),
    "эта-аквариды": (338.0, -1.0), "южные таблиды (тауриды)": (32.0, 9.0),
}


def _radiant(event, city, path, theme):
    """Карта радианта потока в момент максимума."""
    from skyfield.api import Star

    name = event.text.lower().split("потока")[-1].strip()
    coordinates = next((v for k, v in RADIANTS.items() if k in name), None)
    if coordinates is None:
        return None
    ra, dec = coordinates
    highlight = [{"target": Star(ra_hours=ra / 15.0, dec_degrees=dec),
                  "label": "радиант", "color": "#ff9f5a"}]
    return skymap.sky_at(city, event.when, path, theme, highlight,
                         title="Радиант метеорного потока")
