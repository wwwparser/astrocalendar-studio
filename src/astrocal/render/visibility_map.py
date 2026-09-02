"""Географические карты: где на Земле видно явление.

Для затмений и покрытий важна не картина неба, а полоса на поверхности Земли.
Карта строится программно из тех же масок, что считает расчётный слой, — она
не подписывается к результату задним числом, а является его прямым
отображением.

Береговая линия берётся из компактного встроенного контура: тянуть ради двух
карт полноценный geopandas с шейпфайлами нерационально.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

from ..cities import all_cities
from ..geo import RU_REGIONS
from . import skymap, styles


def _graticule(axes, colors, lon_step: int = 30, lat_step: int = 20) -> None:
    for lon in range(-180, 181, lon_step):
        axes.plot([lon, lon], [-90, 90], color=colors.grid, linewidth=0.4,
                  zorder=1)
    for lat in range(-80, 81, lat_step):
        axes.plot([-180, 180], [lat, lat], color=colors.grid, linewidth=0.4,
                  zorder=1)


def _russia_outline(axes, colors) -> None:
    """Прямоугольники опорных регионов — грубый контур страны на карте."""
    from matplotlib.patches import Rectangle
    for _name, _phrase, lat_lo, lat_hi, lon_lo, lon_hi in RU_REGIONS:
        axes.add_patch(Rectangle(
            (lon_lo, lat_lo), lon_hi - lon_lo, lat_hi - lat_lo,
            facecolor=colors.land, edgecolor=colors.grid, linewidth=0.4,
            alpha=0.55, zorder=2))


def band(lat, lon, mask, path: Path, title: str, subtitle: str = "",
         theme: str = "dark", extra_masks: list[dict] | None = None,
         centre_line: list[dict] | None = None,
         mark_cities: bool = True) -> Path:
    """Карта полосы видимости по маске узлов сетки.

    `extra_masks` — дополнительные слои, например полоса полной фазы затмения
    поверх полосы частных фаз.
    """
    styles.apply_defaults()
    colors = styles.palette(theme)

    figure = Figure(figsize=(11.0, 6.2), facecolor=colors.background)
    axes = figure.add_axes([0.05, 0.08, 0.92, 0.80])
    axes.set_facecolor(colors.water)
    axes.set_xlim(-180, 180)
    axes.set_ylim(-85, 85)
    axes.set_xlabel("долгота", color=colors.muted, fontsize=8.5)
    axes.set_ylabel("широта", color=colors.muted, fontsize=8.5)
    axes.tick_params(colors=colors.muted, labelsize=8)
    for spine in axes.spines.values():
        spine.set_color(colors.grid)

    _graticule(axes, colors)
    _russia_outline(axes, colors)

    lat = np.asarray(lat)
    lon = np.asarray(lon)
    mask = np.asarray(mask, dtype=bool)
    if mask.any():
        axes.scatter(lon[mask], lat[mask], s=9, c=colors.band, alpha=0.55,
                     linewidths=0, zorder=3, label="полоса видимости")

    for layer in extra_masks or []:
        layer_mask = np.asarray(layer["mask"], dtype=bool)
        if layer_mask.any():
            axes.scatter(lon[layer_mask], lat[layer_mask],
                         s=layer.get("size", 14), c=layer.get("color", colors.highlight),
                         alpha=layer.get("alpha", 0.9), linewidths=0, zorder=4,
                         label=layer.get("label"))

    if centre_line:
        axes.plot([p["lon"] for p in centre_line], [p["lat"] for p in centre_line],
                  color=colors.highlight, linewidth=2.0, zorder=5,
                  label="центральная линия")
        start, finish = centre_line[0], centre_line[-1]
        axes.scatter([start["lon"]], [start["lat"]], s=48, color=colors.accent,
                     zorder=6)
        axes.scatter([finish["lon"]], [finish["lat"]], s=48,
                     color=colors.highlight, zorder=6)
        if "utc" in start:
            axes.annotate("", xy=(finish["lon"], finish["lat"]),
                          xytext=(start["lon"], start["lat"]),
                          arrowprops=dict(arrowstyle="-|>", color=colors.highlight,
                                          linewidth=1.4, mutation_scale=14,
                                          alpha=0.8), zorder=6)

    if mark_cities:
        for city in all_cities():
            inside = bool(mask[np.argmin((lat - city.lat) ** 2
                                         + (lon - city.lon) ** 2)]) if mask.any() \
                else False
            axes.scatter([city.lon], [city.lat], s=22,
                         color=colors.text if inside else colors.muted,
                         marker="s" if inside else ".", zorder=7)
            axes.text(city.lon + 2, city.lat + 1.5, city.name,
                      color=colors.text if inside else colors.muted,
                      fontsize=7.5, zorder=7)

    handles, labels = axes.get_legend_handles_labels()
    if handles:
        legend = axes.legend(loc="lower left", fontsize=8, framealpha=0.25,
                             facecolor=colors.sky, edgecolor=colors.grid)
        for text in legend.get_texts():
            text.set_color(colors.text)

    figure.text(0.5, 0.965, title, color=colors.text, fontsize=13,
                fontweight="bold", ha="center", va="top")
    if subtitle:
        figure.text(0.5, 0.925, subtitle, color=colors.muted, fontsize=9.5,
                    ha="center", va="top")
    return skymap.save(figure, path)


def occultation_band(record: dict, path: Path, theme: str = "dark") -> Path:
    """Карта полосы покрытия из отчёта модуля покрытий."""
    from ..events.occultations import visibility_band
    from ..core import timescale

    when = record["when"]
    t = timescale().from_datetime(when)
    planet = record.get("planet", "")
    band_data = visibility_band(t, planet if planet in (
        "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune")
        else "venus")
    regions = ", ".join(name for name, _, _ in record.get("ru", [])) or "мимо России"
    return band(band_data["lat"], band_data["lon"], band_data["mask"], path,
                "Полоса видимости покрытия",
                f"{when:%d.%m.%Y %H:%M} МСК · регионы: {regions}", theme)


def eclipse_band(bands: dict, path: Path, title: str, subtitle: str,
                 theme: str = "dark") -> Path:
    """Карта затмения: частные фазы фоном, полная фаза поверх."""
    return band(bands["lat"], bands["lon"], bands["partial"], path, title,
                subtitle, theme,
                extra_masks=[{"mask": bands["central"], "label": "полная фаза",
                              "size": 16, "alpha": 0.95}])


def asteroid_occultation_path(result: dict, path: Path,
                              theme: str = "dark") -> Path:
    """Карта покрытия звезды астероидом: центральная линия и её сдвиги на ±σ."""
    styles.apply_defaults()
    colors = styles.palette(theme)
    candidate = result["candidate"]
    line = result["path"]
    if not line:
        raise ValueError("полоса не найдена")

    latitudes = [p["lat"] for p in line]
    longitudes = [p["lon"] for p in line]
    figure = Figure(figsize=(11.0, 6.2), facecolor=colors.background)
    axes = figure.add_axes([0.05, 0.08, 0.92, 0.80])
    axes.set_facecolor(colors.water)
    axes.set_xlim(max(-180, min(longitudes) - 25), min(180, max(longitudes) + 25))
    axes.set_ylim(max(-85, min(latitudes) - 15), min(85, max(latitudes) + 15))
    axes.tick_params(colors=colors.muted, labelsize=8)
    for spine in axes.spines.values():
        spine.set_color(colors.grid)
    _graticule(axes, colors, 15, 10)
    _russia_outline(axes, colors)

    for key, label, style in (("minus", "сдвиг −σ", ":"), ("plus", "сдвиг +σ", ":")):
        variant = result["shifted"].get(key) or []
        if variant:
            axes.plot([p["lon"] for p in variant], [p["lat"] for p in variant],
                      color=colors.band_edge, linewidth=1.2, linestyle=style,
                      zorder=4, label=label)

    axes.plot(longitudes, latitudes, color=colors.highlight, linewidth=2.4,
              zorder=5, label="центральная линия")
    axes.scatter([longitudes[0]], [latitudes[0]], s=60, color=colors.accent,
                 zorder=6)
    axes.scatter([longitudes[-1]], [latitudes[-1]], s=60, color=colors.highlight,
                 zorder=6)

    for point in line[::max(1, len(line) // 6)]:
        axes.text(point["lon"], point["lat"] + 1.2,
                  point["utc"].strftime("%H:%M:%S"), color=colors.muted,
                  fontsize=7, ha="center", zorder=7)

    for city in all_cities():
        axes.scatter([city.lon], [city.lat], s=18, color=colors.muted, marker=".",
                     zorder=7)
        axes.text(city.lon + 1.2, city.lat + 0.8, city.name, color=colors.muted,
                  fontsize=7, zorder=7)

    legend = axes.legend(loc="lower left", fontsize=8, framealpha=0.25,
                         facecolor=colors.sky, edgecolor=colors.grid)
    for text in legend.get_texts():
        text.set_color(colors.text)

    figure.text(0.5, 0.965,
                f"({candidate.asteroid_number}) {candidate.asteroid_name} × "
                f"{candidate.star_id}",
                color=colors.text, fontsize=13, fontweight="bold", ha="center",
                va="top")
    figure.text(0.5, 0.925,
                f"{line[0]['utc'].strftime('%d.%m.%Y %H:%M:%S')} UTC · "
                f"ширина полосы ≈ {candidate.diameter_km:.0f} км · "
                f"неопределённость ±{candidate.sigma_km:.0f} км",
                color=colors.muted, fontsize=9.5, ha="center", va="top")
    return skymap.save(figure, path)
