/* Подписи на небе.
 *
 * Спрайты с текстом, сгруппированные по назначению: стороны света, созвездия,
 * объекты. Группами их удобно гасить и перестраивать при смене времени, не
 * трогая остальные.
 */
import * as THREE from 'three';
import { skyPoint } from './sky.js';

function textTexture(text, color, fontSize) {
  const pad = 8;
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const font = `600 ${fontSize}px "Segoe UI", system-ui, sans-serif`;
  ctx.font = font;
  const width = Math.ceil(ctx.measureText(text).width) + pad * 2;
  const height = fontSize + pad * 2;
  canvas.width = width;
  canvas.height = height;

  const c = canvas.getContext('2d');
  c.font = font;
  c.textBaseline = 'middle';
  c.textAlign = 'center';
  c.shadowColor = 'rgba(0,0,0,0.9)';
  c.shadowBlur = 5;
  c.fillStyle = color;
  c.fillText(text, width / 2, height / 2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return { texture, width, height };
}

export class Labels {
  constructor(scene) {
    this.scene = scene;
    this.groups = new Map();
  }

  group(name) {
    if (!this.groups.has(name)) {
      const group = new THREE.Group();
      this.scene.add(group);
      this.groups.set(name, group);
    }
    return this.groups.get(name);
  }

  add(groupName, text, azDeg, altDeg, options = {}) {
    const color = options.color || '#dfe7f5';
    const fontSize = options.size || 14;
    const { texture, width, height } = textTexture(text, color, fontSize);
    const material = new THREE.SpriteMaterial({
      map: texture, transparent: true, depthTest: false, depthWrite: false,
      opacity: options.opacity === undefined ? 0.92 : options.opacity,
    });
    const sprite = new THREE.Sprite(material);
    const position = skyPoint(azDeg, altDeg, options.radius || 3600);
    sprite.position.copy(position);
    sprite.userData.baseScale = [width, height];
    sprite.userData.offsetY = options.offsetY || 0;
    sprite.renderOrder = 10;
    this.group(groupName).add(sprite);
    return sprite;
  }

  removeGroup(name) {
    const group = this.groups.get(name);
    if (!group) return;
    for (const child of group.children) {
      if (child.material.map) child.material.map.dispose();
      child.material.dispose();
    }
    group.clear();
  }

  setVisible(name, visible) {
    this.group(name).visible = visible;
  }

  /** Подписи не должны расти вместе с приближением: держим их постоянными
   *  в экранных пикселях. */
  resize(fovDeg, viewportHeight) {
    const perPixel = 2 * Math.tan(THREE.MathUtils.degToRad(fovDeg) / 2) / viewportHeight;
    for (const group of this.groups.values()) {
      for (const sprite of group.children) {
        const [w, h] = sprite.userData.baseScale;
        const distance = sprite.position.length();
        const unit = perPixel * distance;
        sprite.scale.set(w * unit, h * unit, 1);
      }
    }
  }
}
