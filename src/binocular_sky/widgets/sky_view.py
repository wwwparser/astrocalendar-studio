"""Трёхмерное небо: обёртка над QWebEngineView и мост в JavaScript.

Единственное место, где Python разговаривает с рендерером. Наружу виджет
выглядит обычным Qt-виджетом с методами «покажи снимок», «повернись к объекту»,
«включи ночной режим»; всё, что связано с JS, спрятано здесь.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class Bridge(QObject):
    """Объект, видимый из JavaScript как `bridge`."""

    object_selected = Signal(str)
    viewer_ready = Signal()

    @Slot(str)
    def objectSelected(self, target_id: str) -> None:      # noqa: N802 — имя из JS
        self.object_selected.emit(target_id)

    @Slot()
    def viewerReady(self) -> None:                          # noqa: N802 — имя из JS
        self.viewer_ready.emit()


class LoggingPage(QWebEnginePage):
    """Страница, пересылающая сообщения консоли наружу.

    Ошибка в шейдере или опечатка в модуле иначе просто гасит сцену: экран
    остаётся чёрным, и понять причину из Python невозможно.
    """

    message = Signal(str)

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        name = source.rsplit("/", 1)[-1] if source else "?"
        self.message.emit(f"[{name}:{line}] {message}")


class SkyView(QWidget):
    """3D-вид неба и участка."""

    object_selected = Signal(str)
    console_message = Signal(str)
    ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ready = False
        self._pending: list[str] = []

        self.view = QWebEngineView(self)
        self.page = LoggingPage(self.view)
        self.page.message.connect(self.console_message)
        self.view.setPage(self.page)
        self.bridge = Bridge(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)

        self.bridge.object_selected.connect(self.object_selected)
        self.bridge.viewer_ready.connect(self._on_ready)
        self.view.loadFinished.connect(self._on_load_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.view.load(QUrl.fromLocalFile(str(WEB_DIR / "index.html")))

    # ------------------------------------------------------------ готовность

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        # страница загружена; мост может подключиться чуть позже, поэтому
        # окончательным признаком готовности считается сигнал из JS
        self._run("window.sky && window.sky.ready();")

    def _on_ready(self) -> None:
        self._ready = True
        for script in self._pending:
            self.view.page().runJavaScript(script)
        self._pending.clear()
        self.ready.emit()

    def _run(self, script: str) -> None:
        if self._ready:
            self.view.page().runJavaScript(script)
        else:
            self._pending.append(script)

    @staticmethod
    def _literal(payload) -> str:
        """JSON как строковый литерал JavaScript."""
        return json.dumps(json.dumps(payload, ensure_ascii=False))

    # ------------------------------------------------------------ команды

    def show_snapshot(self, snapshot: dict) -> None:
        self._run(f"window.sky.loadSnapshot({self._literal(snapshot)});")

    def look_at(self, azimuth: float, altitude: float,
                immediate: bool = False) -> None:
        self._run(f"window.sky.lookAt({azimuth:.3f}, {altitude:.3f}, "
                  f"{'true' if immediate else 'false'});")

    def select(self, target_id: str) -> None:
        self._run(f"window.sky.selectById({json.dumps(target_id)});")

    def set_night_mode(self, enabled: bool) -> None:
        self._run(f"window.sky.setNightMode({'true' if enabled else 'false'});")

    def set_options(self, **options) -> None:
        self._run(f"window.sky.setOptions({self._literal(options)});")

    def set_banner(self, text: str) -> None:
        self._run(f"window.sky.setBanner({json.dumps(text or '')});")

    def show_track(self, track: dict) -> None:
        self._run(f"window.sky.showTrack({self._literal(track)});")

    def clear_track(self) -> None:
        self._run("window.sky.clearTrack();")

    def enter_binocular(self, field: dict) -> None:
        self._run(f"window.sky.enterBinocular({self._literal(field)});")

    def exit_binocular(self) -> None:
        self._run("window.sky.exitBinocular();")

    def capture_image(self, callback) -> None:
        """Получить снимок сцены и передать его в `callback` как QImage.

        Картинка приходит из самого холста: содержимое QWebEngineView рисуется
        отдельным композитором и в `QWidget.grab()` не попадает.
        """
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QImage

        def receive(data_url) -> None:
            if not data_url or "," not in str(data_url):
                callback(None)
                return
            payload = str(data_url).split(",", 1)[1]
            image = QImage()
            image.loadFromData(QByteArray.fromBase64(payload.encode("ascii")),
                               "PNG")
            callback(None if image.isNull() else image)

        self.view.page().runJavaScript("window.sky.captureImage();", receive)
