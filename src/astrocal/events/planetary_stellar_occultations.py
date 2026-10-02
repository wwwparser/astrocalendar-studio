"""Проверка RMS-кандидатов по свежей эфемериде и опорным городам.

Сферическая поверхность: кольца и атмосферное ослабление не моделируются.
Gaia G сохраняется как G, никогда не подменяется V.
"""
import datetime as dt
import numpy as np
from skyfield.api import Star, wgs84
from ..core import Event, body, planets, timescale, ts_range, to_msk, find_zero
from ..cities import all_cities
from ..horizons import query, table, column_named, CODES

RADII = {"Jupiter": 71492., "Saturn": 60268., "Uranus": 25559.,
         "Neptune": 24764., "Titan": 2574.73, "Triton": 1353.4}
LABELS = {"Jupiter": "Юпитером", "Saturn": "Сатурном", "Uranus": "Ураном",
          "Neptune": "Нептуном", "Titan": "Титаном", "Triton": "Тритоном"}


def parse_position(text):
    h, m, s, d, dm, ds = text.split()
    ra = 15 * (float(h) + float(m) / 60 + float(s) / 3600)
    sign = -1 if d.startswith("-") else 1
    dec = sign * (abs(float(d)) + float(dm) / 60 + float(ds) / 3600)
    if not (0 <= ra < 360 and -90 <= dec <= 90):
        raise ValueError("Неверные координаты звезды RMS")
    return ra, dec


def satellite_track(name, centre):
    """Астрометрические геоцентрические координаты Horizons ICRF."""
    from ..events.close_approaches import _to_float
    code = "801" if name == "Triton" else CODES[name.lower()]
    start, end = centre - dt.timedelta(hours=8), centre + dt.timedelta(hours=8)
    raw = query(code, start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"),
                "1m", quantities="1,20", retries=1, timeout=45, max_cache_age_hours=24)
    records = []
    for row in table(raw):
        ra = _to_float(column_named(row, "R.A."))
        dec = _to_float(column_named(row, "DEC"))
        distance = _to_float(column_named(row, "delta"))
        if ra is None or dec is None or distance is None:
            continue
        stamp = dt.datetime.strptime(row["_time"], "%Y-%b-%d %H:%M").replace(tzinfo=dt.timezone.utc)
        ra, dec = np.radians([ra, dec])
        vector = distance * 149597870.7 * np.array([np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)])
        records.append((timescale().from_datetime(stamp).tt, vector))
    if len(records) < 2:
        raise ValueError("Horizons не дал координат спутника")
    times = np.array([r[0] for r in records])
    vectors = np.array([r[1] for r in records])
    return lambda t: np.array([np.interp(t.tt, times, vectors[:, i]) for i in range(3)])


def local_contacts(item):
    ra, dec = parse_position(item["star_position"])
    star = Star(ra_hours=ra/15, dec_degrees=dec)
    name, centre = item["target"], item["when"]
    radius = RADII[name]
    ts = timescale()
    grid = ts_range(centre - dt.timedelta(hours=6), centre + dt.timedelta(hours=6), 1)
    satellite = satellite_track(name, centre) if name in ("Titan", "Triton") else None
    contacts = []
    for city in all_cities():
        geosite = wgs84.latlon(city.lat, city.lon, city.elevation_m)
        site = planets()["earth"] + geosite
        def margin(t):
            star_vector = site.at(t).observe(star).position.km
            target_vector = (satellite(t) - geosite.at(t).position.km if satellite
                             else site.at(t).observe(body(name.lower())).position.km)
            distance = np.linalg.norm(target_vector, axis=0)
            cosine = np.sum(star_vector * target_vector, axis=0) / (np.linalg.norm(star_vector, axis=0) * distance)
            return np.arccos(np.clip(cosine, -1, 1)) - np.arcsin(radius/distance)
        values = margin(grid)
        beginnings = np.flatnonzero((values[:-1] > 0) & (values[1:] <= 0))
        endings = np.flatnonzero((values[:-1] <= 0) & (values[1:] > 0))
        for index in beginnings:
            later = endings[endings > index]
            if not len(later):
                continue
            finish = int(later[0])
            first = ts.tt_jd(find_zero(lambda tt: float(margin(ts.tt_jd(tt))), grid[index].tt, grid[index+1].tt))
            last = ts.tt_jd(find_zero(lambda tt: float(margin(ts.tt_jd(tt))), grid[finish].tt, grid[finish+1].tt))
            altitude = float(site.at(first).observe(star).apparent().altaz()[0].degrees)
            sun = float(site.at(first).observe(body("sun")).apparent().altaz()[0].degrees)
            if altitude >= 5 and sun <= -6:
                contacts.append({"city": city.name, "start": to_msk(first).isoformat(),
                                 "end": to_msk(last).isoformat(), "altitude_deg": altitude, "sun_altitude_deg": sun})
    return contacts


def build(report):
    events = []
    for item in report.get("events", []):
        # Фотометрический фильтр именно G, не визуальный V.
        if item["g_mag"] > 13:
            item["local_status"] = "faint_G"
            continue
        try:
            contacts = local_contacts(item)
            item["local_contacts"] = contacts
            item["local_status"] = "night_contacts" if contacts else "no_contacts_in_selected_cities"
            if not contacts:
                continue
            when = min(dt.datetime.fromisoformat(c["start"]) for c in contacts)
            ra, dec = parse_position(item["star_position"])
            events.append(Event(
                when=when, text=f"Покрытие звезды Gaia {item['gaia_id']} (G={item['g_mag']:+.1f}m) {LABELS[item['target']]}; ночная видимость: " + ", ".join(c["city"] for c in contacts),
                category="planetary_star_occultation", confidence="средняя", rank="optional",
                computed="Уточнённые топоцентрические контакты на сферическом лимбе; звезда J2000 с положением на эпоху события из RMS. Кольца, атмосфера, эллиптичность не моделируются.",
                sources=[item["source_url"], "JPL Horizons / DE440s"],
                notes="G не равно V. Контакты приближённые, требуют независимой проверки перед публикацией",
                meta={"source_event_id": item["source_id"], "ra_deg": ra, "dec_deg": dec,
                      "review_reason": "Ночные контакты пересчитаны, но сферический лимб и архивные позиции звёзд требуют независимой проверки; кольца и атмосфера не моделируются.",
                      "local_contacts": contacts, "requires_review": True, "photometric_band": "G"},
                provenance=item["provenance"]))
        except Exception as error:
            item["local_status"] = "error"
            item["local_error"] = str(error)
    return events
