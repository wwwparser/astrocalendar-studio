"""Первичная загрузка данных: что считается обязательным и как это качается."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astrocal_app import bootstrap                      # noqa: E402


def fake_catalogue(tmp_path: Path) -> list[bootstrap.Download]:
    return [
        bootstrap.Download("a", "Обязательный A", "http://example/a",
                           tmp_path / "a.bin", 10.0, True),
        bootstrap.Download("b", "Обязательный B", "http://example/b",
                           tmp_path / "b.bin", 5.0, True),
        bootstrap.Download("c", "Необязательный C", "http://example/c",
                           tmp_path / "c.bin", 2.0, False),
    ]


def test_catalogue_lists_ephemerides_and_catalogues():
    keys = {item.key for item in bootstrap.catalogue()}
    assert {"de440s", "jup380s", "hipparcos", "openngc"} <= keys


def test_ephemerides_are_required():
    required = {item.key for item in bootstrap.catalogue() if item.required}
    assert "de440s" in required and "jup380s" in required


def test_optional_data_is_not_required():
    optional = {item.key for item in bootstrap.catalogue() if not item.required}
    # покрытия звёзд астероидами и либрации — полезны, но без них расчёт идёт
    assert "iota_raw" in optional and "moon_orientation" in optional


def test_missing_ignores_present_files(tmp_path, monkeypatch):
    items = fake_catalogue(tmp_path)
    monkeypatch.setattr(bootstrap, "catalogue", lambda: items)
    assert len(bootstrap.missing()) == 3

    (tmp_path / "a.bin").write_bytes(b"x" * 4096)
    assert {item.key for item in bootstrap.missing()} == {"b", "c"}
    assert {item.key for item in bootstrap.missing(required_only=True)} == {"b"}


def test_tiny_file_counts_as_absent(tmp_path, monkeypatch):
    """Обрывок закачки не должен считаться готовым файлом."""
    items = fake_catalogue(tmp_path)
    monkeypatch.setattr(bootstrap, "catalogue", lambda: items)
    (tmp_path / "a.bin").write_bytes(b"oops")
    assert "a" in {item.key for item in bootstrap.missing()}


def test_total_size(tmp_path, monkeypatch):
    items = fake_catalogue(tmp_path)
    monkeypatch.setattr(bootstrap, "catalogue", lambda: items)
    assert bootstrap.total_size_mb(bootstrap.missing(required_only=True)) == 15.0


def test_status_summary_reports_required_first(tmp_path, monkeypatch):
    items = fake_catalogue(tmp_path)
    monkeypatch.setattr(bootstrap, "catalogue", lambda: items)
    assert "Не хватает данных для расчёта" in bootstrap.status_summary()

    for name in ("a.bin", "b.bin"):
        (tmp_path / name).write_bytes(b"x" * 4096)
    assert "Основные данные на месте" in bootstrap.status_summary()

    (tmp_path / "c.bin").write_bytes(b"x" * 4096)
    assert bootstrap.status_summary() == "Все данные на месте"


def test_download_reports_progress_and_leaves_no_part_file(tmp_path, monkeypatch):
    """Скачивание идёт во временный файл и переименовывается в конце."""
    payload = b"y" * (3 << 20)

    class FakeResponse:
        headers = {"content-length": str(len(payload))}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk):
            for start in range(0, len(payload), chunk):
                yield payload[start:start + chunk]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(bootstrap.requests, "get",
                        lambda *args, **kwargs: FakeResponse())
    item = bootstrap.Download("t", "Тест", "http://example/t",
                              tmp_path / "t.bin", 3.0, True)

    seen = []
    path = bootstrap.fetch(item, lambda text, percent: seen.append(percent))

    assert path.read_bytes() == payload
    assert not path.with_suffix(path.suffix + ".part").exists()
    assert seen and all(0 <= value <= 99 for value in seen)
    assert seen == sorted(seen)


def test_failed_download_leaves_no_file(tmp_path, monkeypatch):
    def explode(*_args, **_kwargs):
        raise ConnectionError("сеть недоступна")

    monkeypatch.setattr(bootstrap.requests, "get", explode)
    item = bootstrap.Download("t", "Тест", "http://example/t",
                              tmp_path / "t.bin", 1.0, True)
    with pytest.raises(ConnectionError):
        bootstrap.fetch(item)
    assert not item.path.exists()


def test_download_all_survives_one_failure(tmp_path, monkeypatch):
    items = fake_catalogue(tmp_path)
    monkeypatch.setattr(bootstrap, "catalogue", lambda: items)

    def fetch(item, progress=None):
        if item.key == "b":
            raise ConnectionError("отказ источника")
        item.path.write_bytes(b"x" * 4096)
        return item.path

    monkeypatch.setattr(bootstrap, "fetch", fetch)
    monkeypatch.setattr(bootstrap, "build_star_index", lambda progress=None: None)

    message = bootstrap.download_all(progress=None)
    assert "Загружено файлов: 2" in message
    assert "не удалось" in message and "Обязательный B" in message
