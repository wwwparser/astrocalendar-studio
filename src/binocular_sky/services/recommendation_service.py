"""Что посмотреть сегодня: рейтинг объекта под конкретный бинокль.

Задача рейтинга — не «оценить объект вообще», а ответить, стоит ли выходить во
двор ради него именно сегодня, именно с этой оптикой, именно с этой площадки.
Поэтому M31 и Юпитер не сравниваются одной формулой: у базовой шкалы есть
поправки по типу объекта.

АЛГОРИТМ (BinocularScore, 0–100)
================================

Базовые слагаемые:

    доступность прибору      0–35   виден ли вообще: блеск против предельной
                                    величины, для протяжённых — ещё и
                                    поверхностная яркость против яркости неба
    высота над местным
    горизонтом               0–20   у крыши смотреть нечего, выше 40° прибавка
                                    почти не растёт
    вписывание в поле        0–15   объект целиком в поле — максимум; объект
                                    заметно меньше 1/20 поля — точка, минимум
    помеха от Луны           0–15   фаза × близость × чувствительность типа
    длительность окна        0–10   меньше получаса — не успеть, больше трёх
                                    часов — прибавка перестаёт расти
    поправка по типу        −10…+8  правила ниже

Поправки по типу (`TYPE_RULES`):

* Луна и яркие планеты не должны проваливаться из-за Луны и поверхностной
  яркости: у них чувствительность к Луне около нуля и премия за деталь.
* Галактики и диффузные туманности, наоборот, полностью чувствительны к засветке.
* Рассеянные скопления и астеризмы разрешаются на отдельные звёзды, поэтому
  поверхностная яркость к ним почти не применяется.
* Двойные звёзды оцениваются по тому, разделит ли их прибор: видимое
  расстояние ``ρ·Γ`` должно превышать разрешающую способность глаза.
* Спутники Юпитера имеют смысл, только когда виден сам Юпитер.

Звёзды: ≥80 → ★★★★★, ≥65 → ★★★★, ≥48 → ★★★, ≥30 → ★★, иначе ★.

Модель эмпирическая. Она даёт согласованное упорядочение объектов, а не
физическую гарантию видимости.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import numpy as np

from ..models.binocular import BinocularProfile
from ..models.observer import ObserverProfile
from ..models.target import (ASTERISM, COMET, DOUBLE_STAR, GALAXY,
                             GLOBULAR_CLUSTER, JUPITER_MOON, MOON, NEBULA,
                             OPEN_CLUSTER, PLANET, PLANETARY_NEBULA, STAR, SUN,
                             Target)
from . import astronomy_service as astro
from . import catalog_service, horizon_service

# Яркость фона неба, звёздных величин с квадратной угловой секунды, по классам
# шкалы Бортля. Значения — общепринятые ориентиры для измерений SQM.
SKY_BRIGHTNESS_BY_BORTLE = {
    1: 22.0, 2: 21.7, 3: 21.5, 4: 21.0, 5: 20.5,
    6: 19.5, 7: 18.9, 8: 18.0, 9: 17.5,
}

# Насколько тип объекта страдает от лунной засветки: 1.0 — полностью, 0 — никак.
MOON_SENSITIVITY = {
    SUN: 0.0, MOON: 0.0, PLANET: 0.05, JUPITER_MOON: 0.05,
    STAR: 0.15, DOUBLE_STAR: 0.15, ASTERISM: 0.35, OPEN_CLUSTER: 0.45,
    GLOBULAR_CLUSTER: 0.7, PLANETARY_NEBULA: 0.6, COMET: 0.9,
    NEBULA: 1.0, GALAXY: 1.0,
}

# Премия или штраф по типу объекта.
TYPE_RULES = {
    MOON: 8.0, PLANET: 6.0, JUPITER_MOON: 2.0, OPEN_CLUSTER: 5.0,
    ASTERISM: 4.0, GLOBULAR_CLUSTER: 3.0, DOUBLE_STAR: 2.0, COMET: 3.0,
    NEBULA: 0.0, PLANETARY_NEBULA: -6.0, GALAXY: 0.0, STAR: -2.0, SUN: -100.0,
}

# Разрешающая способность глаза в окуляре: пара звёзд ниже этого видимого
# расстояния сливается в одну. 3′ — консервативная величина для наблюдения ночью.
EYE_RESOLUTION_ARCMIN = 3.0

# Пороги откалиброваны по фактическому распределению оценок: для типового
# бинокля 10×50 при Bortle 4 за ночь набирается около четырёхсот доступных
# объектов, и на них медиана даёт 54, 75-й процентиль 76, 95-й — 87. Пять звёзд
# должны означать «выйти ради этого стоит», а не «объект над горизонтом»,
# поэтому верхняя градация начинается там, куда попадают единицы процентов.
STAR_THRESHOLDS = ((88, 5), (76, 4), (60, 3), (42, 2))


@dataclass
class Recommendation:
    """Оценённый объект для панели «сегодня ночью»."""

    target: Target
    score: int
    stars: int
    altitude_deg: float
    azimuth_deg: float
    magnitude: float | None
    limiting_magnitude: float
    visibility: object                      # horizon_service.LocalVisibility
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    fits_in_field: bool | None = None
    field_fraction: float | None = None
    moon_separation_deg: float | None = None
    breakdown: dict = field(default_factory=dict)

    @property
    def stars_text(self) -> str:
        return "★" * self.stars + "☆" * (5 - self.stars)

    @property
    def window_text(self) -> str:
        windows = self.visibility.windows
        if not windows:
            return "не поднимается над участком"
        if len(windows) == 1 and windows[0].minutes > 5.5 * 60:
            return "всю ночь"
        return " · ".join(f"{w.start:%H:%M}–{w.end:%H:%M}" for w in windows[:2])

    def to_dict(self) -> dict:
        return {
            "id": self.target.id, "name": self.target.name,
            "kind": self.target.kind, "kind_ru": self.target.kind_ru,
            "score": self.score, "stars": self.stars,
            "stars_text": self.stars_text,
            "alt": round(self.altitude_deg, 1), "az": round(self.azimuth_deg, 1),
            "mag": None if self.magnitude is None else round(self.magnitude, 1),
            "window": self.window_text,
            "reasons": self.reasons, "warnings": self.warnings,
            "fits": self.fits_in_field,
        }


# ---------------------------------------------------------------- составляющие

def sky_brightness(bortle: int) -> float:
    return SKY_BRIGHTNESS_BY_BORTLE.get(int(bortle), 21.0)


def moon_penalty_mag(moon: astro.MoonState, separation_deg: float | None) -> float:
    """Насколько Луна поднимает фон неба, в звёздных величинах.

    Под горизонтом Луна не мешает. Над горизонтом вклад растёт с освещённостью
    диска и падает с удалением от объекта: полная Луна в 20° от цели съедает
    заметно больше, чем та же Луна в противоположной части неба.
    """
    if moon.altitude_deg <= 0.0:
        return 0.0
    glare = moon.illumination ** 1.5
    proximity = float(np.clip(1.0 - (separation_deg or 180.0) / 90.0, 0.0, 1.0))
    height = float(np.clip(moon.altitude_deg / 45.0, 0.0, 1.0))
    return 2.4 * glare * (0.35 + 0.65 * proximity) * (0.4 + 0.6 * height)


def detectability_points(target: Target, binocular: BinocularProfile,
                         limiting_mag: float, sky_mag: float) -> tuple[float, list, list]:
    """0–35 очков за то, что объект вообще будет виден."""
    reasons, warnings = [], []
    magnitude = target.magnitude
    if magnitude is None:
        return 18.0, reasons, ["блеск неизвестен, оценка приблизительная"]

    margin = limiting_mag - magnitude
    if target.is_extended and target.kind not in (OPEN_CLUSTER, ASTERISM):
        # свет протяжённого объекта размазан: тот же интегральный блеск даётся
        # тяжелее, чем звезде такой же величины
        size = target.size_arcmin or 5.0
        margin -= min(2.5, max(0.0, 2.5 * math.log10(max(size, 1.0) / 10.0)))

    # запас в шесть величин считаем полным баллом: иначе всё ярче 8m получает
    # одинаковые 35 очков и шкала перестаёт что-либо различать
    points = 35.0 * float(np.clip((margin + 0.5) / 6.0, 0.0, 1.0))

    if margin <= 0.0:
        warnings.append(f"слабее расчётного предела {limiting_mag:+.1f}m — "
                        "скорее всего, не увидите")
    elif margin < 1.0:
        warnings.append("на пределе видимости для этого прибора")
    else:
        reasons.append(f"блеск {magnitude:+.1f}m при расчётном пределе "
                       f"{limiting_mag:+.1f}m")

    # поверхностная яркость: диффузный объект может «не проявиться» даже будучи
    # формально ярче предела
    if target.kind in (GALAXY, NEBULA, PLANETARY_NEBULA):
        surface = target.effective_surface_brightness()
        if surface is not None:
            contrast = sky_mag - surface
            if contrast < -1.5:
                points *= 0.35
                warnings.append("поверхностная яркость ниже фона неба — "
                                "нужно очень тёмное небо")
            elif contrast < 0.0:
                points *= 0.7
                warnings.append("слабый контраст с фоном неба")
            else:
                reasons.append(f"поверхностная яркость {surface:.1f} "
                               f"против фона {sky_mag:.1f}")
    return points, reasons, warnings


def altitude_points(altitude_deg: float, clearance_deg: float) -> tuple[float, list, list]:
    """0–20 очков за высоту над местным горизонтом."""
    reasons, warnings = [], []
    points = 20.0 * float(np.clip(altitude_deg / 50.0, 0.0, 1.0)) ** 0.7
    if altitude_deg >= 40:
        reasons.append(f"высоко над горизонтом — {altitude_deg:.0f}°")
    elif altitude_deg >= 20:
        reasons.append(f"высота {altitude_deg:.0f}°, смотреть удобно")
    elif altitude_deg > 0:
        warnings.append(f"низко над горизонтом — всего {altitude_deg:.0f}°")
    if 0 < clearance_deg < 3.0:
        warnings.append("едва выходит из-за препятствия")
    return points, reasons, warnings


def framing_points(target: Target, binocular: BinocularProfile) -> tuple[float, list, list]:
    """0–15 очков за то, как объект смотрится в поле зрения."""
    reasons, warnings = [], []
    fraction = binocular.field_fraction(target.size_arcmin)
    if fraction is None:
        return 8.0, reasons, warnings
    if fraction <= 1.0:
        # лучше всего, когда объект занимает от десятой доли до половины поля:
        # видно и сам объект, и окружение
        ideal = float(np.clip(fraction / 0.35, 0.0, 1.0)) if fraction < 0.35 else \
            float(np.clip((1.15 - fraction) / 0.8, 0.0, 1.0))
        points = 4.0 + 11.0 * ideal
        if fraction > 0.05:
            reasons.append(f"занимает около {fraction * 100:.0f}% поля "
                           f"{binocular.field_of_view_deg:g}° — помещается целиком")
        else:
            reasons.append("в бинокль выглядит как звёздочка")
    else:
        points = 6.0 * float(np.clip(2.0 / fraction, 0.0, 1.0)) + 2.0
        warnings.append(f"крупнее поля зрения — в поле {binocular.field_of_view_deg:g}° "
                        "войдёт только часть")
    return points, reasons, warnings


def moon_points(target: Target, moon: astro.MoonState,
                separation_deg: float | None) -> tuple[float, list, list]:
    """0–15 очков: сколько осталось после лунной засветки."""
    reasons, warnings = [], []
    sensitivity = MOON_SENSITIVITY.get(target.kind, 0.6)
    if moon.altitude_deg <= 0.0:
        reasons.append("Луна под горизонтом, не мешает")
        return 15.0, reasons, warnings
    glare = moon.illumination ** 1.5
    proximity = float(np.clip(1.0 - (separation_deg or 180.0) / 90.0, 0.0, 1.0))
    interference = sensitivity * glare * (0.4 + 0.6 * proximity)
    points = 15.0 * (1.0 - float(np.clip(interference, 0.0, 1.0)))
    if interference < 0.12:
        reasons.append(f"Луна ({moon.phase_name}) почти не мешает")
    elif interference < 0.4:
        warnings.append(f"Луна подсвечивает небо ({moon.illumination * 100:.0f}%)")
    else:
        warnings.append(f"яркая Луна {'рядом' if proximity > 0.5 else 'на небе'} — "
                        "условия для этого объекта плохие")
    return points, reasons, warnings


def duration_points(minutes: float) -> tuple[float, list, list]:
    """0–10 очков за то, что окно наблюдения не мимолётное."""
    reasons, warnings = [], []
    points = 10.0 * float(np.clip(minutes / 180.0, 0.0, 1.0))
    if minutes < 30:
        warnings.append(f"окно всего {minutes:.0f} мин")
    elif minutes > 240:
        reasons.append("доступен почти всю ночь")
    return points, reasons, warnings


def type_adjustment(target: Target, binocular: BinocularProfile,
                    context: dict) -> tuple[float, list, list]:
    """Поправка по типу объекта — там, где общая формула врёт."""
    reasons, warnings = [], []
    points = TYPE_RULES.get(target.kind, 0.0)

    if target.kind == MOON:
        illumination = context.get("moon_illumination", 0.5)
        if 0.15 < illumination < 0.85:
            reasons.append("терминатор посреди диска — кратеры в рельефе")
        elif illumination >= 0.85:
            warnings.append("полная Луна плоская: деталей у терминатора нет")

    if target.kind == PLANET:
        # различит ли прибор диск: видимый размер против разрешения глаза
        apparent = (target.size_arcmin or 0.0) * binocular.magnification
        if apparent >= EYE_RESOLUTION_ARCMIN:
            reasons.append(f"диск различим: {apparent:.0f}′ видимого размера "
                           f"при {binocular.magnification:g}×")
        else:
            points -= 6.0
            warnings.append("диск не разрешается — в бинокль выглядит звездой")
        if target.id == "jupiter":
            reasons.append("рядом видны галилеевы спутники")
        if target.id == "saturn" and binocular.magnification < 20:
            warnings.append("кольца в бинокль не разделяются — виден вытянутый диск")

    if target.kind == JUPITER_MOON:
        if not context.get("jupiter_visible", False):
            points -= 12.0
            warnings.append("сам Юпитер сейчас не виден")

    if target.kind == DOUBLE_STAR and target.size_arcmin:
        # Видимое расстояние между компонентами против разрешения глаза.
        # Премия растёт плавно: у ступеньки пара, разделяемая «впритык» и
        # разделяемая с запасом, получали одинаковую оценку, и прибор с
        # большим увеличением ничем не выигрывал.
        apparent = target.size_arcmin * binocular.magnification
        ratio = apparent / EYE_RESOLUTION_ARCMIN
        if ratio >= 1.0:
            points += 5.0 * float(np.clip((ratio - 1.0) / 3.0, 0.0, 1.0))
            comfort = ("разделяется уверенно" if ratio >= 2.0
                       else "разделяется на пределе — держите бинокль твёрдо")
            reasons.append(f"пара {comfort}: {target.size_arcmin * 60:.0f}″ "
                           f"при {binocular.magnification:g}× выглядят как "
                           f"{apparent:.1f}′")
        else:
            points -= 10.0
            warnings.append(f"для разделения нужно увеличение около "
                            f"{EYE_RESOLUTION_ARCMIN / max(target.size_arcmin, 1e-6):.0f}×")

    if target.note:
        reasons.append(target.note)
    return points, reasons, warnings


def stars_for(score: int) -> int:
    for threshold, count in STAR_THRESHOLDS:
        if score >= threshold:
            return count
    return 1


# ---------------------------------------------------------------- оценка цели

def evaluate(target: Target, observer: ObserverProfile,
             binocular: BinocularProfile, horizon, landscape,
             when: dt.datetime, start: dt.datetime, end: dt.datetime,
             moon: astro.MoonState | None = None,
             context: dict | None = None, scan=None) -> Recommendation:
    """Оценить одну цель. Возвращает готовую рекомендацию с объяснением."""
    context = dict(context or {})
    moon = moon or astro.moon_state(observer, when)
    context.setdefault("moon_illumination", moon.illumination)

    visibility = horizon_service.analyse(observer, target, horizon, when,
                                         start, end, landscape=landscape, scan=scan)
    window = visibility.best_window
    moment = window.best_time if window else when
    altitude = window.max_altitude_deg if window else visibility.altitude_now
    if target.is_solar or scan is None:
        _, azimuth = astro.scan_altaz_at(observer, target, moment)
    else:
        _, azimuth = scan.clock.altaz_at(target.ra_deg, target.dec_deg, moment)

    separation = None
    if target.kind != MOON:
        try:
            moon_radec = context.get("moon_radec")
            if moon_radec is not None and not target.is_solar:
                separation = astro.separation_from_moon_fixed(target, *moon_radec)
            else:
                separation = astro.separation_from_moon(observer, target, moment)
        except Exception:
            separation = None

    magnitude = target.magnitude
    if target.kind == PLANET:
        from astrocal.magnitudes import planet_magnitude
        try:
            magnitude = planet_magnitude(target.body_key, astro.to_skyfield(moment))
        except Exception:
            pass

    penalty = moon_penalty_mag(moon, separation)
    limiting = binocular.limiting_magnitude(observer.bortle, max(altitude, 1.0), penalty)
    sky = sky_brightness(observer.bortle) - penalty

    scored = Target(**{**target.__dict__, "magnitude": magnitude})

    parts = {}
    reasons, warnings = [], []
    for key, (points, why, warn) in {
        "detect": detectability_points(scored, binocular, limiting, sky),
        "altitude": altitude_points(altitude, visibility.clearance_now),
        "framing": framing_points(scored, binocular),
        "moon": moon_points(scored, moon, separation),
        "duration": duration_points(visibility.total_minutes),
        "type": type_adjustment(scored, binocular, context),
    }.items():
        parts[key] = round(float(points), 1)
        reasons.extend(why)
        warnings.extend(warn)

    total = int(round(float(np.clip(sum(parts.values()), 0.0, 100.0))))
    if not visibility.windows:
        total = 0

    return Recommendation(
        target=scored, score=total, stars=stars_for(total),
        altitude_deg=altitude, azimuth_deg=azimuth, magnitude=magnitude,
        limiting_magnitude=limiting, visibility=visibility,
        reasons=reasons, warnings=warnings,
        fits_in_field=binocular.fits_in_field(target.size_arcmin),
        field_fraction=binocular.field_fraction(target.size_arcmin),
        moon_separation_deg=separation, breakdown=parts)


# ---------------------------------------------------------------- «что посмотреть»

def candidate_targets(when: dt.datetime, mag_limit: float = 10.5) -> list[Target]:
    """Кандидаты: Солнечная система плюс каталог, отсечённый по блеску."""
    targets = [t for t in astro.solar_targets(when) if t.kind != SUN]
    for target in catalog_service.catalog():
        if target.magnitude is not None and target.magnitude <= mag_limit:
            targets.append(target)
    return targets


def tonight(observer: ObserverProfile, binocular: BinocularProfile,
            landscape, date: dt.date, horizon=None,
            limit: int = 15, min_score: int = 30,
            progress=None) -> list[Recommendation]:
    """Список объектов ночи с `date` на следующий день, лучшие сверху.

    Отбор идёт в два прохода. Сначала грубый: цель отбрасывается, если за ночь
    она вообще не поднимается над маской участка либо заведомо слабее предела
    прибора — это снимает с расчёта тысячи объектов каталога. Только выжившие
    считаются полностью, с окнами видимости и лунной геометрией.
    """
    horizon = horizon if horizon is not None else horizon_service.profile_for(
        landscape, observer)
    night = astro.night_for(observer, date)
    start = night.start or dt.datetime.combine(date, dt.time(21, 0), tzinfo=observer.tz)
    end = night.end or (start + dt.timedelta(hours=8))
    middle = start + (end - start) / 2
    moon = astro.moon_state(observer, middle)

    rough_limit = binocular.limiting_magnitude(observer.bortle, 45.0, 0.0)
    candidates = [t for t in candidate_targets(middle, mag_limit=rough_limit + 0.5)]

    survivors = _prefilter(observer, candidates, horizon, start, end)

    jupiter_visible = any(t.id == "jupiter" for t in survivors)
    context = {"jupiter_visible": jupiter_visible,
               "moon_radec": astro.moon_radec(observer, middle)}
    scan = horizon_service.ScanGrid.build(observer, start, end)

    results = []
    for index, target in enumerate(survivors):
        if progress is not None:
            progress(index, len(survivors))
        try:
            recommendation = evaluate(target, observer, binocular, horizon,
                                      landscape, middle, start, end,
                                      moon=moon, context=context, scan=scan)
        except Exception:
            continue
        if recommendation.score >= min_score and recommendation.visibility.windows:
            results.append(recommendation)

    results.sort(key=lambda r: (-r.score, r.target.name))
    return _diversify(results, limit)


def _prefilter(observer: ObserverProfile, targets, horizon,
               start: dt.datetime, end: dt.datetime) -> list[Target]:
    """Быстрый отсев по грубой сетке: кто вообще выходит из-за препятствий."""
    grid = astro.time_grid(start, end, 20.0)
    fixed = [t for t in targets if not t.is_solar and t.ra_deg is not None]
    survivors = [t for t in targets if t.is_solar]

    if fixed:
        ra = np.array([t.ra_deg for t in fixed], dtype=float)
        dec = np.array([t.dec_deg for t in fixed], dtype=float)
        alt, az = astro.coarse_altaz_grid(observer, ra, dec, grid)
        # запас в градус: грубая формула и редкая сетка не должны отсекать
        # объект, который на самом деле выходит из-за крыши на несколько минут
        visible = (alt - horizon.altitude_at(az) > -1.0).any(axis=1)
        survivors.extend(t for t, ok in zip(fixed, visible) if ok)
    return survivors


def _diversify(results: list[Recommendation], limit: int) -> list[Recommendation]:
    """Не отдавать пятнадцать шаровых скоплений подряд.

    Внутри одного типа берётся не больше трети списка: наблюдателю нужна
    программа на вечер, а не выборка из каталога по одному признаку.
    """
    if len(results) <= limit:
        return results
    per_kind_cap = max(2, limit // 3)
    picked, counts = [], {}
    for item in results:
        kind = item.target.kind
        if counts.get(kind, 0) >= per_kind_cap:
            continue
        picked.append(item)
        counts[kind] = counts.get(kind, 0) + 1
        if len(picked) >= limit:
            break
    if len(picked) < limit:
        # добор до нужной длины; сравниваем по идентификатору цели, а не сами
        # рекомендации: у них глубокая структура, и `in` сравнивал бы окна
        # видимости поэлементно
        taken = {item.target.id for item in picked}
        for item in results:
            if item.target.id in taken:
                continue
            picked.append(item)
            taken.add(item.target.id)
            if len(picked) >= limit:
                break
    return picked


def explain(recommendation: Recommendation, binocular: BinocularProfile,
            landscape=None, observer: ObserverProfile | None = None) -> list[str]:
    """Развёрнутое «почему это интересно» — из расчёта, без выдумок."""
    lines = [f"{recommendation.target.name}", recommendation.stars_text]
    if recommendation.reasons:
        lines.append("Почему:")
        lines.extend(f"• {reason}" for reason in dict.fromkeys(recommendation.reasons))
    if recommendation.warnings:
        lines.append("Учтите:")
        lines.extend(f"• {warn}" for warn in dict.fromkeys(recommendation.warnings))
    window = recommendation.visibility.best_window
    if window:
        lines.append(f"Лучшее время: {window.start:%H:%M}–{window.end:%H:%M} "
                     f"(максимум {window.max_altitude_deg:.0f}° в "
                     f"{window.best_time:%H:%M})")
    if landscape is not None and observer is not None:
        lines.append(horizon_service.summarise(recommendation.visibility,
                                               landscape, observer))
    return lines


def show_me_something(recommendations: list[Recommendation],
                      seen_ids: set) -> Recommendation | None:
    """Лучший ещё не показанный объект — для кнопки «покажи что-нибудь»."""
    for recommendation in recommendations:
        if recommendation.target.id not in seen_ids:
            return recommendation
    return recommendations[0] if recommendations else None
