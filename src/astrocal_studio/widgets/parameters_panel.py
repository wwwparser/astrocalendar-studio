"""Левая панель: параметры выпуска и фильтры категорий."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QRadioButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from astrocal.cities import all_cities
from astrocal.fmt import MONTHS_NOM_CAP
from astrocal.taxonomy import grouped_kinds

RANKS = [("must", "must — событие месяца"),
         ("interesting", "interesting — заметное явление"),
         ("optional", "optional — узкое, для полноты"),
         ("technical", "technical — служебное")]


class ParametersPanel(QWidget):
    """Месяц, город, режим, категории, ранги и главные кнопки."""

    calculate_requested = Signal()
    refresh_data_requested = Signal()
    generate_maps_requested = Signal()
    filters_changed = Signal()
    mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._kind_boxes: dict[str, QCheckBox] = {}
        self._rank_boxes: dict[str, QCheckBox] = {}
        self._build()

    # ------------------------------------------------------------ построение

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        outer.addWidget(self._issue_box())
        outer.addWidget(self._mode_box())
        outer.addWidget(self._actions_box())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(8)
        inner_layout.addWidget(self._categories_box())
        inner_layout.addWidget(self._ranks_box())
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

    def _issue_box(self) -> QGroupBox:
        box = QGroupBox("Выпуск")
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        self.year_spin = QSpinBox()
        self.year_spin.setRange(1900, 2150)
        self.year_spin.setValue(2026)
        self.month_combo = QComboBox()
        for number in range(1, 13):
            self.month_combo.addItem(MONTHS_NOM_CAP[number], number)
        self.month_combo.setCurrentIndex(8)
        row.addWidget(QLabel("Год"))
        row.addWidget(self.year_spin, 1)
        row.addWidget(QLabel("Месяц"))
        row.addWidget(self.month_combo, 2)
        layout.addLayout(row)

        timezone_row = QHBoxLayout()
        timezone_row.addWidget(QLabel("Часовой пояс"))
        self.timezone_combo = QComboBox()
        self.timezone_combo.addItem("Москва (UTC+3)", "Europe/Moscow")
        self.timezone_combo.setEnabled(False)
        self.timezone_combo.setToolTip(
            "Выпуск ведётся по московскому времени — так его читает аудитория")
        timezone_row.addWidget(self.timezone_combo, 1)
        layout.addLayout(timezone_row)

        city_row = QHBoxLayout()
        city_row.addWidget(QLabel("Основной город"))
        self.city_combo = QComboBox()
        for city in all_cities():
            self.city_combo.addItem(city.name, city.key)
        city_row.addWidget(self.city_combo, 1)
        layout.addLayout(city_row)
        self.city_combo.currentIndexChanged.connect(
            lambda _: self.filters_changed.emit())
        return box

    def _mode_box(self) -> QGroupBox:
        box = QGroupBox("Режим")
        layout = QHBoxLayout(box)
        self.monthly_radio = QRadioButton("Месячный выпуск")
        self.live_radio = QRadioButton("Live")
        self.monthly_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.monthly_radio)
        group.addButton(self.live_radio)
        layout.addWidget(self.monthly_radio)
        layout.addWidget(self.live_radio)
        self.monthly_radio.toggled.connect(
            lambda checked: checked and self.mode_changed.emit("monthly"))
        self.live_radio.toggled.connect(
            lambda checked: checked and self.mode_changed.emit("live"))
        return box

    def _actions_box(self) -> QGroupBox:
        box = QGroupBox("Действия")
        layout = QVBoxLayout(box)
        self.calculate_button = QPushButton("Рассчитать")
        self.calculate_button.setObjectName("Primary")
        self.refresh_button = QPushButton("Обновить данные")
        self.maps_button = QPushButton("Сгенерировать карты")
        for button in (self.calculate_button, self.refresh_button, self.maps_button):
            layout.addWidget(button)
        self.calculate_button.clicked.connect(self.calculate_requested.emit)
        self.refresh_button.clicked.connect(self.refresh_data_requested.emit)
        self.maps_button.clicked.connect(self.generate_maps_requested.emit)
        return box

    def _categories_box(self) -> QGroupBox:
        box = QGroupBox("Категории событий")
        layout = QVBoxLayout(box)

        for group, kinds in grouped_kinds().items():
            if not kinds:
                continue
            title = QLabel(group)
            title.setObjectName("Muted")
            layout.addWidget(title)
            for kind in kinds:
                checkbox = QCheckBox(kind.title)
                checkbox.setChecked(kind.default_on)
                checkbox.stateChanged.connect(lambda _: self.filters_changed.emit())
                self._kind_boxes[kind.key] = checkbox
                layout.addWidget(checkbox)

        buttons = QHBoxLayout()
        for label, handler in (("Выбрать всё", lambda: self._set_all(True)),
                               ("Снять всё", lambda: self._set_all(False)),
                               ("Только основные", self._select_main)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return box

    def _ranks_box(self) -> QGroupBox:
        box = QGroupBox("Ранг значимости")
        layout = QVBoxLayout(box)
        for key, label in RANKS:
            checkbox = QCheckBox(label)
            checkbox.setChecked(key in ("must", "interesting"))
            checkbox.stateChanged.connect(lambda _: self.filters_changed.emit())
            self._rank_boxes[key] = checkbox
            layout.addWidget(checkbox)
        return box

    # ------------------------------------------------------------ состояние

    def _set_all(self, value: bool) -> None:
        for checkbox in self._kind_boxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.blockSignals(False)
        self.filters_changed.emit()

    MAIN_KINDS = {"moon_phase", "moon_apsis", "moon_planet", "occultation",
                  "solar_eclipse", "lunar_eclipse", "planet_opposition",
                  "planet_elongation", "planet_station", "meteors", "launch",
                  "season", "asteroid_occultation"}

    def _select_main(self) -> None:
        for key, checkbox in self._kind_boxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(key in self.MAIN_KINDS)
            checkbox.blockSignals(False)
        self.filters_changed.emit()

    def enabled_kinds(self) -> set[str]:
        return {key for key, box in self._kind_boxes.items() if box.isChecked()}

    def enabled_ranks(self) -> set[str]:
        return {key for key, box in self._rank_boxes.items() if box.isChecked()}

    def set_enabled_kinds(self, keys) -> None:
        for key, checkbox in self._kind_boxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(key in keys)
            checkbox.blockSignals(False)

    def set_enabled_ranks(self, keys) -> None:
        for key, checkbox in self._rank_boxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(key in keys)
            checkbox.blockSignals(False)

    @property
    def year(self) -> int:
        return self.year_spin.value()

    @property
    def month(self) -> int:
        return int(self.month_combo.currentData())

    @property
    def city_key(self) -> str:
        return str(self.city_combo.currentData())

    @property
    def mode(self) -> str:
        return "live" if self.live_radio.isChecked() else "monthly"

    def set_period(self, year: int, month: int) -> None:
        self.year_spin.setValue(year)
        self.month_combo.setCurrentIndex(month - 1)

    def set_city(self, key: str) -> None:
        index = self.city_combo.findData(key)
        if index >= 0:
            self.city_combo.setCurrentIndex(index)

    def set_busy(self, busy: bool) -> None:
        for button in (self.calculate_button, self.refresh_button, self.maps_button):
            button.setEnabled(not busy)
