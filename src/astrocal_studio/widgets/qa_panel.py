"""Панель проверки выпуска.

Показывает не «всё хорошо», а конкретные цифры: сколько событий сверено с
Horizons, сколько источников, где расхождения. Неопределённости не прячутся —
именно ради них панель и существует.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import theme


class QaPanel(QWidget):
    """Сводка проверок и раскрываемый список замечаний."""

    open_report_requested = Signal()
    recheck_requested = Signal()

    def __init__(self, tokens: theme.Tokens, parent=None):
        super().__init__(parent)
        self.tokens = tokens
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = QLabel("Проверка выпуска")
        title.setObjectName("Heading")
        layout.addWidget(title)

        self.summary = QTextBrowser()
        self.summary.setMaximumHeight(190)
        layout.addWidget(self.summary)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Событие", "Проверка", "Сообщение"])
        self.tree.setColumnWidth(0, 240)
        self.tree.setColumnWidth(1, 120)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.recheck_button = QPushButton("Пересверить с Horizons")
        self.report_button = QPushButton("Открыть QA-отчёт")
        buttons.addWidget(self.recheck_button)
        buttons.addWidget(self.report_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.recheck_button.clicked.connect(self.recheck_requested.emit)
        self.report_button.clicked.connect(self.open_report_requested.emit)

    # ------------------------------------------------------------ наполнение

    def show_issue(self, issue) -> None:
        if issue is None:
            self.summary.setHtml("")
            self.tree.clear()
            return

        events = [item.event for item in issue.events]
        horizons_checked = sum(1 for e in events
                               if (e.provenance or {}).get("horizons"))
        deltas = [float(value) for e in events
                  for value in ((e.provenance or {}).get("horizons") or {}).values()]
        with_sources = sum(1 for e in events if e.sources)
        review = [item for item in issue.events if item.qa_level == "REVIEW"]
        warn = [item for item in issue.events if item.qa_level == "WARN"]
        duplicates = sum(1 for e in events
                         for f in e.flags if f.check == "duplicate")
        distance_flags = sum(1 for e in events for f in e.flags
                             if f.check.startswith("moon_distance"))
        timezone_flags = sum(1 for e in events for f in e.flags
                             if f.check in ("timezone", "range"))

        def mark(ok: bool) -> str:
            color = self.tokens.ok if ok else self.tokens.review
            return f"<span style='color:{color}'>{'✓' if ok else '▲'}</span>"

        rows = [
            (mark(True), "Horizons",
             f"{horizons_checked}/{len(events)}" +
             (f", максимум {max(deltas):.2f}″" if deltas else "")),
            (mark(timezone_flags == 0), "Время и часовой пояс",
             "OK" if timezone_flags == 0 else f"{timezone_flags} замечаний"),
            (mark(duplicates == 0), "Дубликаты", str(duplicates)),
            (mark(with_sources == len(events)), "Источники",
             f"{with_sources}/{len(events)}"),
            (mark(distance_flags == 0), "Расстояния",
             "OK" if distance_flags == 0 else f"{distance_flags} замечаний"),
        ]
        body = "".join(
            f"<tr><td style='padding-right:8px'>{icon}</td>"
            f"<td style='padding-right:14px'>{name}</td><td>{value}</td></tr>"
            for icon, name, value in rows)
        counters = (
            f"<p style='margin-top:8px'>"
            f"<span style='color:{self.tokens.review}'>REVIEW: {len(review)}</span>"
            f" &nbsp;&nbsp; "
            f"<span style='color:{self.tokens.warn}'>WARN: {len(warn)}</span>"
            f"</p>")
        self.summary.setHtml(
            f"<table style='font-size:13px'>{body}</table>{counters}")

        self.tree.clear()
        for item in review + warn:
            parent = QTreeWidgetItem([
                f"{item.when:%d.%m %H:%M} {item.calculated_text[:60]}",
                item.qa_level, ""])
            for flag in item.event.flags:
                parent.addChild(QTreeWidgetItem(["", flag.check, flag.message]))
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)

        # расхождения источников по блеску комет показываем всегда
        for item in issue.events:
            disagreement = (item.event.meta or {}).get("magnitude_sources")
            if not disagreement:
                continue
            parent = QTreeWidgetItem([
                f"{item.when:%d.%m} {item.calculated_text[:60]}",
                "источники блеска", ""])
            for source, value in disagreement.items():
                parent.addChild(QTreeWidgetItem(["", source, f"{value:+.1f}m"]))
            values = list(disagreement.values())
            if len(values) > 1:
                parent.addChild(QTreeWidgetItem(
                    ["", "расхождение", f"{max(values) - min(values):.1f}m"]))
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)
