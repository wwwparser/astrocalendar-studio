"""Хранение пользовательских данных вне репозитория.

Площадки, бинокли, обмер участка и планы — это данные конкретного человека, а
не часть программы. Они живут в ``%APPDATA%\\BinocularSky`` (на других системах —
в ``~/.config/binocular-sky``) и никогда не попадают в git.

Запись атомарная: сначала во временный файл, потом переименование. Выключенный
на середине сохранения ноутбук не должен оставлять человека без профиля.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .models.binocular import BinocularProfile, default_binoculars
from .models.observer import ObserverProfile, demo_observer
from .models.scene import Landscape, demo_landscape
from .services.observing_service import ObservingPlan

SETTINGS_VERSION = 1


def data_dir() -> Path:
    """Каталог пользовательских данных. Переопределяется BINOCULAR_SKY_HOME."""
    override = os.environ.get("BINOCULAR_SKY_HOME")
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / "BinocularSky"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        path = Path(base) / "binocular-sky"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_file() -> Path:
    return data_dir() / "settings.json"


@dataclass
class Settings:
    """Всё, что переживает перезапуск программы."""

    observers: list = field(default_factory=list)
    binoculars: list = field(default_factory=list)
    landscapes: dict = field(default_factory=dict)      # ключ площадки → Landscape
    active_observer: int = 0
    active_binocular: int = 0
    night_mode: bool = False
    star_level: int = 2
    show_constellations: bool = True
    show_labels: bool = True
    plans: dict = field(default_factory=dict)           # ISO-дата → ObservingPlan
    wizard_done: bool = False

    # ------------------------------------------------------------ доступ

    @property
    def observer(self) -> ObserverProfile:
        if not self.observers:
            self.observers = [demo_observer()]
        index = min(max(0, self.active_observer), len(self.observers) - 1)
        return self.observers[index]

    @property
    def binocular(self) -> BinocularProfile:
        if not self.binoculars:
            self.binoculars = default_binoculars()
        index = min(max(0, self.active_binocular), len(self.binoculars) - 1)
        return self.binoculars[index]

    def landscape_for(self, observer: ObserverProfile | None = None) -> Landscape:
        """Участок выбранной площадки. У каждой площадки он свой."""
        observer = observer or self.observer
        landscape = self.landscapes.get(observer.key)
        if landscape is None:
            landscape = demo_landscape() if observer.is_demo else Landscape(
                name=f"Участок — {observer.name}")
            self.landscapes[observer.key] = landscape
        return landscape

    def set_landscape(self, observer: ObserverProfile, landscape: Landscape) -> None:
        self.landscapes[observer.key] = landscape

    def plan_for(self, date: dt.date) -> ObservingPlan:
        key = date.isoformat()
        if key not in self.plans:
            self.plans[key] = ObservingPlan(date=date)
        return self.plans[key]

    # ------------------------------------------------------------ файл

    def to_dict(self) -> dict:
        return {
            "version": SETTINGS_VERSION,
            "observers": [o.to_dict() for o in self.observers],
            "binoculars": [b.to_dict() for b in self.binoculars],
            "landscapes": {k: v.to_dict() for k, v in self.landscapes.items()},
            "active_observer": self.active_observer,
            "active_binocular": self.active_binocular,
            "night_mode": self.night_mode,
            "star_level": self.star_level,
            "show_constellations": self.show_constellations,
            "show_labels": self.show_labels,
            "plans": {k: v.to_dict() for k, v in self.plans.items()},
            "wizard_done": self.wizard_done,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Settings":
        observers = [ObserverProfile.from_dict(o)
                     for o in payload.get("observers", [])] or [demo_observer()]
        binoculars = [BinocularProfile.from_dict(b)
                      for b in payload.get("binoculars", [])] or default_binoculars()
        landscapes = {k: Landscape.from_dict(v)
                      for k, v in (payload.get("landscapes") or {}).items()}
        plans = {k: ObservingPlan.from_dict(v)
                 for k, v in (payload.get("plans") or {}).items()}
        return cls(
            observers=observers, binoculars=binoculars, landscapes=landscapes,
            active_observer=int(payload.get("active_observer", 0)),
            active_binocular=int(payload.get("active_binocular", 0)),
            night_mode=bool(payload.get("night_mode", False)),
            star_level=int(payload.get("star_level", 2)),
            show_constellations=bool(payload.get("show_constellations", True)),
            show_labels=bool(payload.get("show_labels", True)),
            plans=plans, wizard_done=bool(payload.get("wizard_done", False)))


def default_settings() -> Settings:
    """Стартовый набор: реальная площадка пользователя плюс демонстрационная.

    Демонстрационный участок (дом, деревья, забор) привязан к DEMO-площадке и
    явно ею помечен — выдавать выдуманные обмеры за настоящий двор нельзя.
    Реальная площадка заводится без препятствий: их предстоит обмерить.
    """
    home = ObserverProfile(
        name="Дача", latitude=55.324769, longitude=38.349526,
        elevation_m=120.0, eye_height_m=1.75, timezone="Europe/Moscow",
        bortle=4, notes="Координаты площадки наблюдения.")
    demo = demo_observer()
    settings = Settings(observers=[home, demo], binoculars=default_binoculars(),
                        active_observer=0, active_binocular=0)
    settings.landscapes[home.key] = Landscape(
        name="Участок — Дача", natural_horizon_deg=1.0,
        obstacles=[])
    settings.landscapes[demo.key] = demo_landscape()
    return settings


def load(path: Path | None = None) -> Settings:
    """Прочитать настройки. Битый или отсутствующий файл — не повод падать."""
    path = path or settings_file()
    if not path.exists():
        return default_settings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_settings()
    try:
        return Settings.from_dict(payload)
    except Exception:
        return default_settings()


def save(settings: Settings, path: Path | None = None) -> Path:
    """Записать настройки атомарно."""
    path = path or settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8")
    temporary.replace(path)
    return path
