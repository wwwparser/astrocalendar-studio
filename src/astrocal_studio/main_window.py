"""Главное окно AstroCalendar Studio.

Окно только связывает виджеты и сервисный слой: расчёты живут в `astrocal`,
модель выпуска — в `astrocal_app`, отрисовка карт — в `astrocal.render`. Здесь
нет ни одной астрономической формулы, и это сознательно.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox,
                               QHBoxLayout, QInputDialog, QLabel, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

from astrocal import config as cfg
from astrocal.cities import by_key
from astrocal_app import bootstrap, datastatus, live, service, workspace

from . import theme
from .widgets.data_panel import DataStatusPanel, LivePanel
from .widgets.event_details import EventDetails
from .widgets.events_table import EventsTable
from .widgets.parameters_panel import ParametersPanel
from .widgets.qa_panel import QaPanel
from .widgets.telegram_preview import TelegramPreview
from .workers import TaskRunner

ORGANISATION = "AstroCalendar"
APPLICATION = "AstroCalendar Studio"
MAPS_DIR = cfg.OUT / "maps"


class MainWindow(QMainWindow):
    def __init__(self, theme_name: str = "dark"):
        super().__init__()
        self.theme_name = theme_name
        self.tokens = theme.tokens(theme_name)
        self.settings = QSettings(ORGANISATION, APPLICATION)
        self.runner = TaskRunner()
        self.issue = None
        self.live_items: list = []

        self.setWindowTitle(APPLICATION)
        self.setMinimumSize(1180, 700)
        self._build()
        self._menu()
        self._restore_settings()
        QTimer.singleShot(200, self._check_data)

    # ------------------------------------------------------------ интерфейс

    def _build(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.splitter = QSplitter(Qt.Horizontal)

        self.parameters = ParametersPanel()
        self.parameters.setMinimumWidth(260)
        self.parameters.setMaximumWidth(420)
        self.splitter.addWidget(self.parameters)

        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        self.table = EventsTable(self.tokens)
        centre_layout.addWidget(self.table, 3)
        self.details = EventDetails()
        centre_layout.addWidget(self.details, 2)
        self.splitter.addWidget(centre)

        right = QTabWidget()
        self.preview = TelegramPreview(self.tokens)
        right.addTab(self.preview, "Публикация")
        self.qa_panel = QaPanel(self.tokens)
        right.addTab(self.qa_panel, "Проверка")
        self.data_panel = DataStatusPanel(self.tokens)
        right.addTab(self.data_panel, "Данные")
        self.live_panel = LivePanel(self.tokens)
        right.addTab(self.live_panel, "Live")
        right.setMinimumWidth(430)
        self.right_tabs = right
        self.splitter.addWidget(right)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setSizes([290, 900, 470])
        layout.addWidget(self.splitter, 1)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Готово")
        self.status_label.setObjectName("Status")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.progress)
        layout.addLayout(status_row)

        self.setCentralWidget(central)
        self._connect()

    def _connect(self) -> None:
        self.parameters.calculate_requested.connect(self.calculate)
        self.parameters.refresh_data_requested.connect(
            lambda: self.refresh_data("all"))
        self.parameters.generate_maps_requested.connect(self.generate_maps)
        self.parameters.filters_changed.connect(self.apply_filters)
        self.parameters.mode_changed.connect(self._mode_changed)

        self.table.current_changed.connect(self.details.show_event)
        self.table.changed.connect(self.update_preview)

        self.details.text_saved.connect(self._save_text)
        self.details.text_reverted.connect(self._revert_text)
        self.details.map_requested.connect(self._build_map)

        self.preview.save_requested.connect(self._save_publication)
        self.preview.send_requested.connect(self._send_to_telegram)
        self.preview.copied.connect(self.set_status)

        self.qa_panel.open_report_requested.connect(self._open_qa_report)
        self.qa_panel.recheck_requested.connect(lambda: self.calculate(True))

        self.data_panel.refresh_requested.connect(self.refresh_data)
        self.data_panel.download_requested.connect(self.download_data)
        self.live_panel.refresh_requested.connect(self.refresh_live)

    def _menu(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")
        for title, shortcut, handler in (
                ("Рассчитать выпуск", "Ctrl+R", self.calculate),
                ("Сохранить состояние", QKeySequence.Save, self.save_workspace),
                ("Открыть сохранённое", "Ctrl+O", self.load_workspace),
                ("Сохранить выходные файлы", "Ctrl+Shift+S", self.write_outputs),
                ("Выход", QKeySequence.Quit, self.close)):
            action = QAction(title, self)
            action.setShortcut(shortcut)
            action.triggered.connect(handler)
            file_menu.addAction(action)

        data_action = QAction("Скачать недостающие данные…", self)
        data_action.triggered.connect(lambda: self.download_data(True))
        file_menu.insertAction(file_menu.actions()[1], data_action)

        edit_menu = self.menuBar().addMenu("Правка")
        add_action = QAction("Добавить событие вручную…", self)
        add_action.setShortcut("Ctrl+N")
        add_action.triggered.connect(self.add_manual_event)
        edit_menu.addAction(add_action)

        view_menu = self.menuBar().addMenu("Вид")
        for label, name in (("Тёмная тема", "dark"), ("Светлая тема", "light")):
            action = QAction(label, self)
            action.triggered.connect(lambda _=False, n=name: self.switch_theme(n))
            view_menu.addAction(action)

        help_menu = self.menuBar().addMenu("Справка")
        about = QAction("О программе", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    # ------------------------------------------------------------ данные

    def _check_data(self) -> None:
        """При первом запуске данных ещё нет — предложить скачать сразу."""
        required = bootstrap.missing(required_only=True)
        self.set_status(bootstrap.status_summary())
        if not required:
            return
        self.right_tabs.setCurrentWidget(self.data_panel)
        listing = "\n".join(f"· {item.title} — {item.size_text}"
                            for item in required)
        answer = QMessageBox.question(
            self, "Нужно скачать данные",
            "Для расчёта не хватает эфемерид и каталогов:\n\n"
            f"{listing}\n\n"
            f"Всего {bootstrap.total_size_mb(required)} МБ. Скачать сейчас?\n\n"
            "Файлы лягут в каталог data рядом с программой и понадобятся "
            "только один раз.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self.download_data(required_only=True)

    def download_data(self, required_only: bool = True) -> None:
        """Скачать недостающие эфемериды и каталоги."""
        if self.runner.busy:
            self.set_status("Дождитесь окончания текущей операции")
            return
        items = bootstrap.missing(required_only=required_only)
        if not items:
            self.set_status("Скачивать нечего — все данные на месте")
            return
        self._set_busy(True, f"Загрузка данных: {len(items)} файл(ов), "
                             f"{bootstrap.total_size_mb(items)} МБ…")
        self.runner.submit(
            "download", bootstrap.download_all, required_only,
            on_progress=self._progress,
            on_result=self._download_done,
            on_error=self._task_failed)

    def _download_done(self, message: str) -> None:
        self._set_busy(False)
        self.data_panel.reload()
        self.set_status(str(message))
        if not bootstrap.missing(required_only=True):
            self.right_tabs.setCurrentWidget(self.preview)

    # ------------------------------------------------------------ расчёт

    def calculate(self, use_horizons: bool = True) -> None:
        if self.runner.busy:
            self.set_status("Дождитесь окончания текущей операции")
            return
        missing_data = bootstrap.missing(required_only=True)
        if missing_data:
            self._check_data()
            return
        year, month = self.parameters.year, self.parameters.month
        self._set_busy(True, f"Расчёт выпуска {month:02d}.{year}…")
        self.runner.submit(
            "compute", service.compute_issue, year, month,
            use_horizons=bool(use_horizons),
            on_progress=self._progress,
            on_result=self._issue_ready,
            on_error=self._task_failed)

    def _issue_ready(self, issue) -> None:
        self.issue = issue
        restored = workspace.load_into(issue)
        self.parameters.set_enabled_kinds(issue.enabled_kinds)
        self.parameters.set_enabled_ranks(issue.enabled_ranks)
        self.apply_filters()
        self.qa_panel.show_issue(issue)
        self.data_panel.reload()
        self._set_busy(False)

        counts = issue.counts()
        message = (f"Рассчитано {counts['total']}, в публикации "
                   f"{counts['published']}, REVIEW {counts['review']}")
        if restored["restored"]:
            message += f", восстановлено решений: {restored['restored']}"
        self.set_status(message)

        if restored["changed"]:
            QMessageBox.information(
                self, "Исходные данные изменились",
                "Исходные данные этих событий изменились после вашей "
                "редакторской правки:\n\n"
                + "\n\n".join(workspace.describe_changes(issue)[:10]))

    def apply_filters(self) -> None:
        if self.issue is None:
            return
        self.issue.enabled_kinds = self.parameters.enabled_kinds()
        self.issue.enabled_ranks = self.parameters.enabled_ranks()
        self.issue.primary_city = self.parameters.city_key
        self.table.set_items(self.issue.visible_events())
        self.update_preview()

    def update_preview(self) -> None:
        if self.issue is None:
            return
        self.preview.set_publication(service.publication(self.issue))
        counts = self.issue.counts()
        self.setWindowTitle(
            f"{APPLICATION} — {self.issue.month:02d}.{self.issue.year} "
            f"({counts['published']} событий в посте)")

    # ------------------------------------------------------------ редактирование

    def _save_text(self, item, text: str) -> None:
        item.editor_text = text or None
        self.table.refresh()
        self.update_preview()
        self.set_status("Редакция сохранена")

    def _revert_text(self, item) -> None:
        item.revert()
        self.table.refresh()
        self.update_preview()
        self.set_status("Возвращён расчётный текст")

    def add_manual_event(self) -> None:
        if self.issue is None:
            self.set_status("Сначала рассчитайте выпуск")
            return
        text, accepted = QInputDialog.getText(
            self, "Ручное событие",
            "Текст события (например: «Лекция в планетарии»):")
        if not accepted or not text.strip():
            return
        when, accepted = QInputDialog.getText(
            self, "Ручное событие", "Дата и время (ДД.ММ ЧЧ:ММ):",
            text=f"01.{self.issue.month:02d} 20:00")
        if not accepted:
            return
        try:
            moment = dt.datetime.strptime(
                f"{when.strip()} {self.issue.year}", "%d.%m %H:%M %Y")
        except ValueError:
            QMessageBox.warning(self, "Неверная дата",
                                "Ожидается формат ДД.ММ ЧЧ:ММ")
            return
        service.add_manual_event(self.issue, moment.replace(tzinfo=cfg.MSK),
                                 text.strip())
        self.apply_filters()
        self.set_status("Добавлено ручное событие — оно помечено как ручное")

    # ------------------------------------------------------------ карты

    def _build_map(self, item, kind: str) -> None:
        if self.runner.busy:
            self.set_status("Дождитесь окончания текущей операции")
            return
        city = by_key(self.parameters.city_key) or by_key("москва")
        self._set_busy(True, "Построение карты…")
        self.runner.submit(
            "map", _render_map, item, kind, city,
            on_result=lambda path, i=item, k=kind: self._map_ready(i, k, path),
            on_error=self._task_failed)

    def _map_ready(self, item, kind: str, path) -> None:
        self._set_busy(False)
        if path is None:
            self.details.show_map_message(
                kind, "Для этого типа события такая карта не строится.")
            self.set_status("Карта для этого события не требуется")
            return
        item.maps[kind] = str(path)
        if self.details.item is item:
            self.details.show_map(kind, Path(path))
        self.set_status(f"Карта сохранена: {path}")

    def generate_maps(self) -> None:
        if self.issue is None:
            self.set_status("Сначала рассчитайте выпуск")
            return
        if self.runner.busy:
            return
        city = by_key(self.parameters.city_key) or by_key("москва")
        items = [item for item in self.issue.published() if item.rank == "must"]
        if not items:
            self.set_status("Нет событий ранга must для карт")
            return
        self._set_busy(True, f"Карты для {len(items)} событий…")
        self.runner.submit(
            "maps", _render_batch, items, city,
            on_progress=self._progress,
            on_result=self._batch_ready,
            on_error=self._task_failed)

    def _batch_ready(self, produced: list) -> None:
        self._set_busy(False)
        self.set_status(f"Построено карт: {len(produced)} → {MAPS_DIR}")

    # ------------------------------------------------------------ данные и live

    def refresh_data(self, what: str) -> None:
        if self.runner.busy:
            return
        year, month = self.parameters.year, self.parameters.month
        actions = {
            "all": lambda progress=None: datastatus.refresh_all(year, month, progress),
            "tle": lambda progress=None: datastatus.refresh_tle(progress),
            "comets": lambda progress=None: datastatus.refresh_comets(progress),
            "launches": lambda progress=None: datastatus.refresh_launches(
                year, month, progress),
            "neo": lambda progress=None: datastatus.refresh_neo(year, month, progress),
        }
        self._set_busy(True, "Обновление данных…")
        self.runner.submit(
            "refresh", actions.get(what, actions["all"]),
            on_progress=self._progress,
            on_result=self._refresh_done,
            on_error=self._task_failed)

    def _refresh_done(self, message: str) -> None:
        self._set_busy(False)
        self.data_panel.reload()
        self.set_status(str(message).replace("\n", " · "))

    def refresh_live(self, hours: float) -> None:
        if self.runner.busy:
            return
        self._set_busy(True, "Оперативная сводка…")
        self.runner.submit(
            "live", live.collect, self.parameters.city_key, hours,
            on_progress=self._progress,
            on_result=self._live_ready,
            on_error=self._task_failed)

    def _live_ready(self, items: list) -> None:
        self._set_busy(False)
        self.live_items = items
        self.live_panel.show_items(items)
        self.set_status(f"Live: событий {len(items)}")

    def _mode_changed(self, mode: str) -> None:
        if mode == "live":
            self.right_tabs.setCurrentWidget(self.live_panel)
            self.set_status("Режим Live: данные не кэшируются, "
                            "нажмите «Обновить сейчас»")
        else:
            self.right_tabs.setCurrentWidget(self.preview)

    # ------------------------------------------------------------ сохранение

    def save_workspace(self) -> None:
        if self.issue is None:
            return
        path = workspace.save(self.issue)
        self.set_status(f"Состояние сохранено: {path}")

    def load_workspace(self) -> None:
        if self.issue is None:
            self.set_status("Сначала рассчитайте выпуск")
            return
        restored = workspace.load_into(self.issue)
        self.apply_filters()
        self.set_status(f"Восстановлено решений: {restored['restored']}")

    def write_outputs(self) -> None:
        if self.issue is None:
            return
        files = service.write_outputs(self.issue)
        self.set_status("Сохранено: " + ", ".join(p.name for p in files.values()))

    def _save_publication(self, kind: str) -> None:
        if self.issue is None:
            return
        stem = f"calendar_{self.issue.year:04d}-{self.issue.month:02d}"
        if kind == "txt":
            path = self.preview.ask_save_path(str(cfg.OUT / f"{stem}.txt"),
                                              "Текст (*.txt)")
            if path:
                Path(path).write_text(service.publication(self.issue).plain_text,
                                      encoding="utf-8")
        elif kind == "md":
            path = self.preview.ask_save_path(str(cfg.OUT / f"{stem}.md"),
                                              "Markdown (*.md)")
            if path:
                Path(path).write_text(service.publication_markdown(self.issue),
                                      encoding="utf-8")
        else:
            import json
            path = self.preview.ask_save_path(str(cfg.OUT / f"{stem}.json"),
                                              "JSON (*.json)")
            if path:
                Path(path).write_text(
                    json.dumps(service.publication_json(self.issue),
                               ensure_ascii=False, indent=2), encoding="utf-8")
        if path:
            self.set_status(f"Сохранено: {path}")

    def _send_to_telegram(self) -> None:
        if self.issue is None:
            return
        publication = service.publication(self.issue)
        answer = QMessageBox.question(
            self, "Отправить в Telegram",
            "Отправить сообщение в канал?\n"
            "Действие будет выполнено немедленно.\n\n"
            f"Частей: {len(publication.parts)}, символов: {publication.length}.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self._set_busy(True, "Отправка в Telegram…")
        self.runner.submit("send", _send_publication, publication,
                           on_result=lambda message: (self._set_busy(False),
                                                      self.set_status(message)),
                           on_error=self._task_failed)

    def _open_qa_report(self) -> None:
        if self.issue is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("QA-отчёт")
        dialog.resize(900, 640)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(service.qa_report_text(self.issue))
        view.setReadOnly(True)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    # ------------------------------------------------------------ служебное

    def _progress(self, stage: str, percent: int) -> None:
        self.progress.setValue(percent)
        self.status_label.setText(stage)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.progress.setVisible(busy)
        self.progress.setValue(0 if busy else 100)
        self.parameters.set_busy(busy)
        if message:
            self.status_label.setText(message)
        elif not busy:
            self.status_label.setText("Готово")

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _task_failed(self, message: str, details: str) -> None:
        self._set_busy(False)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Не удалось выполнить операцию")
        box.setText(message)
        box.setDetailedText(details)
        box.exec()
        self.set_status(f"Ошибка: {message}")

    def switch_theme(self, name: str) -> None:
        self.settings.setValue("theme", name)
        QMessageBox.information(
            self, "Тема", "Тема будет применена при следующем запуске.")

    def _about(self) -> None:
        QMessageBox.about(
            self, "О программе",
            "<b>AstroCalendar Studio</b><br><br>"
            "Настольная система подготовки, проверки и визуализации "
            "астрономических календарей.<br><br>"
            "Расчёт: JPL DE440s, Horizons, MPC, IOTA, CNEOS, Celestrak, "
            "Hipparcos, OpenNGC.<br>"
            "Эфемериды и каталоги программа скачивает сама: вкладка "
            "«Данные» → «Скачать недостающее».<br>"
            "Проект создавался в том числе на реальных выпусках канала "
            "AstroAlert, но не является официальным продуктом канала.")

    # ------------------------------------------------------------ настройки окна

    def _restore_settings(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("splitter")
        if state and not self.splitter.restoreState(state):
            self.splitter.setSizes([290, 900, 470])
        year = self.settings.value("year", type=int)
        month = self.settings.value("month", type=int)
        if year and month:
            self.parameters.set_period(year, month)
        city = self.settings.value("city")
        if city:
            self.parameters.set_city(str(city))

    def closeEvent(self, event):        # noqa: N802 (Qt naming)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        self.settings.setValue("year", self.parameters.year)
        self.settings.setValue("month", self.parameters.month)
        self.settings.setValue("city", self.parameters.city_key)
        if self.issue is not None:
            try:
                workspace.save(self.issue)
            except OSError:
                pass
        QTimer.singleShot(0, lambda: self.runner.wait(2000))
        super().closeEvent(event)


# ------------------------------------------------------------------ задачи


def _render_map(item, kind: str, city):
    """Построить карту события. Выполняется в рабочем потоке."""
    from astrocal.render import event_map, visibility_map

    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{item.event_id}_{kind}"
    path = MAPS_DIR / f"{stem}.png"

    if kind == "sky":
        return event_map.for_event(item.event, city, path)

    if item.kind in ("solar_eclipse", "lunar_eclipse"):
        from astrocal.core import timescale
        from astrocal.events.eclipses import solar_bands
        t = timescale().from_datetime(item.event.when)
        bands = solar_bands(t)
        return visibility_map.eclipse_band(
            bands, path, item.calculated_text[:70],
            f"{item.when:%d.%m.%Y %H:%M} МСК")

    if item.kind == "occultation":
        from astrocal.core import timescale
        from astrocal.events.occultations import visibility_band
        planet = next((name for name in ("mercury", "venus", "mars", "jupiter",
                                         "saturn", "uranus", "neptune")
                       if name in (item.event.meta or {}).get("planet", "")), None)
        if planet is None:
            return None
        t = timescale().from_datetime(item.event.when)
        band = visibility_band(t, planet)
        return visibility_map.band(band["lat"], band["lon"], band["mask"], path,
                                   "Полоса видимости покрытия",
                                   f"{item.when:%d.%m.%Y %H:%M} МСК")
    return None


def _render_batch(items, city, progress=None):
    from astrocal.render import event_map

    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    produced = []
    for index, item in enumerate(items):
        if progress:
            progress(f"Карта {index + 1} из {len(items)}",
                     int(100 * index / max(1, len(items))))
        try:
            path = event_map.for_event(
                item.event, city, MAPS_DIR / f"{item.event_id}_sky.png")
        except Exception:
            path = None
        if path:
            item.maps["sky"] = str(path)
            produced.append(path)
    if progress:
        progress("Готово", 100)
    return produced


def _send_publication(publication):
    from astrocal_app.publishing import send
    return send(publication)
