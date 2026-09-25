"""Предпросмотр публикации в виде сообщения мессенджера.

Главная задача панели — показать ровно то, что уйдёт в канал, и предупредить о
лимите заранее, а не в момент отправки. Длина считается по правилам Telegram
(единицы UTF-16), поэтому эмодзи в заголовке и маркерах учтены честно.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox,QFileDialog, QHBoxLayout, QLabel, QPushButton,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from astrocal.telegram import TELEGRAM_LIMIT, Publication

from .. import theme


class BubbleView(QTextBrowser):
    """Текст сообщения в «пузыре», как его увидит читатель канала."""

    def __init__(self, tokens: theme.Tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens
        self.setOpenExternalLinks(False)
        self.setStyleSheet(
            f"QTextBrowser {{ background: {tokens.surface_alt};"
            f" border: 1px solid {tokens.border}; border-radius: 10px;"
            f" padding: 10px; }}")

    def show_text(self, text: str) -> None:
        escaped = (text.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;").replace("\n", "<br>"))
        self.setHtml(
            f"<div style='font-size:13px; line-height:150%;'>{escaped}</div>")


class TelegramPreview(QWidget):
    """Предпросмотр, счётчик символов, копирование и сохранение."""

    copied = Signal(str)
    icons_toggled = Signal(bool)
    save_requested = Signal(str)
    send_requested = Signal()

    def __init__(self, tokens: theme.Tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens
        self.publication: Publication | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Предпросмотр публикации")
        title.setObjectName("Heading")
        header.addWidget(title)
        header.addStretch(1)
        self.counter = QLabel("0 / 4096")
        header.addWidget(self.counter)
        layout.addLayout(header)

        # Значки вместо общего маркера ▪️: пост на полсотни строк иначе
        # читается как сплошная стена
        self.icons_box = QCheckBox("Значки событий вместо ▪️")
        self.icons_box.setToolTip("Планетам — свои символы, метеорам, кометам "
                                  "и покрытиям — свои")
        self.icons_box.stateChanged.connect(
            lambda _state: self.icons_toggled.emit(self.icons_box.isChecked()))
        layout.addWidget(self.icons_box)

        self.notice = QLabel("")
        self.notice.setObjectName("Muted")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Панель узкая, поэтому кнопки в два ряда: иначе подписи обрезаются
        top_row = QHBoxLayout()
        self.copy_all_button = QPushButton("Скопировать всё")
        self.copy_all_button.setObjectName("Primary")
        self.send_button = QPushButton("Отправить в Telegram")
        top_row.addWidget(self.copy_all_button, 1)
        top_row.addWidget(self.send_button, 1)
        layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        self.save_txt_button = QPushButton("TXT")
        self.save_md_button = QPushButton("Markdown")
        self.save_json_button = QPushButton("JSON")
        save_label = QLabel("Сохранить:")
        save_label.setObjectName("Muted")
        bottom_row.addWidget(save_label)
        for button in (self.save_txt_button, self.save_md_button,
                       self.save_json_button):
            bottom_row.addWidget(button, 1)
        layout.addLayout(bottom_row)

        self.copy_all_button.clicked.connect(self._copy_all)
        self.save_txt_button.clicked.connect(lambda: self.save_requested.emit("txt"))
        self.save_md_button.clicked.connect(lambda: self.save_requested.emit("md"))
        self.save_json_button.clicked.connect(lambda: self.save_requested.emit("json"))
        self.send_button.clicked.connect(self.send_requested.emit)

    # ------------------------------------------------------------ обновление

    def set_publication(self, publication: Publication) -> None:
        self.publication = publication
        self._update_counter(publication)
        self._rebuild_tabs(publication)

    def _update_counter(self, publication: Publication) -> None:
        length = publication.length
        self.counter.setText(f"{length} / {TELEGRAM_LIMIT} символов")
        color = self.tokens.ok if length <= TELEGRAM_LIMIT else self.tokens.warn
        self.counter.setStyleSheet(f"color: {color}; font-weight: 600;")

        notes = []
        if publication.needs_split:
            notes.append(f"Сообщение будет разделено на {len(publication.parts)} "
                         f"части — ни одно событие не разорвано.")
        if publication.oversized_lines:
            notes.append(f"{len(publication.oversized_lines)} строк(и) сами длиннее "
                         f"лимита: их нужно сократить.")
        self.notice.setText(" ".join(notes))
        self.notice.setStyleSheet(
            f"color: {self.tokens.warn};" if notes else "")

    def _rebuild_tabs(self, publication: Publication) -> None:
        current = self.tabs.currentIndex()
        while self.tabs.count():
            self.tabs.removeTab(0)
        for part in publication.parts:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(6, 6, 6, 6)
            bubble = BubbleView(self.tokens)
            bubble.show_text(part.text)
            page_layout.addWidget(bubble, 1)

            row = QHBoxLayout()
            length_label = QLabel(f"{part.length} символов")
            length_label.setObjectName("Muted")
            row.addWidget(length_label)
            row.addStretch(1)
            copy_button = QPushButton("Копировать")
            copy_button.clicked.connect(
                lambda _=False, text=part.text: self._copy(text))
            row.addWidget(copy_button)
            page_layout.addLayout(row)

            label = part.label if publication.needs_split else "Сообщение"
            self.tabs.addTab(page, label)
        if 0 <= current < self.tabs.count():
            self.tabs.setCurrentIndex(current)

    # ------------------------------------------------------------ буфер обмена

    def _copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.copied.emit("Текст скопирован в буфер обмена")

    def _copy_all(self) -> None:
        if not self.publication:
            return
        self._copy(self.publication.full_text)

    def ask_save_path(self, suggested: str, filters: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить", suggested, filters)
        return path or None
