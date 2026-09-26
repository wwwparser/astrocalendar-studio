"""Веб-версия: доступ только по паролю, редактор выпуска, фоновые задачи.

Астрономия здесь не считается: в архив кладётся готовый выпуск из нескольких
событий. Проверяется поведение сайта — что без входа не отдаётся ничего, что
правки сохраняются между запросами и что долгий расчёт не выполняется внутри
обработчика.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient                        # noqa: E402

from astrocal.config import MSK                                  # noqa: E402
from astrocal.core import Event                                  # noqa: E402
from astrocal.qa import Flag                                     # noqa: E402
from astrocal_app import archive                                 # noqa: E402
from astrocal_app.models import EditableEvent, Issue             # noqa: E402
from astrocal_web import auth, jobs                              # noqa: E402

PASSWORD = "dolgij-parol-2026"


def make_issue() -> Issue:
    def event(day, text, category="moon", rank="must", flags=()):
        item = Event(when=dt.datetime(2026, 10, day, 21, 0, tzinfo=MSK),
                     text=text, category=category, rank=rank,
                     computed="тестовый расчёт", sources=["тест"])
        item.flags = list(flags)
        return item

    issue = Issue(year=2026, month=10,
                  enabled_kinds={"moon_phase", "moon_planet", "planet_opposition"},
                  enabled_ranks={"must", "interesting"})
    events = [
        event(4, "Сатурн в противостоянии с Солнцем", "planet",
              flags=[Flag("REVIEW", "format", "пример замечания")]),
        event(10, "Луна в фазе новолуние в созвездии Дева"),
        event(26, "Луна в фазе полнолуние в созвездии Овен", rank="interesting"),
    ]
    issue.events = [EditableEvent(event=item, order=index)
                    for index, item in enumerate(events)]
    return issue


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTROCAL_WEB_SECRET", "x" * 48)
    monkeypatch.setenv("ASTROCAL_WEB_INSECURE", "1")
    monkeypatch.setattr(archive, "ARCHIVE_DIR", tmp_path / "issues")
    # UserStore берёт путь из модульной переменной при создании, поэтому
    # подмены самой переменной достаточно
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(jobs, "MANAGER", jobs.JobManager())

    auth.UserStore().add("stas", PASSWORD, "тест")
    archive.save(make_issue())

    from astrocal_web.app import create_app
    return TestClient(create_app())


@pytest.fixture
def signed_in(client):
    response = client.post("/login", data={"username": "stas",
                                           "password": PASSWORD})
    assert response.status_code == 200
    return client


# ------------------------------------------------------------------ доступ


@pytest.mark.parametrize("path", [
    "/", "/live", "/issues/2026-10", "/issues/2026-10/publication",
    "/issues/2026-10/qa", "/issues/2026-10/download/txt"])
def test_pages_require_login(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_api_answers_json_not_redirect(client):
    response = client.get("/api/jobs/anything")
    assert response.status_code == 401
    assert "нужен вход" in response.json()["error"]


def test_login_page_is_open(client):
    assert client.get("/login").status_code == 200


def test_wrong_password_is_rejected(client):
    response = client.post("/login", data={"username": "stas",
                                           "password": "не тот"})
    assert response.status_code == 401
    assert "неверный логин или пароль" in response.text


def test_unknown_user_gets_the_same_answer(client):
    """Разные ответы подсказывали бы, какие логины существуют."""
    response = client.post("/login", data={"username": "чужой",
                                           "password": "не тот"})
    assert "неверный логин или пароль" in response.text


def test_login_succeeds_and_opens_the_site(client):
    client.post("/login", data={"username": "stas", "password": PASSWORD})
    assert client.get("/", follow_redirects=False).status_code == 200


def test_logout_closes_the_site(signed_in):
    signed_in.post("/logout")
    assert signed_in.get("/", follow_redirects=False).status_code == 303


def test_password_is_not_in_the_users_file(client, tmp_path):
    assert PASSWORD not in (tmp_path / "users.json").read_text(encoding="utf-8")


def test_lockout_after_repeated_failures(client):
    auth.ATTEMPTS.failures.clear()
    for _ in range(auth.MAX_ATTEMPTS):
        client.post("/login", data={"username": "stas", "password": "нет"})
    response = client.post("/login", data={"username": "stas",
                                           "password": PASSWORD})
    assert "слишком много неудачных попыток" in response.text
    auth.ATTEMPTS.failures.clear()


def test_pages_are_closed_from_search_engines(client):
    assert 'name="robots"' in client.get("/login").text


# ------------------------------------------------------------------ выпуски


def test_issue_list_shows_the_saved_issue(signed_in):
    body = signed_in.get("/").text
    assert "Октябрь 2026" in body


def test_issue_page_lists_events(signed_in):
    body = signed_in.get("/issues/2026-10").text
    assert "Сатурн в противостоянии с Солнцем" in body
    assert "Луна в фазе новолуние" in body


def test_missing_issue_gives_404(signed_in):
    assert signed_in.get("/issues/2030-01").status_code == 404


def test_toggle_is_saved_between_requests(signed_in):
    issue = archive.read(2026, 10)
    target = issue.events[0].event_id

    response = signed_in.post("/api/issues/2026-10/toggle",
                              json={"id": target, "selected": False})
    assert response.status_code == 200
    assert response.json()["published"] == 2

    again = archive.read(2026, 10)
    assert again.by_id(target).selected is False


def test_editing_text_is_saved(signed_in):
    issue = archive.read(2026, 10)
    target = issue.events[1].event_id

    response = signed_in.post("/api/issues/2026-10/text",
                              json={"id": target, "text": "Моя формулировка"})
    assert response.json()["edited"] is True

    again = archive.read(2026, 10)
    item = again.by_id(target)
    assert item.text == "Моя формулировка"
    assert item.calculated_text.startswith("Луна в фазе новолуние"), \
        "расчётный текст должен сохраняться отдельно"


def test_empty_edit_returns_the_calculated_text(signed_in):
    issue = archive.read(2026, 10)
    target = issue.events[1].event_id
    signed_in.post("/api/issues/2026-10/text",
                   json={"id": target, "text": "Временный"})
    response = signed_in.post("/api/issues/2026-10/text",
                              json={"id": target, "text": ""})
    assert response.json()["edited"] is False


def test_unknown_event_is_404(signed_in):
    response = signed_in.post("/api/issues/2026-10/toggle",
                              json={"id": "нет такого", "selected": True})
    assert response.status_code == 404


def test_filters_are_saved(signed_in):
    signed_in.post("/issues/2026-10/filters",
                   data={"rank": ["must"], "kind": ["planet_opposition"],
                         "icons": "on"}, follow_redirects=False)
    issue = archive.read(2026, 10)
    assert issue.enabled_ranks == {"must"}
    assert issue.icons is True


def test_icons_change_the_publication(signed_in):
    before = signed_in.get("/issues/2026-10/download/txt").text
    signed_in.post("/issues/2026-10/filters",
                   data={"rank": ["must", "interesting"],
                         "kind": ["planet_opposition", "moon_phase"],
                         "icons": "on"}, follow_redirects=False)
    after = signed_in.get("/issues/2026-10/download/txt").text
    assert "▪️" in before
    assert "🪐" in after


# ------------------------------------------------------------------ вывод


def test_publication_page_shows_the_post(signed_in):
    body = signed_in.get("/issues/2026-10/publication").text
    assert "АСТРОНОМИЧЕСКИЕ СОБЫТИЯ" in body
    assert "4096" in body


@pytest.mark.parametrize("kind,marker", [
    ("txt", "АСТРОНОМИЧЕСКИЕ СОБЫТИЯ"), ("md", "АСТРОНОМИЧЕСКИЕ"),
    ("json", '"events"')])
def test_downloads(signed_in, kind, marker):
    response = signed_in.get(f"/issues/2026-10/download/{kind}")
    assert response.status_code == 200
    assert marker in response.text
    assert "attachment" in response.headers["content-disposition"]


def test_unknown_download_format(signed_in):
    assert signed_in.get("/issues/2026-10/download/pdf").status_code == 404


def test_qa_page_lists_the_flag(signed_in):
    body = signed_in.get("/issues/2026-10/qa").text
    assert "пример замечания" in body
    assert "REVIEW" in body


# ------------------------------------------------------------------ задачи


def test_calculation_starts_in_background(signed_in, monkeypatch):
    """Обработчик не должен считать месяц сам: он ставит задачу и отвечает."""
    calls = []

    def fake(year, month, use_horizons=True, progress=None):
        calls.append((year, month))
        if progress:
            progress("готово", 100)
        return {"total": 0, "published": 0, "review": 0}

    monkeypatch.setattr("astrocal_web.app.compute_and_store", fake)
    response = signed_in.post("/issues/new",
                              data={"year": 2027, "month": 3, "horizons": "on"},
                              follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/jobs/")

    job_id = response.headers["location"].split("/")[-1]
    for _ in range(100):
        if not jobs.MANAGER.get(job_id).active:
            break
        import time
        time.sleep(0.05)
    assert calls == [(2027, 3)]


def test_second_request_reuses_the_running_job(signed_in, monkeypatch):
    import threading
    release = threading.Event()

    def slow(year, month, use_horizons=True, progress=None):
        release.wait(timeout=5)
        return {}

    monkeypatch.setattr("astrocal_web.app.compute_and_store", slow)
    first = signed_in.post("/issues/new", data={"year": 2027, "month": 4},
                           follow_redirects=False)
    second = signed_in.post("/issues/new", data={"year": 2027, "month": 4},
                            follow_redirects=False)
    release.set()
    assert first.headers["location"] == second.headers["location"]


def test_bad_month_is_rejected(signed_in):
    response = signed_in.post("/issues/new", data={"year": 2027, "month": 13},
                              follow_redirects=False)
    assert response.status_code == 400


def test_job_status_is_json(signed_in, monkeypatch):
    monkeypatch.setattr("astrocal_web.app.compute_and_store",
                        lambda *a, **k: {})
    response = signed_in.post("/issues/new", data={"year": 2027, "month": 5},
                              follow_redirects=False)
    job_id = response.headers["location"].split("/")[-1]
    status = signed_in.get(f"/api/jobs/{job_id}").json()
    assert status["id"] == job_id
    assert status["payload"]["month"] == 5


def test_unknown_job(signed_in):
    assert signed_in.get("/jobs/нетакой").status_code == 404


# ------------------------------------------------------------------ лента


def test_live_page_opens_without_data(signed_in):
    body = signed_in.get("/live").text
    assert "LIVE" in body
    assert "Обновить сейчас" in body
