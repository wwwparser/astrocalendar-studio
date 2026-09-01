"""Видимые звёздные величины планет (Skyfield, модель Mallama 2018)."""
from __future__ import annotations

from skyfield.magnitudelib import planetary_magnitude

from .core import body, earth

_FALLBACK = {"mercury": 0.0, "venus": -4.0, "mars": 1.2, "jupiter": -2.0,
             "saturn": 0.6, "uranus": 5.7, "neptune": 7.8}


def planet_magnitude(name: str, t) -> float:
    try:
        astrometric = earth().at(t).observe(body(name))
        return float(planetary_magnitude(astrometric))
    except Exception:
        return _FALLBACK[name]
