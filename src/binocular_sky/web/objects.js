/* Объекты: Солнце, Луна, планеты, объекты глубокого космоса и траектории.
 *
 * Все они приходят из Python уже с азимутом и высотой. Размер значка отражает
 * тип и блеск, а не «как красивее»: диск Луны рисуется её настоящим угловым
 * размером, иначе человек будет искать на небе не то, что увидит.
 */
import * as THREE from 'three';
import { SKY_RADIUS, direction, skyPoint } from './sky.js';

const KIND_COLOR = {
  SUN: '#ffd27f', MOON: '#e9e6da', PLANET: '#ffd9a0', JUPITER_MOON: '#cfd6e6',
  COMET: '#9ff2d8', OPEN_CLUSTER: '#a8d8ff', GLOBULAR_CLUSTER: '#ffd6a8',
  NEBULA: '#b9a8ff', PLANETARY_NEBULA: '#8ce0d0', GALAXY: '#ffb2c8',
  DOUBLE_STAR: '#d8e4ff', ASTERISM: '#b8e8c0', STAR: '#ffffff',
};

function color(kind) {
  return KIND_COLOR[kind] || '#c8d4e8';
}

function discTexture(hex, ring) {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (ring) {
    ctx.strokeStyle = hex;
    ctx.lineWidth = 7;
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2 - 10, 0, Math.PI * 2);
    ctx.stroke();
  } else {
    const gradient = ctx.createRadialGradient(size / 2, size / 2, 0,
                                              size / 2, size / 2, size / 2);
    gradient.addColorStop(0, hex);
    gradient.addColorStop(0.55, hex);
    gradient.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

const textureCache = new Map();
function cachedTexture(hex, ring) {
  const key = `${hex}|${ring}`;
  if (!textureCache.has(key)) textureCache.set(key, discTexture(hex, ring));
  return textureCache.get(key);
}

/** Угловой размер значка в градусах. */
function markerAngle(entry) {
  if (entry.kind === 'MOON' || entry.kind === 'SUN') {
    return Math.max(0.5, (entry.size || 31) / 60);   // настоящий диск
  }
  if (entry.kind === 'PLANET') return 0.9;
  return Math.max(0.8, Math.min(4.0, (entry.size || 12) / 60));
}

export class SkyObjects {
  constructor(scene, labels) {
    this.scene = scene;
    this.labels = labels;
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.entries = [];
    this.selected = null;
    this.selectionRing = null;
    this.trackGroup = new THREE.Group();
    this.scene.add(this.trackGroup);
  }

  update(solar, deepSky, showLabels, dsoLabelLimit = 6.5) {
    this.group.clear();
    this.labels.removeGroup('objects');
    this.entries = [];

    for (const entry of solar || []) {
      if (entry.alt < -3) continue;
      const filled = entry.kind === 'MOON' || entry.kind === 'SUN'
        || entry.kind === 'PLANET' || entry.kind === 'JUPITER_MOON';
      this.addMarker(entry, !filled);
      if (showLabels && entry.kind !== 'JUPITER_MOON') {
        this.labels.add('objects', entry.name, entry.az,
                        entry.alt + markerAngle(entry) / 2 + 1.2,
                        { color: color(entry.kind), size: 15 });
      }
    }

    for (const entry of deepSky || []) {
      if (entry.alt < -1) continue;
      this.addMarker(entry, true);
      if (showLabels && entry.mag <= dsoLabelLimit && entry.alt > 4) {
        this.labels.add('objects', entry.name, entry.az, entry.alt + 1.6,
                        { color: color(entry.kind), size: 12, opacity: 0.8 });
      }
    }
    if (this.selected) this.highlight(this.selected);
  }

  addMarker(entry, ring) {
    const angle = markerAngle(entry);
    const radius = SKY_RADIUS;
    const worldSize = 2 * radius * Math.tan(THREE.MathUtils.degToRad(angle) / 2);
    const material = new THREE.SpriteMaterial({
      map: cachedTexture(color(entry.kind), ring),
      transparent: true, depthTest: false, depthWrite: false,
      opacity: entry.blocked ? 0.3 : 0.95,
    });
    const sprite = new THREE.Sprite(material);
    sprite.position.copy(skyPoint(entry.az, entry.alt, radius));
    sprite.scale.set(worldSize, worldSize, 1);
    sprite.renderOrder = 5;
    sprite.userData.entry = entry;
    this.group.add(sprite);
    this.entries.push(entry);
  }

  /** Кольцо вокруг выбранного объекта. */
  highlight(entry) {
    this.selected = entry;
    if (this.selectionRing) {
      this.scene.remove(this.selectionRing);
      this.selectionRing = null;
    }
    if (!entry) return;
    const angle = Math.max(2.0, markerAngle(entry) * 1.8);
    const radius = SKY_RADIUS * 0.98;
    const worldSize = 2 * radius * Math.tan(THREE.MathUtils.degToRad(angle) / 2);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: cachedTexture('#7fffd4', true),
      transparent: true, depthTest: false, depthWrite: false, opacity: 0.9,
    }));
    sprite.position.copy(skyPoint(entry.az, entry.alt, radius));
    sprite.scale.set(worldSize, worldSize, 1);
    sprite.renderOrder = 20;
    this.selectionRing = sprite;
    this.scene.add(sprite);
  }

  /** Траектория за ночь. Закрытые участком отрезки — пунктиром и тусклее. */
  showTrack(track) {
    this.trackGroup.clear();
    this.labels.removeGroup('track');
    if (!track || !track.points || track.points.length < 2) return;

    const runs = [];
    let current = null;
    for (const point of track.points) {
      if (point.alt < -2) { current = null; continue; }
      if (!current || current.blocked !== point.blocked) {
        current = { blocked: point.blocked, points: [] };
        runs.push(current);
        const previous = runs[runs.length - 2];
        if (previous && previous.points.length) {
          current.points.push(previous.points[previous.points.length - 1]);
        }
      }
      current.points.push(direction(point.az, point.alt).multiplyScalar(3800));
    }

    for (const run of runs) {
      if (run.points.length < 2) continue;
      const geometry = new THREE.BufferGeometry().setFromPoints(run.points);
      let line;
      if (run.blocked) {
        const material = new THREE.LineDashedMaterial({
          color: 0x7a8ba0, dashSize: 40, gapSize: 40,
          transparent: true, opacity: 0.45,
        });
        line = new THREE.Line(geometry, material);
        line.computeLineDistances();
      } else {
        line = new THREE.Line(geometry, new THREE.LineBasicMaterial({
          color: 0x7fffd4, transparent: true, opacity: 0.85,
        }));
      }
      line.frustumCulled = false;
      this.trackGroup.add(line);
    }

    for (const point of track.points) {
      if (point.hour && point.alt > 0) {
        this.labels.add('track', point.label, point.az, point.alt + 1.0,
                        { color: point.blocked ? '#6d7c90' : '#7fffd4',
                          size: 11, opacity: 0.85, radius: 3700 });
      }
    }
  }

  clearTrack() {
    this.trackGroup.clear();
    this.labels.removeGroup('track');
  }

  /** Ближайший к экранной точке объект — для выбора двойным щелчком. */
  pick(camera, ndcX, ndcY, maxPixels, viewport) {
    const projected = new THREE.Vector3();
    let best = null;
    let bestDistance = Infinity;
    for (const sprite of this.group.children) {
      projected.copy(sprite.position).project(camera);
      if (projected.z < -1 || projected.z > 1) continue;
      const dx = (projected.x - ndcX) * viewport.width / 2;
      const dy = (projected.y - ndcY) * viewport.height / 2;
      const distance = Math.hypot(dx, dy);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = sprite.userData.entry;
      }
    }
    return bestDistance <= maxPixels ? best : null;
  }
}
