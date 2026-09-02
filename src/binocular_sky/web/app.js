/* Точка входа 3D-вида и мост в Python.
 *
 * Разделение обязанностей: Python считает, JS показывает. Наружу отдаётся
 * объект `window.sky` — набор команд, которые вызывает Qt через QWebChannel:
 * загрузить снимок, повернуться к объекту, включить ночной режим, показать
 * поле бинокля. Обратно уходят события: выбран объект, изменилось направление
 * взгляда.
 */
import * as THREE from 'three';
import { Constellations, StarField, buildGrid, direction } from './sky.js';
import { Labels } from './labels.js';
import { Terrain } from './terrain.js';
import { SkyObjects } from './objects.js';
import { drawBinocularView } from './binocular.js';

const COMPASS = ['С', 'ССВ', 'СВ', 'ВСВ', 'В', 'ВЮВ', 'ЮВ', 'ЮЮВ',
                 'Ю', 'ЮЮЗ', 'ЮЗ', 'ЗЮЗ', 'З', 'ЗСЗ', 'СЗ', 'ССЗ'];

const BASE_FOV = 60;
const MIN_FOV = 4;
const MAX_FOV = 100;

class Viewer {
  constructor() {
    this.stage = document.getElementById('stage');
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.stage.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x05070d);
    this.camera = new THREE.PerspectiveCamera(BASE_FOV, 1, 0.1, 20000);

    this.labels = new Labels(this.scene);
    this.stars = new StarField(this.scene);
    this.constellations = new Constellations(this.scene, this.labels);
    this.terrain = new Terrain(this.scene);
    this.objects = new SkyObjects(this.scene, this.labels);
    buildGrid(this.scene, this.labels);

    this.azimuth = 180;
    this.altitude = 30;
    this.targetAzimuth = null;
    this.targetAltitude = null;
    this.night = false;
    this.showLabels = true;
    this.showConstellations = true;
    this.snapshot = null;
    this.binocularMode = false;

    this.bindInput();
    window.addEventListener('resize', () => this.resize());
    this.resize();
    this.renderer.setAnimationLoop(() => this.frame());
  }

  // ------------------------------------------------------------ управление

  bindInput() {
    const element = this.renderer.domElement;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;

    element.addEventListener('pointerdown', (event) => {
      dragging = true;
      lastX = event.clientX;
      lastY = event.clientY;
      element.setPointerCapture(event.pointerId);
    });
    element.addEventListener('pointerup', (event) => {
      dragging = false;
      element.releasePointerCapture(event.pointerId);
    });
    element.addEventListener('pointermove', (event) => {
      if (!dragging) return;
      // чувствительность привязана к полю зрения: при увеличении поворот мельче
      const scale = this.camera.fov / this.stage.clientHeight;
      this.targetAzimuth = null;
      this.azimuth = (this.azimuth - (event.clientX - lastX) * scale + 360) % 360;
      this.altitude = THREE.MathUtils.clamp(
        this.altitude + (event.clientY - lastY) * scale, -25, 89);
      lastX = event.clientX;
      lastY = event.clientY;
    });
    element.addEventListener('wheel', (event) => {
      event.preventDefault();
      const factor = Math.exp(event.deltaY * 0.0016);
      this.camera.fov = THREE.MathUtils.clamp(this.camera.fov * factor,
                                              MIN_FOV, MAX_FOV);
      this.camera.updateProjectionMatrix();
    }, { passive: false });

    element.addEventListener('dblclick', (event) => {
      const rect = element.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      const entry = this.objects.pick(this.camera, x, y, 34,
                                      { width: rect.width, height: rect.height });
      if (entry) {
        this.objects.highlight(entry);
        this.emit('objectSelected', entry.id);
      }
    });
  }

  emit(name, payload) {
    if (window.bridge && window.bridge[name]) window.bridge[name](payload);
  }

  // ------------------------------------------------------------ кадр

  frame() {
    if (this.targetAzimuth !== null) {
      // плавный доворот к выбранному объекту по кратчайшей дуге
      const delta = ((this.targetAzimuth - this.azimuth + 540) % 360) - 180;
      this.azimuth = (this.azimuth + delta * 0.12 + 360) % 360;
      this.altitude += (this.targetAltitude - this.altitude) * 0.12;
      if (Math.abs(delta) < 0.15
          && Math.abs(this.targetAltitude - this.altitude) < 0.15) {
        this.azimuth = this.targetAzimuth;
        this.altitude = this.targetAltitude;
        this.targetAzimuth = null;
      }
    }

    const look = direction(this.azimuth, this.altitude).multiplyScalar(100);
    this.camera.position.set(0, this.terrain.eyeHeight || 1.7, 0);
    this.camera.lookAt(look.x, (this.terrain.eyeHeight || 1.7) + look.y, look.z);

    this.stars.setZoom(this.camera.fov, BASE_FOV);
    this.labels.resize(this.camera.fov, this.stage.clientHeight);
    this.updateReadout();
    this.renderer.render(this.scene, this.camera);
  }

  resize() {
    const width = this.stage.clientWidth;
    const height = this.stage.clientHeight;
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    if (this.binocularMode) this.renderBinocular();
  }

  updateReadout() {
    document.getElementById('az').textContent = `${this.azimuth.toFixed(0)}°`;
    document.getElementById('alt').textContent = `${this.altitude.toFixed(0)}°`;
    const sector = COMPASS[Math.round(this.azimuth / 22.5) % 16];
    document.getElementById('dir').textContent = sector;
    this.drawCompass();
  }

  drawCompass() {
    const canvas = document.getElementById('compass-canvas');
    const ctx = canvas.getContext('2d');
    const size = canvas.width;
    const centre = size / 2;
    ctx.clearRect(0, 0, size, size);

    const ink = this.night ? '#b03a2e' : '#9fb6d8';
    const dim = this.night ? '#5c1f18' : '#5a6c8a';
    ctx.strokeStyle = dim;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(centre, centre, centre - 8, 0, Math.PI * 2);
    ctx.stroke();

    ctx.save();
    ctx.translate(centre, centre);
    ctx.rotate(-this.azimuth * Math.PI / 180);
    ctx.font = '600 13px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const [angle, text] of [[0, 'С'], [90, 'В'], [180, 'Ю'], [270, 'З']]) {
      const a = angle * Math.PI / 180;
      const r = centre - 20;
      ctx.fillStyle = text === 'С' ? (this.night ? '#d0483a' : '#ff8f6b') : ink;
      ctx.fillText(text, r * Math.sin(a), -r * Math.cos(a));
    }
    ctx.restore();

    // стрелка направления взгляда — всегда вверх
    ctx.fillStyle = this.night ? '#d0483a' : '#7fffd4';
    ctx.beginPath();
    ctx.moveTo(centre, 14);
    ctx.lineTo(centre - 6, 26);
    ctx.lineTo(centre + 6, 26);
    ctx.closePath();
    ctx.fill();
  }

  // ------------------------------------------------------------ команды

  loadSnapshot(snapshot) {
    this.snapshot = snapshot;
    this.stars.update(snapshot.stars);
    this.constellations.update(snapshot.constellations,
                               this.showConstellations, this.showLabels);
    if (snapshot.terrain) this.terrain.update(snapshot.terrain, this.night);
    this.objects.update(snapshot.solar, snapshot.deep_sky, this.showLabels);
    this.labels.setVisible('constellation', this.showLabels);
    if (this.binocularMode) this.renderBinocular();
  }

  lookAt(azimuth, altitude, immediate) {
    if (immediate) {
      this.azimuth = ((azimuth % 360) + 360) % 360;
      this.altitude = THREE.MathUtils.clamp(altitude, -25, 89);
      this.targetAzimuth = null;
    } else {
      this.targetAzimuth = ((azimuth % 360) + 360) % 360;
      this.targetAltitude = THREE.MathUtils.clamp(altitude, -25, 89);
    }
  }

  selectById(id) {
    const entry = this.objects.entries.find((item) => item.id === id);
    if (!entry) return false;
    this.objects.highlight(entry);
    this.lookAt(entry.az, entry.alt, false);
    return true;
  }

  setNightMode(enabled) {
    this.night = enabled;
    document.body.classList.toggle('night', enabled);
    if (this.snapshot && this.snapshot.terrain) {
      this.terrain.update(this.snapshot.terrain, enabled);
    }
  }

  setOptions(options) {
    if (options.showLabels !== undefined) this.showLabels = options.showLabels;
    if (options.showConstellations !== undefined) {
      this.showConstellations = options.showConstellations;
    }
    if (this.snapshot) this.loadSnapshot(this.snapshot);
  }

  setBanner(text) {
    const banner = document.getElementById('banner');
    banner.textContent = text || '';
    banner.hidden = !text;
  }

  showTrack(track) { this.objects.showTrack(track); }

  clearTrack() { this.objects.clearTrack(); }

  // ------------------------------------------------------------ бинокль

  enterBinocular(data) {
    this.binocularData = data;
    this.binocularMode = true;
    document.getElementById('binocular-view').hidden = false;
    document.getElementById('hint').hidden = true;
    this.renderBinocular();
  }

  renderBinocular() {
    if (!this.binocularData) return;
    const canvas = document.getElementById('binocular-canvas');
    const data = this.binocularData;
    const box = document.getElementById('binocular-view');
    drawBinocularView(canvas, data,
                      { size: Math.min(box.clientWidth, box.clientHeight) - 70 });
    const caption = document.getElementById('binocular-caption');
    caption.textContent =
      `${data.target.name} · поле ${data.fov_deg}° · предел ≈ ${data.limiting_mag}m`
      + ` · азимут ${data.centre.az}°, высота ${data.centre.alt}°`;
  }

  exitBinocular() {
    this.binocularMode = false;
    document.getElementById('binocular-view').hidden = true;
    document.getElementById('hint').hidden = false;
  }
}

const viewer = new Viewer();

/* Публичный интерфейс для Qt. Аргументы приходят строками JSON: так проще
   всего переживать границу между Python и JS без промежуточных схем. */
window.sky = {
  loadSnapshot: (json) => viewer.loadSnapshot(JSON.parse(json)),
  lookAt: (az, alt, immediate) => viewer.lookAt(az, alt, !!immediate),
  selectById: (id) => viewer.selectById(id),
  setNightMode: (on) => viewer.setNightMode(!!on),
  setOptions: (json) => viewer.setOptions(JSON.parse(json)),
  setBanner: (text) => viewer.setBanner(text),
  showTrack: (json) => viewer.showTrack(JSON.parse(json)),
  clearTrack: () => viewer.clearTrack(),
  enterBinocular: (json) => viewer.enterBinocular(JSON.parse(json)),
  exitBinocular: () => viewer.exitBinocular(),
  viewDirection: () => JSON.stringify({ az: viewer.azimuth, alt: viewer.altitude }),
  ready: () => true,
  /* Снимок самой сцены. Содержимое QWebEngineView не попадает в QWidget.grab():
     оно рисуется отдельным композитором. Поэтому картинку отдаёт сам холст. */
  captureImage: () => {
    if (viewer.binocularMode) {
      return document.getElementById('binocular-canvas').toDataURL('image/png');
    }
    // без preserveDrawingBuffer буфер очищается после вывода на экран,
    // поэтому рисуем кадр заново прямо перед чтением
    viewer.renderer.render(viewer.scene, viewer.camera);
    return viewer.renderer.domElement.toDataURL('image/png');
  },
};

/* Подключение к Python. Без QWebChannel (например, при открытии файла в
   обычном браузере) сцена работает, просто не сообщает о выборе объекта. */
function connectBridge() {
  if (!window.QWebChannel || !window.qt || !window.qt.webChannelTransport) {
    return;
  }
  new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
    window.bridge = channel.objects.bridge;
    if (window.bridge && window.bridge.viewerReady) window.bridge.viewerReady();
  });
}

if (document.readyState === 'complete') connectBridge();
else window.addEventListener('load', connectBridge);
