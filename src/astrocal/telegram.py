"""Подготовка публикации: лимит Telegram и разбиение на сообщения.

Telegram считает длину сообщения в кодовых точках UTF-16, а не в символах
Python: эмодзи вроде ▪️ и ✨ занимают там по две единицы. Поэтому длина
считается честно, иначе пост «на 4090 символов» неожиданно не отправляется.

Разбиение подчиняется одному правилу: строку события рвать нельзя. Делим
только по границам строк, и если одна строка сама длиннее лимита — это
ошибка данных, о которой надо сказать, а не молча обрезать.
"""
from __future__ import annotations

from dataclasses import dataclass

TELEGRAM_LIMIT = 4096


def telegram_length(text: str) -> int:
    """Длина сообщения так, как её считает Telegram (единицы UTF-16)."""
    return len(text.encode("utf-16-le")) // 2


@dataclass
class Part:
    index: int
    total: int
    text: str

    @property
    def length(self) -> int:
        return telegram_length(self.text)

    @property
    def label(self) -> str:
        return f"Сообщение {self.index}/{self.total}"


@dataclass
class Publication:
    header: str
    lines: list[str]
    parts: list[Part]
    oversized_lines: list[str]

    @property
    def full_text(self) -> str:
        return "\n\n".join(part.text for part in self.parts)

    @property
    def length(self) -> int:
        return telegram_length(self.plain_text)

    @property
    def plain_text(self) -> str:
        body = "\n".join(self.lines)
        return f"{self.header}\n\n{body}\n" if self.lines else f"{self.header}\n"

    @property
    def needs_split(self) -> bool:
        return len(self.parts) > 1

    @property
    def status(self) -> str:
        if self.oversized_lines:
            return (f"{self.length} / {TELEGRAM_LIMIT} символов — "
                    f"{len(self.oversized_lines)} строк(и) длиннее лимита")
        if self.needs_split:
            return (f"{self.length} / {TELEGRAM_LIMIT} символов — сообщение будет "
                    f"разделено на {len(self.parts)} части")
        return f"{self.length} / {TELEGRAM_LIMIT} символов"


def split_lines(header: str, lines: list[str],
                limit: int = TELEGRAM_LIMIT,
                repeat_header: bool = True) -> tuple[list[str], list[str]]:
    """Разложить строки по сообщениям, не разрывая ни одной.

    Возвращает (тексты сообщений, строки, которые сами длиннее лимита).
    """
    oversized = [line for line in lines
                 if telegram_length(line) + telegram_length(header) + 4 > limit]

    chunks: list[list[str]] = []
    current: list[str] = []
    prefix = header

    def chunk_length(candidate: list[str], with_header: str) -> int:
        body = "\n".join(candidate)
        return telegram_length(f"{with_header}\n\n{body}\n" if with_header else body)

    for line in lines:
        trial = current + [line]
        head = prefix if (not chunks or repeat_header) else ""
        if current and chunk_length(trial, head) > limit:
            chunks.append(current)
            current = [line]
            prefix = header if repeat_header else ""
        else:
            current = trial
    if current:
        chunks.append(current)

    texts = []
    for i, chunk in enumerate(chunks):
        head = header if (i == 0 or repeat_header) else ""
        body = "\n".join(chunk)
        texts.append(f"{head}\n\n{body}" if head else body)
    return texts, oversized


def build(header: str, lines: list[str], limit: int = TELEGRAM_LIMIT,
          repeat_header: bool = True) -> Publication:
    """Собрать публикацию из заголовка и строк событий."""
    texts, oversized = split_lines(header, lines, limit, repeat_header)
    parts = [Part(index=i + 1, total=len(texts), text=text)
             for i, text in enumerate(texts)]
    return Publication(header=header, lines=list(lines), parts=parts,
                       oversized_lines=oversized)


def as_markdown(header: str, lines: list[str]) -> str:
    """Тот же выпуск в Markdown — для архива и публикации вне Telegram."""
    body = "\n".join(f"- {line.lstrip('▪️').strip()}" for line in lines)
    return f"# {header}\n\n{body}\n"
