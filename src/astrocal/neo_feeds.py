"""Блеск околоземных астероидов: независимый источник к нашему расчёту.

CNEOS отвечает на вопрос «что и как близко пролетит», но блеска он не даёт
вовсе — только абсолютную величину H, из которой видимый блеск напрямую не
следует. Поэтому отбор по данным CNEOS получается по размеру и расстоянию, а
это критерий не наблюдателя: метровый камень в двух лунных расстояниях
формально «близкий», но +22-й величины и недоступен никакому любительскому
телескопу.

Сайт Гидеона ван Бёйтенена ведёт две таблицы, отобранные как раз по блеску:

* `brightneos` — объекты, которые станут ярче 14-й величины в ближайшие
  12 месяцев, с датой и блеском в максимуме;
* `neos` — сближения ближе 25 лунных расстояний на три месяца вперёд, с
  блеском и координатами на момент наибольшего сближения.

Нужен он нам для двух вещей. Первая — категория «яркие сближения года»,
которой из месячного расчёта не видно: максимум блеска объекта может прийтись
на месяц, до которого мы ещё не дошли. Вторая, и более важная, — сверка. Свой
блеск мы считаем через Horizons; расхождение с независимым источником больше
чем на половину величины означает, что кто-то из нас ошибается, и это повод
посмотреть глазами, а не публиковать.

Таблицы разбираются штатным `html.parser`: разметка простая, а тянуть ради неё
lxml в сборку незачем. Если структура таблицы изменится, разбор не станет
молча выдавать мусор — он скажет, что колонки не те.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from . import config as cfg
from .net import fetch

BRIGHT_URL = "https://astro.vanbuitenen.nl/brightneos"
APPROACH_URL = "https://astro.vanbuitenen.nl/neos"
SOURCE = "astro.vanbuitenen.nl (G. van Buitenen)"

# Ожидаемые колонки. Проверяются при разборе: лучше явная ошибка, чем тихо
# разъехавшиеся значения.
BRIGHT_COLUMNS = ["designation", "h", "diameter est.", "magn", "delta (ld)",
                  "date", "delta (ld)", "magn", "date", "magn"]
APPROACH_COLUMNS = ["designation", "diameter", "magn", "delta (au)",
                    "delta (ld)", "date", "ra", "dec", "magn", "delta (au)",
                    "delta (ld)"]


class _TableParser(HTMLParser):
    """Первая таблица страницы: заголовки и строки как списки строк."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headers: list[str] = []
        self.rows: list[list[str]] = []
        self._in_table = False
        self._done = False
        self._in_head = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        if tag == "table":
            self._in_table = True
        elif tag == "thead" and self._in_table:
            self._in_head = True
        elif tag == "tr" and self._in_table:
            # На странице ярких объектов строки не закрыты: <tr> идёт сразу
            # после последней ячейки предыдущей. По правилам HTML новый <tr>
            # закрывает предыдущий — иначе таблица разбирается в пустоту.
            self._flush_row()
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._flush_cell()
            self._cell = []

    def _flush_cell(self) -> None:
        if self._cell is None:
            return
        text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
        if self._row is not None:
            self._row.append(text)
        self._cell = None

    def _flush_row(self) -> None:
        self._flush_cell()
        if not self._row:
            self._row = None
            return
        if self._in_head:
            # У таблицы две строки заголовка: верхняя — группы колонок
            # («Today», «Closest Approach»), нижняя — сами колонки
            if len(self._row) > len(self.headers):
                self.headers = self._row
        else:
            self.rows.append(self._row)
        self._row = None

    def handle_endtag(self, tag):
        if self._done:
            return
        if tag in ("td", "th"):
            self._flush_cell()
        elif tag == "tr":
            self._flush_row()
        elif tag == "thead":
            self._flush_row()
            self._in_head = False
        elif tag in ("tbody", "table") and self._in_table:
            self._flush_row()
            if tag == "table":
                self._in_table = False
                self._done = True

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_table(html: str) -> tuple[list[str], list[list[str]]]:
    parser = _TableParser()
    parser.feed(html)
    return parser.headers, parser.rows


def _normalise_header(text: str) -> str:
    """Имя колонки без украшений.

    В заголовке стоит «H» с подстрочным знаком, и сайт в разное время
    использовал разные символы подстрочника. Сравнивать по ним нельзя —
    оставляем только латиницу, цифры и скобки.
    """
    cleaned = "".join(ch for ch in (text or "").lower()
                      if ch.isascii() and (ch.isalnum() or ch in " ().-"))
    return re.sub(r"\s+", " ", cleaned).strip()


def _check_columns(headers: list[str], expected: list[str], url: str) -> None:
    actual = [_normalise_header(h) for h in headers]
    if actual != expected:
        raise ValueError(
            f"структура таблицы {url} изменилась: ожидались колонки "
            f"{expected}, получены {actual}")


# ------------------------------------------------------------------ значения


def _number(text: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text or "")
    return float(match.group()) if match else None


def _date(text: str) -> dt.datetime | None:
    """«13 Nov 2026» → дата в МСК (у источника это календарная дата UTC)."""
    try:
        naive = dt.datetime.strptime((text or "").strip(), "%d %b %Y")
    except ValueError:
        return None
    return naive.replace(tzinfo=dt.timezone.utc).astimezone(cfg.MSK)


def _ra_degrees(text: str) -> float | None:
    match = re.match(r"\s*(\d+)h(\d+)m", text or "")
    if not match:
        return None
    return (int(match.group(1)) + int(match.group(2)) / 60.0) * 15.0


def _dec_degrees(text: str) -> float | None:
    match = re.match(r"\s*([-+]?)(\d+)°(\d+)", text or "")
    if not match:
        return None
    value = int(match.group(2)) + int(match.group(3)) / 60.0
    return -value if match.group(1) == "-" else value


# ------------------------------------------------------------------ запись


@dataclass
class FeedNeo:
    """Строка таблицы: объект, его блеск и обстоятельства сближения."""
    designation: str
    diameter_text: str = ""
    absolute_magnitude: float | None = None
    magnitude_today: float | None = None
    delta_today_ld: float | None = None
    closest_date: dt.datetime | None = None
    closest_ld: float | None = None
    closest_au: float | None = None
    closest_magnitude: float | None = None
    brightest_date: dt.datetime | None = None
    brightest_magnitude: float | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None
    table: str = ""
    source: str = SOURCE
    source_updated_at: str = ""

    @property
    def peak_magnitude(self) -> float | None:
        """Самый яркий блеск, который источник называет для объекта."""
        values = [v for v in (self.brightest_magnitude, self.closest_magnitude)
                  if v is not None]
        return min(values) if values else None

    @property
    def peak_when(self) -> dt.datetime | None:
        if self.brightest_magnitude is not None and self.brightest_date:
            return self.brightest_date
        return self.closest_date

    @property
    def keys(self) -> set[str]:
        """Варианты обозначения для сопоставления с CNEOS.

        В таблице объект записан как «(363790) 2005 JE46» или «(217628) Lugh»,
        а CNEOS отдаёт либо номер, либо предварительное обозначение. Поэтому
        ключом считается и то и другое.
        """
        return designation_keys(self.designation)

    def provenance(self) -> dict:
        return {"source": self.source, "url": (BRIGHT_URL if self.table == "bright"
                                               else APPROACH_URL),
                "source_updated_at": self.source_updated_at,
                "table": self.table}


def designation_keys(designation: str) -> set[str]:
    """Нормализованные ключи обозначения: номер и имя/обозначение отдельно."""
    text = (designation or "").strip()
    keys: set[str] = set()
    number = re.match(r"\((\d+)\)\s*(.*)", text)
    if number:
        keys.add(number.group(1))
        rest = number.group(2).strip()
    else:
        rest = text
    if rest:
        keys.add(re.sub(r"\s+", "", rest).upper())
    keys.add(re.sub(r"[\s()]+", "", text).upper())
    return {key for key in keys if key}


# ------------------------------------------------------------------ источники


def _rows(url: str, expected: list[str], use_cache: bool,
          ttl_hours: float) -> tuple[list[list[str]], str]:
    response = fetch(url, ttl_hours=ttl_hours, use_cache=use_cache, timeout=60.0)
    headers, rows = parse_table(response.body)
    if not headers:
        raise ValueError(f"на странице {url} не найдена таблица")
    _check_columns(headers, expected, url)
    return rows, response.fetched_at.isoformat()


def bright(use_cache: bool = True, ttl_hours: float = 24.0) -> list[FeedNeo]:
    """Объекты, которые станут ярче 14-й величины в ближайший год."""
    rows, updated = _rows(BRIGHT_URL, BRIGHT_COLUMNS, use_cache, ttl_hours)
    out = []
    for row in rows:
        if len(row) < len(BRIGHT_COLUMNS):
            continue
        out.append(FeedNeo(
            designation=row[0],
            absolute_magnitude=_number(row[1]),
            diameter_text=row[2],
            magnitude_today=_number(row[3]),
            delta_today_ld=_number(row[4]),
            closest_date=_date(row[5]),
            closest_ld=_number(row[6]),
            closest_magnitude=_number(row[7]),
            brightest_date=_date(row[8]),
            brightest_magnitude=_number(row[9]),
            table="bright", source_updated_at=updated))
    return out


def approaches(use_cache: bool = True, ttl_hours: float = 12.0) -> list[FeedNeo]:
    """Сближения ближе 25 лунных расстояний на три месяца вперёд."""
    rows, updated = _rows(APPROACH_URL, APPROACH_COLUMNS, use_cache, ttl_hours)
    out = []
    for row in rows:
        if len(row) < len(APPROACH_COLUMNS):
            continue
        out.append(FeedNeo(
            designation=row[0],
            diameter_text=row[1],
            magnitude_today=_number(row[2]),
            delta_today_ld=_number(row[4]),
            closest_date=_date(row[5]),
            ra_deg=_ra_degrees(row[6]),
            dec_deg=_dec_degrees(row[7]),
            closest_magnitude=_number(row[8]),
            closest_au=_number(row[9]),
            closest_ld=_number(row[10]),
            table="approach", source_updated_at=updated))
    return out


# ------------------------------------------------------------------ поиск


@dataclass
class FeedIndex:
    """Обе таблицы, разложенные по ключам обозначения."""
    entries: list[FeedNeo] = field(default_factory=list)
    by_key: dict[str, FeedNeo] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def find(self, designation: str) -> FeedNeo | None:
        for key in designation_keys(designation):
            entry = self.by_key.get(key)
            if entry is not None:
                return entry
        return None

    @property
    def available(self) -> bool:
        return bool(self.entries)


def load(use_cache: bool = True, tables=("approach", "bright")) -> FeedIndex:
    """Обе таблицы разом. Недоступность источника не мешает расчёту."""
    index = FeedIndex()
    loaders = {"approach": approaches, "bright": bright}
    for name in tables:
        try:
            entries = loaders[name](use_cache=use_cache)
        except Exception as error:               # noqa: BLE001
            index.errors.append(f"{name}: {error}")
            continue
        index.entries += entries
        for entry in entries:
            for key in entry.keys:
                # таблица сближений точнее по датам, таблица ярких — по
                # максимуму блеска; при совпадении оставляем первую загруженную
                index.by_key.setdefault(key, entry)
    return index
