from astrocal_app.revisions import archive_calendar


def test_revision_changes_only_with_content(tmp_path):
    path = tmp_path / "calendar_2026-10.txt"
    path.write_text("Первый выпуск", encoding="utf-8")
    assert archive_calendar(path)["version"] == 1
    assert archive_calendar(path)["version"] == 1
    path.write_text("Исправленный выпуск", encoding="utf-8")
    assert archive_calendar(path)["version"] == 2
    previous = tmp_path / "revisions/calendar_2026-10/calendar_2026-10_v001.txt"
    assert previous.read_text(encoding="utf-8") == "Первый выпуск"
