"""Панель «моя ночь»: программа наблюдений и её порядок."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

ROLE_ID = Qt.UserRole + 1


class PlanPanel(QWidget):
    """Список запланированных объектов с временем."""

    target_activated = Signal(str)
    optimise_requested = Signal()
    remove_requested = Signal(str)
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        title = QLabel("МОЯ НОЧЬ")
        title.setObjectName("panelTitle")

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(
            lambda item: self.target_activated.emit(item.data(ROLE_ID)))
        self.list.itemChanged.connect(self._item_changed)

        self.hint = QLabel("Добавляйте объекты кнопкой «В план»")
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)

        optimise = QPushButton("Оптимизировать порядок")
        optimise.clicked.connect(self.optimise_requested)
        remove = QPushButton("Убрать")
        remove.clicked.connect(self._remove_current)
        clear = QPushButton("Очистить")
        clear.clicked.connect(self.clear_requested)

        buttons = QHBoxLayout()
        buttons.addWidget(remove)
        buttons.addWidget(clear)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(title)
        layout.addWidget(self.list, 1)
        layout.addWidget(optimise)
        layout.addLayout(buttons)
        layout.addWidget(self.hint)

    def show_plan(self, plan) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for item in plan.items:
            when = f"{item.scheduled:%H:%M}" if item.scheduled else "—:—"
            stars = "★" * item.stars
            text = f"{when}   {item.name}  {stars}"
            if item.note:
                text += f"   ({item.note})"
            entry = QListWidgetItem(text)
            entry.setData(ROLE_ID, item.target_id)
            entry.setFlags(entry.flags() | Qt.ItemIsUserCheckable)
            entry.setCheckState(Qt.Checked if item.done else Qt.Unchecked)
            self.list.addItem(entry)
        self.list.blockSignals(False)
        self.hint.setText("Двойной щелчок — повернуться к объекту"
                          if plan.items else
                          "Добавляйте объекты кнопкой «В план»")
        self.plan = plan

    def _item_changed(self, item: QListWidgetItem) -> None:
        plan = getattr(self, "plan", None)
        if plan is None:
            return
        for entry in plan.items:
            if entry.target_id == item.data(ROLE_ID):
                entry.done = item.checkState() == Qt.Checked

    def _remove_current(self) -> None:
        item = self.list.currentItem()
        if item:
            self.remove_requested.emit(item.data(ROLE_ID))
