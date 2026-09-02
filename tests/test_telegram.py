"""Публикация: лимит Telegram, разбиение, Unicode."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal.telegram import (TELEGRAM_LIMIT, as_markdown, build,   # noqa: E402
                               split_lines, telegram_length)

HEADER = "АСТРОНОМИЧЕСКИЕ СОБЫТИЯ Сентября 2026 года (время московское)✨"


def make_lines(count: int, width: int = 90) -> list[str]:
    return [f"▪️{index:02d} сентября, 12:00 — " + "событие " * (width // 8)
            for index in range(1, count + 1)]


def test_length_counts_utf16_units_like_telegram():
    # ▪️ — это два кодовых пункта (символ и модификатор эмодзи), и Telegram
    # считает их за два, а не за один «символ»
    assert telegram_length("▪️") == 2
    assert telegram_length("абв") == 3
    assert telegram_length("✨") == 1
    # символ вне BMP занимает две единицы UTF-16
    assert telegram_length("🔭") == 2


def test_short_post_is_one_message():
    publication = build(HEADER, make_lines(5))
    assert len(publication.parts) == 1
    assert not publication.needs_split
    assert publication.parts[0].label == "Сообщение 1/1"


def test_long_post_is_split():
    publication = build(HEADER, make_lines(80))
    assert publication.needs_split
    assert len(publication.parts) >= 2


def test_no_part_exceeds_the_limit():
    publication = build(HEADER, make_lines(120))
    assert all(part.length <= TELEGRAM_LIMIT for part in publication.parts)


def test_no_event_is_torn_apart():
    """Главное правило разбиения: строка события целиком в одном сообщении."""
    lines = make_lines(120)
    publication = build(HEADER, lines)
    collected = [line for part in publication.parts
                 for line in part.text.splitlines() if line.startswith("▪️")]
    assert collected == lines


def test_every_part_carries_the_header():
    publication = build(HEADER, make_lines(120))
    assert all(part.text.startswith(HEADER) for part in publication.parts)


def test_single_oversized_line_is_reported_not_cut():
    monster = "▪️01 сентября, 12:00 — " + "очень длинное описание " * 250
    publication = build(HEADER, [monster])
    assert publication.oversized_lines == [monster]
    assert "длиннее лимита" in publication.status


def test_parts_are_numbered():
    publication = build(HEADER, make_lines(120))
    total = len(publication.parts)
    assert [part.label for part in publication.parts] == [
        f"Сообщение {i}/{total}" for i in range(1, total + 1)]


def test_plain_text_matches_calendar_file_shape():
    publication = build(HEADER, make_lines(3))
    text = publication.plain_text
    assert text.startswith(HEADER + "\n\n")
    assert text.endswith("\n")


@pytest.mark.parametrize("count", [1, 7, 40, 200])
def test_split_is_stable_for_any_size(count):
    texts, oversized = split_lines(HEADER, make_lines(count))
    assert texts
    assert not oversized
    assert sum(text.count("▪️") for text in texts) == count


def test_markdown_export_keeps_all_events():
    lines = make_lines(4)
    markdown = as_markdown(HEADER, lines)
    assert markdown.startswith("# ")
    assert markdown.count("- ") == 4
