"""Карточка объекта: что это, где искать и стоит ли смотреть.

Текст собирается из рассчитанных величин по шаблонам. Никаких обобщений вроде
«отличный объект» без числа за ними: если написано «помещается в поле», это
следует из размера объекта и поля зрения прибора.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QGridLayout, QLabel, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)


class ObjectDetails(QWidget):
    """Панель выбранного объекта."""

    look_requested = Signal()
    binocular_requested = Signal()
    track_requested = Signal()
    plan_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_id: str | None = None

        self.title = QLabel("Объект не выбран")
        self.title.setObjectName("panelTitle")
        self.title.setWordWrap(True)

        self.subtitle = QLabel("")
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        self.body.setMinimumHeight(150)

        self.look_button = QPushButton("Повернуться к объекту")
        self.binocular_button = QPushButton("Вид в бинокль")
        self.track_button = QPushButton("Траектория ночи")
        self.plan_button = QPushButton("Добавить в план")
        self.look_button.clicked.connect(self.look_requested)
        self.binocular_button.clicked.connect(self.binocular_requested)
        self.track_button.clicked.connect(self.track_requested)
        self.plan_button.clicked.connect(self.plan_requested)

        buttons = QGridLayout()
        buttons.addWidget(self.look_button, 0, 0)
        buttons.addWidget(self.binocular_button, 0, 1)
        buttons.addWidget(self.track_button, 1, 0)
        buttons.addWidget(self.plan_button, 1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.body, 1)
        layout.addLayout(buttons)
        self.set_enabled(False)

    def set_enabled(self, enabled: bool) -> None:
        for button in (self.look_button, self.binocular_button,
                       self.track_button, self.plan_button):
            button.setEnabled(enabled)

    def clear(self) -> None:
        self.target_id = None
        self.title.setText("Объект не выбран")
        self.subtitle.setText("")
        self.body.setHtml("")
        self.set_enabled(False)

    # ------------------------------------------------------------ наполнение

    def show_target(self, recommendation, binocular, where_text: str,
                    in_plan: bool = False) -> None:
        target = recommendation.target
        self.target_id = target.id
        self.title.setText(target.name)

        parts = [target.kind_ru]
        if target.constellation:
            from astrocal.constellations import name_ru
            parts.append(name_ru(target.constellation))
        self.subtitle.setText(" · ".join(parts))

        rows = []
        if recommendation.magnitude is not None:
            rows.append(("Блеск", f"{recommendation.magnitude:+.1f}m"))
        if target.size_arcmin:
            rows.append(("Размер", _size_text(target.size_arcmin)))
        surface = target.effective_surface_brightness()
        if surface is not None and target.is_extended:
            rows.append(("Поверхностная яркость", f"{surface:.1f} mag/□″"))
        if target.distance_text:
            rows.append(("Расстояние", target.distance_text))

        rows.append(("Азимут", f"{recommendation.azimuth_deg:.0f}°"))
        rows.append(("Высота", f"{recommendation.altitude_deg:.0f}°"))
        rows.append((f"Для {binocular.short_label}",
                     f"{recommendation.stars_text} ({recommendation.score}/100)"))
        rows.append(("Предел прибора", f"≈ {recommendation.limiting_magnitude:+.1f}m"))
        if recommendation.fits_in_field is not None:
            fraction = recommendation.field_fraction or 0.0
            rows.append(("В поле зрения",
                         "да, целиком" if recommendation.fits_in_field
                         else f"нет — крупнее поля в {fraction:.1f} раза"))
        window = recommendation.visibility.best_window
        if window:
            rows.append(("Лучшее время",
                         f"{window.start:%H:%M}–{window.end:%H:%M}"))

        html = ["<style>td{padding:2px 8px 2px 0;} .k{color:#8f9bb3;}</style>",
                "<table>"]
        for key, value in rows:
            html.append(f"<tr><td class='k'>{key}</td><td><b>{value}</b></td></tr>")
        html.append("</table>")

        html.append(f"<p><b>Где искать:</b><br>{where_text}</p>")

        if recommendation.reasons:
            html.append("<p><b>Почему стоит смотреть:</b></p><ul>")
            html.extend(f"<li>{reason}</li>"
                        for reason in dict.fromkeys(recommendation.reasons))
            html.append("</ul>")
        if recommendation.warnings:
            html.append("<p><b>Учтите:</b></p><ul>")
            html.extend(f"<li>{warning}</li>"
                        for warning in dict.fromkeys(recommendation.warnings))
            html.append("</ul>")

        self.body.setHtml("".join(html))
        self.set_enabled(True)
        self.plan_button.setText("Уже в плане" if in_plan else "Добавить в план")
        self.plan_button.setEnabled(not in_plan)


def _size_text(arcmin: float) -> str:
    if arcmin >= 60:
        return f"{arcmin / 60:.1f}° ({arcmin:.0f}′)"
    if arcmin >= 1:
        return f"{arcmin:.1f}′"
    return f"{arcmin * 60:.0f}″"
