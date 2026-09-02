"""Фигуры созвездий: пары HIP-номеров, соединённые линиями.

Раньше загрузка жила внутри `render/skymap.py` и тянула за собой matplotlib.
Данные нужны обоим приложениям — и календарной карте, и трёхмерному небу
Binocular Sky, — поэтому вынесены в ядро. `render.skymap` реэкспортирует
`constellation_lines`, так что старый код продолжает работать.
"""
from __future__ import annotations

from functools import lru_cache

from . import config as cfg

CONSTELLATION_FILE = cfg.CACHE / "constellationship.fab"
CONSTELLATION_URL = ("https://raw.githubusercontent.com/Stellarium/stellarium/"
                     "v0.21.3/skycultures/western/constellationship.fab")

# Латинские сокращения → русские названия. Используются и картой, и 3D-небом.
NAMES_RU = {
    "And": "Андромеда", "Ant": "Насос", "Aps": "Райская Птица", "Aql": "Орёл",
    "Aqr": "Водолей", "Ara": "Жертвенник", "Ari": "Овен", "Aur": "Возничий",
    "Boo": "Волопас", "Cae": "Резец", "Cam": "Жираф", "Cnc": "Рак",
    "CVn": "Гончие Псы", "CMa": "Большой Пёс", "CMi": "Малый Пёс",
    "Cap": "Козерог", "Car": "Киль", "Cas": "Кассиопея", "Cen": "Центавр",
    "Cep": "Цефей", "Cet": "Кит", "Cha": "Хамелеон", "Cir": "Циркуль",
    "Col": "Голубь", "Com": "Волосы Вероники", "CrA": "Южная Корона",
    "CrB": "Северная Корона", "Crv": "Ворон", "Crt": "Чаша", "Cru": "Южный Крест",
    "Cyg": "Лебедь", "Del": "Дельфин", "Dor": "Золотая Рыба", "Dra": "Дракон",
    "Equ": "Малый Конь", "Eri": "Эридан", "For": "Печь", "Gem": "Близнецы",
    "Gru": "Журавль", "Her": "Геркулес", "Hor": "Часы", "Hya": "Гидра",
    "Hyi": "Южная Гидра", "Ind": "Индеец", "Lac": "Ящерица", "Leo": "Лев",
    "LMi": "Малый Лев", "Lep": "Заяц", "Lib": "Весы", "Lup": "Волк",
    "Lyn": "Рысь", "Lyr": "Лира", "Men": "Столовая Гора", "Mic": "Микроскоп",
    "Mon": "Единорог", "Mus": "Муха", "Nor": "Наугольник", "Oct": "Октант",
    "Oph": "Змееносец", "Ori": "Орион", "Pav": "Павлин", "Peg": "Пегас",
    "Per": "Персей", "Phe": "Феникс", "Pic": "Живописец", "Psc": "Рыбы",
    "PsA": "Южная Рыба", "Pup": "Корма", "Pyx": "Компас", "Ret": "Сетка",
    "Sge": "Стрела", "Sgr": "Стрелец", "Sco": "Скорпион", "Scl": "Скульптор",
    "Sct": "Щит", "Ser": "Змея", "Sex": "Секстант", "Tau": "Телец",
    "Tel": "Телескоп", "Tri": "Треугольник", "TrA": "Южный Треугольник",
    "Tuc": "Тукан", "UMa": "Большая Медведица", "UMi": "Малая Медведица",
    "Vel": "Паруса", "Vir": "Дева", "Vol": "Летучая Рыба", "Vul": "Лисичка",
}


@lru_cache(maxsize=1)
def constellation_lines():
    """Пары HIP-номеров, соединённые линиями созвездий.

    Пустой кортеж, если файла нет и скачать его не удалось: карта и 3D-небо
    должны работать офлайн даже без фигур.
    """
    from skyfield.data import stellarium

    if not CONSTELLATION_FILE.exists():
        try:
            import requests
            response = requests.get(CONSTELLATION_URL, timeout=60)
            response.raise_for_status()
            CONSTELLATION_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONSTELLATION_FILE.write_bytes(response.content)
        except Exception:
            return ()
    try:
        with CONSTELLATION_FILE.open("rb") as handle:
            return tuple(stellarium.parse_constellations(handle))
    except Exception:
        return ()


def name_ru(abbrev: str) -> str:
    return NAMES_RU.get(abbrev, abbrev)
