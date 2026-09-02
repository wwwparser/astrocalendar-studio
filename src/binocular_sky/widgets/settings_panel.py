"""Диалоги настройки: площадки, приборы, участок и первый запуск.

Программа обязана запускаться и без обмеров участка: сначала человек хочет
увидеть небо, а дом и деревья добавляет потом. Поэтому мастер первого запуска
позволяет пропустить шаг с участком, а редактор препятствий открывается
отдельно и в любой момент.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget, QWizard, QWizardPage)

from ..models.binocular import ORIENTATION_RU, BinocularProfile
from ..models.observer import ObserverProfile, parse_latlon
from ..models.scene import (CUSTOM_HORIZON, FENCE, HOUSE, KIND_RU, TREE,
                            TREE_LINE, Landscape, Obstacle, PanoramaPhoto)

TIMEZONES = ["Europe/Kaliningrad", "Europe/Moscow", "Europe/Samara",
             "Asia/Yekaterinburg", "Asia/Omsk", "Asia/Novosibirsk",
             "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Yakutsk",
             "Asia/Vladivostok", "Asia/Magadan", "Asia/Kamchatka", "UTC"]

BORTLE_HINT = {
    1: "1 — идеальное тёмное небо", 2: "2 — очень тёмное",
    3: "3 — сельское", 4: "4 — сельское с засветкой у горизонта",
    5: "5 — окраина города", 6: "6 — яркая окраина",
    7: "7 — городское", 8: "8 — центр города", 9: "9 — яркий центр",
}


def _spin(minimum, maximum, value, decimals=2, step=1.0, suffix=""):
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    return box


# ---------------------------------------------------------------- площадка

class ObserverEditor(QWidget):
    """Поля одной площадки."""

    def __init__(self, observer: ObserverProfile, parent=None):
        super().__init__(parent)
        self.name = QLineEdit(observer.name)
        self.latitude = _spin(-90, 90, observer.latitude, 6, 0.001, "°")
        self.longitude = _spin(-180, 180, observer.longitude, 6, 0.001, "°")
        self.elevation = _spin(-500, 6000, observer.elevation_m, 0, 10, " м")
        self.eye_height = _spin(0, 5, observer.eye_height_m, 2, 0.05, " м")
        self.timezone = QComboBox()
        self.timezone.setEditable(True)
        self.timezone.addItems(TIMEZONES)
        self.timezone.setCurrentText(observer.timezone)
        self.bortle = QSpinBox()
        self.bortle.setRange(1, 9)
        self.bortle.setValue(observer.bortle)
        self.bortle_hint = QLabel(BORTLE_HINT[observer.bortle])
        self.bortle_hint.setObjectName("muted")
        self.bortle.valueChanged.connect(
            lambda v: self.bortle_hint.setText(BORTLE_HINT[v]))

        self.paste = QLineEdit()
        self.paste.setPlaceholderText("Вставьте «55.324769, 38.349526»")
        self.paste.textEdited.connect(self._paste_coordinates)

        form = QFormLayout(self)
        form.addRow("Название", self.name)
        form.addRow("Вставить координаты", self.paste)
        form.addRow("Широта", self.latitude)
        form.addRow("Долгота", self.longitude)
        form.addRow("Высота над уровнем моря", self.elevation)
        form.addRow("Высота глаз", self.eye_height)
        form.addRow("Часовой пояс", self.timezone)
        form.addRow("Класс неба (Бортль)", self.bortle)
        form.addRow("", self.bortle_hint)

    def _paste_coordinates(self, text: str) -> None:
        parsed = parse_latlon(text)
        if parsed:
            self.latitude.setValue(parsed[0])
            self.longitude.setValue(parsed[1])
            self.paste.setStyleSheet("")
        elif text.strip():
            self.paste.setStyleSheet("border:1px solid #a04040;")

    def profile(self, is_demo: bool = False, notes: str = "") -> ObserverProfile:
        return ObserverProfile(
            name=self.name.text().strip() or "Площадка",
            latitude=self.latitude.value(), longitude=self.longitude.value(),
            elevation_m=self.elevation.value(),
            eye_height_m=self.eye_height.value(),
            timezone=self.timezone.currentText().strip() or "UTC",
            bortle=self.bortle.value(), is_demo=is_demo, notes=notes)


class ObserverDialog(QDialog):
    """Список площадок с редактированием."""

    def __init__(self, observers, active: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Места наблюдения")
        self.observers = [ObserverProfile.from_dict(o.to_dict()) for o in observers]
        self.active = active

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._switch)
        self.editor_holder = QVBoxLayout()
        self.editor: ObserverEditor | None = None

        add = QPushButton("Добавить")
        remove = QPushButton("Удалить")
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        side_buttons = QHBoxLayout()
        side_buttons.addWidget(add)
        side_buttons.addWidget(remove)

        left = QVBoxLayout()
        left.addWidget(self.list)
        left.addLayout(side_buttons)

        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addLayout(self.editor_holder, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(body)
        layout.addWidget(buttons)
        self._reload(active)
        self.resize(720, 420)

    def _reload(self, row: int) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for observer in self.observers:
            self.list.addItem(observer.name + ("  [DEMO]" if observer.is_demo else ""))
        self.list.setCurrentRow(min(row, len(self.observers) - 1))
        self.list.blockSignals(False)
        self._switch(self.list.currentRow())

    def _switch(self, row: int) -> None:
        self._commit()
        if row < 0 or row >= len(self.observers):
            return
        if self.editor is not None:
            self.editor.setParent(None)
        self.editor = ObserverEditor(self.observers[row])
        self.editor_holder.addWidget(self.editor)
        self._row = row

    def _commit(self) -> None:
        row = getattr(self, "_row", None)
        if self.editor is None or row is None or row >= len(self.observers):
            return
        previous = self.observers[row]
        self.observers[row] = self.editor.profile(previous.is_demo, previous.notes)

    def _add(self) -> None:
        self._commit()
        self.observers.append(ObserverProfile(name="Новая площадка"))
        self._reload(len(self.observers) - 1)

    def _remove(self) -> None:
        row = self.list.currentRow()
        if len(self.observers) <= 1 or row < 0:
            return
        self.observers.pop(row)
        self._row = None
        self._reload(max(0, row - 1))

    def _accept(self) -> None:
        self._commit()
        self.active = max(0, self.list.currentRow())
        self.accept()


# ---------------------------------------------------------------- прибор

class BinocularDialog(QDialog):
    """Список приборов: бинокли, труба, невооружённый глаз."""

    def __init__(self, binoculars, active: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Приборы")
        self.binoculars = [BinocularProfile.from_dict(b.to_dict())
                           for b in binoculars]
        self.active = active

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._switch)

        self.name = QLineEdit()
        self.magnification = _spin(1, 300, 10, 1, 1, "×")
        self.aperture = _spin(1, 500, 50, 0, 1, " мм")
        self.field = _spin(0.05, 120, 6.5, 2, 0.1, "°")
        self.override = QLineEdit()
        self.override.setPlaceholderText("авто")
        self.orientation = QComboBox()
        for key, label in ORIENTATION_RU.items():
            self.orientation.addItem(label, key)
        self.derived = QLabel("")
        self.derived.setObjectName("muted")
        self.derived.setWordWrap(True)

        for widget in (self.magnification, self.aperture, self.field):
            widget.valueChanged.connect(self._update_derived)

        form = QFormLayout()
        form.addRow("Название", self.name)
        form.addRow("Увеличение", self.magnification)
        form.addRow("Апертура", self.aperture)
        form.addRow("Поле зрения", self.field)
        form.addRow("Предел вручную, m", self.override)
        form.addRow("Ориентация изображения", self.orientation)
        form.addRow("", self.derived)

        add = QPushButton("Добавить")
        remove = QPushButton("Удалить")
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        side_buttons = QHBoxLayout()
        side_buttons.addWidget(add)
        side_buttons.addWidget(remove)

        left = QVBoxLayout()
        left.addWidget(self.list)
        left.addLayout(side_buttons)

        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addLayout(form, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(body)
        layout.addWidget(buttons)
        self._row = None
        self._reload(active)
        self.resize(680, 360)

    def _reload(self, row: int) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for binocular in self.binoculars:
            self.list.addItem(binocular.name)
        self.list.setCurrentRow(min(row, len(self.binoculars) - 1))
        self.list.blockSignals(False)
        self._switch(self.list.currentRow())

    def _switch(self, row: int) -> None:
        self._commit()
        if row < 0 or row >= len(self.binoculars):
            return
        item = self.binoculars[row]
        self.name.setText(item.name)
        self.magnification.setValue(item.magnification)
        self.aperture.setValue(item.aperture_mm)
        self.field.setValue(item.field_of_view_deg)
        self.override.setText("" if item.limiting_mag_override is None
                              else f"{item.limiting_mag_override:g}")
        index = self.orientation.findData(item.orientation)
        self.orientation.setCurrentIndex(max(0, index))
        self._row = row
        self._update_derived()

    def _current(self) -> BinocularProfile:
        try:
            override = float(self.override.text().replace(",", ".")) \
                if self.override.text().strip() else None
        except ValueError:
            override = None
        return BinocularProfile(
            name=self.name.text().strip() or "Прибор",
            magnification=self.magnification.value(),
            aperture_mm=self.aperture.value(),
            field_of_view_deg=self.field.value(),
            limiting_mag_override=override,
            orientation=self.orientation.currentData() or "NORMAL")

    def _update_derived(self) -> None:
        item = self._current()
        self.derived.setText(
            f"Выходной зрачок {item.exit_pupil_mm:.1f} мм · "
            f"видимое поле {item.apparent_field_deg:.0f}° · "
            f"предел на тёмном небе ≈ {item.limiting_magnitude(4, 60, 0):+.1f}m")

    def _commit(self) -> None:
        if self._row is not None and self._row < len(self.binoculars):
            self.binoculars[self._row] = self._current()

    def _add(self) -> None:
        self._commit()
        self.binoculars.append(BinocularProfile(name="Новый прибор"))
        self._reload(len(self.binoculars) - 1)

    def _remove(self) -> None:
        row = self.list.currentRow()
        if len(self.binoculars) <= 1 or row < 0:
            return
        self.binoculars.pop(row)
        self._row = None
        self._reload(max(0, row - 1))

    def _accept(self) -> None:
        self._commit()
        self.active = max(0, self.list.currentRow())
        self.accept()


# ---------------------------------------------------------------- участок

OBSTACLE_COLUMNS = [
    ("Тип", "kind"), ("Название", "name"), ("Азимут, °", "azimuth_deg"),
    ("Расст., м", "distance_m"), ("Ширина, м", "width_m"),
    ("Длина, м", "length_m"), ("Стены, м", "wall_height_m"),
    ("Конёк, м", "ridge_height_m"), ("Поворот, °", "rotation_deg"),
    ("Ствол, м", "trunk_height_m"), ("Крона R, м", "crown_radius_m"),
    ("Крона H, м", "crown_height_m"), ("Аз. от, °", "azimuth_start_deg"),
    ("Аз. до, °", "azimuth_end_deg"), ("Высота, м", "height_m"),
]


class LandscapeDialog(QDialog):
    """Обмер участка: препятствия и привязка фотографий."""

    def __init__(self, landscape: Landscape, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Участок: дом, деревья, забор")
        self.landscape = Landscape.from_dict(landscape.to_dict())

        self.natural = _spin(0, 40, self.landscape.natural_horizon_deg, 1, 0.5, "°")
        self.table = QTableWidget(0, len(OBSTACLE_COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in OBSTACLE_COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)

        add_house = QPushButton("+ дом")
        add_tree = QPushButton("+ дерево")
        add_line = QPushButton("+ полоса деревьев")
        add_fence = QPushButton("+ забор")
        remove = QPushButton("Удалить строку")
        add_house.clicked.connect(lambda: self._add(HOUSE))
        add_tree.clicked.connect(lambda: self._add(TREE))
        add_line.clicked.connect(lambda: self._add(TREE_LINE))
        add_fence.clicked.connect(lambda: self._add(FENCE))
        remove.clicked.connect(self._remove)

        row_buttons = QHBoxLayout()
        for button in (add_house, add_tree, add_line, add_fence, remove):
            row_buttons.addWidget(button)
        row_buttons.addStretch(1)

        # ---------------------------------------------------------- фотографии
        self.photo_list = QListWidget()
        self.photo_list.setMaximumHeight(110)
        import_photos = QPushButton("Импортировать фотографии…")
        import_photos.clicked.connect(self._import_photos)
        import_panorama = QPushButton("Импортировать 360° панораму…")
        import_panorama.clicked.connect(self._import_panorama)
        clear_photos = QPushButton("Очистить")
        clear_photos.clicked.connect(self._clear_photos)
        photo_buttons = QHBoxLayout()
        photo_buttons.addWidget(import_photos)
        photo_buttons.addWidget(import_panorama)
        photo_buttons.addWidget(clear_photos)
        photo_buttons.addStretch(1)

        note = QLabel(
            "Азимут отсчитывается от севера по часовой стрелке: 0° — север, "
            "90° — восток, 180° — юг. Расстояние и высоты — в метрах от точки, "
            "где вы стоите.\n"
            "Фотографии сейчас сохраняются с привязкой к азимуту центра кадра "
            "и используются как ориентир; автоматическая склейка панорамы — "
            "следующий этап.")
        note.setWordWrap(True)
        note.setObjectName("muted")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Естественный горизонт", self.natural)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.table, 1)
        layout.addLayout(row_buttons)
        layout.addWidget(QLabel("Фотографии местности"))
        layout.addWidget(self.photo_list)
        layout.addLayout(photo_buttons)
        layout.addWidget(note)
        layout.addWidget(buttons)

        self._fill()
        self.resize(1080, 560)

    def _fill(self) -> None:
        self.table.setRowCount(0)
        for obstacle in self.landscape.obstacles:
            self._append_row(obstacle)
        self._fill_photos()

    def _fill_photos(self) -> None:
        self.photo_list.clear()
        if self.landscape.equirectangular_path:
            self.photo_list.addItem(
                f"360°: {self.landscape.equirectangular_path}")
        for photo in self.landscape.photos:
            self.photo_list.addItem(
                f"{photo.center_azimuth_deg:.0f}° — {photo.path}")

    def _append_row(self, obstacle: Obstacle) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, (_, attribute) in enumerate(OBSTACLE_COLUMNS):
            value = getattr(obstacle, attribute)
            if attribute == "kind":
                box = QComboBox()
                for key in (HOUSE, TREE, TREE_LINE, FENCE, CUSTOM_HORIZON):
                    box.addItem(KIND_RU[key], key)
                box.setCurrentIndex(max(0, box.findData(value)))
                self.table.setCellWidget(row, column, box)
                continue
            text = value if isinstance(value, str) else f"{float(value):g}"
            item = QTableWidgetItem(text)
            self.table.setItem(row, column, item)

    def _add(self, kind: str) -> None:
        defaults = {
            HOUSE: Obstacle(kind=HOUSE, name="Дом", distance_m=14, azimuth_deg=180),
            TREE: Obstacle(kind=TREE, name="Дерево", distance_m=12, azimuth_deg=90),
            TREE_LINE: Obstacle(kind=TREE_LINE, name="Полоса деревьев",
                                distance_m=50, height_m=12),
            FENCE: Obstacle(kind=FENCE, name="Забор", distance_m=8, height_m=2),
        }
        self._append_row(defaults[kind])

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _import_photos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Фотографии местности", "",
            "Изображения (*.jpg *.jpeg *.png *.webp)")
        if not paths:
            return
        step = 360.0 / len(paths)
        for index, path in enumerate(paths):
            self.landscape.photos.append(PanoramaPhoto(
                path=path, center_azimuth_deg=round(index * step, 1),
                label=f"Кадр {index + 1}"))
        self.landscape.panorama_mode = "PHOTOS"
        self._fill_photos()
        QMessageBox.information(
            self, "Фотографии добавлены",
            "Кадрам проставлены равномерные азимуты. Уточните азимут центра "
            "каждого кадра в поле рядом с ним — от этого зависит, куда они "
            "лягут вокруг наблюдателя.")

    def _import_panorama(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Панорама 360°", "", "Изображения (*.jpg *.jpeg *.png)")
        if not path:
            return
        self.landscape.equirectangular_path = path
        self.landscape.panorama_mode = "EQUIRECTANGULAR"
        self._fill_photos()

    def _clear_photos(self) -> None:
        self.landscape.photos = []
        self.landscape.equirectangular_path = ""
        self.landscape.panorama_mode = "NONE"
        self._fill_photos()

    def _accept(self) -> None:
        obstacles = []
        for row in range(self.table.rowCount()):
            values = {}
            for column, (_, attribute) in enumerate(OBSTACLE_COLUMNS):
                if attribute == "kind":
                    widget = self.table.cellWidget(row, column)
                    values["kind"] = widget.currentData()
                    continue
                item = self.table.item(row, column)
                text = item.text().strip() if item else ""
                if attribute == "name":
                    values["name"] = text or KIND_RU.get(values.get("kind"), "")
                    continue
                try:
                    values[attribute] = float(text.replace(",", "."))
                except ValueError:
                    values[attribute] = 0.0
            obstacles.append(Obstacle.from_dict(values))
        self.landscape.obstacles = obstacles
        self.landscape.natural_horizon_deg = self.natural.value()
        self.landscape.is_demo = False if obstacles else self.landscape.is_demo
        self.accept()


# ---------------------------------------------------------------- мастер

class SetupWizard(QWizard):
    """Первый запуск: место, прибор, небо. Участок можно пропустить."""

    def __init__(self, observer: ObserverProfile, binocular: BinocularProfile,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Binocular Sky — первая настройка")
        self.setWizardStyle(QWizard.ModernStyle)
        self.add_house = False

        self.observer_editor = ObserverEditor(observer)
        place = QWizardPage()
        place.setTitle("Где наблюдаем?")
        place.setSubTitle("Координаты можно вставить прямо из карт.")
        place_layout = QVBoxLayout(place)
        place_layout.addWidget(self.observer_editor)
        self.addPage(place)

        optics = QWizardPage()
        optics.setTitle("Ваш бинокль")
        optics.setSubTitle("Увеличение, апертура и поле зрения написаны на корпусе.")
        self.magnification = _spin(1, 300, binocular.magnification, 1, 1, "×")
        self.aperture = _spin(1, 500, binocular.aperture_mm, 0, 1, " мм")
        self.field = _spin(0.05, 120, binocular.field_of_view_deg, 2, 0.1, "°")
        self.optics_name = QLineEdit(binocular.name)
        optics_form = QFormLayout(optics)
        optics_form.addRow("Название", self.optics_name)
        optics_form.addRow("Увеличение", self.magnification)
        optics_form.addRow("Апертура", self.aperture)
        optics_form.addRow("Поле зрения", self.field)
        self.addPage(optics)

        terrain = QWizardPage()
        terrain.setTitle("Участок")
        terrain.setSubTitle("Дом и деревья можно добавить позже — "
                            "программа работает и без них.")
        self.skip_label = QLabel(
            "Нажмите «Готово», чтобы начать без модели участка, или отметьте "
            "галочку, чтобы сразу открыть редактор дома и деревьев.")
        self.skip_label.setWordWrap(True)
        from PySide6.QtWidgets import QCheckBox
        self.house_check = QCheckBox("Открыть редактор участка после настройки")
        terrain_layout = QVBoxLayout(terrain)
        terrain_layout.addWidget(self.skip_label)
        terrain_layout.addWidget(self.house_check)
        self.addPage(terrain)
        self.resize(620, 480)

    def result_observer(self) -> ObserverProfile:
        return self.observer_editor.profile()

    def result_binocular(self) -> BinocularProfile:
        return BinocularProfile(
            name=self.optics_name.text().strip() or "Бинокль",
            magnification=self.magnification.value(),
            aperture_mm=self.aperture.value(),
            field_of_view_deg=self.field.value())

    def wants_landscape(self) -> bool:
        return self.house_check.isChecked()
