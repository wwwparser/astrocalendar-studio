"""Панели статуса данных и режима Live."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from astrocal_app import datastatus

from .. import theme


class DataStatusPanel(QWidget):
    """Возраст внешних источников и точечное обновление."""

    refresh_requested = Signal(str)

    def __init__(self, tokens: theme.Tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens
        self._build()
        self.reload()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = QLabel("Источники данных")
        title.setObjectName("Heading")
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Источник", "Статус", "Обновлено"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setRootIsDecorated(False)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.refresh_all_button = QPushButton("Обновить всё")
        self.refresh_all_button.setObjectName("Primary")
        buttons.addWidget(self.refresh_all_button)
        for label, key in (("Обновить TLE", "tle"),
                           ("Обновить кометы", "comets"),
                           ("Обновить пуски", "launches"),
                           ("Обновить NEO", "neo")):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, k=key:
                                   self.refresh_requested.emit(k))
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.refresh_all_button.clicked.connect(
            lambda: self.refresh_requested.emit("all"))

        hint = QLabel("Обновляются только те источники, которые действительно "
                      "стареют: эфемериды и каталоги звёзд лежат локально.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def reload(self) -> None:
        self.tree.clear()
        colors = {"актуально": self.tokens.ok, "стареет": self.tokens.warn,
                  "устарело": self.tokens.review, "нет данных": self.tokens.review,
                  "локальный": self.tokens.muted}
        for source in datastatus.sources():
            item = QTreeWidgetItem([source.title, source.status, source.age_text])
            color = colors.get(source.status, self.tokens.muted)
            from PySide6.QtGui import QBrush, QColor
            item.setForeground(1, QBrush(QColor(color)))
            if source.note:
                item.setToolTip(0, source.note)
            self.tree.addTopLevelItem(item)


class LivePanel(QWidget):
    """Оперативная сводка ближайших событий."""

    refresh_requested = Signal(float)
    item_selected = Signal(object)

    WINDOWS = [("Сегодня", 24.0), ("Завтра", 48.0), ("48 часов", 48.0),
               ("72 часа", 72.0)]

    def __init__(self, tokens: theme.Tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens
        self.items: list = []
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Ближайшие события")
        title.setObjectName("Heading")
        header.addWidget(title)
        header.addStretch(1)
        self.window_combo = QComboBox()
        for label, hours in self.WINDOWS:
            self.window_combo.addItem(label, hours)
        self.window_combo.setCurrentIndex(2)
        header.addWidget(self.window_combo)
        self.refresh_button = QPushButton("Обновить сейчас")
        self.refresh_button.setObjectName("Primary")
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Когда", "Через", "Событие", "Уверенность"])
        self.tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)

        self.status = QLabel("Нажмите «Обновить сейчас»: данные Live не кэшируются.")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.refresh_button.clicked.connect(
            lambda: self.refresh_requested.emit(
                float(self.window_combo.currentData())))
        self.tree.currentItemChanged.connect(self._selection_changed)

    def show_items(self, items: list) -> None:
        self.items = items
        self.tree.clear()
        from PySide6.QtGui import QBrush, QColor
        colors = {"высокая": self.tokens.ok, "средняя": self.tokens.warn,
                  "низкая": self.tokens.review}
        for index, item in enumerate(items):
            row = QTreeWidgetItem([f"{item.when:%d.%m %H:%M}", item.relative,
                                   item.title, item.confidence])
            row.setToolTip(2, item.detail)
            row.setData(0, Qt.UserRole, index)
            row.setForeground(3, QBrush(QColor(
                colors.get(item.confidence, self.tokens.muted))))
            self.tree.addTopLevelItem(row)
        self.status.setText(
            f"Событий: {len(items)}. Данные получены только что и не кэшируются."
            if items else "На выбранном интервале событий не найдено.")

    def _selection_changed(self, current, _previous) -> None:
        if current is None:
            return
        index = current.data(0, Qt.UserRole)
        if index is not None and 0 <= index < len(self.items):
            self.item_selected.emit(self.items[index])
