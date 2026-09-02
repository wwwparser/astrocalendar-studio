"""Каталог целей: что вообще можно предложить наблюдателю с биноклем.

Основа — OpenNGC из ядра `astrocal`. Она закрывает почти весь Мессье и тысячи
NGC/IC, но не всё: Плеяды, Гиады, Вешалка и другие крупные близкие скопления в
NGC не входят, а именно они — лучшие объекты для бинокля. Поэтому к каталогу
добавляется небольшая курируемая таблица: объекты, которых в OpenNGC нет,
двойные звёзды и астеризмы, а также русские имена и алиасы для поиска.

Курируемая таблица дополняет каталог, а не заменяет его: список из двадцати
объектов не может быть единственным источником рекомендаций.
"""
from __future__ import annotations

from functools import lru_cache

from ..models.target import (ASTERISM, DOUBLE_STAR, GALAXY, GLOBULAR_CLUSTER,
                             NGC_TYPE_TO_KIND, OPEN_CLUSTER, Target)

# Объекты, которых нет в OpenNGC, плюс лучшие бинокулярные двойные и астеризмы.
# Координаты — J2000, размеры в угловых минутах.
EXTRA_TARGETS = [
    dict(id="M45", name="M45 — Плеяды", kind=OPEN_CLUSTER,
         ra_deg=56.75, dec_deg=24.1167, magnitude=1.6, major_arcmin=110.0,
         constellation="Tau",
         aliases=("Плеяды", "Pleiades", "Стожары", "Melotte 22", "Mel 22", "Семь сестёр"),
         note="Десятки ярких звёзд, целиком помещается в поле бинокля.",
         distance_text="≈ 444 св. года"),
    dict(id="Mel25", name="Гиады", kind=OPEN_CLUSTER,
         ra_deg=66.75, dec_deg=15.8667, magnitude=0.5, major_arcmin=330.0,
         constellation="Tau",
         aliases=("Hyades", "Гиады", "Melotte 25", "Mel 25", "Caldwell 41"),
         note="Ближайшее рассеянное скопление; шире поля бинокля, но эффектно.",
         distance_text="≈ 153 св. года"),
    dict(id="Cr399", name="Вешалка (Collinder 399)", kind=ASTERISM,
         ra_deg=286.35, dec_deg=20.1833, magnitude=3.6, major_arcmin=60.0,
         constellation="Vul",
         aliases=("Coathanger", "Вешалка", "Collinder 399", "Cr 399",
                  "Brocchi", "Скопление Брокки"),
         note="Классический бинокулярный астеризм: перекладина и крючок.",
         distance_text="≈ 730 св. лет"),
    dict(id="Mel20", name="Скопление α Персея", kind=OPEN_CLUSTER,
         ra_deg=51.0, dec_deg=49.8667, magnitude=1.2, major_arcmin=300.0,
         constellation="Per",
         aliases=("Melotte 20", "Mel 20", "Alpha Persei Cluster", "Мирфак",
                  "скопление альфы Персея"),
         note="Россыпь ярких звёзд вокруг Мирфака, объект именно для бинокля.",
         distance_text="≈ 560 св. лет"),
    dict(id="Mel111", name="Скопление Волос Вероники", kind=OPEN_CLUSTER,
         ra_deg=186.0, dec_deg=25.85, magnitude=1.8, major_arcmin=275.0,
         constellation="Com",
         aliases=("Melotte 111", "Mel 111", "Coma Star Cluster",
                  "Волосы Вероники"),
         note="Разреженная группа звёзд 5–6m, красива в широком поле.",
         distance_text="≈ 280 св. лет"),
    dict(id="Kemble", name="Каскад Кембла", kind=ASTERISM,
         ra_deg=59.25, dec_deg=63.05, magnitude=4.0, major_arcmin=150.0,
         constellation="Cam",
         aliases=("Kemble's Cascade", "Каскад Кембла", "Kemble 1"),
         note="Цепочка звёзд длиной около 2.5°, видна только в широкое поле.",
         distance_text="—"),
    dict(id="MizarAlcor", name="Мицар и Алькор", kind=DOUBLE_STAR,
         ra_deg=200.9815, dec_deg=54.9254, magnitude=2.2, major_arcmin=11.8,
         constellation="UMa",
         aliases=("Mizar", "Alcor", "Мицар", "Алькор", "ζ UMa", "zeta UMa"),
         note="Пара 2.2m и 4.0m в 12′ — разделяется даже слабым биноклем.",
         distance_text="≈ 83 св. года"),
    dict(id="AlphaCap", name="α Козерога (Альгеди)", kind=DOUBLE_STAR,
         ra_deg=304.5137, dec_deg=-12.5449, magnitude=3.6, major_arcmin=6.3,
         constellation="Cap",
         aliases=("Algedi", "Альгеди", "alpha Cap", "α Cap", "α1/α2 Козерога"),
         note="Оптическая пара 3.6m и 4.3m в 6′ — лёгкая цель для бинокля.",
         distance_text="≈ 109 и 690 св. лет"),
    dict(id="NuDra", name="ν Дракона (Кума)", kind=DOUBLE_STAR,
         ra_deg=263.0543, dec_deg=55.1853, magnitude=4.9, major_arcmin=1.03,
         constellation="Dra",
         aliases=("Kuma", "Кума", "nu Dra", "ν Dra", "ню Дракона"),
         note="Две одинаковые звёзды 4.9m в 62″ — «фары» в поле бинокля.",
         distance_text="≈ 100 св. лет"),
    dict(id="Albireo", name="Альбирео (β Лебедя)", kind=DOUBLE_STAR,
         ra_deg=292.6804, dec_deg=27.9597, magnitude=3.1, major_arcmin=0.58,
         constellation="Cyg",
         aliases=("Albireo", "Альбирео", "beta Cyg", "β Cyg", "бета Лебедя"),
         note="Золотая и голубая звёзды в 35″: в 10× разделяются на пределе, уверенно — от 15×.",
         distance_text="≈ 430 св. лет"),
    dict(id="M40", name="M40 — пара Виннеке 4", kind=DOUBLE_STAR,
         ra_deg=185.5521, dec_deg=58.0828, magnitude=9.0, major_arcmin=0.8,
         constellation="UMa",
         aliases=("Winnecke 4", "Виннеке 4", "M 40"),
         note="Ошибка Мессье: не туманность, а пара звёзд 9m.",
         distance_text="—"),
]

# Русские имена и дополнительные алиасы для объектов, которые уже есть в OpenNGC.
NAMES_RU = {
    "M1": ("Крабовидная туманность", ("Crab Nebula", "Краб")),
    "M2": ("M2 — шаровое скопление в Водолее", ()),
    "M3": ("M3 — шаровое скопление в Гончих Псах", ()),
    "M4": ("M4 — шаровое скопление у Антареса", ()),
    "M5": ("M5 — шаровое скопление в Змее", ()),
    "M6": ("Скопление Бабочка", ("Butterfly Cluster", "Бабочка")),
    "M7": ("Скопление Птолемея", ("Ptolemy Cluster", "скопление Птолемея")),
    "M8": ("Туманность Лагуна", ("Lagoon Nebula", "Лагуна")),
    "M11": ("Скопление Дикая Утка", ("Wild Duck Cluster", "Дикая утка")),
    "M13": ("M13 — Большое скопление в Геркулесе", ("Hercules Cluster", "Геркулес")),
    "M15": ("M15 — шаровое скопление в Пегасе", ()),
    "M16": ("Туманность Орёл", ("Eagle Nebula", "Орёл")),
    "M17": ("Туманность Омега", ("Omega Nebula", "Омега", "Лебедь")),
    "M20": ("Тройная туманность", ("Trifid Nebula", "Трёхраздельная")),
    "M22": ("M22 — шаровое скопление в Стрельце", ()),
    "M24": ("Звёздное облако Стрельца", ("Sagittarius Star Cloud",)),
    "M27": ("Туманность Гантель", ("Dumbbell Nebula", "Гантель")),
    "M31": ("M31 — Галактика Андромеды", ("Andromeda", "Андромеда",
                                           "туманность Андромеды")),
    "M32": ("M32 — спутник Андромеды", ()),
    "M33": ("M33 — Галактика Треугольника", ("Triangulum Galaxy", "Треугольник")),
    "M34": ("M34 — рассеянное скопление в Персее", ()),
    "M35": ("M35 — рассеянное скопление в Близнецах", ()),
    "M36": ("M36 — рассеянное скопление в Возничем", ()),
    "M37": ("M37 — рассеянное скопление в Возничем", ()),
    "M38": ("M38 — рассеянное скопление в Возничем", ()),
    "M39": ("M39 — рассеянное скопление в Лебеде", ()),
    "M41": ("M41 — скопление под Сириусом", ()),
    "M42": ("M42 — Туманность Ориона", ("Orion Nebula", "Орион",
                                         "туманность Ориона")),
    "M43": ("M43 — туманность де Мерана", ()),
    "M44": ("M44 — Ясли", ("Beehive", "Praesepe", "Ясли", "Улей")),
    "M46": ("M46 — рассеянное скопление в Корме", ()),
    "M47": ("M47 — рассеянное скопление в Корме", ()),
    "M48": ("M48 — рассеянное скопление в Гидре", ()),
    "M50": ("M50 — рассеянное скопление в Единороге", ()),
    "M51": ("Водоворот", ("Whirlpool Galaxy", "Водоворот")),
    "M52": ("M52 — рассеянное скопление в Кассиопее", ()),
    "M57": ("Кольцо", ("Ring Nebula", "Кольцо", "туманность Кольцо")),
    "M63": ("Подсолнух", ("Sunflower Galaxy", "Подсолнух")),
    "M64": ("Чёрный Глаз", ("Black Eye Galaxy", "Чёрный глаз")),
    "M65": ("M65 — галактика в Льве", ()),
    "M66": ("M66 — галактика в Льве", ()),
    "M67": ("M67 — старое скопление в Раке", ()),
    "M78": ("M78 — отражательная туманность в Орионе", ()),
    "M81": ("Галактика Боде", ("Bode's Galaxy", "Боде")),
    "M82": ("Сигара", ("Cigar Galaxy", "Сигара")),
    "M92": ("M92 — шаровое скопление в Геркулесе", ()),
    "M93": ("M93 — рассеянное скопление в Корме", ()),
    "M94": ("M94 — галактика в Гончих Псах", ()),
    "M101": ("Вертушка", ("Pinwheel Galaxy", "Вертушка")),
    "M103": ("M103 — рассеянное скопление в Кассиопее", ()),
    "M104": ("Сомбреро", ("Sombrero Galaxy", "Сомбреро")),
    "M106": ("M106 — галактика в Гончих Псах", ()),
    "M110": ("M110 — спутник Андромеды", ()),
    "NGC869": ("Двойное скопление h Персея", ("Double Cluster", "Двойное скопление",
                                               "h Persei", "h и χ Персея", "h Per")),
    "NGC884": ("Двойное скопление χ Персея", ("Double Cluster", "chi Persei",
                                               "χ Persei", "chi Per")),
    "NGC752": ("NGC 752 — рассеянное скопление в Андромеде", ()),
    "NGC457": ("Скопление Сова", ("Owl Cluster", "Сова", "ET Cluster")),
    "NGC7000": ("Северная Америка", ("North America Nebula", "Северная Америка")),
    "NGC6960": ("Вуаль (западная часть)", ("Veil Nebula", "Вуаль")),
    "NGC6992": ("Вуаль (восточная часть)", ("Veil Nebula", "Вуаль")),
    "IC4665": ("IC 4665 — рассеянное скопление в Змееносце", ()),
    "NGC2264": ("Скопление Рождественская Ёлка", ("Christmas Tree Cluster", "Ёлка")),
    "NGC253": ("Галактика Скульптора", ("Sculptor Galaxy", "Скульптор")),
    "NGC5139": ("Омега Центавра", ("Omega Centauri", "Омега Центавра")),
    "NGC7789": ("Роза Каролины", ("Caroline's Rose", "Роза Каролины")),
    "NGC6231": ("NGC 6231 — скопление в Скорпионе", ()),
    "IC2391": ("IC 2391 — скопление в Парусах", ()),
    "IC2602": ("Южные Плеяды", ("Southern Pleiades", "Южные Плеяды")),
}

# Ярче этого предела объект вообще не рассматривается как цель для бинокля:
# даже в 15×70 на тёмном небе диффузный объект слабее 11m — это пятно на пределе
# восприятия, и рекомендовать его как «посмотрите сегодня» нечестно.
CATALOG_MAG_LIMIT = 11.0

# Слишком мелкие объекты в бинокль неотличимы от звезды. Планетарные туманности
# оставляем и мелкими: их выдаёт цвет и «нерезкость».
MIN_SIZE_ARCMIN = 2.0


def _clean_name(row) -> str:
    """Читаемое имя: Мессье, собственное имя или обозначение каталога."""
    designation = _designation(row)
    override = NAMES_RU.get(designation)
    if override:
        return override[0]
    common = (row.common or "").split(",")[0].strip()
    if row.messier and common:
        return f"{row.messier} — {common}"
    if row.messier:
        return f"{row.messier} — {row.type_ru}"
    if common:
        return common
    return _pretty_ngc(row.Name)


def _designation(row) -> str:
    """Ключ для таблицы русских имён: 'M31' либо 'NGC869' без ведущих нулей."""
    return row.messier or _pretty_ngc(row.Name).replace(" ", "")


_NGC_NAME = __import__("re").compile(r"^(NGC|IC)(\d+)(.*)$")


def _pretty_ngc(name: str) -> str:
    """'NGC0224' → 'NGC 224'. Суффиксы OpenNGC вида 'NGC4656 NED01' сохраняются."""
    match = _NGC_NAME.match(name or "")
    if not match:
        return name
    prefix, digits, suffix = match.groups()
    return f"{prefix} {int(digits)}{suffix}"


def _aliases(row) -> tuple[str, ...]:
    designation = _designation(row)
    items = {row.Name, _pretty_ngc(row.Name)}
    if row.messier:
        items.add(row.messier)
        items.add(f"M {row.messier[1:]}")
    for part in (row.common or "").split(","):
        if part.strip():
            items.add(part.strip())
    override = NAMES_RU.get(designation)
    if override:
        items.update(override[1])
    for token in (row.identifiers or "").split(","):
        token = token.strip()
        if token and len(token) <= 14 and not token.startswith("2MASX"):
            items.add(token)
    return tuple(sorted(items))


@lru_cache(maxsize=2)
def catalog(mag_limit: float = CATALOG_MAG_LIMIT) -> tuple[Target, ...]:
    """Все цели каталога: OpenNGC плюс курируемые дополнения."""
    from astrocal.catalogs import deep_sky_extended

    frame = deep_sky_extended(mag_limit=mag_limit)
    targets: list[Target] = []
    for row in frame.itertuples(index=False):
        kind = NGC_TYPE_TO_KIND.get(row.Type)
        if kind is None:
            continue
        size = None if row.major_arcmin != row.major_arcmin else float(row.major_arcmin)
        if kind in (OPEN_CLUSTER, GLOBULAR_CLUSTER, GALAXY) and (size or 0.0) < MIN_SIZE_ARCMIN:
            continue
        minor = None if row.minor_arcmin != row.minor_arcmin else float(row.minor_arcmin)
        surface = (None if row.surface_brightness != row.surface_brightness
                   else float(row.surface_brightness))
        targets.append(Target(
            id=row.Name, name=_clean_name(row), kind=kind,
            ra_deg=float(row.ra_degrees), dec_deg=float(row.dec_degrees),
            magnitude=float(row.mag), major_arcmin=size, minor_arcmin=minor,
            surface_brightness=surface, constellation=row.Const,
            aliases=_aliases(row)))

    known = {t.id for t in targets}
    for extra in EXTRA_TARGETS:
        if extra["id"] in known:
            continue
        targets.append(Target(**extra))
    return tuple(targets)


@lru_cache(maxsize=2)
def by_id(mag_limit: float = CATALOG_MAG_LIMIT) -> dict[str, Target]:
    return {t.id: t for t in catalog(mag_limit)}


@lru_cache(maxsize=2)
def _index(mag_limit: float = CATALOG_MAG_LIMIT) -> dict[str, str]:
    """Ключ поиска → id цели."""
    index: dict[str, str] = {}
    for target in catalog(mag_limit):
        for key in target.search_keys():
            index.setdefault(key, target.id)
            index.setdefault(key.replace(" ", ""), target.id)
    return index


def normalise(query: str) -> str:
    return (query or "").strip().lower().replace("ё", "е")


def find(query: str, mag_limit: float = CATALOG_MAG_LIMIT) -> Target | None:
    """Точный поиск по имени или алиасу («M31», «Андромеда», «ngc 869»)."""
    key = normalise(query)
    if not key:
        return None
    index = _index(mag_limit)
    target_id = index.get(key) or index.get(key.replace(" ", ""))
    return by_id(mag_limit).get(target_id) if target_id else None


def search(query: str, limit: int = 20,
           mag_limit: float = CATALOG_MAG_LIMIT) -> list[Target]:
    """Подсказки поиска: точное совпадение, затем начало, затем вхождение."""
    key = normalise(query)
    if not key:
        return []
    exact, prefix, inside = [], [], []
    for target in catalog(mag_limit):
        keys = target.search_keys()
        if key in keys:
            exact.append(target)
        elif any(k.startswith(key) for k in keys):
            prefix.append(target)
        elif any(key in k for k in keys):
            inside.append(target)
    ranked = exact + prefix + inside
    return ranked[:limit]
