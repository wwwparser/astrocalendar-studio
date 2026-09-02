"""Панель события: текст, карты, обстоятельства, проверки.

Расчётный текст и редакторская правка живут в разных полях. Первый доступен
только для чтения — иначе одно неосторожное нажатие уничтожает то, что
посчитала система, и восстановить это можно только полным пересчётом.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QScrollArea, QTabWidget, QTextBrowser, QVBoxLayout,
                               QWidget)


class ImageView(QScrollArea):
    """Просмотр PNG с сообщением-заглушкой, когда карты нет."""

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.placeholder = placeholder
        self.label = QLabel(placeholder)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setObjectName("Muted")
        self.setWidget(self.label)
        self.setWidgetResizable(True)
        self._path: Path | None = None

    def show_message(self, text: str) -> None:
        self._path = None
        self.label.setPixmap(QPixmap())
        self.label.setText(text)

    def show_image(self, path: Path) -> None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.show_message("Не удалось открыть изображение")
            return
        self._path = path
        self.label.setText("")
        available = max(320, self.viewport().width() - 12)
        self.label.setPixmap(pixmap.scaledToWidth(
            min(available, pixmap.width()), Qt.SmoothTransformation))

    def resizeEvent(self, event):       # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        if self._path:
            self.show_image(self._path)


class EventDetails(QWidget):
    """Вкладки выбранного события."""

    text_saved = Signal(object, str)
    text_reverted = Signal(object)
    map_requested = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.item = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._text_tab(), "Текст")
        self.sky_view = ImageView("Выберите событие и нажмите «Построить карту».")
        self.tabs.addTab(self._map_tab(self.sky_view, "sky"), "Карта неба")
        self.band_view = ImageView("Для этого типа события карта полосы не требуется.")
        self.tabs.addTab(self._map_tab(self.band_view, "band"), "Полоса")
        self.cities_browser = QTextBrowser()
        self.tabs.addTab(self.cities_browser, "По городам")
        self.qa_browser = QTextBrowser()
        self.tabs.addTab(self.qa_browser, "QA")
        layout.addWidget(self.tabs)

    def _text_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        calculated_label = QLabel("Расчётный текст")
        calculated_label.setObjectName("Muted")
        layout.addWidget(calculated_label)
        self.calculated_view = QPlainTextEdit()
        self.calculated_view.setReadOnly(True)
        self.calculated_view.setMaximumHeight(70)
        layout.addWidget(self.calculated_view)

        editor_label = QLabel("Редакторский текст")
        editor_label.setObjectName("Muted")
        layout.addWidget(editor_label)
        self.editor = QPlainTextEdit()
        self.editor.setMaximumHeight(90)
        layout.addWidget(self.editor)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("Сохранить редакцию")
        self.save_button.setObjectName("Primary")
        self.revert_button = QPushButton("Вернуть расчётный текст")
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.revert_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.save_button.clicked.connect(self._save)
        self.revert_button.clicked.connect(self._revert)

        self.info = QTextBrowser()
        layout.addWidget(self.info, 1)
        return page

    def _map_tab(self, view: ImageView, kind: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        button = QPushButton("Построить карту")
        button.clicked.connect(lambda: self.item and
                               self.map_requested.emit(self.item, kind))
        layout.addWidget(button, 0, Qt.AlignLeft)
        layout.addWidget(view, 1)
        return page

    # ------------------------------------------------------------ содержимое

    def show_event(self, item) -> None:
        self.item = item
        if item is None:
            self.calculated_view.setPlainText("")
            self.editor.setPlainText("")
            self.info.setHtml("")
            self.cities_browser.setHtml("")
            self.qa_browser.setHtml("")
            self.sky_view.show_message("Событие не выбрано.")
            self.band_view.show_message("Событие не выбрано.")
            return

        self.calculated_view.setPlainText(item.calculated_text)
        self.editor.setPlainText(item.text)
        self.info.setHtml(self._info_html(item))
        self.cities_browser.setHtml(self._cities_html(item))
        self.qa_browser.setHtml(self._qa_html(item))

        cached_sky = item.maps.get("sky")
        if cached_sky and Path(cached_sky).exists():
            self.sky_view.show_image(Path(cached_sky))
        else:
            self.sky_view.show_message(
                "Нажмите «Построить карту», чтобы рассчитать вид неба.")

        cached_band = item.maps.get("band")
        if cached_band and Path(cached_band).exists():
            self.band_view.show_image(Path(cached_band))
        elif item.kind in ("occultation", "solar_eclipse", "lunar_eclipse",
                           "asteroid_occultation"):
            self.band_view.show_message(
                "Нажмите «Построить карту», чтобы рассчитать полосу видимости.")
        else:
            self.band_view.show_message(
                "Для этого типа события карта полосы не требуется.")

    def _info_html(self, item) -> str:
        event = item.event
        rows = [
            ("Расчётное время", f"{event.when:%d.%m.%Y %H:%M:%S} МСК"),
            ("В публикации", f"{item.when:%d.%m.%Y %H:%M} МСК"),
            ("Часовой пояс", "Europe/Moscow (UTC+3), без перехода"),
            ("Категория", f"{item.kind_title} ({event.category})"),
            ("Ранг", item.rank_title),
            ("Уверенность", event.confidence),
            ("Расчёт", event.computed or "—"),
            ("Источники", "; ".join(event.sources) or "—"),
            ("Примечание", event.notes or "—"),
        ]
        horizons = (event.provenance or {}).get("horizons")
        if horizons:
            rows.append(("Сверка с Horizons",
                         ", ".join(f"{name}: {value}″"
                                   for name, value in horizons.items())))
        provenance = event.provenance or {}
        for key in ("ephemeris", "catalogs", "computed_at_utc"):
            if provenance.get(key):
                rows.append((key, str(provenance[key])))
        if item.source_changed:
            rows.append(("Внимание",
                         "Исходные данные этого события изменились после вашей "
                         "редакторской правки."))
        body = "".join(
            f"<tr><td style='padding:2px 10px 2px 0;color:#8d99ab;"
            f"vertical-align:top'>{name}</td><td>{value}</td></tr>"
            for name, value in rows)
        return f"<table style='font-size:12px'>{body}</table>"

    def _cities_html(self, item) -> str:
        if not item.circumstances:
            return ("<p style='color:#8d99ab'>Для этого события обстоятельства "
                    "по городам не рассчитываются.</p>")
        rows = []
        for c in item.circumstances:
            if not c.visible:
                rows.append(f"<tr><td>{c.city.name}</td><td colspan='5' "
                            f"style='color:#8d99ab'>не наблюдается — {c.note}</td></tr>")
                continue
            rows.append(
                f"<tr><td>{c.city.name}</td>"
                f"<td>{c.stars_text}</td>"
                f"<td>{c.best_time:%d.%m %H:%M}</td>"
                f"<td>{c.altitude_deg:.0f}°</td>"
                f"<td>{c.azimuth_deg:.0f}° ({c.direction})</td>"
                f"<td>Солнце {c.sun_altitude_deg:.0f}°, {c.instrument_ru}</td></tr>")
        header = ("<tr style='color:#8d99ab'><th align='left'>Город</th>"
                  "<th align='left'>Условия</th><th align='left'>Лучшее время</th>"
                  "<th align='left'>Высота</th><th align='left'>Азимут</th>"
                  "<th align='left'>Прочее</th></tr>")
        return (f"<table style='font-size:12px' cellpadding='3'>{header}"
                f"{''.join(rows)}</table>")

    def _qa_html(self, item) -> str:
        event = item.event
        parts = [f"<p><b>Статус: {item.qa_level}</b></p>"]
        if event.flags:
            parts.append("<ul>")
            for flag in event.flags:
                parts.append(f"<li><b>{flag.level}</b> · {flag.check}: "
                             f"{flag.message}</li>")
            parts.append("</ul>")
        else:
            parts.append("<p style='color:#8d99ab'>Проверки пройдены без "
                         "замечаний.</p>")
        parts.append(f"<p style='color:#8d99ab'>Расчёт: {event.computed}</p>")
        parts.append("<p style='color:#8d99ab'>Источники: "
                     f"{'; '.join(event.sources) or '—'}</p>")
        return "".join(parts)

    # ------------------------------------------------------------ действия

    def _save(self) -> None:
        if self.item is None:
            return
        self.text_saved.emit(self.item, self.editor.toPlainText().strip())

    def _revert(self) -> None:
        if self.item is None:
            return
        self.text_reverted.emit(self.item)
        self.editor.setPlainText(self.item.calculated_text)

    def show_map(self, kind: str, path: Path) -> None:
        view = self.sky_view if kind == "sky" else self.band_view
        view.show_image(path)

    def show_map_message(self, kind: str, message: str) -> None:
        view = self.sky_view if kind == "sky" else self.band_view
        view.show_message(message)
