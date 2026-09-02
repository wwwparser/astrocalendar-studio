"""Лента времени: ползунок по ночи, шаги и воспроизведение.

Ползунок размечен в минутах от начала ночи, а не в абсолютном времени: ночь
короче суток, и растягивать её на двадцать четыре часа значит отдать половину
шкалы дневному небу.
"""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

STEPS = [("1 мин", 1), ("5 мин", 5), ("15 мин", 15), ("1 час", 60)]

# Скорость воспроизведения: за одну реальную секунду проходит столько минут неба.
PLAY_MINUTES_PER_SECOND = 10.0
PLAY_INTERVAL_MS = 200


class Timeline(QWidget):
    """Управление моментом времени внутри выбранной ночи."""

    moment_changed = Signal(object)      # dt.datetime

    def __init__(self, parent=None):
        super().__init__(parent)
        self._start = dt.datetime.now(dt.timezone.utc)
        self._end = self._start + dt.timedelta(hours=8)
        self._moment = self._start
        self._quiet = False

        self.start_label = QLabel("—")
        self.end_label = QLabel("—")
        self.moment_label = QLabel("—")
        self.moment_label.setObjectName("clock")
        self.moment_label.setAlignment(Qt.AlignCenter)
        self.moment_label.setMinimumWidth(150)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(480)
        self.slider.valueChanged.connect(self._slider_moved)

        self.step_box = QComboBox()
        for label, _ in STEPS:
            self.step_box.addItem(label)
        self.step_box.setCurrentIndex(1)

        self.first_button = QPushButton("⏮")
        self.back_button = QPushButton("◀")
        self.play_button = QPushButton("▶")
        self.forward_button = QPushButton("▶|")
        self.last_button = QPushButton("⏭")
        self.now_button = QPushButton("Сейчас")
        for button in (self.first_button, self.back_button, self.play_button,
                       self.forward_button, self.last_button):
            button.setFixedWidth(38)

        self.first_button.clicked.connect(lambda: self.set_moment(self._start))
        self.last_button.clicked.connect(lambda: self.set_moment(self._end))
        self.back_button.clicked.connect(lambda: self.nudge(-1))
        self.forward_button.clicked.connect(lambda: self.nudge(+1))
        self.play_button.clicked.connect(self.toggle_play)

        self._timer = QTimer(self)
        self._timer.setInterval(PLAY_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

        controls = QHBoxLayout()
        controls.addWidget(self.first_button)
        controls.addWidget(self.back_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.forward_button)
        controls.addWidget(self.last_button)
        controls.addSpacing(8)
        controls.addWidget(QLabel("Шаг"))
        controls.addWidget(self.step_box)
        controls.addSpacing(8)
        controls.addWidget(self.now_button)
        controls.addStretch(1)
        controls.addWidget(self.moment_label)

        track = QHBoxLayout()
        track.addWidget(self.start_label)
        track.addWidget(self.slider, 1)
        track.addWidget(self.end_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 6)
        layout.addLayout(track)
        layout.addLayout(controls)

    # ------------------------------------------------------------ границы

    def set_night(self, start: dt.datetime, end: dt.datetime,
                  moment: dt.datetime | None = None) -> None:
        self._start, self._end = start, end
        minutes = max(30, int((end - start).total_seconds() // 60))
        self._quiet = True
        self.slider.setMaximum(minutes)
        self._quiet = False
        self.start_label.setText(f"{start:%H:%M}")
        self.end_label.setText(f"{end:%H:%M}")
        self.set_moment(moment or self._moment)

    @property
    def moment(self) -> dt.datetime:
        return self._moment

    @property
    def step_minutes(self) -> int:
        return STEPS[self.step_box.currentIndex()][1]

    # ------------------------------------------------------------ движение

    def set_moment(self, moment: dt.datetime, emit: bool = True) -> None:
        moment = min(max(moment, self._start), self._end)
        self._moment = moment
        offset = int((moment - self._start).total_seconds() // 60)
        self._quiet = True
        self.slider.setValue(max(0, min(self.slider.maximum(), offset)))
        self._quiet = False
        self.moment_label.setText(f"{moment:%d.%m  %H:%M}")
        if emit:
            self.moment_changed.emit(moment)

    def nudge(self, direction: int) -> None:
        self.set_moment(self._moment
                        + dt.timedelta(minutes=direction * self.step_minutes))

    def _slider_moved(self, value: int) -> None:
        if self._quiet:
            return
        self.set_moment(self._start + dt.timedelta(minutes=value))

    # ------------------------------------------------------------ проигрывание

    def toggle_play(self) -> None:
        if self._timer.isActive():
            self.stop()
        else:
            self._timer.start()
            self.play_button.setText("⏸")

    def stop(self) -> None:
        self._timer.stop()
        self.play_button.setText("▶")

    def _tick(self) -> None:
        step = PLAY_MINUTES_PER_SECOND * PLAY_INTERVAL_MS / 1000.0
        nextMoment = self._moment + dt.timedelta(minutes=step)
        if nextMoment >= self._end:
            self.set_moment(self._end)
            self.stop()
            return
        self.set_moment(nextMoment)
