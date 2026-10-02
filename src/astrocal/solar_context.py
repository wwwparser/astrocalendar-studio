"""Элонгация наблюдаемой цели; не заменяет местные условия видимости."""
def enrich(event):
    from .core import body, earth, timescale
    from .observing import guess_target
    target, _ = guess_target(event)
    if target is None and event.meta.get("comet"):
        from .events.comets import load_elements, comet_name, _orbit
        for _, row in load_elements().iterrows():
            if comet_name(row["designation"]) == event.meta["comet"]:
                target = _orbit(row)
                break
    if target is None and event.category == "meteors" and event.meta.get("code"):
        from .events.meteors import RADIANTS
        from skyfield.api import Star
        coordinates = RADIANTS.get(event.meta["code"])
        if coordinates:
            target = Star(ra_hours=coordinates[0] / 15, dec_degrees=coordinates[1])
    if event.category in ("moon", "occultation", "lunar_feature", "libration", "eclipse"):
        target = body("moon")
    if target is None:
        return False
    t = timescale().from_datetime(event.when)
    apparent = earth().at(t).observe(target).apparent()
    sun = earth().at(t).observe(body("sun")).apparent()
    elongation = float(apparent.separation_from(sun).degrees)
    dec = float(apparent.radec()[1].degrees - sun.radec()[1].degrees)
    direction = "севернее" if dec >= 0 else "южнее"
    regime = "рядом с Солнцем" if elongation < 25 else "сумеречная область" if elongation < 50 else "возможна ночная видимость"
    event.meta.update(elongation_deg=elongation, sun_direction=direction,
                      sun_declination_offset_deg=dec, solar_regime=regime)
    event.meta.setdefault("identity_text", event.text)
    event.text += f", элонгация {elongation:.0f}° ({direction} Солнца)"
    event.computed += f"; геоцентрическая элонгация {elongation:.3f}°, {regime}; местная высота требует отдельной проверки"
    return True
