"""Каталог источников: что это, кто ведёт и что мы оттуда берём.

Список источников есть в README и в провенансе каждого события, но в обоих
случаях он безымянный: «JPL Horizons», «COBS». Человеку, который открыл
календарь и хочет понять, чему верить, этого мало. Здесь у каждого источника
есть три вещи: чем он является, как часто обновляется и что именно мы из него
достаём — а рядом фактический возраст локальной копии.

Описания живут в коде, а не в базе: они меняются вместе с тем, как мы
используем источник, и должны править́ся в том же коммите.
"""
from __future__ import annotations

from dataclasses import dataclass

from astrocal import config as cfg


@dataclass
class Source:
    key: str
    name: str
    kind: str                 # эфемериды | каталог | лента | наблюдения
    maintainer: str
    url: str
    cadence: str              # как часто обновляется у них
    we_take: str              # что берём мы
    note: str = ""
    local: str = ""           # путь к локальной копии, если она есть

    @property
    def age_text(self) -> str:
        """Возраст локальной копии. Пусто, если файла нет или он не нужен."""
        import datetime as dt

        if not self.local:
            return ""
        path = cfg.DATA / self.local
        if not path.exists():
            return "нет локальной копии"
        age = (dt.datetime.now(dt.timezone.utc).timestamp()
               - path.stat().st_mtime) / 3600.0
        if age < 1:
            return f"{age * 60:.0f} мин назад"
        if age < 48:
            return f"{age:.0f} ч назад"
        return f"{age / 24:.0f} дн назад"


CATALOGUE: tuple[Source, ...] = (
    Source(
        key="de440s", name="JPL DE440s", kind="эфемериды",
        maintainer="NASA JPL, Solar System Dynamics",
        url="https://ssd.jpl.nasa.gov/planets/eph_export.html",
        cadence="выпускается раз в несколько лет,DE440 выпущена в 2021 году",
        we_take="положения Солнца, Луны и планет с 1849 по 2150 год",
        note="основа всех расчётов: любое время и любой угол в календаре "
             "в конечном счёте получены отсюда",
        local="de440s.bsp"),
    Source(
        key="jup380s", name="JPL jup380s", kind="эфемериды",
        maintainer="NASA JPL",
        url="https://ssd.jpl.nasa.gov/sats/ephem/",
        cadence="обновляется по мере уточнения орбит спутников",
        we_take="положения галилеевых спутников Юпитера",
        note="из неё считаются и конфигурации, и прохождения по диску, и "
             "взаимные явления спутников",
        local="jup380s.bsp"),
    Source(
        key="moon_pa", name="JPL DE421 (ориентация Луны)", kind="эфемериды",
        maintainer="NASA NAIF",
        url="https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/",
        cadence="не меняется",
        we_take="ориентация лунного шара: либрации и колонгитуда Солнца",
        note="без неё не считаются Lunar X и благоприятные либрации",
        local="cache/moon_pa_de421_1900-2050.bpc"),
    Source(
        key="horizons", name="JPL Horizons", kind="эфемериды",
        maintainer="NASA JPL",
        url="https://ssd.jpl.nasa.gov/horizons/",
        cadence="непрерывно, орбиты малых тел уточняются по новым наблюдениям",
        we_take="эфемериды астероидов и Титана, положения тел для сверки",
        note="второй независимый источник: положения планет и Луны, "
             "посчитанные нами, сверяются с ним с допуском в одну угловую "
             "секунду"),
    Source(
        key="sbdb", name="JPL Small-Body Database", kind="каталог",
        maintainer="NASA JPL",
        url="https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html",
        cadence="непрерывно",
        we_take="дата решения орбиты астероида",
        note="по ней видно, не устарел ли прогноз покрытия"),
    Source(
        key="hipparcos", name="Hipparcos", kind="каталог",
        maintainer="ESA, каталог 1997 года",
        url="https://cdsarc.cds.unistra.fr/ftp/cats/I/239/",
        cadence="не меняется",
        we_take="положения и блеск звёзд ярче 8-й величины",
        note="по нему строятся карты, ищутся сближения и подписываются "
             "покрываемые звёзды",
        local="cache/hip_bright.parquet"),
    Source(
        key="openngc", name="OpenNGC", kind="каталог",
        maintainer="Маттиа Верга, открытый проект",
        url="https://github.com/mattiaverga/OpenNGC",
        cadence="правки приходят постоянно",
        we_take="туманности, скопления и галактики с блеском и размерами",
        local="cache/NGC.csv"),
    Source(
        key="mpc", name="MPC CometEls", kind="каталог",
        maintainer="Центр малых планет МАС",
        url="https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt",
        cadence="еженедельно",
        we_take="орбитальные элементы комет",
        note="только орбиты. Блеск отсюда не берём: формула по архивным "
             "параметрам ошибается на величины",
        local="cache/CometEls.txt"),
    Source(
        key="cobs", name="COBS", kind="наблюдения",
        maintainer="Comet OBServation database, Словения",
        url="https://cobs.si/",
        cadence="ежедневно, по мере поступления оценок наблюдателей",
        we_take="наблюдённый блеск комет: текущий и в максимуме",
        note="им калибруется модель блеска. Комета без наблюдений в "
             "календарь не идёт"),
    Source(
        key="vanbuitenen", name="astro.vanbuitenen.nl", kind="лента",
        maintainer="Гидеон ван Бёйтенен",
        url="https://astro.vanbuitenen.nl/",
        cadence="ежедневный пересчёт",
        we_take="блеск околоземных астероидов и прогноз по кометам",
        note="второе мнение к нашему расчёту блеска: расхождение больше "
             "половины величины попадает в проверку"),
    Source(
        key="cneos", name="NASA CNEOS", kind="лента",
        maintainer="Center for Near-Earth Object Studies, JPL",
        url="https://cneos.jpl.nasa.gov/ca/",
        cadence="непрерывно",
        we_take="список тесных сближений: дата, расстояние, скорость, H",
        note="блеска не даёт вовсе — его мы считаем сами"),
    Source(
        key="iota", name="IOTA / asteroidoccultation.com", kind="лента",
        maintainer="Стив Престон, Международная ассоциация хронометрии "
                   "покрытий",
        url="https://www.asteroidoccultation.com/",
        cadence="годовой файл считается один раз и не обновляется",
        we_take="кандидатов: какой астероид какую звезду и примерно когда "
                "покрывает",
        note="полосу мы пересчитываем сами по свежей орбите: прогноз "
             "годичной давности уезжает на часы",
        local="cache/occ2026-raw-generic.zip"),
    Source(
        key="astrovert", name="astrovert.ru", kind="лента",
        maintainer="наблюдатели, русскоязычный список",
        url="https://astrovert.ru/journal/events/",
        cadence="раз в год",
        we_take="контрольный список ярких покрытий над Россией",
        note="источником данных не является: по нему проверяется полнота "
             "нашего расчёта",
        local="control_occultations_2026.json"),
    Source(
        key="rms_annex", name="RMS Annex: покрытия звёзд планетами", kind="каталог",
        maintainer="French & Souami / PDS Ring-Moon Systems Node",
        url="https://pds-rings.seti.org/rms-annex/french23_occult_pred/",
        cadence="опубликован в 2023 году, период 2023–2050",
        we_take="контрольные кандидаты Юпитера, Сатурна, Урана, Нептуна, Титана и Тритона",
        note="G/K не заменяют V; время сближения не является местным контактом. Нужна отдельная проверка наблюдаемости."),
    Source(
        key="tns", name="Transient Name Server", kind="лента",
        maintainer="Международный астрономический союз",
        url="https://www.wis-tns.org/",
        cadence="непрерывно",
        we_take="новые и сверхновые: имя, координаты, блеск, тип",
        note="требует ключа бота. Без ключа остальные источники работают"),
    Source(
        key="imo", name="IMO Meteor Shower Calendar", kind="каталог",
        maintainer="Международная метеорная организация",
        url="https://www.imo.net/resources/calendar/",
        cadence="ежегодно",
        we_take="долготу Солнца в максимуме, ожидаемое ZHR, радианты",
        note="момент максимума вычисляется на конкретный год, а не "
             "переписывается из прошлогоднего календаря"),
    Source(
        key="celestrak", name="Celestrak", kind="лента",
        maintainer="Т. С. Келсо",
        url="https://celestrak.org/",
        cadence="несколько раз в сутки",
        we_take="элементы орбит МКС и китайской станции",
        note="прогноз по ним точен трое суток: дальше в календаре "
             "указывается период, а не минута",
        local="cache/iss_tle.txt"),
    Source(
        key="ll2", name="Launch Library 2", kind="лента",
        maintainer="The Space Devs",
        url="https://thespacedevs.com/llapi",
        cadence="непрерывно",
        we_take="расписание пусков со статусами Go, TBC и TBD"),
    Source(
        key="stellarium", name="Линии созвездий Stellarium", kind="каталог",
        maintainer="проект Stellarium",
        url="https://stellarium.org/",
        cadence="не меняется",
        we_take="рисунок созвездий для карт неба",
        local="cache/constellationship.fab"),
)

BY_KEY = {item.key: item for item in CATALOGUE}


def by_kind() -> dict[str, list[Source]]:
    order = ["эфемериды", "каталог", "наблюдения", "лента"]
    groups: dict[str, list[Source]] = {name: [] for name in order}
    for item in CATALOGUE:
        groups.setdefault(item.kind, []).append(item)
    return {name: items for name, items in groups.items() if items}


# Сначала — приметы в адресе, потом домен. Порядок важен: у JPL на одном
# домене живут и файлы эфемерид, и Horizons, и база малых тел, и по одному
# имени хоста их не различить.
URL_MARKERS = (
    ("pds-rings.seti.org/rms-annex", "rms_annex"),
    ("horizons.api", "horizons"),
    ("/cad.api", "cneos"),
    ("/sbdb.api", "sbdb"),
    ("/eph/planets/", "de440s"),
    ("/eph/satellites/", "jup380s"),
    ("naif.jpl.nasa.gov", "moon_pa"),
    ("cobs.si", "cobs"),
    ("vanbuitenen", "vanbuitenen"),
    ("minorplanetcenter", "mpc"),
    ("asteroidoccultation", "iota"),
    ("astrovert", "astrovert"),
    ("wis-tns.org", "tns"),
    ("celestrak", "celestrak"),
    ("thespacedevs", "ll2"),
    ("cds.unistra", "hipparcos"),
    ("OpenNGC", "openngc"),
    ("stellarium", "stellarium"),
)


def match(url: str) -> Source | None:
    """Источник по адресу обращения — для трассировки."""
    from urllib.parse import urlparse

    if not url:
        return None
    lowered = url.lower()
    for marker, key in URL_MARKERS:
        if marker.lower() in lowered:
            return BY_KEY.get(key)
    host = urlparse(url).netloc.lower()
    if not host:
        return None
    for item in CATALOGUE:
        if urlparse(item.url).netloc.lower() == host:
            return item
    return None
