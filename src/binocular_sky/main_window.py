"""Главное окно Binocular Sky.

Окно ничего не считает само: оно собирает состояние (площадка, прибор, момент),
отправляет расчёты в фоновые задачи и раскладывает результат по панелям. Такое
разделение нужно не ради чистоты, а ради отзывчивости: перебор нескольких сотен
объектов на ночь занимает секунду с лишним, и в потоке интерфейса он выглядел бы
зависанием ровно после нажатия главной кнопки.
"""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QLabel, QMainWindow, QMessageBox, QSplitter,
                               QStatusBar, QTabWidget, QVBoxLayout, QWidget)

from . import storage, theme
from .models.observer import ObserverProfile
from .services import (astronomy_service as astro, catalog_service,
                       horizon_service, observing_service,
                       recommendation_service as rec, scene_service)
from .widgets.binocular_panel import SidePanel
from .widgets.object_details import ObjectDetails
from .widgets.plan_panel import PlanPanel
from .widgets.settings_panel import (BinocularDialog, LandscapeDialog,
                                     ObserverDialog, SetupWizard)
from .widgets.sky_view import SkyView
from .widgets.timeline import Timeline
from .widgets.tonight_panel import TonightPanel
from .workers import Runner, shutdown as shutdown_workers

# Пересчёт неба при движении ползунка не должен идти на каждый пиксель:
# короткая задержка склеивает серию движений в один расчёт.
SNAPSHOT_DELAY_MS = 120


class MainWindow(QMainWindow):
    def __init__(self, settings: storage.Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Binocular Sky")
        self.resize(1500, 940)

        self.date = dt.date.today()
        self.night = None
        self.horizon = None
        self.recommendations: list = []
        self.by_id: dict = {}
        self.current: rec.Recommendation | None = None
        self.seen_ids: set = set()
        self.binocular_mode = False

        self._build_ui()
        self._build_menu()
        self._connect()

        self.snapshot_runner = Runner(self)
        self.tonight_runner = Runner(self)
        self.detail_runner = Runner(self)
        self.snapshot_runner.finished.connect(self._snapshot_ready)
        self.snapshot_runner.failed.connect(self._task_failed)
        self.tonight_runner.finished.connect(self._tonight_ready)
        self.tonight_runner.failed.connect(self._task_failed)
        self.tonight_runner.busy_changed.connect(self.tonight_panel.set_busy)
        self.detail_runner.finished.connect(self._detail_ready)
        self.detail_runner.failed.connect(self._task_failed)

        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setSingleShot(True)
        self._snapshot_timer.setInterval(SNAPSHOT_DELAY_MS)
        self._snapshot_timer.timeout.connect(self._request_snapshot)

        self.apply_theme()
        self.reload_profiles()
        self.set_date(dt.date.today(), refresh=False)
        self.sky_view.ready.connect(self._on_viewer_ready)

    # ------------------------------------------------------------ построение

    def _build_ui(self) -> None:
        self.sky_view = SkyView(self)
        self.side = SidePanel(self)
        self.tonight_panel = TonightPanel(self)
        self.details = ObjectDetails(self)
        self.plan_panel = PlanPanel(self)
        self.timeline = Timeline(self)

        right = QTabWidget()
        right.addTab(self.tonight_panel, "Сегодня")
        right.addTab(self.details, "Объект")
        right.addTab(self.plan_panel, "План")
        self.right_tabs = right

        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        centre_layout.setSpacing(0)
        centre_layout.addWidget(self.sky_view, 1)
        centre_layout.addWidget(self.timeline)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.side)
        splitter.addWidget(centre)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 860, 340])
        self.setCentralWidget(splitter)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel("")
        self.status.addPermanentWidget(self.status_label)

    def _build_menu(self) -> None:
        bar = self.menuBar()

        view_menu = bar.addMenu("Вид")
        self.night_action = QAction("Ночной режим", self, checkable=True)
        self.night_action.setShortcut(QKeySequence("Ctrl+N"))
        self.night_action.setChecked(self.settings.night_mode)
        self.night_action.toggled.connect(self.set_night_mode)
        view_menu.addAction(self.night_action)

        self.fullscreen_action = QAction("Полный экран", self, checkable=True)
        self.fullscreen_action.setShortcut(QKeySequence("F11"))
        self.fullscreen_action.toggled.connect(self._toggle_fullscreen)
        view_menu.addAction(self.fullscreen_action)

        self.binocular_action = QAction("Вид в бинокль", self, checkable=True)
        self.binocular_action.setShortcut(QKeySequence("B"))
        self.binocular_action.toggled.connect(self.set_binocular_mode)
        view_menu.addAction(self.binocular_action)

        settings_menu = bar.addMenu("Настройки")
        settings_menu.addAction("Места наблюдения…", self.edit_observers)
        settings_menu.addAction("Приборы…", self.edit_binoculars)
        settings_menu.addAction("Участок…", self.edit_landscape)
        settings_menu.addSeparator()
        settings_menu.addAction("Мастер первой настройки…", self.run_wizard)

        help_menu = bar.addMenu("Справка")
        help_menu.addAction("О программе", self._about)

    def _connect(self) -> None:
        self.side.date_changed.connect(self.set_date)
        self.side.tonight_requested.connect(lambda: self.set_date(dt.date.today()))
        self.side.observer_changed.connect(self.set_observer)
        self.side.binocular_changed.connect(self.set_binocular)
        self.side.options_changed.connect(self.schedule_snapshot)
        self.side.search_activated.connect(self.search)
        self.side.search_result_chosen.connect(self.select_target)
        self.side.edit_observer.connect(self.edit_observers)
        self.side.edit_binocular.connect(self.edit_binoculars)
        self.side.edit_landscape.connect(self.edit_landscape)

        self.timeline.moment_changed.connect(self._moment_changed)

        self.tonight_panel.refresh_requested.connect(self.compute_tonight)
        self.tonight_panel.surprise_requested.connect(self.surprise)
        self.tonight_panel.target_activated.connect(self.select_target)
        self.tonight_panel.add_to_plan.connect(self.add_to_plan)

        self.details.look_requested.connect(self._look_at_current)
        self.details.binocular_requested.connect(
            lambda: self.binocular_action.setChecked(True))
        self.details.track_requested.connect(self.show_track)
        self.details.plan_requested.connect(
            lambda: self.add_to_plan(self.details.target_id))

        self.plan_panel.target_activated.connect(self.select_target)
        self.plan_panel.optimise_requested.connect(self.optimise_plan)
        self.plan_panel.remove_requested.connect(self.remove_from_plan)
        self.plan_panel.clear_requested.connect(self.clear_plan)

        self.sky_view.object_selected.connect(self.select_target)

    # ------------------------------------------------------------ состояние

    @property
    def observer(self) -> ObserverProfile:
        return self.settings.observer

    @property
    def binocular(self):
        return self.settings.binocular

    @property
    def landscape(self):
        return self.settings.landscape_for()

    def reload_profiles(self) -> None:
        self.side.set_observers(self.settings.observers,
                                self.settings.active_observer)
        self.side.set_binoculars(self.settings.binoculars,
                                 self.settings.active_binocular)
        self.horizon = horizon_service.profile_for(self.landscape, self.observer)

    def _on_viewer_ready(self) -> None:
        self.sky_view.set_night_mode(self.settings.night_mode)
        self._request_snapshot()
        if self.landscape.is_demo:
            self.sky_view.set_banner(
                "DEMO-участок: дом и деревья заданы примерными числами. "
                "Замените их своими обмерами в «Настройки → Участок».")

    # ------------------------------------------------------------ дата и время

    def set_date(self, date: dt.date, refresh: bool = True) -> None:
        self.date = date
        self.side.set_date(date)
        self.night = astro.night_for(self.observer, date)
        start = self.night.start or dt.datetime.combine(
            date, dt.time(20, 0), tzinfo=self.observer.tz)
        end = self.night.end or (start + dt.timedelta(hours=9))

        moment = astro.default_moment(self.observer, date)
        now = self.observer.now()
        if start <= now <= end:
            moment = now
        self.timeline.set_night(start, end, moment)
        self.side.set_night_text(self._night_text())
        self.plan_panel.show_plan(self.settings.plan_for(date))
        if refresh:
            self.schedule_snapshot()

    def _night_text(self) -> str:
        night = self.night
        if night is None:
            return ""
        if not night.has_darkness:
            return ("Тёмного времени в эту ночь нет: Солнце не опускается "
                    "ниже −12°.")
        parts = []
        if night.sunset:
            parts.append(f"Закат {night.sunset:%H:%M}")
        parts.append(f"темнеет {night.dark_start:%H:%M}")
        parts.append(f"светает {night.dark_end:%H:%M}")
        if night.sunrise:
            parts.append(f"восход {night.sunrise:%H:%M}")
        return " · ".join(parts)

    def _moment_changed(self, moment: dt.datetime) -> None:
        self.schedule_snapshot()
        if self.binocular_mode and self.current:
            self._request_binocular_field()

    # ------------------------------------------------------------ снимок неба

    def schedule_snapshot(self) -> None:
        self._snapshot_timer.start()

    def _request_snapshot(self) -> None:
        moment = self.timeline.moment
        self.sky_view.set_options(
            showLabels=self.side.labels_check.isChecked(),
            showConstellations=self.side.constellations_check.isChecked())
        self.snapshot_runner.submit(
            scene_service.sky_snapshot, self.observer, self.binocular,
            self.landscape, moment, self.horizon,
            self.side.star_mag_limit)

    def _snapshot_ready(self, snapshot: dict) -> None:
        self.sky_view.show_snapshot(snapshot)
        moon = snapshot["moon"]
        self.status_label.setText(
            f"Солнце {snapshot['sun_altitude']:+.0f}° · "
            f"Луна {moon['alt']:+.0f}°, {moon['phase_name']}, "
            f"{moon['illumination'] * 100:.0f}% · "
            f"предел ≈ {self.binocular.limiting_magnitude(self.observer.bortle, 45.0, 0.0):+.1f}m")

    def _task_failed(self, message: str) -> None:
        self.status.showMessage(message.strip().splitlines()[-1], 8000)

    # ------------------------------------------------------------ площадка

    def set_observer(self, index: int) -> None:
        self.settings.active_observer = index
        self.side.observer_label.setText(self.observer.describe())
        self.horizon = horizon_service.profile_for(self.landscape, self.observer)
        self.recommendations = []
        self.by_id = {}
        self.tonight_panel.show_recommendations([])
        self.details.clear()
        self.set_date(self.date)
        self.save()

    def set_binocular(self, index: int) -> None:
        self.settings.active_binocular = index
        self.side.binocular_label.setText(self.binocular.describe())
        self.schedule_snapshot()
        if self.recommendations:
            self.compute_tonight()
        if self.binocular_mode and self.current:
            self._request_binocular_field()
        self.save()

    # ------------------------------------------------------------ рекомендации

    def compute_tonight(self) -> None:
        self.status.showMessage("Считаю, что видно этой ночью…")
        self.tonight_runner.submit(
            rec.tonight, self.observer, self.binocular, self.landscape,
            self.date, self.horizon, 15, 30)

    def _tonight_ready(self, recommendations: list) -> None:
        self.recommendations = recommendations
        self.by_id = {r.target.id: r for r in recommendations}
        self.tonight_panel.show_recommendations(
            recommendations,
            f"{self.date:%d.%m.%Y} · {self.binocular.short_label} · "
            f"Bortle {self.observer.bortle} · найдено {len(recommendations)}")
        self.right_tabs.setCurrentWidget(self.tonight_panel)
        self.status.showMessage(f"Готово: {len(recommendations)} объектов", 4000)

    def surprise(self) -> None:
        """Кнопка «покажи что-нибудь»: лучший ещё не показанный объект."""
        if not self.recommendations:
            self.compute_tonight()
            self.status.showMessage(
                "Сначала считаю программу на ночь — потом покажу", 4000)
            return
        choice = rec.show_me_something(self.recommendations, self.seen_ids)
        if choice is None:
            return
        self.seen_ids.add(choice.target.id)
        if len(self.seen_ids) >= len(self.recommendations):
            self.seen_ids.clear()
        self.tonight_panel.select_target(choice.target.id)
        self.select_target(choice.target.id)
        self.sky_view.set_banner(f"Попробуйте: {choice.target.name}")

    # ------------------------------------------------------------ выбор цели

    def select_target(self, target_id: str) -> None:
        if not target_id:
            return
        self.sky_view.select(target_id)
        existing = self.by_id.get(target_id)
        if existing is not None:
            self._show_details(existing)
            return
        target = self._find_target(target_id)
        if target is None:
            self.status.showMessage(f"Объект «{target_id}» не найден", 4000)
            return
        self.status.showMessage(f"Считаю условия для {target.name}…")
        self.detail_runner.submit(self._evaluate_target, target)

    def _find_target(self, target_id: str):
        for target in astro.solar_targets(self.timeline.moment):
            if target.id == target_id:
                return target
        return catalog_service.by_id().get(target_id) or \
            catalog_service.find(target_id)

    def _evaluate_target(self, target):
        start = self.night.start or self.timeline.moment
        end = self.night.end or (start + dt.timedelta(hours=8))
        return rec.evaluate(target, self.observer, self.binocular, self.horizon,
                            self.landscape, self.timeline.moment, start, end)

    def _detail_ready(self, recommendation) -> None:
        self.by_id[recommendation.target.id] = recommendation
        self._show_details(recommendation)
        self.status.clearMessage()

    def _show_details(self, recommendation) -> None:
        self.current = recommendation
        where = horizon_service.summarise(recommendation.visibility,
                                          self.landscape, self.observer)
        plan = self.settings.plan_for(self.date)
        self.details.show_target(recommendation, self.binocular, where,
                                 plan.contains(recommendation.target.id))
        self.right_tabs.setCurrentWidget(self.details)
        self.sky_view.set_banner(where)
        self._look_at_current()
        if self.binocular_mode:
            self._request_binocular_field()

    def _look_at_current(self) -> None:
        if self.current is None:
            return
        visibility = self.current.visibility
        self.sky_view.look_at(visibility.azimuth_now, visibility.altitude_now)

    def search(self, query: str) -> None:
        matches = catalog_service.search(query, limit=12)
        solar = [t for t in astro.solar_targets(self.timeline.moment)
                 if catalog_service.normalise(query) in
                 " ".join(t.search_keys())]
        combined = solar + [m for m in matches if m.id not in {s.id for s in solar}]
        self.side.set_search_results(combined)
        if not combined:
            self.side.set_search_status("Ничего не найдено")
        else:
            self.side.set_search_status("")

    # ------------------------------------------------------------ траектория

    def show_track(self) -> None:
        if self.current is None:
            return
        start = self.night.start or self.timeline.moment
        end = self.night.end or (start + dt.timedelta(hours=8))
        track = scene_service.track(self.observer, self.current.target,
                                    self.landscape, self.horizon, start, end)
        self.sky_view.show_track(track)
        self.status.showMessage(
            "Пунктиром показаны участки, закрытые домом и деревьями", 6000)

    # ------------------------------------------------------------ бинокль

    def set_binocular_mode(self, enabled: bool) -> None:
        self.binocular_mode = enabled
        if not enabled:
            self.sky_view.exit_binocular()
            return
        if self.current is None:
            self.binocular_action.setChecked(False)
            self.status.showMessage(
                "Сначала выберите объект — поле строится вокруг него", 4000)
            return
        self._request_binocular_field()

    def _request_binocular_field(self) -> None:
        if self.current is None:
            return
        try:
            field = scene_service.binocular_field(
                self.observer, self.binocular, self.current.target,
                self.timeline.moment)
        except Exception as error:
            self.status.showMessage(f"Не удалось построить поле: {error}", 6000)
            return
        self.sky_view.enter_binocular(field)

    # ------------------------------------------------------------ план

    def add_to_plan(self, target_id: str) -> None:
        recommendation = self.by_id.get(target_id)
        if recommendation is None:
            self.status.showMessage("Сначала выберите объект", 3000)
            return
        plan = self.settings.plan_for(self.date)
        if plan.add(observing_service.item_from_recommendation(recommendation)):
            self.plan_panel.show_plan(plan)
            self.status.showMessage(
                f"{recommendation.target.name} — в плане", 3000)
            self.save()

    def remove_from_plan(self, target_id: str) -> None:
        plan = self.settings.plan_for(self.date)
        plan.remove(target_id)
        self.plan_panel.show_plan(plan)
        self.save()

    def clear_plan(self) -> None:
        plan = self.settings.plan_for(self.date)
        plan.items = []
        self.plan_panel.show_plan(plan)
        self.save()

    def optimise_plan(self) -> None:
        plan = self.settings.plan_for(self.date)
        start = self.night.start or self.timeline.moment
        end = self.night.end or (start + dt.timedelta(hours=8))
        observing_service.optimise(plan, start, end)
        self.plan_panel.show_plan(plan)
        self.save()

    # ------------------------------------------------------------ настройки

    def edit_observers(self) -> None:
        dialog = ObserverDialog(self.settings.observers,
                                self.settings.active_observer, self)
        if dialog.exec() != ObserverDialog.Accepted:
            return
        self.settings.observers = dialog.observers
        self.settings.active_observer = dialog.active
        self.reload_profiles()
        self.set_observer(dialog.active)

    def edit_binoculars(self) -> None:
        dialog = BinocularDialog(self.settings.binoculars,
                                 self.settings.active_binocular, self)
        if dialog.exec() != BinocularDialog.Accepted:
            return
        self.settings.binoculars = dialog.binoculars
        self.settings.active_binocular = dialog.active
        self.side.set_binoculars(self.settings.binoculars, dialog.active)
        self.set_binocular(dialog.active)

    def edit_landscape(self) -> None:
        dialog = LandscapeDialog(self.landscape, self)
        if dialog.exec() != LandscapeDialog.Accepted:
            return
        self.settings.set_landscape(self.observer, dialog.landscape)
        self.horizon = horizon_service.profile_for(dialog.landscape, self.observer)
        self.sky_view.set_banner("" if not dialog.landscape.is_demo else
                                 "DEMO-участок: замените обмеры своими")
        self.schedule_snapshot()
        self.recommendations = []
        self.tonight_panel.show_recommendations([])
        self.save()

    def run_wizard(self) -> None:
        wizard = SetupWizard(self.observer, self.binocular, self)
        if wizard.exec() != SetupWizard.Accepted:
            return
        self.settings.observers[self.settings.active_observer] = \
            wizard.result_observer()
        self.settings.binoculars[self.settings.active_binocular] = \
            wizard.result_binocular()
        self.settings.wizard_done = True
        self.reload_profiles()
        self.set_date(self.date)
        self.save()
        if wizard.wants_landscape():
            self.edit_landscape()

    # ------------------------------------------------------------ режимы

    def set_night_mode(self, enabled: bool) -> None:
        self.settings.night_mode = enabled
        self.apply_theme()
        self.sky_view.set_night_mode(enabled)
        self.save()

    def apply_theme(self) -> None:
        self.setStyleSheet(theme.stylesheet(self.settings.night_mode))

    def _toggle_fullscreen(self, enabled: bool) -> None:
        if enabled:
            self.showFullScreen()
        else:
            self.showNormal()

    def _about(self) -> None:
        from . import __version__
        QMessageBox.about(
            self, "Binocular Sky",
            f"<b>Binocular Sky</b> {__version__}<br><br>"
            "Персональный планетарий для наблюдений в бинокль.<br>"
            "Астрономия — ядро AstroCalendar Studio (Skyfield, JPL DE440s, "
            "Hipparcos, OpenNGC).<br>"
            "Трёхмерная сцена — three.js (MIT), локально, без интернета.<br><br>"
            "Оценка предельной звёздной величины и бинокулярный рейтинг — "
            "эмпирические модели; они дают согласованное сравнение объектов, "
            "а не гарантию видимости.")

    # ------------------------------------------------------------ сохранение

    def save(self) -> None:
        try:
            storage.save(self.settings)
        except OSError as error:
            self.status.showMessage(f"Не удалось сохранить профиль: {error}", 6000)

    def closeEvent(self, event) -> None:            # noqa: N802 — имя из Qt
        self.timeline.stop()
        self.save()
        shutdown_workers(wait=False)
        super().closeEvent(event)
