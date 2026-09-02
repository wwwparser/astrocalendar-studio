"""Оптический прибор: бинокль, зрительная труба или невооружённый глаз.

Здесь же живёт модель предельной звёздной величины. Она эмпирическая и даёт
оценку, а не гарантию: реальный предел зависит от прозрачности, адаптации глаза
и опыта наблюдателя. Формула собрана из общепринятых наблюдательских правил и
задокументирована в :func:`limiting_magnitude`, чтобы её можно было проверить и
поправить, а не угадывать.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields

# Диаметр адаптированного к темноте зрачка. 7 мм — учебное значение для молодого
# глаза; на практике у большинства взрослых 6 мм, и именно оно определяет, какая
# часть светового пучка бинокля реально попадает в глаз.
EYE_PUPIL_MM = 6.0

# Невооружённым глазом при разных классах шкалы Бортля.
NELM_BY_BORTLE = {
    1: 7.8, 2: 7.4, 3: 7.0, 4: 6.5, 5: 6.0, 6: 5.5, 7: 5.0, 8: 4.3, 9: 3.8,
}

# Коэффициент атмосферного поглощения, звёздных величин на единицу воздушной массы.
EXTINCTION_PER_AIRMASS = 0.28

ORIENTATION_NORMAL = "NORMAL"
ORIENTATION_INVERTED = "INVERTED"
ORIENTATION_MIRROR = "MIRROR"

ORIENTATION_RU = {
    ORIENTATION_NORMAL: "прямое",
    ORIENTATION_INVERTED: "перевёрнутое",
    ORIENTATION_MIRROR: "зеркальное (диагональ)",
}


@dataclass
class BinocularProfile:
    """Прибор наблюдателя.

    `field_of_view_deg` — истинное поле зрения на небе (то, что пишут на корпусе
    как «6.5°» или пересчитывают из «114 м на 1000 м»).
    """

    name: str = "Бинокль 10×50"
    magnification: float = 10.0
    aperture_mm: float = 50.0
    field_of_view_deg: float = 6.5
    limiting_mag_override: float | None = None
    orientation: str = ORIENTATION_NORMAL

    def __post_init__(self) -> None:
        self.magnification = max(1.0, float(self.magnification))
        self.aperture_mm = max(1.0, float(self.aperture_mm))
        self.field_of_view_deg = max(0.05, min(120.0, float(self.field_of_view_deg)))
        if self.limiting_mag_override is not None:
            self.limiting_mag_override = float(self.limiting_mag_override)
        if self.orientation not in ORIENTATION_RU:
            self.orientation = ORIENTATION_NORMAL

    # ------------------------------------------------------------ оптика

    @property
    def exit_pupil_mm(self) -> float:
        return self.aperture_mm / self.magnification

    @property
    def apparent_field_deg(self) -> float:
        """Видимое поле — то, каким поле выглядит в окуляре."""
        return self.field_of_view_deg * self.magnification

    @property
    def effective_aperture_mm(self) -> float:
        """Апертура, свет которой реально доходит до сетчатки.

        Если выходной зрачок больше зрачка глаза, лишний свет упирается в радужку
        и в работе не участвует: бинокль 7×50 в городе работает как 7×42.
        """
        return min(self.aperture_mm, self.magnification * EYE_PUPIL_MM)

    @property
    def is_naked_eye(self) -> bool:
        return self.magnification <= 1.0

    @property
    def short_label(self) -> str:
        if self.is_naked_eye:
            return "глаз"
        return f"{self.magnification:g}×{self.aperture_mm:g}"

    # ------------------------------------------------------------ предел блеска

    def limiting_magnitude(self, bortle: int = 4, altitude_deg: float = 60.0,
                           moon_penalty: float = 0.0) -> float:
        """Ожидаемая предельная величина точечного источника.

        Складывается из четырёх слагаемых:

        1. *Небо.* Предел невооружённого глаза по классу Бортля
           (:data:`NELM_BY_BORTLE`).
        2. *Апертура.* ``5·lg(D_эфф / D_зрачка)`` — во сколько раз больше света
           собирает объектив по сравнению с глазом. Для глаза слагаемое равно нулю.
        3. *Увеличение.* ``1.4·lg(Γ)`` — увеличение растягивает фон неба, а
           звезда остаётся точкой, поэтому контраст растёт. Коэффициент подобран
           так, чтобы 10× давал около +1.4m, что соответствует практике.
        4. *Высота и Луна.* Поглощение в атмосфере ``k·(X − 1)`` по воздушной
           массе X и отдельный штраф за подсветку Луной.

        Ручное значение ``limiting_mag_override`` перекрывает пункты 1–3, но
        высота и Луна вычитаются и из него: они меняются в течение ночи.
        """
        if self.limiting_mag_override is not None:
            base = self.limiting_mag_override
        else:
            sky = NELM_BY_BORTLE.get(int(bortle), 6.0)
            aperture_gain = 0.0
            magnification_gain = 0.0
            if not self.is_naked_eye:
                aperture_gain = 5.0 * math.log10(
                    max(self.effective_aperture_mm, EYE_PUPIL_MM) / EYE_PUPIL_MM)
                magnification_gain = 1.4 * math.log10(self.magnification)
            base = sky + aperture_gain + magnification_gain

        return base - self.extinction_mag(altitude_deg) - max(0.0, moon_penalty)

    @staticmethod
    def airmass(altitude_deg: float) -> float:
        """Воздушная масса по Пиквертону–Пёрселлу; у горизонта не уходит в бесконечность."""
        h = max(-2.0, min(90.0, float(altitude_deg)))
        z = 90.0 - h
        denominator = math.cos(math.radians(z)) + 0.50572 * (6.07995 + h) ** -1.6364
        if denominator <= 0.0:
            return 40.0
        return min(40.0, 1.0 / denominator)

    def extinction_mag(self, altitude_deg: float) -> float:
        return EXTINCTION_PER_AIRMASS * (self.airmass(altitude_deg) - 1.0)

    # ------------------------------------------------------------ поле зрения

    def fits_in_field(self, size_arcmin: float | None) -> bool | None:
        """Помещается ли объект целиком в поле. None — размер неизвестен."""
        if size_arcmin is None or size_arcmin <= 0:
            return None
        return size_arcmin / 60.0 <= self.field_of_view_deg

    def field_fraction(self, size_arcmin: float | None) -> float | None:
        """Какую долю диаметра поля занимает объект."""
        if size_arcmin is None or size_arcmin <= 0:
            return None
        return (size_arcmin / 60.0) / self.field_of_view_deg

    # ------------------------------------------------------------ сериализация

    def to_dict(self) -> dict:
        return {
            "name": self.name, "magnification": self.magnification,
            "aperture_mm": self.aperture_mm,
            "field_of_view_deg": self.field_of_view_deg,
            "limiting_mag_override": self.limiting_mag_override,
            "orientation": self.orientation,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "BinocularProfile":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})

    def describe(self) -> str:
        if self.is_naked_eye:
            return f"{self.name}: поле {self.field_of_view_deg:g}°"
        return (f"{self.name}: {self.short_label}, поле {self.field_of_view_deg:g}°, "
                f"выходной зрачок {self.exit_pupil_mm:.1f} мм")


def default_binoculars() -> list[BinocularProfile]:
    """Набор приборов по умолчанию: типовые бинокли плюс невооружённый глаз."""
    return [
        BinocularProfile("Бинокль 10×50", 10.0, 50.0, 6.5),
        BinocularProfile("Бинокль 12×50", 12.0, 50.0, 5.5),
        BinocularProfile("Бинокль 15×70", 15.0, 70.0, 4.4),
        BinocularProfile("Невооружённый глаз", 1.0, EYE_PUPIL_MM, 60.0),
    ]
