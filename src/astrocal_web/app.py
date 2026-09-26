"""Веб-версия AstroCalendar: тот же редактор выпуска, только в браузере.

Слои те же, что у настольной программы: расчёт живёт в `astrocal`, модель
выпуска — в `astrocal_app`, здесь только маршруты и шаблоны. Астрономии в этом
файле нет ни строки, и это сознательно — иначе две версии разъедутся.

Три вещи, которых нет у настольной версии и которые определяют устройство.

**Расчёт не помещается в запрос.** Месяц считается десять–пятнадцать минут,
поэтому кнопка ставит задачу в очередь (`jobs`), а страница опрашивает
прогресс. Повторное нажатие не запускает вторую копию: задача с теми же
параметрами находится и переиспользуется.

**Результат нужно хранить.** Настольная программа держит выпуск в памяти,
браузер — нет. Рассчитанный выпуск целиком ложится в `data/issues/`
(`astrocal_app.archive`), и любая страница поднимает его оттуда за миллисекунды.

**Сайт закрыт целиком.** Без входа не отдаётся ничего, кроме формы входа и
таблицы стилей. Проверка сессии стоит в одном месте — в зависимости
`current_user`, а не расставлена по обработчикам, где её легко забыть.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER

from astrocal import config as cfg
from astrocal.fmt import MONTHS_NOMINATIVE
from astrocal.taxonomy import grouped_kinds
from astrocal_app import archive, service
from astrocal_app.models import Issue

from . import jobs
from .auth import AuthError, authenticate, session_secret

HERE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))
RANKS = [("must", "событие месяца"), ("interesting", "заметное явление"),
         ("optional", "узкое, для полноты"), ("technical", "служебное")]
SESSION_HOURS = 12


# ------------------------------------------------------------------ сессия


def current_user(request: Request) -> str:
    """Имя вошедшего пользователя. Иначе — перенаправление на вход."""
    name = request.session.get("user")
    started = request.session.get("since")
    if not name or not started:
        raise HTTPException(status_code=401)
    try:
        since = dt.datetime.fromisoformat(started)
    except ValueError:
        raise HTTPException(status_code=401) from None
    if (dt.datetime.now(dt.timezone.utc) - since).total_seconds() > \
            SESSION_HOURS * 3600:
        request.session.clear()
        raise HTTPException(status_code=401)
    return name


def client_address(request: Request) -> str:
    """Адрес клиента с учётом обратного прокси."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


# ------------------------------------------------------------------ выпуски


def load_issue(year: int, month: int) -> Issue:
    issue = archive.read(year, month)
    if issue is None:
        raise HTTPException(status_code=404, detail="выпуск ещё не рассчитан")
    return issue


def compute_and_store(year: int, month: int, use_horizons: bool = True,
                      progress=None) -> dict:
    """Расчёт месяца и сохранение результата. Выполняется в фоне."""
    issue = service.compute_issue(year, month, use_horizons=use_horizons,
                                  with_circumstances=False, progress=progress)
    if progress:
        progress("Сохранение выпуска", 98)
    path = archive.save(issue)
    counts = issue.counts()
    return {"path": str(path), "total": counts["total"],
            "published": counts["published"], "review": counts["review"]}


def month_title(year: int, month: int) -> str:
    return f"{MONTHS_NOMINATIVE[month]} {year}"


# ------------------------------------------------------------------ приложение


def create_app() -> FastAPI:
    application = FastAPI(title="AstroCalendar", docs_url=None, redoc_url=None)
    application.add_middleware(
        SessionMiddleware, secret_key=session_secret(),
        session_cookie="astrocal", max_age=SESSION_HOURS * 3600,
        same_site="lax", https_only=_https_only())
    application.mount("/static", StaticFiles(directory=str(HERE / "static")),
                      name="static")
    _routes(application)
    return application


def _https_only() -> bool:
    import os

    return os.environ.get("ASTROCAL_WEB_INSECURE", "").strip() != "1"


def _page(request: Request, name: str, user: str, **context) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request, name, {"user": user, "months": MONTHS_NOMINATIVE, **context})


def _routes(application: FastAPI) -> None:

    @application.exception_handler(401)
    async def unauthorised(request: Request, _exc):        # noqa: ANN001
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "нужен вход"}, status_code=401)
        return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)

    # ------------------------------------------------------------ вход

    @application.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request):
        if request.session.get("user"):
            return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)
        return TEMPLATES.TemplateResponse(request, "login.html", {"error": ""})

    @application.post("/login", response_class=HTMLResponse)
    async def login(request: Request, username: str = Form(""),
                    password: str = Form("")):
        try:
            user = authenticate(username, password, client_address(request))
        except AuthError as error:
            return TEMPLATES.TemplateResponse(
                request, "login.html", {"error": str(error)}, status_code=401)
        request.session.clear()
        request.session["user"] = user.name
        request.session["since"] = dt.datetime.now(dt.timezone.utc).isoformat()
        return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)

    @application.post("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)

    # ------------------------------------------------------------ список

    @application.get("/", response_class=HTMLResponse)
    async def index(request: Request, user: str = Depends(current_user)):
        now = dt.datetime.now(cfg.MSK)
        return _page(request, "issues.html", user,
                     issues=archive.available(),
                     jobs=jobs.MANAGER.all()[:8],
                     year=now.year, month=now.month)

    @application.post("/issues/new")
    async def start_calculation(request: Request, year: int = Form(...),
                                month: int = Form(...),
                                horizons: str = Form(""),
                                user: str = Depends(current_user)):
        if not (1900 <= year <= 2150 and 1 <= month <= 12):
            raise HTTPException(status_code=400, detail="неверный месяц")
        existing = jobs.MANAGER.find_for("calc", year=year, month=month)
        if existing is not None:
            return RedirectResponse(f"/jobs/{existing.id}",
                                    status_code=HTTP_303_SEE_OTHER)
        job = jobs.MANAGER.submit(
            "calc", f"Расчёт выпуска {month_title(year, month)}",
            compute_and_store, year, month, horizons == "on",
            payload={"year": year, "month": month})
        return RedirectResponse(f"/jobs/{job.id}",
                                status_code=HTTP_303_SEE_OTHER)

    # ------------------------------------------------------------ задачи

    @application.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_page(request: Request, job_id: str,
                       user: str = Depends(current_user)):
        job = jobs.MANAGER.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="задача не найдена")
        return _page(request, "job.html", user, job=job)

    @application.get("/api/jobs/{job_id}")
    async def job_status(job_id: str, user: str = Depends(current_user)):
        job = jobs.MANAGER.get(job_id)
        if job is None:
            raise HTTPException(status_code=404)
        return JSONResponse(job.as_dict())

    # ------------------------------------------------------------ выпуск

    @application.get("/issues/{year}-{month}", response_class=HTMLResponse)
    async def issue_page(request: Request, year: int, month: int,
                         user: str = Depends(current_user)):
        issue = load_issue(year, month)
        return _page(request, "issue.html", user, issue=issue,
                     title=month_title(year, month),
                     visible=issue.visible_events(), counts=issue.counts(),
                     groups=grouped_kinds(), ranks=RANKS,
                     publication=service.publication(issue))

    @application.post("/issues/{year}-{month}/filters")
    async def set_filters(request: Request, year: int, month: int,
                          user: str = Depends(current_user)):
        issue = load_issue(year, month)
        form = await request.form()
        kinds = set(form.getlist("kind"))
        ranks = set(form.getlist("rank"))
        issue.enabled_kinds = kinds
        issue.enabled_ranks = ranks or {"must"}
        issue.icons = form.get("icons") == "on"
        archive.save(issue)
        return RedirectResponse(f"/issues/{year}-{month:02d}",
                                status_code=HTTP_303_SEE_OTHER)

    @application.post("/api/issues/{year}-{month}/toggle")
    async def toggle_event(year: int, month: int, request: Request,
                           user: str = Depends(current_user)):
        body = await request.json()
        issue = load_issue(year, month)
        item = issue.by_id(str(body.get("id", "")))
        if item is None:
            raise HTTPException(status_code=404, detail="событие не найдено")
        item.selected = bool(body.get("selected"))
        archive.save(issue)
        counts = issue.counts()
        publication = service.publication(issue)
        return JSONResponse({"published": counts["published"],
                             "length": publication.length,
                             "parts": len(publication.parts)})

    @application.post("/api/issues/{year}-{month}/text")
    async def edit_text(year: int, month: int, request: Request,
                        user: str = Depends(current_user)):
        body = await request.json()
        issue = load_issue(year, month)
        item = issue.by_id(str(body.get("id", "")))
        if item is None:
            raise HTTPException(status_code=404, detail="событие не найдено")
        text = (body.get("text") or "").strip()
        # пустая правка означает возврат к расчётному тексту, а не пустую строку
        item.editor_text = text or None
        archive.save(issue)
        return JSONResponse({"text": item.text, "edited": item.edited,
                             "line": item.line()})

    @application.get("/issues/{year}-{month}/publication",
                     response_class=HTMLResponse)
    async def publication_page(request: Request, year: int, month: int,
                               user: str = Depends(current_user)):
        issue = load_issue(year, month)
        return _page(request, "publication.html", user, issue=issue,
                     title=month_title(year, month),
                     publication=service.publication(issue))

    @application.get("/issues/{year}-{month}/qa", response_class=HTMLResponse)
    async def qa_page(request: Request, year: int, month: int,
                      user: str = Depends(current_user)):
        issue = load_issue(year, month)
        flagged = [item for item in issue.ordered()
                   if item.event.flags]
        return _page(request, "qa.html", user, issue=issue,
                     title=month_title(year, month), flagged=flagged,
                     counts=issue.counts())

    @application.get("/issues/{year}-{month}/download/{kind}")
    async def download(year: int, month: int, kind: str,
                       user: str = Depends(current_user)):
        issue = load_issue(year, month)
        stem = f"calendar_{year:04d}-{month:02d}"
        if kind == "txt":
            body = service.publication(issue).plain_text
            return PlainTextResponse(body, headers=_attachment(f"{stem}.txt"))
        if kind == "md":
            return PlainTextResponse(service.publication_markdown(issue),
                                     headers=_attachment(f"{stem}.md"))
        if kind == "json":
            body = json.dumps(service.publication_json(issue),
                              ensure_ascii=False, indent=2)
            return Response(body, media_type="application/json",
                            headers=_attachment(f"{stem}.json"))
        if kind == "protocol":
            return PlainTextResponse(service.protocol_text(issue),
                                     headers=_attachment(f"protocol_{stem}.md"))
        if kind == "qa":
            return PlainTextResponse(service.qa_report_text(issue),
                                     headers=_attachment(f"QA_{stem}.md"))
        raise HTTPException(status_code=404, detail="неизвестный формат")

    # ------------------------------------------------------------ живая лента

    @application.get("/live", response_class=HTMLResponse)
    async def live_page(request: Request, user: str = Depends(current_user)):
        from astrocal.live.state import LiveState

        state = LiveState()
        job = jobs.MANAGER.active_of_kind("live")
        return _page(request, "live.html", user, records=_live_records(),
                     unread=state.unread_count(), job=job)

    @application.post("/live/refresh")
    async def live_refresh(request: Request, user: str = Depends(current_user)):
        existing = jobs.MANAGER.active_of_kind("live")
        if existing is not None:
            return RedirectResponse(f"/jobs/{existing.id}",
                                    status_code=HTTP_303_SEE_OTHER)
        job = jobs.MANAGER.submit("live", "Обновление живой ленты",
                                  _refresh_live)
        return RedirectResponse(f"/jobs/{job.id}",
                                status_code=HTTP_303_SEE_OTHER)

    @application.get("/health")
    async def health():
        return JSONResponse({"status": "ok",
                             "time": dt.datetime.now(cfg.MSK).isoformat()})


def _attachment(filename: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


# ------------------------------------------------------------------ лента


LIVE_CACHE: dict = {"records": [], "updated": None}


def _refresh_live(progress=None) -> dict:
    from astrocal_app.livefeed import Feed

    feed = Feed()
    result = feed.refresh(progress=progress)
    LIVE_CACHE["records"] = feed.visible()
    LIVE_CACHE["updated"] = dt.datetime.now(cfg.MSK)
    return {"new": result.new, "updated": result.updated,
            "unchanged": result.unchanged, "errors": result.errors}


def _live_records() -> list:
    return LIVE_CACHE.get("records") or []


app_instance = None


def get_app() -> FastAPI:
    """Ленивое создание: до чтения ключа сессии приложение не собирается."""
    global app_instance
    if app_instance is None:
        app_instance = create_app()
    return app_instance
