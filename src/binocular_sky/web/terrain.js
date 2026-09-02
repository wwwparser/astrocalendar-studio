/* Земля и участок: дом, деревья, забор, профиль местного горизонта.
 *
 * Геометрия строится по тем же числам, по которым Python считает маску
 * горизонта. Дом на экране и дом в расчёте — один и тот же дом; если бы
 * картинку рисовали отдельно, объект «за крышей» мог бы висеть на экране
 * рядом с ней.
 *
 * Координаты сцены: восток = +X, север = −Z, верх = +Y, метры.
 */
import * as THREE from 'three';
import { direction } from './sky.js';

/** Азимут и расстояние → точка на земле. */
function ground(distance, azimuthDeg) {
  const az = THREE.MathUtils.degToRad(azimuthDeg);
  return new THREE.Vector3(distance * Math.sin(az), 0, -distance * Math.cos(az));
}

const WALL = 0xb9ac96;
const ROOF = 0x8a4b3c;
const TRUNK = 0x5b4635;
const CROWN = 0x2f4a2b;
const FENCE = 0x6b5a45;

function material(color, night) {
  return new THREE.MeshLambertMaterial({
    color, flatShading: true,
    emissive: new THREE.Color(color).multiplyScalar(night ? 0.05 : 0.12),
  });
}

/** Коробка с двускатной крышей.
 *
 *  Конёк идёт вдоль локальной оси длины, скаты смотрят поперёк — та же
 *  геометрия, что в `models/scene.py:house_faces`.
 */
function buildHouse(spec, night) {
  const group = new THREE.Group();
  const halfW = spec.width_m / 2;
  const halfL = spec.length_m / 2;
  const wall = spec.wall_height_m;
  const ridge = spec.ridge_height_m;

  const body = new THREE.Mesh(
    new THREE.BoxGeometry(spec.width_m, wall, spec.length_m),
    material(WALL, night));
  body.position.y = wall / 2;
  group.add(body);

  // крыша: две наклонные плоскости и два фронтона, собранные вручную —
  // готового примитива «двускатная крыша» в three.js нет
  const positions = [];
  const push = (...points) => {
    for (const p of points) positions.push(p[0], p[1], p[2]);
  };
  const eaveA = [-halfW, wall, -halfL];
  const eaveB = [-halfW, wall, halfL];
  const eaveC = [halfW, wall, halfL];
  const eaveD = [halfW, wall, -halfL];
  const ridgeA = [0, ridge, -halfL];
  const ridgeB = [0, ridge, halfL];

  push(eaveA, eaveB, ridgeB, eaveA, ridgeB, ridgeA);   // западный скат
  push(eaveC, eaveD, ridgeA, eaveC, ridgeA, ridgeB);   // восточный скат
  push(eaveA, ridgeA, eaveD);                          // фронтон
  push(eaveB, eaveC, ridgeB);                          // фронтон

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position',
    new THREE.BufferAttribute(new Float32Array(positions), 3));
  geometry.computeVertexNormals();
  const roof = new THREE.Mesh(geometry,
    new THREE.MeshLambertMaterial({ color: ROOF, side: THREE.DoubleSide,
                                    flatShading: true }));
  group.add(roof);

  // окно и дверь — только ориентиры, на маску горизонта они не влияют
  const glass = new THREE.MeshBasicMaterial({ color: night ? 0x2a0d08 : 0x24303f });
  for (const dz of [-halfL * 0.4, halfL * 0.4]) {
    const window = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 1.0), glass);
    window.position.set(-halfW - 0.02, wall * 0.62, dz);
    window.rotation.y = -Math.PI / 2;
    group.add(window);
  }
  const door = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 2.0),
    new THREE.MeshBasicMaterial({ color: 0x4a3a2a }));
  door.position.set(0, 1.0, halfL + 0.02);
  group.add(door);

  const position = ground(spec.distance_m, spec.azimuth_deg);
  group.position.copy(position);
  group.rotation.y = THREE.MathUtils.degToRad(spec.rotation_deg || 0);
  return group;
}

function buildTree(spec, night) {
  const group = new THREE.Group();
  const trunk = new THREE.Mesh(
    new THREE.CylinderGeometry(0.16, 0.24, spec.trunk_height_m, 7),
    material(TRUNK, night));
  trunk.position.y = spec.trunk_height_m / 2;
  group.add(trunk);

  const crown = new THREE.Mesh(
    new THREE.SphereGeometry(1, 14, 11), material(CROWN, night));
  crown.scale.set(spec.crown_radius_m, spec.crown_height_m / 2, spec.crown_radius_m);
  crown.position.y = spec.trunk_height_m + spec.crown_height_m / 2;
  group.add(crown);

  group.position.copy(ground(spec.distance_m, spec.azimuth_deg));
  return group;
}

/** Забор и полоса деревьев: стенка заданной высоты в секторе азимутов. */
function buildSpan(spec, night) {
  const group = new THREE.Group();
  let span = ((spec.azimuth_end_deg - spec.azimuth_start_deg) % 360 + 360) % 360;
  if (span === 0) span = 360;
  const steps = Math.max(2, Math.round(span / 2));
  const color = spec.kind === 'TREE_LINE' ? CROWN : FENCE;

  const positions = [];
  for (let i = 0; i < steps; i += 1) {
    const a0 = spec.azimuth_start_deg + (span * i) / steps;
    const a1 = spec.azimuth_start_deg + (span * (i + 1)) / steps;
    const p0 = ground(spec.distance_m, a0);
    const p1 = ground(spec.distance_m, a1);
    const h = spec.height_m;
    positions.push(p0.x, 0, p0.z, p1.x, 0, p1.z, p1.x, h, p1.z);
    positions.push(p0.x, 0, p0.z, p1.x, h, p1.z, p0.x, h, p0.z);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position',
    new THREE.BufferAttribute(new Float32Array(positions), 3));
  geometry.computeVertexNormals();
  group.add(new THREE.Mesh(geometry,
    new THREE.MeshLambertMaterial({ color, side: THREE.DoubleSide,
                                    flatShading: true })));
  return group;
}

export class Terrain {
  constructor(scene) {
    this.scene = scene;
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.horizonMesh = null;
    this.lights = null;
  }

  ensureLights(night) {
    if (this.lights) this.scene.remove(this.lights);
    this.lights = new THREE.Group();
    const ambient = new THREE.AmbientLight(0xffffff, night ? 0.18 : 0.42);
    const moonlight = new THREE.DirectionalLight(0xbcd0ff, night ? 0.15 : 0.5);
    moonlight.position.set(-60, 90, 40);
    this.lights.add(ambient, moonlight);
    this.scene.add(this.lights);
  }

  update(terrain, night) {
    this.group.clear();
    this.ensureLights(night);
    if (!terrain) return;

    const groundDisc = new THREE.Mesh(
      new THREE.CircleGeometry(900, 72),
      new THREE.MeshLambertMaterial({ color: night ? 0x0d0704 : 0x14201a }));
    groundDisc.rotation.x = -Math.PI / 2;
    groundDisc.position.y = -0.02;
    this.group.add(groundDisc);

    for (const spec of terrain.obstacles || []) {
      let mesh = null;
      if (spec.kind === 'HOUSE') mesh = buildHouse(spec, night);
      else if (spec.kind === 'TREE') mesh = buildTree(spec, night);
      else if (spec.kind === 'TREE_LINE' || spec.kind === 'FENCE') {
        mesh = buildSpan(spec, night);
      }
      if (mesh) {
        mesh.userData.obstacle = spec;
        this.group.add(mesh);
      }
    }

    this.buildHorizonLine(terrain.horizon, night);
    // наблюдатель стоит на земле, глаза — на высоте eye_height_m
    this.eyeHeight = terrain.eye_height_m || 1.7;
  }

  /** Линия местного горизонта на небе: где кончается видимое.
   *
   *  Она показывает не абстрактную маску, а именно то, что закрывает участок —
   *  включая далёкий лес, который в метровой геометрии не построишь.
   */
  buildHorizonLine(curve, night) {
    if (!curve || !curve.length) return;
    const points = [];
    for (const [az, alt] of curve) points.push(direction(az, alt).multiplyScalar(3900));
    points.push(points[0].clone());
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({
      color: night ? 0x7a2a22 : 0x4d7ea8, transparent: true, opacity: 0.75,
    }));
    line.frustumCulled = false;
    this.group.add(line);
  }
}
