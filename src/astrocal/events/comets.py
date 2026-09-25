"""Кометы: отбор ярких, трассировка по небу и автопоиск сближений.

**Про блеск.** Формула MPC `m = g + 5·lg Δ + k·lg r` — не измерение, а прикидка
по двум параметрам из архива, и для комет, сменивших активность, она ошибается
на величины: 65P/Gunn по ней выходит +10,5ᵐ при наблюдаемых 18,8ᵐ, 116P/Wild —
+11,8ᵐ при 21,7ᵐ. Публиковать такое нельзя.

Поэтому модель отвечает только за **форму** кривой блеска (зависимость от
расстояний r и Δ), а её уровень калибруется по наблюдению из COBS: считается
сдвиг Δm = наблюдение − модель на сегодня и применяется ко всей кривой. Комета,
которой нет ни в одном источнике наблюдений, в календарь не идёт: её блеск
ничем не подтверждён.

Порядок работы:
1. орбитальные элементы MPC (CometEls.txt) → тела Skyfield;
2. грубая сетка по месяцу → блеск, откалиброванный по наблюдениям → отбор;
3. частая сетка (15 мин) для отобранных → RA/Dec;
4. кросс-матч с Hipparcos и OpenNGC → локальные минимумы углового расстояния;
5. одно сближение = одна строка (момент минимума), а не 20 почти одинаковых.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

import numpy as np
import pandas as pd
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
from skyfield.data import mpc

from .. import config as cfg
from ..catalogs import STAR_NAMES_RU, angular_distance_deg, bright_stars, deep_sky
from ..core import (Event, body, constellation_at, earth, local_minima, observer,
                    refine_minimum, southern_observer, timescale, to_msk, ts_range)
from ..fmt import angle_deg, ru_constellation

COMET_ELS = cfg.CACHE / "CometEls.txt"

# Кометы, которые ведём независимо от формального порога блеска
# (интересная геометрия прохода по небу в этом месяце)
WATCHLIST = ("161P",)


def load_elements() -> pd.DataFrame:
    if not COMET_ELS.exists():
        from skyfield.api import load
        with load.open(mpc.COMET_URL, filename=str(COMET_ELS)) as f:
            return mpc.load_comets_dataframe(f)
    with COMET_ELS.open("rb") as f:
        return mpc.load_comets_dataframe(f)


def orbit(row):
    """Тело Skyfield по строке орбитальных элементов MPC.

    Публичная точка входа: Binocular Sky строит по ней альт/азимут комет,
    не повторяя разбор элементов у себя.
    """
    return body("sun") + mpc.comet_orbit(row, timescale(), GM_SUN)


_orbit = orbit      # исторический внутренний псевдоним


def estimate_magnitude(row, r_au, delta_au, offset: float = 0.0) -> np.ndarray:
    """m = g + 5·lg Δ + k·lg r (обозначения MPC) плюс калибровочный сдвиг.

    `offset` приводит модель к наблюдённому блеску: без него значение остаётся
    сырой оценкой по архивным параметрам и годится только для отбора кандидатов.
    """
    g = row["magnitude_g"]
    k = row["magnitude_k"]
    if not np.isfinite(g):
        return np.full_like(np.asarray(delta_au, dtype=float), 99.0)
    k = 10.0 if not np.isfinite(k) else k
    return g + 5.0 * np.log10(delta_au) + k * np.log10(r_au) + offset


@lru_cache(maxsize=1)
def brightness_index():
    """Наблюдённый блеск комет. None — источники недоступны."""
    from ..comet_feeds import load

    try:
        index = load()
    except Exception:                          # noqa: BLE001
        return None
    return index if index.available else None


def model_magnitude_now(row) -> float | None:
    """Блеск кометы по модели MPC на текущий момент. None — посчитать нечем."""
    now = timescale().from_datetime(dt.datetime.now(dt.timezone.utc))
    try:
        comet = _orbit(row)
        delta = float(earth().at(now).observe(comet).distance().au)
        r = float(body("sun").at(now).observe(comet).distance().au)
        value = float(estimate_magnitude(row, r, delta))
    except Exception:                          # noqa: BLE001
        return None
    return value if np.isfinite(value) else None


def calibrate(row) -> tuple[float, object]:
    """Сдвиг модели до наблюдения и сама запись наблюдения.

    Возвращает (0.0, None), если кометы нет в источниках: тогда блеск остаётся
    модельным, и это фиксируется в событии.
    """
    index = brightness_index()
    if index is None:
        return 0.0, None
    entry = index.find(str(row["designation"]))
    if entry is None or entry.current_magnitude is None:
        return 0.0, None
    model_now = model_magnitude_now(row)
    if model_now is None:
        return 0.0, entry
    return float(entry.current_magnitude) - model_now, entry


def magnitude_note(entry, offset: float) -> str:
    """Откуда взялся блеск — строка для протокола."""
    if entry is None:
        return ("блеск только по модели MPC, наблюдений в COBS и у ван Бёйтенена "
                "нет — значение ненадёжно")
    return (f"модель MPC откалибрована по наблюдению {entry.source}: "
            f"текущий блеск {entry.current_magnitude:+.1f}m, сдвиг модели "
            f"{offset:+.1f}m")


def select_bright(start: dt.datetime, end: dt.datetime,
                  mag_limit: float = None) -> pd.DataFrame:
    """Кометы, которые в течение месяца бывают ярче mag_limit."""
    limit = cfg.COMET_MAG_LIMIT if mag_limit is None else mag_limit
    df = load_elements()
    grid = ts_range(start, end, 24 * 60 * 5)   # раз в 5 суток — этого хватает для отбора
    sun, e = body("sun"), earth()
    rows = []
    for _, row in df.iterrows():
        if not np.isfinite(row.get("magnitude_g", np.nan)):
            continue
        try:
            comet = _orbit(row)
            astro = e.at(grid).observe(comet)
            delta = astro.distance().au
            r = sun.at(grid).observe(comet).distance().au
        except Exception:
            continue
        # Сначала грубый отбор по сырой модели — иначе калибровать пришлось бы
        # все девятьсот комет каталога. Порог с запасом: сырая оценка бывает
        # и завышенной, и заниженной.
        raw = estimate_magnitude(row, r, delta)
        if np.nanmin(raw) > limit + 6.0:
            continue
        offset, entry = calibrate(row)
        m = raw + offset
        if np.nanmin(m) <= limit:
            rows.append({"designation": row["designation"],
                         "mag_min": float(np.nanmin(m)),
                         "mag_raw_min": float(np.nanmin(raw)),
                         "offset": offset,
                         "observed": entry is not None,
                         "magnitude_source": entry.source if entry else "",
                         "observed_magnitude": (entry.current_magnitude
                                                if entry else None),
                         "row": row})
    if not rows:
        return pd.DataFrame(columns=["designation", "mag_min", "row"])
    return pd.DataFrame(rows).sort_values("mag_min").reset_index(drop=True)


def comet_name(designation: str) -> str:
    """'161P/Hartley-IRAS' из записи MPC."""
    return designation.split("(")[0].strip().rstrip(")").strip()


def _fmt_mag(m: float) -> str:
    return f"V={m:+.1f}m".replace(".", ",")


def track(row, start: dt.datetime, end: dt.datetime, step_minutes: int = None,
          offset: float | None = None):
    """RA/Dec/блеск кометы на частой сетке. Блеск откалиброван по наблюдению."""
    step = cfg.COMET_STEP_MINUTES if step_minutes is None else step_minutes
    grid = ts_range(start, end, step)
    comet = _orbit(row)
    astro = earth().at(grid).observe(comet)
    ra, dec, distance = astro.radec()
    r = body("sun").at(grid).observe(comet).distance().au
    shift = calibrate(row)[0] if offset is None else offset
    mag = estimate_magnitude(row, r, distance.au, shift)
    return grid, ra.degrees, dec.degrees, mag, comet


def _nearby(catalog: pd.DataFrame, ra_track, dec_track, pad_deg: float = 2.0):
    """Грубый отбор объектов каталога вблизи трека (прямоугольник + запас)."""
    dec_lo, dec_hi = dec_track.min() - pad_deg, dec_track.max() + pad_deg
    sel = catalog[(catalog.dec_degrees >= dec_lo) & (catalog.dec_degrees <= dec_hi)]
    if sel.empty:
        return sel
    ra_min, ra_max = ra_track.min(), ra_track.max()
    if ra_max - ra_min > 180:      # трек пересекает 0h
        return sel
    scale = np.cos(np.radians(np.clip((dec_lo + dec_hi) / 2, -89, 89)))
    pad_ra = pad_deg / max(scale, 0.05)
    return sel[(sel.ra_degrees >= ra_min - pad_ra) & (sel.ra_degrees <= ra_max + pad_ra)]


def _direction_from_offsets(d_ra_cos: float, d_dec: float) -> str:
    if abs(d_ra_cos) >= abs(d_dec):
        return "восточнее" if d_ra_cos > 0 else "западнее"
    return "севернее" if d_dec > 0 else "южнее"


def observability(grid, comet):
    """Высоты кометы и Солнца + маска моментов, когда объект виден из России.

    Проверяем две площадки — Москву и юг Европейской части: объекты со
    склонением ниже −20° из Москвы не поднимаются, но с юга наблюдаются
    нормально, и терять их календарю незачем.
    """
    best_alt = None
    best_sun = None
    mask = None
    for site in (observer(), southern_observer()):
        alt = site.at(grid).observe(comet).apparent().altaz()[0].degrees
        sun_alt = site.at(grid).observe(body("sun")).apparent().altaz()[0].degrees
        good = (alt > 10.0) & (sun_alt < -12.0)
        if best_alt is None:
            best_alt, best_sun, mask = alt, sun_alt, good
        else:
            better = alt > best_alt
            best_alt = np.where(better, alt, best_alt)
            best_sun = np.where(better, sun_alt, best_sun)
            mask = mask | good
    return best_alt, best_sun, mask


def _approach_events(row, grid, ra, dec, mag, catalog, kind: str,
                     limit_deg: float, describe, obs=None,
                     brightness=None) -> list[Event]:
    """Локальные минимумы расстояния комета–объект каталога.

    Момент наибольшего сближения часто приходится на светлое время или на период,
    когда объект под горизонтом. В календарь в этом случае ставим ближайший
    момент, когда картинку реально видно из Москвы и сближение ещё в силе, —
    так же поступают печатные календари.
    """
    out: list[Event] = []
    sel = _nearby(catalog, ra, dec)
    name = comet_name(row["designation"])
    comet = _orbit(row)
    ts = timescale()
    grid_tt = grid.tt
    alt_v, sun_v, obs_mask = obs if obs is not None else observability(grid, comet)
    offset, entry = brightness if brightness is not None else calibrate(row)
    magnitude_sources = (["MPC CometEls.txt (элементы)"]
                         + ([entry.source + " (блеск)"] if entry else []))

    for _, obj in sel.iterrows():
        d = angular_distance_deg(ra, dec, obj.ra_degrees, obj.dec_degrees)
        if d.min() > limit_deg:
            continue
        for i in local_minima(grid, d):
            if d[i] > limit_deg:
                continue

            def dist_at(tt, obj=obj):
                p = earth().at(ts.tt_jd(tt)).observe(comet)
                r_, dc_, _ = p.radec()
                return float(angular_distance_deg(r_.degrees, dc_.degrees,
                                                  obj.ra_degrees, obj.dec_degrees))

            tt_min = refine_minimum(dist_at, grid[max(i - 1, 0)].tt,
                                    grid[min(i + 1, len(grid) - 1)].tt)
            sep_min = dist_at(tt_min)

            # ближайший наблюдаемый узел сетки, где сближение ещё в пределах порога
            candidates = np.where(obs_mask & (d <= limit_deg))[0]
            visible = len(candidates) > 0
            if visible:
                j = int(candidates[np.argmin(np.abs(candidates - i))])
                if abs(j - i) * cfg.COMET_STEP_MINUTES > 14 * 60:
                    visible = False
            if visible:
                t = grid[j]
                sep = float(d[j])
                alt, sun_alt = float(alt_v[j]), float(sun_v[j])
            else:
                t = ts.tt_jd(tt_min)
                sep = sep_min
                alt = float(np.interp(tt_min, grid_tt, alt_v))
                sun_alt = float(np.interp(tt_min, grid_tt, sun_v))

            when = to_msk(t)
            p = earth().at(t).observe(comet)
            c_ra, c_dec, _ = p.radec()
            d_dec = float(c_dec.degrees) - obj.dec_degrees
            d_ra = ((float(c_ra.degrees) - obj.ra_degrees + 180) % 360 - 180) *                 np.cos(np.radians(obj.dec_degrees))
            const = ru_constellation(constellation_at()(
                earth().at(t).observe(comet).apparent()))
            out.append(Event(
                when=when,
                text=(f"Комета {name} ({_fmt_mag(float(np.interp(t.tt, grid_tt, mag)))}) "
                      f"проходит в {angle_deg(sep)} "
                      f"{_direction_from_offsets(d_ra, d_dec)} {describe(obj)} "
                      f"в созвездии {const}"),
                category=f"comet_{kind}",
                confidence="средняя" if entry is not None else "низкая",
                computed=(f"минимум расстояния {sep_min * 60:.1f}′ в "
                          f"{to_msk(ts.tt_jd(tt_min)):%d.%m %H:%M} МСК; в календаре "
                          f"момент наблюдаемости, разделение {sep * 60:.1f}′; "
                          f"наибольшая высота кометы (Москва/юг ЕЧР) {alt:.0f}°, "
                          f"Солнце {sun_alt:.0f}°; "
                          + magnitude_note(entry, offset)),
                sources=magnitude_sources + ["Hipparcos / OpenNGC",
                                             "Skyfield/DE440s"],
                precision="hour",
                notes=("наблюдаемо из России" if visible
                       else "из России в эти сутки не наблюдается"),
                meta={"comet": name, "sep_deg": sep, "sep_min_deg": sep_min,
                      "alt": alt, "sun_alt": sun_alt, "visible": visible,
                      "object_mag": float(obj.magnitude if kind == "star" else obj.mag),
                      "object": f"HIP {int(obj.hip)}" if kind == "star" else obj.Name,
                      "kind": kind,
                      "comet_mag": float(np.interp(t.tt, grid_tt, mag)),
                      "magnitude_observed": entry is not None,
                      "magnitude_source": entry.source if entry else "",
                      "magnitude_offset": offset},
            ))
    return out


def _describe_star(obj) -> str:
    hip = int(obj.hip)
    named = STAR_NAMES_RU.get(hip)
    mag = f"V={obj.magnitude:+.1f}m".replace(".", ",")
    return f"звезды {named} (HIP {hip}, {mag})" if named else f"звезды HIP {hip} ({mag})"


def _describe_dso(obj) -> str:
    label = obj.Name
    label = ("NGC " + label[3:] if label.startswith("NGC")
             else "IC " + label[2:] if label.startswith("IC") else label)
    label = label.replace(" 0", " ").rstrip()
    if pd.notna(obj.messier) and obj.messier:
        label = f"{obj.messier} ({label})"
    common = (obj.common or "").split(",")[0].strip()
    if common:
        label = f'{obj.type_gen} "{common}" {label}'
    else:
        label = f"{obj.type_gen} {label}"
    mag = f"V={obj.mag:+.1f}m".replace(".", ",")
    return f"{label} ({mag})"


def interesting(meta: dict) -> bool:
    """Отбор в календарь: тесно, объект яркий, видно из России, блеск подтверждён.

    Последнее условие появилось после разбора октябрьского выпуска: по одной
    лишь модели MPC комета 65P/Gunn получила +10,6ᵐ при наблюдаемых 18,8ᵐ.
    Событие с непроверенным блеском вводит читателя в заблуждение сильнее, чем
    его отсутствие, поэтому такие строки остаются в протоколе.
    """
    if not meta["visible"]:
        return False
    if not meta.get("magnitude_observed"):
        return False
    sep, mag = meta["sep_deg"], meta["object_mag"]
    if meta["kind"] == "star":
        # яркая звезда — интересно и на градусе, слабая — только при тесном проходе
        return (mag <= 4.5 and sep <= 1.0) or (mag <= 6.5 and sep <= 0.5)
    return sep <= 1.0 and mag <= 11.5


def deduplicate(events: list[Event], hours: float = 12.0) -> list[Event]:
    """Одно сближение — одна строка: в окне hours оставляем самое тесное."""
    kept: list[Event] = []
    for ev in sorted(events, key=lambda e: e.meta["sep_deg"]):
        clash = any(
            other.meta["comet"] == ev.meta["comet"]
            and other.meta["kind"] == ev.meta["kind"]
            and abs((other.when - ev.when).total_seconds()) < hours * 3600
            for other in kept)
        if not clash:
            kept.append(ev)
    return sorted(kept, key=lambda e: e.when)


def horizons_magnitude(designation: str, start: dt.datetime, end: dt.datetime):
    """Блеск кометы по JPL Horizons — второй источник для сверки.

    Возвращает (минимум, максимум) или None, если Horizons не отвечает или
    обозначение неоднозначно.
    """
    from ..horizons import query, rows

    tag = designation.split("/")[0].split("(")[0].strip()
    try:
        text = query(f"DES={tag};CAP;", start.strftime("%Y-%m-%d"),
                     end.strftime("%Y-%m-%d"), "5d", quantities="1,9")
    except Exception:
        return None
    values = []
    for row in rows(text):
        cells = [c for c in row[1:] if c.strip()]
        try:
            values.append(float(cells[2]))
        except (ValueError, IndexError):
            continue
    return (min(values), max(values)) if values else None


def milestones(start: dt.datetime, end: dt.datetime,
               max_comets: int = 8) -> list[Event]:
    """Опорные точки видимости кометы: перигелий, минимум расстояния, максимум блеска.

    Эти события не привязаны к сближению с каталожным объектом, но именно они
    определяют, стоит ли вообще искать комету в этом месяце.
    """
    from ..observing import best_city

    bright = select_bright(start, end)
    grid = ts_range(start, end, 360)
    out: list[Event] = []

    for _, item in bright.head(max_comets).iterrows():
        row = item["row"]
        name = comet_name(row["designation"])
        comet = _orbit(row)
        offset, entry = calibrate(row)
        astro = earth().at(grid).observe(comet)
        distance = astro.distance().au
        heliocentric = body("sun").at(grid).observe(comet).distance().au
        magnitudes = estimate_magnitude(row, heliocentric, distance, offset)

        # перигелий: минимум гелиоцентрического расстояния внутри месяца
        index = int(np.argmin(heliocentric))
        if 0 < index < len(grid) - 1:
            when = to_msk(grid[index])
            out.append(Event(
                when=when,
                text=(f"Комета {name} ({_fmt_mag(float(magnitudes[index]))}) "
                      f"проходит перигелий на расстоянии "
                      + f"{heliocentric[index]:.3f}".replace(".", ",")
                      + " а.е. от Солнца"),
                category="comet_milestone", confidence="средняя",
                rank="interesting",
                computed=(f"минимум гелиоцентрического расстояния "
                          f"{heliocentric[index]:.4f} а.е. по элементам MPC; "
                          + magnitude_note(entry, offset)),
                sources=["MPC CometEls.txt", "Skyfield/DE440s"]
                        + ([entry.source] if entry else []),
                precision="hour",
                meta={"comet": name, "milestone": "perihelion",
                      "magnitude_observed": entry is not None}))

        # минимум геоцентрического расстояния
        index = int(np.argmin(distance))
        if 0 < index < len(grid) - 1:
            when = to_msk(grid[index])
            out.append(Event(
                when=when,
                text=(f"Комета {name} ({_fmt_mag(float(magnitudes[index]))}) "
                      "ближе всего к Земле — "
                      + f"{distance[index]:.3f}".replace(".", ",") + " а.е."),
                category="comet_milestone", confidence="средняя",
                rank="interesting",
                computed=(f"минимум геоцентрического расстояния "
                          f"{distance[index]:.4f} а.е."),
                sources=["MPC CometEls.txt", "Skyfield/DE440s"],
                precision="hour", meta={"comet": name, "milestone": "closest"}))

        # максимум блеска и лучшее окно наблюдения
        index = int(np.argmin(magnitudes))
        when = to_msk(grid[index])
        if start <= when < end:
            sources = {"MPC": float(magnitudes[index])}
            horizons = horizons_magnitude(row["designation"], start, end)
            if horizons:
                sources["JPL Horizons"] = horizons[0]
            circumstance = None
            try:
                event_stub = Event(when=when, text=name, category="comet",
                                   meta={})
                circumstance = best_city(event_stub)
            except Exception:
                circumstance = None
            note = ""
            if len(sources) > 1:
                spread = max(sources.values()) - min(sources.values())
                note = (f"оценки блеска расходятся на {spread:.1f}m: "
                        + ", ".join(f"{k} {v:+.1f}m" for k, v in sources.items()))
            out.append(Event(
                when=when,
                text=(f"Комета {name} в максимуме блеска "
                      f"({_fmt_mag(float(magnitudes[index]))}) — расчётная оценка, "
                      f"не измерение"),
                category="comet_milestone", confidence="низкая",
                rank="optional",
                computed=("минимум расчётной звёздной величины по формуле MPC"
                          + (f"; {note}" if note else "")
                          + (f"; лучшие условия: {circumstance.city.name}, "
                             f"{circumstance.stars_text}" if circumstance else "")),
                sources=["MPC CometEls.txt"] + (["JPL Horizons"] if horizons else []),
                precision="hour",
                notes="Блеск кометы — прогноз по орбитальным параметрам, "
                      "реальная яркость может отличаться на величины",
                meta={"comet": name, "milestone": "peak",
                      "magnitude_sources": sources}))
    return out


def all_events(start: dt.datetime, end: dt.datetime, max_comets: int = 20):
    """События по кометам.

    Возвращает (строки для календаря, все найденные сближения, таблица комет).
    """
    bright = select_bright(start, end)
    selected = list(bright.head(max_comets)["row"])
    known = {comet_name(r["designation"]) for r in selected}
    # кометы из списка наблюдения добавляем, даже если формально слабее порога
    df = load_elements()
    for tag in WATCHLIST:
        for _, row in df[df.designation.str.startswith(tag, na=False)].iterrows():
            if comet_name(row["designation"]) not in known:
                selected.append(row)
                known.add(comet_name(row["designation"]))

    stars, dso = bright_stars(), deep_sky()
    found: list[Event] = []
    for row in selected:
        brightness = calibrate(row)
        grid, ra, dec, mag, comet = track(row, start, end, offset=brightness[0])
        obs = observability(grid, comet)
        found += _approach_events(row, grid, ra, dec, mag, stars, "star",
                                  cfg.APPROACH_LIMIT_DEG, _describe_star, obs,
                                  brightness)
        found += _approach_events(row, grid, ra, dec, mag, dso, "dso",
                                  cfg.APPROACH_LIMIT_DEG, _describe_dso, obs,
                                  brightness)
    calendar = deduplicate([e for e in found if interesting(e.meta)])
    return calendar, found, bright
