"""Левая колонка: дата, площадка, прибор, поиск и настройки вида."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QGroupBox,
                               QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout,
                               QWidget)

ROLE_ID = Qt.UserRole + 1


class SidePanel(QWidget):
    """Что наблюдаем, откуда и чем."""

    date_changed = Signal(object)             # dt.date
    observer_changed = Signal(int)
    binocular_changed = Signal(int)
    options_changed = Signal()
    search_activated = Signal(str)
    search_result_chosen = Signal(str)
    edit_observer = Signal()
    edit_binocular = Signal()
    edit_landscape = Signal()
    tonight_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---------------------------------------------------------- дата
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.dateChanged.connect(self._date_changed)

        self.today_button = QPushButton("Сегодня ночью")
        self.today_button.clicked.connect(self.tonight_requested)

        date_box = QGroupBox("Ночь")
        date_layout = QVBoxLayout(date_box)
        date_layout.addWidget(self.date_edit)
        date_layout.addWidget(self.today_button)
        self.night_label = QLabel("—")
        self.night_label.setObjectName("muted")
        self.night_label.setWordWrap(True)
        date_layout.addWidget(self.night_label)

        # ---------------------------------------------------------- площадка
        self.observer_box = QComboBox()
        self.observer_box.currentIndexChanged.connect(self._observer_changed)
        self.observer_label = QLabel("—")
        self.observer_label.setObjectName("muted")
        self.observer_label.setWordWrap(True)
        observer_edit = QPushButton("Настроить площадку…")
        observer_edit.clicked.connect(self.edit_observer)
        landscape_edit = QPushButton("Участок: дом и деревья…")
        landscape_edit.clicked.connect(self.edit_landscape)

        place_box = QGroupBox("Место наблюдения")
        place_layout = QVBoxLayout(place_box)
        place_layout.addWidget(self.observer_box)
        place_layout.addWidget(self.observer_label)
        place_layout.addWidget(observer_edit)
        place_layout.addWidget(landscape_edit)

        # ---------------------------------------------------------- прибор
        self.binocular_box = QComboBox()
        self.binocular_box.currentIndexChanged.connect(self._binocular_changed)
        self.binocular_label = QLabel("—")
        self.binocular_label.setObjectName("muted")
        self.binocular_label.setWordWrap(True)
        binocular_edit = QPushButton("Настроить приборы…")
        binocular_edit.clicked.connect(self.edit_binocular)

        optics_box = QGroupBox("Прибор")
        optics_layout = QVBoxLayout(optics_box)
        optics_layout.addWidget(self.binocular_box)
        optics_layout.addWidget(self.binocular_label)
        optics_layout.addWidget(binocular_edit)

        # ---------------------------------------------------------- поиск
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Найти объект…  M31, Андромеда, Юпитер")
        self.search_field.returnPressed.connect(self._search)
        self.search_field.textEdited.connect(self._search_typed)
        self.search_results = QListWidget()
        self.search_results.setMaximumHeight(130)
        self.search_results.itemClicked.connect(
            lambda item: self.search_result_chosen.emit(item.data(ROLE_ID)))
        self.search_results.hide()
        self.search_status = QLabel("")
        self.search_status.setObjectName("muted")
        self.search_status.setWordWrap(True)

        search_box = QGroupBox("Поиск")
        search_layout = QVBoxLayout(search_box)
        search_layout.addWidget(self.search_field)
        search_layout.addWidget(self.search_results)
        search_layout.addWidget(self.search_status)

        # ---------------------------------------------------------- вид
        self.constellations_check = QCheckBox("Фигуры созвездий")
        self.constellations_check.setChecked(True)
        self.labels_check = QCheckBox("Подписи объектов")
        self.labels_check.setChecked(True)
        self.star_level_box = QComboBox()
        for label in ("Только яркие (4.5m)", "Городское небо (5.5m)",
                      "Тёмное небо (6.5m)"):
            self.star_level_box.addItem(label)
        self.star_level_box.setCurrentIndex(2)
        for widget in (self.constellations_check, self.labels_check):
            widget.toggled.connect(self.options_changed)
        self.star_level_box.currentIndexChanged.connect(self.options_changed)

        view_box = QGroupBox("Небо")
        view_layout = QVBoxLayout(view_box)
        view_layout.addWidget(self.constellations_check)
        view_layout.addWidget(self.labels_check)
        view_layout.addWidget(QLabel("Глубина звёзд"))
        view_layout.addWidget(self.star_level_box)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        for box in (date_box, place_box, optics_box, search_box, view_box):
            layout.addWidget(box)
        layout.addStretch(1)

    # ------------------------------------------------------------ заполнение

    def set_observers(self, observers, active: int) -> None:
        self.observer_box.blockSignals(True)
        self.observer_box.clear()
        for observer in observers:
            mark = "  [DEMO]" if observer.is_demo else ""
            self.observer_box.addItem(f"{observer.name}{mark}")
        self.observer_box.setCurrentIndex(active)
        self.observer_box.blockSignals(False)
        self.observer_label.setText(observers[active].describe())

    def set_binoculars(self, binoculars, active: int) -> None:
        self.binocular_box.blockSignals(True)
        self.binocular_box.clear()
        for binocular in binoculars:
            self.binocular_box.addItem(binocular.name)
        self.binocular_box.setCurrentIndex(active)
        self.binocular_box.blockSignals(False)
        self.binocular_label.setText(binoculars[active].describe())

    def set_date(self, date: dt.date) -> None:
        self.date_edit.blockSignals(True)
        self.date_edit.setDate(QDate(date.year, date.month, date.day))
        self.date_edit.blockSignals(False)

    def set_night_text(self, text: str) -> None:
        self.night_label.setText(text)

    def set_search_results(self, targets) -> None:
        self.search_results.clear()
        if not targets:
            self.search_results.hide()
            return
        for target in targets[:12]:
            item = QListWidgetItem(f"{target.name}  ·  {target.kind_ru}")
            item.setData(ROLE_ID, target.id)
            self.search_results.addItem(item)
        self.search_results.show()

    def set_search_status(self, text: str) -> None:
        self.search_status.setText(text)

    @property
    def star_mag_limit(self) -> float:
        return (4.5, 5.5, 6.5)[self.star_level_box.currentIndex()]

    # ------------------------------------------------------------ события

    def _date_changed(self, value: QDate) -> None:
        self.date_changed.emit(dt.date(value.year(), value.month(), value.day()))

    def _observer_changed(self, index: int) -> None:
        self.observer_changed.emit(index)

    def _binocular_changed(self, index: int) -> None:
        self.binocular_changed.emit(index)

    def _search(self) -> None:
        self.search_activated.emit(self.search_field.text())

    def _search_typed(self, text: str) -> None:
        if len(text.strip()) >= 2:
            self.search_activated.emit(text)
        else:
            self.search_results.hide()
            self.search_status.setText("")
