"""Участок вокруг наблюдателя: дом, деревья, забор, естественный горизонт.

Каждое препятствие умеет две вещи:

* отдать свой **силуэт** — набор точек (азимут, высота) с точки зрения глаз
  наблюдателя. Из силуэтов собирается маска местного горизонта, по которой
  считается, закрыт объект или виден;
* отдать **геометрию** для трёхмерной сцены, которую рисует Three.js.

Обе стороны считаются из одних и тех же чисел, поэтому дом на экране и дом в
расчёте — это один и тот же дом. Если бы 3D-модель жила отдельно от маски,
картинка и ответ «виден / не виден» разошлись бы уже на первом препятствии.

Система координат сцены — локальная ENU относительно наблюдателя:
``x`` на восток, ``y`` на север, ``z`` вверх, начало на уровне земли.
Глаза наблюдателя подняты на ``eye_height_m``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields

import numpy as np

HOUSE = "HOUSE"
TREE = "TREE"
TREE_LINE = "TREE_LINE"
FENCE = "FENCE"
CUSTOM_HORIZON = "CUSTOM_HORIZON"

KIND_RU = {
    HOUSE: "дом",
    TREE: "дерево",
    TREE_LINE: "полоса деревьев",
    FENCE: "забор",
    CUSTOM_HORIZON: "измеренный горизонт",
}


# ---------------------------------------------------------------- геометрия

def enu_from_polar(distance_m: float, azimuth_deg: float) -> tuple[float, float]:
    """Азимут (от севера по часовой) и расстояние → (восток, север)."""
    a = math.radians(azimuth_deg)
    return distance_m * math.sin(a), distance_m * math.cos(a)


def altaz_of_points(points: np.ndarray, eye_height_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Точки сцены (N, 3) → азимут и высота с точки зрения глаз, градусы."""
    x, y, z = points[:, 0], points[:, 1], points[:, 2] - eye_height_m
    horizontal = np.hypot(x, y)
    azimuth = np.degrees(np.arctan2(x, y)) % 360.0
    altitude = np.degrees(np.arctan2(z, np.maximum(horizontal, 1e-6)))
    return azimuth, altitude


def _sample_segments(segments, samples: int = 24) -> np.ndarray:
    """Разбить рёбра на точки: проекция ребра на небо не прямая линия."""
    out = []
    fractions = np.linspace(0.0, 1.0, samples)[:, None]
    for start, finish in segments:
        a = np.asarray(start, dtype=float)
        b = np.asarray(finish, dtype=float)
        out.append(a + (b - a) * fractions)
    return np.vstack(out) if out else np.zeros((0, 3))


def _sample_quads(quads, density: int = 18) -> np.ndarray:
    """Заполнить четырёхугольные грани сеткой точек (билинейно по вершинам)."""
    u = np.linspace(0.0, 1.0, density)[:, None, None]
    v = np.linspace(0.0, 1.0, density)[None, :, None]
    out = []
    for quad in quads:
        a, b, c, d = (np.asarray(p, dtype=float) for p in quad)
        bottom = a + (b - a) * u
        top = d + (c - d) * u
        out.append((bottom[:, None, :] * (1.0 - v) + top[:, None, :] * v)
                   .reshape(-1, 3))
    return np.vstack(out) if out else np.zeros((0, 3))


# ---------------------------------------------------------------- препятствия

@dataclass
class Obstacle:
    """Общая часть: имя, тип и место на участке."""

    kind: str = HOUSE
    name: str = "Препятствие"
    distance_m: float = 15.0
    azimuth_deg: float = 180.0

    # дом / забор / полоса деревьев
    width_m: float = 8.0
    length_m: float = 10.0
    wall_height_m: float = 3.0
    ridge_height_m: float = 5.5
    rotation_deg: float = 0.0

    # дерево
    trunk_height_m: float = 3.0
    crown_radius_m: float = 2.5
    crown_height_m: float = 5.0

    # протяжённые препятствия
    azimuth_start_deg: float = 150.0
    azimuth_end_deg: float = 210.0
    height_m: float = 6.0

    # измеренный горизонт: список [[азимут, высота], ...]
    points: list = field(default_factory=list)

    enabled: bool = True

    def __post_init__(self) -> None:
        if self.kind not in KIND_RU:
            self.kind = HOUSE
        self.azimuth_deg %= 360.0
        self.ridge_height_m = max(self.ridge_height_m, self.wall_height_m)

    # ------------------------------------------------------------ силуэт

    def silhouette(self, eye_height_m: float) -> tuple[np.ndarray, np.ndarray]:
        """Азимуты и высоты точек силуэта препятствия."""
        if not self.enabled:
            return np.zeros(0), np.zeros(0)
        if self.kind == CUSTOM_HORIZON:
            if not self.points:
                return np.zeros(0), np.zeros(0)
            data = np.asarray(self.points, dtype=float)
            return data[:, 0] % 360.0, data[:, 1]
        if self.kind in (TREE_LINE, FENCE):
            return self._span_silhouette(eye_height_m)
        points = self._mesh_points()
        if len(points) == 0:
            return np.zeros(0), np.zeros(0)
        return altaz_of_points(points, eye_height_m)

    def _span_silhouette(self, eye_height_m: float) -> tuple[np.ndarray, np.ndarray]:
        """Забор и полоса деревьев: постоянная высота в секторе азимутов."""
        start, end = self.azimuth_start_deg % 360.0, self.azimuth_end_deg % 360.0
        span = (end - start) % 360.0
        if span == 0.0:
            span = 360.0
        count = max(3, int(span / 0.5) + 1)
        azimuth = (start + np.linspace(0.0, span, count)) % 360.0
        rise = self.height_m - eye_height_m
        altitude = np.degrees(np.arctan2(rise, max(self.distance_m, 0.5)))
        return azimuth, np.full(count, altitude)

    def _mesh_points(self) -> np.ndarray:
        if self.kind == HOUSE:
            return self.house_points()
        if self.kind == TREE:
            return self.tree_points()
        return np.zeros((0, 3))

    def house_points(self, density: int = 18) -> np.ndarray:
        """Точки поверхности дома, а не только его рёбра.

        По одним рёбрам маска горизонта получается дырявой: азимут, который
        смотрит в середину ската, не попадает ни на конёк, ни на карниз, и в
        крыше открывается щель, сквозь которую «просвечивают» планеты. Поэтому
        грани заполняются сеткой точек.
        """
        return _sample_quads(self.house_faces(), density)

    # ------------------------------------------------------------ дом

    def house_edges(self) -> list[tuple[tuple, tuple]]:
        """Рёбра коробки с двускатной крышей в координатах сцены.

        Конёк идёт вдоль локальной оси Y (длина дома), скаты смотрят в ±X.
        """
        half_w, half_l = self.width_m / 2.0, self.length_m / 2.0
        wall, ridge = self.wall_height_m, self.ridge_height_m
        place = self._placer()

        corners = [(-half_w, -half_l), (half_w, -half_l),
                   (half_w, half_l), (-half_w, half_l)]
        edges = []
        for index, (cx, cy) in enumerate(corners):
            nx, ny = corners[(index + 1) % 4]
            edges.append((place(cx, cy, 0.0), place(nx, ny, 0.0)))          # низ
            edges.append((place(cx, cy, wall), place(nx, ny, wall)))        # карниз
            edges.append((place(cx, cy, 0.0), place(cx, cy, wall)))         # угол
        for sign in (-1.0, 1.0):
            apex = place(0.0, sign * half_l, ridge)
            edges.append((place(-half_w, sign * half_l, wall), apex))       # фронтон
            edges.append((place(half_w, sign * half_l, wall), apex))
        edges.append((place(0.0, -half_l, ridge), place(0.0, half_l, ridge)))  # конёк
        return edges

    def house_faces(self) -> list[tuple]:
        """Грани дома как четырёхугольники (у фронтонов третья вершина сдвоена)."""
        half_w, half_l = self.width_m / 2.0, self.length_m / 2.0
        wall, ridge = self.wall_height_m, self.ridge_height_m
        place = self._placer()

        corners = [(-half_w, -half_l), (half_w, -half_l),
                   (half_w, half_l), (-half_w, half_l)]
        faces = []
        for index, (cx, cy) in enumerate(corners):          # стены
            nx, ny = corners[(index + 1) % 4]
            faces.append((place(cx, cy, 0.0), place(nx, ny, 0.0),
                          place(nx, ny, wall), place(cx, cy, wall)))
        for sign in (-1.0, 1.0):                            # скаты крыши
            faces.append((place(sign * half_w, -half_l, wall),
                          place(sign * half_w, half_l, wall),
                          place(0.0, half_l, ridge),
                          place(0.0, -half_l, ridge)))
        for sign in (-1.0, 1.0):                            # фронтоны
            apex = place(0.0, sign * half_l, ridge)
            faces.append((place(-half_w, sign * half_l, wall),
                          place(half_w, sign * half_l, wall), apex, apex))
        return faces

    def _placer(self):
        angle = math.radians(self.rotation_deg)
        east, north = enu_from_polar(self.distance_m, self.azimuth_deg)

        def place(px: float, py: float, pz: float) -> tuple[float, float, float]:
            rx = px * math.cos(angle) + py * math.sin(angle)
            ry = -px * math.sin(angle) + py * math.cos(angle)
            return east + rx, north + ry, pz

        return place

    # ------------------------------------------------------------ дерево

    def tree_points(self, rings: int = 48, per_ring: int = 96) -> np.ndarray:
        """Точки поверхности кроны плюс ствол.

        Сетка намеренно частая: близкое дерево занимает на небе десятки градусов,
        и редкая сетка оставляет в кроне просветы, которых у настоящей берёзы нет.
        """
        east, north = enu_from_polar(self.distance_m, self.azimuth_deg)
        centre_z = self.trunk_height_m + self.crown_height_m / 2.0
        radius_z = max(self.crown_height_m / 2.0, 0.1)
        radius_xy = max(self.crown_radius_m, 0.1)

        theta = np.linspace(0.0, math.pi, rings)[:, None]
        phi = np.linspace(0.0, 2.0 * math.pi, per_ring)[None, :]
        x = east + radius_xy * (np.sin(theta) * np.cos(phi))
        y = north + radius_xy * (np.sin(theta) * np.sin(phi))
        z = centre_z + radius_z * np.cos(theta) * np.ones_like(phi)
        crown = np.stack([x.ravel(), y.ravel(), z.ravel()], axis=1)

        trunk_z = np.linspace(0.0, self.trunk_height_m, 6)
        trunk = np.stack([np.full_like(trunk_z, east), np.full_like(trunk_z, north),
                          trunk_z], axis=1)
        return np.vstack([crown, trunk])

    # ------------------------------------------------------------ сцена и файл

    def scene_geometry(self) -> dict:
        """Параметры для Three.js. Единицы — метры, азимут от севера."""
        east, north = enu_from_polar(self.distance_m, self.azimuth_deg)
        common = {"kind": self.kind, "name": self.name,
                  "east": east, "north": north,
                  "distance_m": self.distance_m, "azimuth_deg": self.azimuth_deg}
        if self.kind == HOUSE:
            common.update(width_m=self.width_m, length_m=self.length_m,
                          wall_height_m=self.wall_height_m,
                          ridge_height_m=self.ridge_height_m,
                          rotation_deg=self.rotation_deg)
        elif self.kind == TREE:
            common.update(trunk_height_m=self.trunk_height_m,
                          crown_radius_m=self.crown_radius_m,
                          crown_height_m=self.crown_height_m)
        elif self.kind in (TREE_LINE, FENCE):
            common.update(azimuth_start_deg=self.azimuth_start_deg,
                          azimuth_end_deg=self.azimuth_end_deg,
                          height_m=self.height_m,
                          distance_m=self.distance_m)
        elif self.kind == CUSTOM_HORIZON:
            common.update(points=[[float(a), float(h)] for a, h in self.points])
        return common

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict) -> "Obstacle":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})


# ---------------------------------------------------------------- панорама

@dataclass
class PanoramaPhoto:
    """Фотография местности, привязанная к азимуту центра кадра.

    Первая версия не сшивает панораму автоматически: она хранит привязку и
    показывает снимок как ориентир. Формат подобран так, чтобы позже сюда легли
    и цилиндрическая склейка, и измеренный по фото горизонт, не ломая файлы
    профилей.
    """

    path: str = ""
    center_azimuth_deg: float = 0.0
    horizontal_fov_deg: float = 60.0
    horizon_pixel_fraction: float = 0.5      # где на кадре линия горизонта, 0..1
    label: str = ""

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict) -> "PanoramaPhoto":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})


@dataclass
class Landscape:
    """Всё, что закрывает небо с этой площадки."""

    name: str = "Участок"
    obstacles: list = field(default_factory=list)
    natural_horizon_deg: float = 1.5
    panorama_mode: str = "NONE"              # NONE | PHOTOS | EQUIRECTANGULAR
    photos: list = field(default_factory=list)
    equirectangular_path: str = ""
    equirectangular_north_offset_deg: float = 0.0
    is_demo: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "obstacles": [o.to_dict() for o in self.obstacles],
            "natural_horizon_deg": self.natural_horizon_deg,
            "panorama_mode": self.panorama_mode,
            "photos": [p.to_dict() for p in self.photos],
            "equirectangular_path": self.equirectangular_path,
            "equirectangular_north_offset_deg": self.equirectangular_north_offset_deg,
            "is_demo": self.is_demo,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Landscape":
        return cls(
            name=payload.get("name", "Участок"),
            obstacles=[Obstacle.from_dict(o) for o in payload.get("obstacles", [])],
            natural_horizon_deg=float(payload.get("natural_horizon_deg", 1.5)),
            panorama_mode=payload.get("panorama_mode", "NONE"),
            photos=[PanoramaPhoto.from_dict(p) for p in payload.get("photos", [])],
            equirectangular_path=payload.get("equirectangular_path", ""),
            equirectangular_north_offset_deg=float(
                payload.get("equirectangular_north_offset_deg", 0.0)),
            is_demo=bool(payload.get("is_demo", False)),
        )

    def scene_geometry(self) -> list[dict]:
        return [o.scene_geometry() for o in self.obstacles if o.enabled]


def demo_landscape() -> Landscape:
    """Условный дачный участок: дом на юго-западе, деревья, забор.

    Числа выдуманы и помечены DEMO — это не обмер настоящего участка.
    """
    return Landscape(
        name="DEMO — дачный участок",
        natural_horizon_deg=1.5,
        is_demo=True,
        obstacles=[
            Obstacle(kind=HOUSE, name="Дачный дом", distance_m=14.0,
                     azimuth_deg=205.0, width_m=8.0, length_m=10.0,
                     wall_height_m=3.0, ridge_height_m=5.5, rotation_deg=25.0),
            Obstacle(kind=TREE, name="Берёза у калитки", distance_m=11.0,
                     azimuth_deg=118.0, trunk_height_m=3.5,
                     crown_radius_m=2.6, crown_height_m=6.0),
            Obstacle(kind=TREE, name="Ель за баней", distance_m=17.0,
                     azimuth_deg=292.0, trunk_height_m=2.0,
                     crown_radius_m=2.2, crown_height_m=8.0),
            Obstacle(kind=TREE_LINE, name="Лес на северо-востоке",
                     distance_m=60.0, azimuth_start_deg=20.0,
                     azimuth_end_deg=75.0, height_m=14.0),
            Obstacle(kind=FENCE, name="Забор", distance_m=9.0,
                     azimuth_start_deg=240.0, azimuth_end_deg=340.0,
                     height_m=2.0),
        ])
