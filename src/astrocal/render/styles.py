"""Оформление карт: палитра, размеры, подписи.

Карты должны читаться и на экране, и в мессенджере после сжатия, поэтому фон
тёмный, линии тонкие, а подписи крупнее, чем принято в научной графике.
"""
from __future__ import annotations

from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")          # рендерим в файл, без оконной подсистемы


@dataclass(frozen=True)
class Palette:
    background: str
    sky: str
    horizon: str
    grid: str
    text: str
    muted: str
    star: str
    constellation: str
    track: str
    highlight: str
    accent: str
    land: str
    water: str
    band: str
    band_edge: str


DARK = Palette(
    background="#0d1220", sky="#131a2b", horizon="#3a4a6b", grid="#22304a",
    text="#e8eef7", muted="#8ea0bd", star="#ffffff", constellation="#3d5680",
    track="#ffb347", highlight="#ff6b6b", accent="#5bc8ff",
    land="#1c2740", water="#0e1526", band="#ffb347", band_edge="#7a5426",
)

LIGHT = Palette(
    background="#ffffff", sky="#eef3fb", horizon="#8fa4c4", grid="#d5deec",
    text="#16202f", muted="#5b6b84", star="#16202f", constellation="#9fb4d4",
    track="#c2691a", highlight="#c0392b", accent="#1b6ea8",
    land="#e8eef7", water="#f6f9fd", band="#c2691a", band_edge="#e0b184",
)

FIGURE_DPI = 130
FONT_FAMILY = ["Segoe UI", "DejaVu Sans", "Arial"]


def apply_defaults() -> None:
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": FONT_FAMILY,
        "figure.dpi": FIGURE_DPI,
        "savefig.dpi": FIGURE_DPI,
        "axes.unicode_minus": False,
    })


def palette(theme: str = "dark") -> Palette:
    return LIGHT if theme == "light" else DARK


def star_marker_size(magnitude: float, limit: float = 5.5) -> float:
    """Размер маркера звезды: ярче — заметно крупнее."""
    magnitude = min(magnitude, limit)
    return max(1.0, (limit - magnitude + 0.6) ** 2.1)
