"""Панель «сегодня ночью»: список того, ради чего стоит выйти во двор."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

ROLE_ID = Qt.UserRole + 1


class TonightPanel(QWidget):
    """Рекомендации на выбранную ночь."""

    target_activated = Signal(str)
    add_to_plan = Signal(str)
    refresh_requested = Signal()
    surprise_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.recommendations: list = []

        self.title = QLabel("СЕГОДНЯ НОЧЬЮ")
        self.title.setObjectName("panelTitle")
        self.summary = QLabel("Нажмите «Что посмотреть сегодня»")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("muted")

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setUniformItemSizes(False)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(self._double_clicked)

        self.refresh_button = QPushButton("⭐  Что посмотреть сегодня")
        self.refresh_button.setObjectName("primary")
        self.refresh_button.clicked.connect(self.refresh_requested)

        self.surprise_button = QPushButton("✨  Покажи что-нибудь")
        self.surprise_button.clicked.connect(self.surprise_requested)

        self.plan_button = QPushButton("В план")
        self.plan_button.setEnabled(False)
        self.plan_button.clicked.connect(self._add_current)

        buttons = QHBoxLayout()
        buttons.addWidget(self.surprise_button, 1)
        buttons.addWidget(self.plan_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.title)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.summary)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)

    # ------------------------------------------------------------ содержимое

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.refresh_button.setText("Считаю…" if busy
                                    else "⭐  Что посмотреть сегодня")

    def show_recommendations(self, recommendations: list, night_text: str = "") -> None:
        self.recommendations = recommendations
        self.list.clear()
        if not recommendations:
            self.summary.setText(
                "Ничего подходящего не найдено: проверьте дату, "
                "препятствия на участке и выбранный прибор.")
            return
        self.summary.setText(night_text or f"Найдено объектов: {len(recommendations)}")
        for recommendation in recommendations:
            item = QListWidgetItem()
            item.setText(f"{recommendation.stars_text}  {recommendation.target.name}\n"
                         f"      {recommendation.window_text} · "
                         f"выс. {recommendation.altitude_deg:.0f}°")
            item.setData(ROLE_ID, recommendation.target.id)
            tip = [f"{recommendation.target.kind_ru}, оценка "
                   f"{recommendation.score}/100"]
            tip.extend(recommendation.reasons[:4])
            item.setToolTip("\n".join(tip))
            self.list.addItem(item)

    def select_target(self, target_id: str) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(ROLE_ID) == target_id:
                self.list.setCurrentItem(item)
                return

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ROLE_ID) if item else None

    # ------------------------------------------------------------ события

    def _selection_changed(self) -> None:
        target_id = self.current_id()
        self.plan_button.setEnabled(bool(target_id))
        if target_id:
            self.target_activated.emit(target_id)

    def _double_clicked(self, item: QListWidgetItem) -> None:
        self.target_activated.emit(item.data(ROLE_ID))

    def _add_current(self) -> None:
        target_id = self.current_id()
        if target_id:
            self.add_to_plan.emit(target_id)
