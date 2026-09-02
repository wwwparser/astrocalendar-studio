"""Вкладка LIVE: открытия и уточнения.

Лента устроена карточками, а не таблицей, потому что решение по каждой записи
принимается отдельно: одну добавить в выпуск, о другой написать отдельный пост,
третью скрыть. В таблице такие действия негде разместить, а читать её приходится
глазами по столбцам.

Ни одно действие в этой панели не ходит в сеть. Данные берутся из результата
последнего обновления: раскрытие карточки, переключение фильтров и переход
между записями работают мгновенно и не расходуют лимиты внешних API.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox, QFrame,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from astrocal import qa_live
from astrocal.live.model import (KIND_COMET, KIND_NEO, KIND_OCCULTATION,
                                 KIND_TRANSIENT, STATUS_NEW, STATUS_UPDATED)

from .. import theme

WINDOWS = [("24 часа", 24.0), ("48 часов", 48.0), ("7 дней", 168.0),
           ("Все", None)]

KIND_FILTERS = [(KIND_OCCULTATION, "Покрытия"), (KIND_NEO, "Сближения"),
                (KIND_COMET, "Кометы"), (KIND_TRANSIENT, "Новые и сверхновые")]


class LiveCard(QFrame):
    """Одна запись ленты."""

    opened = Signal(object)
    map_requested = Signal(object)
    add_requested = Signal(object)
    post_requested = Signal(object)
    ignore_requested = Signal(object)

    def __init__(self, record, tokens: theme.Tokens, parent=None):
        super().__init__(parent)
        self.record = record
        self.tokens = tokens
        self.expanded = False
        self.setObjectName("LiveCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._build()

    def _build(self) -> None:
        record = self.record
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        head = QHBoxLayout()
        status = QLabel(self._status_text())
        status.setStyleSheet(f"color: {self._status_color()}; font-weight: 600;")
        head.addWidget(status)
        kind = QLabel(record.kind_title)
        kind.setStyleSheet(f"color: {self.tokens.muted};")
        head.addWidget(kind)
        head.addStretch(1)
        if record.stars:
            stars = QLabel("★" * record.stars)
            stars.setStyleSheet(f"color: {self.tokens.must};")
            head.addWidget(stars)
        when = QLabel(record.relative)
        when.setStyleSheet(f"color: {self.tokens.muted};")
        head.addWidget(when)
        layout.addLayout(head)

        title = QLabel(record.title)
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        title.setWordWrap(True)
        layout.addWidget(title)

        self.body = QLabel(self._short_text())
        self.body.setWordWrap(True)
        self.body.setStyleSheet(f"color: {self.tokens.text};")
        layout.addWidget(self.body)

        level = qa_live.qa_level(record)
        if level != "OK":
            messages = "; ".join(flag.message for flag
                                 in (record.state or {}).get("qa", []))
            warning = QLabel(f"{level}: {messages}")
            warning.setWordWrap(True)
            warning.setStyleSheet(
                f"color: {self.tokens.review if level == 'REVIEW' else self.tokens.warn};")
            layout.addWidget(warning)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self.details_button = QPushButton("Подробнее")
        self.details_button.clicked.connect(self.toggle)
        buttons.addWidget(self.details_button)
        for label, signal in (("Карта", self.map_requested),
                              ("В выпуск", self.add_requested),
                              ("Пост", self.post_requested)):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, s=signal: s.emit(self.record))
            buttons.addWidget(button)
        hide_button = QPushButton("Скрыть" if not record.ignored else "Вернуть")
        hide_button.clicked.connect(
            lambda: self.ignore_requested.emit(self.record))
        buttons.addWidget(hide_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    # ------------------------------------------------------------ содержимое

    def _status_text(self) -> str:
        record = self.record
        icon = record.icon
        if record.status == STATUS_NEW:
            return f"{icon} НОВОЕ"
        if record.status == STATUS_UPDATED:
            return f"{icon} ОБНОВЛЕНО"
        return icon

    def _status_color(self) -> str:
        if self.record.status == STATUS_NEW:
            return self.tokens.ok
        if self.record.status == STATUS_UPDATED:
            return self.tokens.warn
        return self.tokens.muted

    def _short_text(self) -> str:
        return "\n".join(self.record.lines[:3]) or self.record.summary

    def toggle(self) -> None:
        self.expanded = not self.expanded
        self.body.setText("\n".join(self.record.lines) if self.expanded
                          else self._short_text())
        self.details_button.setText("Свернуть" if self.expanded else "Подробнее")
        if self.expanded:
            self.opened.emit(self.record)


class LiveFeedPanel(QWidget):
    """Лента открытий и уточнений с фильтрами."""

    refresh_requested = Signal(float)          # горизонт прогноза в сутках
    filters_changed = Signal()
    card_opened = Signal(object)
    map_requested = Signal(object)
    add_requested = Signal(object)
    post_requested = Signal(object)
    ignore_requested = Signal(object)

    def __init__(self, tokens: theme.Tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens
        self.records: list = []
        self.hours: float | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        head = QHBoxLayout()
        title = QLabel("LIVE")
        title.setObjectName("Heading")
        head.addWidget(title)
        self.updated_label = QLabel("не обновлялась")
        self.updated_label.setStyleSheet(f"color: {self.tokens.muted};")
        head.addWidget(self.updated_label)
        head.addStretch(1)
        self.refresh_button = QPushButton("Обновить сейчас")
        self.refresh_button.setObjectName("Primary")
        self.refresh_button.clicked.connect(
            lambda: self.refresh_requested.emit(30.0))
        head.addWidget(self.refresh_button)
        layout.addLayout(head)

        windows = QHBoxLayout()
        self.window_group = QButtonGroup(self)
        self.window_group.setExclusive(True)
        for index, (label, hours) in enumerate(WINDOWS):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(hours is None)
            button.clicked.connect(lambda _=False, h=hours: self._set_hours(h))
            self.window_group.addButton(button, index)
            windows.addWidget(button)
        windows.addStretch(1)
        layout.addLayout(windows)

        layout.addWidget(self._filters_box())

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.container = QWidget()
        self.cards_layout = QVBoxLayout(self.container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(6)
        self.cards_layout.addStretch(1)
        self.area.setWidget(self.container)
        layout.addWidget(self.area, 1)

        self.status = QLabel("Нажмите «Обновить сейчас»: лента сравнит источники "
                             "с прошлым снимком и покажет, что появилось.")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def _filters_box(self) -> QGroupBox:
        box = QGroupBox("Что показывать")
        layout = QVBoxLayout(box)
        layout.setSpacing(3)

        kinds = QHBoxLayout()
        self.kind_boxes: dict[str, QCheckBox] = {}
        for key, label in KIND_FILTERS:
            check = QCheckBox(label)
            check.setChecked(True)
            check.stateChanged.connect(lambda _=0: self.filters_changed.emit())
            self.kind_boxes[key] = check
            kinds.addWidget(check)
        layout.addLayout(kinds)

        transient_row = QHBoxLayout()
        self.novae_box = QCheckBox("Новые")
        self.supernovae_box = QCheckBox("Сверхновые")
        self.confirmed_box = QCheckBox("Только подтверждённые")
        for widget in (self.novae_box, self.supernovae_box, self.confirmed_box):
            widget.setChecked(True)
            widget.stateChanged.connect(lambda _=0: self.filters_changed.emit())
            transient_row.addWidget(widget)
        layout.addLayout(transient_row)

        magnitude_row = QHBoxLayout()
        magnitude_row.addWidget(QLabel("Максимальный блеск транзиента"))
        self.magnitude_spin = QDoubleSpinBox()
        self.magnitude_spin.setRange(-5.0, 25.0)
        self.magnitude_spin.setSingleStep(0.5)
        self.magnitude_spin.setValue(13.0)
        self.magnitude_spin.setSuffix("m")
        self.magnitude_spin.valueChanged.connect(
            lambda _=0.0: self.filters_changed.emit())
        magnitude_row.addWidget(self.magnitude_spin)
        magnitude_row.addWidget(QLabel("звезды в покрытии"))
        self.star_spin = QDoubleSpinBox()
        self.star_spin.setRange(0.0, 15.0)
        self.star_spin.setSingleStep(0.5)
        self.star_spin.setValue(10.0)
        self.star_spin.setSuffix("m")
        self.star_spin.valueChanged.connect(
            lambda _=0.0: self.filters_changed.emit())
        magnitude_row.addWidget(self.star_spin)
        magnitude_row.addStretch(1)
        layout.addLayout(magnitude_row)

        conditions = QHBoxLayout()
        self.visible_box = QCheckBox("Только наблюдаемые из России")
        self.night_box = QCheckBox("Только доступные ночью")
        self.russia_box = QCheckBox("Полоса через Россию")
        self.uncertain_box = QCheckBox("Показывать с большой неопределённостью")
        for widget in (self.visible_box, self.night_box, self.russia_box,
                       self.uncertain_box):
            widget.setChecked(True)
            widget.stateChanged.connect(lambda _=0: self.filters_changed.emit())
        conditions.addWidget(self.visible_box)
        conditions.addWidget(self.night_box)
        layout.addLayout(conditions)

        second = QHBoxLayout()
        second.addWidget(self.russia_box)
        second.addWidget(self.uncertain_box)
        layout.addLayout(second)

        self.show_all_box = QCheckBox("Показать все, включая скрытые и слабые")
        self.show_all_box.stateChanged.connect(
            lambda _=0: self.filters_changed.emit())
        layout.addWidget(self.show_all_box)
        return box

    # ------------------------------------------------------------ данные

    def _set_hours(self, hours: float | None) -> None:
        self.hours = hours
        self.filters_changed.emit()

    def filter_values(self) -> dict:
        """Значения фильтров для сервисного слоя."""
        return {
            "hours": self.hours,
            "show_all": self.show_all_box.isChecked(),
            "kinds": {key for key, box in self.kind_boxes.items()
                      if box.isChecked()},
            "novae": self.novae_box.isChecked(),
            "supernovae": self.supernovae_box.isChecked(),
            "confirmed_only": self.confirmed_box.isChecked(),
            "magnitude_limit": self.magnitude_spin.value(),
            "only_visible": self.visible_box.isChecked(),
            "only_at_night": self.night_box.isChecked(),
            "occultations_russia_only": self.russia_box.isChecked(),
            "occultation_star_mag_limit": self.star_spin.value(),
            "show_uncertain": self.uncertain_box.isChecked(),
        }

    def show_records(self, records: list, updated_at=None) -> None:
        self.records = records
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for index, record in enumerate(records):
            card = LiveCard(record, self.tokens)
            card.opened.connect(self.card_opened)
            card.map_requested.connect(self.map_requested)
            card.add_requested.connect(self.add_requested)
            card.post_requested.connect(self.post_requested)
            card.ignore_requested.connect(self.ignore_requested)
            self.cards_layout.insertWidget(index, card)

        if updated_at is not None:
            self.updated_label.setText(f"обновлено {updated_at:%H:%M}")
        self.status.setText(
            f"Записей: {len(records)}." if records else
            "По текущим фильтрам записей нет. Снимите фильтры или нажмите "
            "«Показать все».")

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)


def card_palette(tokens: theme.Tokens) -> str:
    """Оформление карточек — отдельно, чтобы не смешивать со стилем окна."""
    border = QColor(tokens.border).name()
    return (f"QFrame#LiveCard {{ background: {tokens.surface}; "
            f"border: 1px solid {border}; border-radius: 6px; }}")
