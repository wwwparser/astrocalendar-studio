"""Каталоги для кросс-матча: яркие звёзды Hipparcos и объекты OpenNGC."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
import requests

from . import config as cfg

HIP_RAW = cfg.CACHE / "hip_main.dat"
HIP_PARQUET = cfg.CACHE / "hip_bright.parquet"
NGC_CSV = cfg.CACHE / "NGC.csv"
NGC_URL = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv"

# Собственные имена ярких звёзд по-русски. Каждый HIP сверен с каталогом
# Hipparcos по блеску и созвездию (см. tests/test_catalogs.py).
STAR_NAMES_RU = {
    677: "Альферац", 746: "Каф", 1067: "Альгениб", 3179: "Шедар", 3419: "Дифда",
    5447: "Мирах", 6686: "Рукбах", 7588: "Ахернар", 9487: "Альриша",
    9640: "Альмак", 9884: "Хамаль", 10826: "Мира", 11767: "Полярная",
    14135: "Менкар", 14576: "Алголь", 15863: "Мирфак", 17702: "Альциона",
    21421: "Альдебаран", 24436: "Ригель", 24608: "Капелла", 25336: "Беллатрикс",
    25428: "Эльнат", 25930: "Минтака", 26311: "Альнилам", 26727: "Альнитак",
    27366: "Саиф", 27989: "Бетельгейзе", 30324: "Мирцам", 30438: "Канопус",
    31681: "Альхена", 32349: "Сириус", 33579: "Адара", 34444: "Везен",
    35904: "Алудра", 36188: "Гомейза", 36850: "Кастор", 37279: "Процион",
    37826: "Поллукс", 46390: "Альфард", 49669: "Регул", 50583: "Альгиеба",
    53910: "Мерак", 54061: "Дубхе", 54872: "Зосма", 57632: "Денебола",
    58001: "Фекда", 59774: "Мегрец", 62956: "Алиот", 63125: "Сердце Карла",
    65378: "Мицар", 65474: "Спика", 67301: "Алькаид", 68702: "Хадар",
    68933: "Менкент", 69673: "Арктур", 71683: "Альфа Центавра", 72105: "Ицар",
    72607: "Кохаб", 73555: "Неккар", 74785: "Зубенешамали", 76267: "Альфекка",
    78820: "Акраб", 80763: "Антарес", 81693: "Корнефорос", 84012: "Сабик",
    84345: "Рас-Альгети", 85927: "Шаула", 86032: "Рас-Альхаге", 87833: "Этамин",
    90185: "Каус Аустралис", 91262: "Вега", 92420: "Шелиак", 92855: "Нунки",
    93194: "Сулафат", 95947: "Альбирео", 97278: "Таразед", 97649: "Альтаир",
    98036: "Альшаин", 100453: "Садр", 100751: "Павлин", 102098: "Денеб",
    102488: "Дженах", 105199: "Альдерамин", 107315: "Эниф", 109268: "Альнаир",
    113368: "Фомальгаут", 113881: "Шеат", 113963: "Маркаб",
}


@lru_cache(maxsize=1)
def bright_stars(mag_limit: float = None) -> pd.DataFrame:
    """Hipparcos, ярче mag_limit. Колонки: hip, magnitude, ra_degrees, dec_degrees."""
    limit = cfg.STAR_MAG_LIMIT if mag_limit is None else mag_limit
    if HIP_PARQUET.exists():
        df = pd.read_parquet(HIP_PARQUET)
    else:
        from skyfield.api import load
        from skyfield.data import hipparcos
        src = HIP_RAW.open("rb") if HIP_RAW.exists() else load.open(hipparcos.URL)
        with src as f:
            df = hipparcos.load_dataframe(f)
        df = df[df.magnitude <= 8.0]
        df.to_parquet(HIP_PARQUET)
    df = df[df.magnitude <= limit].copy()
    # у части записей Hipparcos нет астрометрии — без координат они бесполезны
    df = df.dropna(subset=["ra_degrees", "dec_degrees", "magnitude"])
    df["hip"] = df.index
    return df.reset_index(drop=True)


def _hms_to_deg(value: str) -> float:
    h, m, s = (float(x) for x in value.split(":"))
    return (h + m / 60.0 + s / 3600.0) * 15.0


def _dms_to_deg(value: str) -> float:
    sign = -1.0 if value.strip().startswith("-") else 1.0
    d, m, s = (float(x) for x in value.strip().lstrip("+-").split(":"))
    return sign * (d + m / 60.0 + s / 3600.0)


TYPE_RU = {
    "G": "галактика", "GPair": "пара галактик", "GTrpl": "тройка галактик",
    "GGroup": "группа галактик", "PN": "планетарная туманность",
    "OCl": "рассеянное скопление", "GCl": "шаровое скопление",
    "Cl+N": "скопление с туманностью", "EmN": "эмиссионная туманность",
    "Neb": "туманность", "RfN": "отражательная туманность",
    "SNR": "остаток сверхновой", "HII": "область HII", "DrkN": "тёмная туманность",
    "*": "звезда", "**": "двойная звезда", "*Ass": "звёздная ассоциация",
    "Dup": "дубликат", "Other": "объект", "NonEx": "несуществующий объект",
}


TYPE_RU_GEN = {
    "галактика": "галактики", "пара галактик": "пары галактик",
    "тройка галактик": "тройки галактик", "группа галактик": "группы галактик",
    "планетарная туманность": "планетарной туманности",
    "рассеянное скопление": "рассеянного скопления",
    "шаровое скопление": "шарового скопления",
    "скопление с туманностью": "скопления с туманностью",
    "эмиссионная туманность": "эмиссионной туманности",
    "туманность": "туманности", "отражательная туманность": "отражательной туманности",
    "остаток сверхновой": "остатка сверхновой", "область HII": "области HII",
    "тёмная туманность": "тёмной туманности", "звезда": "звезды",
    "двойная звезда": "двойной звезды", "звёздная ассоциация": "звёздной ассоциации",
    "объект": "объекта",
}


@lru_cache(maxsize=1)
def deep_sky(mag_limit: float = None) -> pd.DataFrame:
    """OpenNGC: NGC/IC/Messier ярче mag_limit, с русским типом объекта."""
    limit = cfg.DSO_MAG_LIMIT if mag_limit is None else mag_limit
    if not NGC_CSV.exists():
        r = requests.get(NGC_URL, timeout=120)
        r.raise_for_status()
        NGC_CSV.write_bytes(r.content)
    df = pd.read_csv(NGC_CSV, sep=";", low_memory=False)
    df = df[df["Type"].isin(TYPE_RU) & ~df["Type"].isin(["Dup", "NonEx"])]
    df = df.dropna(subset=["RA", "Dec"])
    mag = df["V-Mag"].fillna(df["B-Mag"])
    df = df.assign(mag=mag).dropna(subset=["mag"])
    df = df[df["mag"] <= limit].copy()
    df["ra_degrees"] = df["RA"].map(_hms_to_deg)
    df["dec_degrees"] = df["Dec"].map(_dms_to_deg)
    df["type_ru"] = df["Type"].map(TYPE_RU)
    df["type_gen"] = df["type_ru"].map(TYPE_RU_GEN).fillna(df["type_ru"])
    df["messier"] = df["M"].apply(lambda v: f"M{int(v)}" if pd.notna(v) else None)
    df["common"] = df["Common names"].fillna("")
    return df[["Name", "messier", "common", "type_ru", "type_gen", "mag",
               "ra_degrees", "dec_degrees", "Const"]].reset_index(drop=True)


def angular_distance_deg(ra1, dec1, ra2, dec2):
    """Гаверсинус: расстояние между точками на сфере, градусы. Векторизуется."""
    ra1, dec1, ra2, dec2 = (np.radians(np.asarray(v, dtype=float))
                            for v in (ra1, dec1, ra2, dec2))
    d = np.sin((dec2 - dec1) / 2) ** 2 + \
        np.cos(dec1) * np.cos(dec2) * np.sin((ra2 - ra1) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(d, 0, 1))))
