"""Первичная загрузка данных, без которых расчёт не пойдёт.

Эфемериды и каталоги специально не вшиты в сборку: обновление каталога не
должно требовать пересборки приложения, а дистрибутив не должен весить
полгигабайта. Но требовать от пользователя вручную качать файлы по ссылкам —
плохая идея, поэтому здесь всё то же самое делается одной кнопкой.

Загрузка потоковая и с докачкой в том смысле, что недокачанный файл не
остаётся на диске: он пишется во временный файл и переименовывается только
после успешного завершения. Иначе оборванная закачка превращается в битый
BSP, который потом падает в середине расчёта.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

from astrocal import config as cfg

CHUNK = 1 << 20          # 1 МБ


@dataclass(frozen=True)
class Download:
    key: str
    title: str
    url: str
    path: Path
    size_mb: float
    required: bool
    note: str = ""

    @property
    def present(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 1024

    @property
    def size_text(self) -> str:
        """Размер человеческим языком: килобайты не показываем как «0.0 МБ»."""
        if self.size_mb < 0.1:
            return f"{self.size_mb * 1024:.0f} КБ"
        return f"{self.size_mb:.1f} МБ"


def catalogue() -> list[Download]:
    """Всё, что приложение умеет скачать само."""
    cache = cfg.CACHE
    return [
        Download("de440s", "Эфемериды планет и Луны (JPL DE440s)",
                 "https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de440s.bsp",
                 cfg.DATA / "de440s.bsp", 31.2, True,
                 "основа всех расчётов, 1849–2150 годы"),
        Download("jup380s", "Галилеевы спутники (JPL jup380s)",
                 "https://ssd.jpl.nasa.gov/ftp/eph/satellites/bsp/jup380s.bsp",
                 cfg.DATA / "jup380s.bsp", 51.6, True,
                 "конфигурации спутников, прохождения и тени"),
        Download("hipparcos", "Каталог звёзд Hipparcos",
                 "https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat",
                 cache / "hip_main.dat", 50.9, True,
                 "звёзды на картах и кросс-матч сближений"),
        Download("openngc", "Каталог объектов OpenNGC",
                 "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/"
                 "database_files/NGC.csv",
                 cache / "NGC.csv", 3.7, True,
                 "туманности, скопления и галактики"),
        Download("constellations", "Линии созвездий (Stellarium)",
                 "https://raw.githubusercontent.com/Stellarium/stellarium/"
                 "v0.21.3/skycultures/western/constellationship.fab",
                 cache / "constellationship.fab", 0.01, True,
                 "рисунок созвездий на картах неба"),
        Download("comets", "Орбитальные элементы комет (MPC)",
                 "https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt",
                 cache / "CometEls.txt", 0.2, True,
                 "обновляется еженедельно"),
        Download("moon_frame", "Ориентация Луны: система координат",
                 "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/fk/"
                 "satellites/moon_080317.tf",
                 cache / "moon_080317.tf", 0.02, False,
                 "нужна для либраций и Lunar X"),
        Download("moon_constants", "Ориентация Луны: константы",
                 "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/"
                 "pck00010.tpc",
                 cache / "pck00010.tpc", 0.12, False),
        Download("moon_orientation", "Ориентация Луны: эфемерида DE421",
                 "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/"
                 "moon_pa_de421_1900-2050.bpc",
                 cache / "moon_pa_de421_1900-2050.bpc", 1.7, False),
        Download("iota", "Предсказания покрытий звёзд астероидами (IOTA)",
                 "https://www.asteroidoccultation.com/2026/2026-iota.zip",
                 cache / "occ2026-iota.zip", 0.9, False,
                 "отобранные события года"),
        Download("iota_raw", "Полный набор предсказаний покрытий (IOTA)",
                 "https://www.asteroidoccultation.com/2026/2026-raw-generic.zip",
                 cache / "occ2026-raw-generic.zip", 53.7, False,
                 "нужен, чтобы не пропустить покрытия ярких звёзд"),
    ]


def missing(required_only: bool = False) -> list[Download]:
    return [item for item in catalogue()
            if not item.present and (item.required or not required_only)]


def total_size_mb(items: list[Download]) -> float:
    return round(sum(item.size_mb for item in items), 1)


def fetch(item: Download, progress=None) -> Path:
    """Скачать один файл. Недокачанный файл на диске не остаётся."""
    item.path.parent.mkdir(parents=True, exist_ok=True)
    temporary = item.path.with_suffix(item.path.suffix + ".part")

    with requests.get(item.url, stream=True, timeout=600) as response:
        response.raise_for_status()
        declared = int(response.headers.get("content-length") or 0)
        written = 0
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(CHUNK):
                if not chunk:
                    continue
                handle.write(chunk)
                written += len(chunk)
                if not progress:
                    continue
                # content-length относится к сжатому потоку, а считаем мы уже
                # распакованные байты, поэтому долю ограничиваем сверху
                expected = max(declared, int(item.size_mb * 1e6))
                percent = min(99, int(100 * written / expected)) if expected else 0
                progress(f"{item.title}: {written / 1e6:.1f} из "
                         f"{expected / 1e6:.1f} МБ", percent)
    temporary.replace(item.path)
    return item.path


def build_star_index(progress=None) -> None:
    """Собрать компактный индекс ярких звёзд из скачанного Hipparcos.

    Полный каталог — 51 МБ текста; при каждом запуске разбирать его заново
    незачем, поэтому один раз готовится parquet со звёздами ярче 8-й величины.
    """
    from astrocal.catalogs import HIP_PARQUET, HIP_RAW

    if HIP_PARQUET.exists() or not HIP_RAW.exists():
        return
    if progress:
        progress("Подготовка индекса звёзд", 50)
    from skyfield.data import hipparcos
    with HIP_RAW.open("rb") as handle:
        frame = hipparcos.load_dataframe(handle)
    frame[frame.magnitude <= 8.0].to_parquet(HIP_PARQUET)


def download_all(required_only: bool = False, progress=None) -> str:
    """Скачать всё недостающее. Возвращает отчёт для строки состояния."""
    items = missing(required_only)
    if not items:
        return "Все данные на месте — скачивать нечего"

    done, failed = [], []
    for index, item in enumerate(items):
        base = int(100 * index / len(items))
        span = int(100 / len(items))

        def report(text: str, percent: int, base=base, span=span) -> None:
            if progress:
                progress(text, min(99, base + percent * span // 100))

        report(f"{item.title}", 0)
        try:
            fetch(item, report)
            done.append(item.title)
        except Exception as error:              # noqa: BLE001
            failed.append(f"{item.title} ({error})")

    try:
        build_star_index(progress)
    except Exception:
        pass

    if progress:
        progress("Готово", 100)

    message = f"Загружено файлов: {len(done)}"
    if failed:
        message += f"; не удалось: {', '.join(failed)}"
    return message


def status_summary() -> str:
    """Короткая фраза о готовности данных — для строки состояния."""
    absent_required = missing(required_only=True)
    absent_all = missing()
    if absent_required:
        return (f"Не хватает данных для расчёта: {len(absent_required)} файл(ов), "
                f"{total_size_mb(absent_required)} МБ. "
                f"Вкладка «Данные» → «Скачать недостающее»")
    if absent_all:
        return (f"Основные данные на месте; дополнительно можно скачать "
                f"{len(absent_all)} файл(ов) ({total_size_mb(absent_all)} МБ)")
    return "Все данные на месте"
