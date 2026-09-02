"""Центральная таблица событий выпуска.

Таблица — главный рабочий инструмент редактора, поэтому здесь всё, что нужно
для быстрой работы: галочка включения, сортировка, множественное выделение,
пакетное включение и выключение, перетаскивание строк для ручного порядка.
"""
from __future__ import annotations

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
                            Qt, Signal)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableView, QVBoxLayout, QWidget)

from .. import theme

COLUMNS = ["", "Дата", "Время", "Событие", "Тип", "Ранг", "Набл.", "Увер.", "QA"]
COL_CHECK, COL_DATE, COL_TIME, COL_TEXT, COL_KIND, COL_RANK, COL_STARS, \
    COL_CONFIDENCE, COL_QA = range(9)


class EventsModel(QAbstractTableModel):
    """Модель над списком EditableEvent выпуска."""

    selection_changed = Signal()

    def __init__(self, tokens: theme.Tokens, parent=None):
        super().__init__(parent)
        self.items: list = []
        self.tokens = tokens

    def set_items(self, items: list) -> None:
        self.beginResetModel()
        self.items = list(items)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def item_at(self, row: int):
        return self.items[row] if 0 <= row < len(self.items) else None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        if index.column() == COL_CHECK:
            return base | Qt.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        column = index.column()

        if role == Qt.CheckStateRole and column == COL_CHECK:
            return Qt.Checked if item.selected else Qt.Unchecked

        if role == Qt.DisplayRole:
            if column == COL_DATE:
                return f"{item.when:%d.%m}"
            if column == COL_TIME:
                return f"{item.when:%H:%M}"
            if column == COL_TEXT:
                mark = "✎ " if item.edited else ("✍ " if item.manual else "")
                return mark + item.text
            if column == COL_KIND:
                return item.kind_title
            if column == COL_RANK:
                return item.rank_title
            if column == COL_STARS:
                return item.stars_text
            if column == COL_CONFIDENCE:
                return item.confidence_title
            if column == COL_QA:
                return {"OK": "✓", "WARN": "!", "REVIEW": "▲"}[item.qa_level]
            return None

        if role == Qt.ForegroundRole:
            if column == COL_RANK:
                return QBrush(QColor(theme.RANK_COLORS[item.rank](self.tokens)))
            if column == COL_QA:
                return QBrush(QColor(theme.QA_COLORS[item.qa_level](self.tokens)))
            if not item.selected:
                return QBrush(QColor(self.tokens.muted))
            if item.source_changed:
                return QBrush(QColor(self.tokens.warn))
            return None

        if role == Qt.ToolTipRole:
            lines = [item.calculated_text]
            if item.edited:
                lines.append(f"Редакция: {item.text}")
            if item.source_changed:
                lines.append("Исходные данные изменились после сохранения.")
            if item.event.flags:
                lines += [f"{f.level}: {f.message}" for f in item.event.flags]
            return "\n".join(lines)

        if role == Qt.TextAlignmentRole and column in (COL_RANK, COL_QA,
                                                       COL_CONFIDENCE):
            return int(Qt.AlignCenter)
        return None

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if role == Qt.CheckStateRole and index.column() == COL_CHECK:
            item = self.items[index.row()]
            item.selected = Qt.CheckState(value) == Qt.Checked
            self.dataChanged.emit(index.siblingAtColumn(0),
                                  index.siblingAtColumn(len(COLUMNS) - 1))
            self.selection_changed.emit()
            return True
        return False

    # ------------------------------------------------------------ порядок

    def move_rows(self, rows: list[int], offset: int) -> None:
        if not rows:
            return
        order = sorted(rows, reverse=offset > 0)
        for row in order:
            target = row + offset
            if not (0 <= target < len(self.items)):
                continue
            self.beginResetModel()
            self.items[row], self.items[target] = self.items[target], self.items[row]
            self.endResetModel()
        for position, item in enumerate(self.items):
            item.order = position
        self.selection_changed.emit()

    def current_order(self) -> list[str]:
        return [item.event_id for item in self.items]


class EventsTable(QWidget):
    """Таблица со строкой инструментов над ней."""

    current_changed = Signal(object)
    changed = Signal()

    def __init__(self, tokens: theme.Tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens
        self.model = EventsModel(tokens, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.DisplayRole)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        tools = QHBoxLayout()
        self.count_label = QLabel("Событий: 0")
        self.count_label.setObjectName("Muted")
        tools.addWidget(self.count_label)
        tools.addStretch(1)
        for label, slot in (("Включить", lambda: self._bulk(True)),
                            ("Исключить", lambda: self._bulk(False)),
                            ("Выше", lambda: self._move(-1)),
                            ("Ниже", lambda: self._move(1)),
                            ("Хронологически", self.sort_chronologically)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            tools.addWidget(button)
        layout.addLayout(tools)

        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSortingEnabled(True)
        self.view.setDragDropMode(QAbstractItemView.InternalMove)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(24)
        self.view.setWordWrap(False)

        # Ширины заданы явно: автоподбор по содержимому раздувает служебные
        # колонки и не оставляет места главному — тексту события
        self.view.setTextElideMode(Qt.ElideRight)
        header = self.view.horizontalHeader()
        header.setMinimumSectionSize(28)
        header.setStretchLastSection(False)
        fixed = {COL_CHECK: 32, COL_DATE: 58, COL_TIME: 54, COL_RANK: 56,
                 COL_STARS: 72, COL_CONFIDENCE: 60, COL_QA: 32}
        for column, width in fixed.items():
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.view.setColumnWidth(column, width)
        header.setSectionResizeMode(COL_KIND, QHeaderView.Interactive)
        self.view.setColumnWidth(COL_KIND, 150)
        header.setSectionResizeMode(COL_TEXT, QHeaderView.Stretch)

        self.view.selectionModel().currentRowChanged.connect(self._current_changed)
        self.model.selection_changed.connect(self.changed.emit)
        self.model.dataChanged.connect(lambda *_: self.changed.emit())
        layout.addWidget(self.view, 1)

    # ------------------------------------------------------------ данные

    def set_items(self, items: list) -> None:
        self.model.set_items(items)
        self.count_label.setText(f"Событий: {len(items)}")
        if items:
            self.view.selectRow(0)

    def selected_items(self) -> list:
        rows = {self.proxy.mapToSource(index).row()
                for index in self.view.selectionModel().selectedRows()}
        return [self.model.item_at(row) for row in sorted(rows)
                if self.model.item_at(row)]

    def current_item(self):
        index = self.view.currentIndex()
        if not index.isValid():
            return None
        return self.model.item_at(self.proxy.mapToSource(index).row())

    def refresh(self) -> None:
        top = self.model.index(0, 0)
        bottom = self.model.index(max(0, self.model.rowCount() - 1),
                                  len(COLUMNS) - 1)
        self.model.dataChanged.emit(top, bottom)

    # ------------------------------------------------------------ действия

    def _bulk(self, selected: bool) -> None:
        items = self.selected_items()
        if not items:
            return
        for item in items:
            item.selected = selected
        self.refresh()
        self.changed.emit()

    def _move(self, offset: int) -> None:
        rows = sorted({self.proxy.mapToSource(index).row()
                       for index in self.view.selectionModel().selectedRows()})
        if not rows:
            return
        self.view.setSortingEnabled(False)
        self.proxy.sort(-1)
        self.model.move_rows(rows, offset)
        for row in [r + offset for r in rows]:
            if 0 <= row < self.model.rowCount():
                self.view.selectRow(row)
        self.changed.emit()

    def sort_chronologically(self) -> None:
        self.model.beginResetModel()
        self.model.items.sort(key=lambda item: (item.when, item.text))
        for position, item in enumerate(self.model.items):
            item.order = position
        self.model.endResetModel()
        self.proxy.sort(-1)
        self.changed.emit()

    def _current_changed(self, current, _previous) -> None:
        if not current.isValid():
            self.current_changed.emit(None)
            return
        self.current_changed.emit(
            self.model.item_at(self.proxy.mapToSource(current).row()))
