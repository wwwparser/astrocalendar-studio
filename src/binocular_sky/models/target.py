"""Наблюдаемая цель: всё, на что можно навести бинокль.

Модель одна для Луны, Юпитера, шарового скопления и Мицара — иначе рейтинг,
поиск и панель «сегодня» пришлось бы писать по разу на каждый тип. Различия
типов живут в поле `kind` и учитываются рейтингом, а не в структуре данных.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

SUN = "SUN"
MOON = "MOON"
PLANET = "PLANET"
JUPITER_MOON = "JUPITER_MOON"
COMET = "COMET"
ASTEROID = "ASTEROID"
OPEN_CLUSTER = "OPEN_CLUSTER"
GLOBULAR_CLUSTER = "GLOBULAR_CLUSTER"
NEBULA = "NEBULA"
PLANETARY_NEBULA = "PLANETARY_NEBULA"
GALAXY = "GALAXY"
DOUBLE_STAR = "DOUBLE_STAR"
ASTERISM = "ASTERISM"
STAR = "STAR"

KIND_RU = {
    SUN: "Солнце", MOON: "Луна", PLANET: "планета",
    JUPITER_MOON: "спутник Юпитера", COMET: "комета", ASTEROID: "астероид",
    OPEN_CLUSTER: "рассеянное скопление", GLOBULAR_CLUSTER: "шаровое скопление",
    NEBULA: "туманность", PLANETARY_NEBULA: "планетарная туманность",
    GALAXY: "галактика", DOUBLE_STAR: "двойная звезда",
    ASTERISM: "астеризм", STAR: "звезда",
}

# Протяжённые объекты, для которых важны размер и поверхностная яркость.
EXTENDED_KINDS = {OPEN_CLUSTER, GLOBULAR_CLUSTER, NEBULA, PLANETARY_NEBULA,
                  GALAXY, ASTERISM}

# Объекты Солнечной системы: координаты считаются по эфемеридам, а не из каталога.
SOLAR_KINDS = {SUN, MOON, PLANET, JUPITER_MOON, COMET, ASTEROID}

NGC_TYPE_TO_KIND = {
    "OCl": OPEN_CLUSTER, "GCl": GLOBULAR_CLUSTER, "Cl+N": OPEN_CLUSTER,
    "G": GALAXY, "GPair": GALAXY, "GTrpl": GALAXY, "GGroup": GALAXY,
    "PN": PLANETARY_NEBULA, "EmN": NEBULA, "Neb": NEBULA, "RfN": NEBULA,
    "SNR": NEBULA, "HII": NEBULA, "DrkN": NEBULA,
    # одиночная звезда (`*`) в каталог целей не попадает: как объект для
    # бинокля она ничего не даёт, а обозначения OpenNGC вида "gam Cyg"
    # засоряют список рекомендаций
    "**": DOUBLE_STAR, "*Ass": ASTERISM,
}


@dataclass
class Target:
    """Цель наблюдения.

    Для объектов Солнечной системы `ra_deg`/`dec_deg` не заполняются: их считает
    астрономический сервис на нужный момент. Для всего остального координаты
    фиксированы (собственным движением за время жизни программы можно пренебречь).
    """

    id: str
    name: str                                  # основное имя в интерфейсе
    kind: str = GALAXY
    ra_deg: float | None = None
    dec_deg: float | None = None
    magnitude: float | None = None
    major_arcmin: float | None = None
    minor_arcmin: float | None = None
    surface_brightness: float | None = None    # mag/кв.угл.сек
    constellation: str = ""
    aliases: tuple = field(default_factory=tuple)
    note: str = ""                             # чем интересен именно в бинокль
    body_key: str = ""                         # ключ эфемериды для тел Солнечной системы
    distance_text: str = ""

    @property
    def kind_ru(self) -> str:
        return KIND_RU.get(self.kind, "объект")

    @property
    def is_solar(self) -> bool:
        return self.kind in SOLAR_KINDS

    @property
    def is_extended(self) -> bool:
        return self.kind in EXTENDED_KINDS

    @property
    def size_arcmin(self) -> float | None:
        """Больший угловой размер, угловые минуты."""
        return self.major_arcmin

    def effective_surface_brightness(self) -> float | None:
        """Поверхностная яркость: из каталога либо оценка по блеску и размеру.

        Оценка ``μ = m + 2.5·lg(площадь в кв. угловых секундах)`` — стандартное
        приближение: считаем, что весь свет объекта равномерно размазан по его
        видимому эллипсу. Для скоплений это заведомо грубо (свет собран в
        отдельных звёздах), поэтому рейтинг применяет её только к диффузным типам.
        """
        if self.surface_brightness is not None:
            return float(self.surface_brightness)
        if self.magnitude is None or not self.major_arcmin:
            return None
        major = self.major_arcmin * 60.0
        minor = (self.minor_arcmin or self.major_arcmin) * 60.0
        area = math.pi * (major / 2.0) * (minor / 2.0)
        if area <= 0:
            return None
        return float(self.magnitude) + 2.5 * math.log10(area)

    def search_keys(self) -> tuple[str, ...]:
        keys = [self.id, self.name, *self.aliases]
        return tuple(k.lower().replace("ё", "е") for k in keys if k)
