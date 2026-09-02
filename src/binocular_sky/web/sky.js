/* Небо: звёзды, фигуры созвездий и их подписи.
 *
 * Ни одной астрономической формулы здесь нет. Python присылает готовые азимут
 * и высоту, JS переводит их в направление и рисует. Так картинка не может
 * разойтись с ответом «виден / закрыт», который считается в Python.
 */
import * as THREE from 'three';

/** Радиус небесной сферы. Земные объекты меряются в метрах и стоят внутри. */
export const SKY_RADIUS = 4000;

/** Азимут (от севера по часовой) и высота → направление в сцене.
 *  Восток = +X, север = −Z, зенит = +Y. */
export function direction(azDeg, altDeg) {
  const az = THREE.MathUtils.degToRad(azDeg);
  const alt = THREE.MathUtils.degToRad(altDeg);
  const c = Math.cos(alt);
  return new THREE.Vector3(c * Math.sin(az), Math.sin(alt), -c * Math.cos(az));
}

export function skyPoint(azDeg, altDeg, radius = SKY_RADIUS) {
  return direction(azDeg, altDeg).multiplyScalar(radius);
}

/** Видимый размер звезды по её блеску. */
function starSize(mag, limit) {
  const span = Math.max(0.5, limit + 1.5 - (-1.5));
  const t = THREE.MathUtils.clamp((limit + 1.5 - mag) / span, 0, 1);
  return 2.0 + 26.0 * Math.pow(t, 2.3);
}

function starTexture() {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0,
                                            size / 2, size / 2, size / 2);
  gradient.addColorStop(0.0, 'rgba(255,255,255,1)');
  gradient.addColorStop(0.25, 'rgba(255,255,255,0.85)');
  gradient.addColorStop(0.6, 'rgba(190,210,255,0.22)');
  gradient.addColorStop(1.0, 'rgba(190,210,255,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

let sharedStarTexture = null;

export class StarField {
  constructor(scene) {
    this.scene = scene;
    this.points = null;
    this.material = null;
  }

  update(stars) {
    if (this.points) {
      this.scene.remove(this.points);
      this.points.geometry.dispose();
      this.points = null;
    }
    const count = stars.az.length;
    if (!count) return;

    const positions = new Float32Array(count * 3);
    const sizes = new Float32Array(count);
    const alphas = new Float32Array(count);
    for (let i = 0; i < count; i += 1) {
      const p = skyPoint(stars.az[i], stars.alt[i]);
      positions[i * 3] = p.x;
      positions[i * 3 + 1] = p.y;
      positions[i * 3 + 2] = p.z;
      sizes[i] = starSize(stars.mag[i], stars.mag_limit);
      // звёзды у горизонта тускнеют — так же, как в атмосфере
      alphas[i] = THREE.MathUtils.clamp(0.25 + stars.alt[i] / 25.0, 0.15, 1.0);
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
    geometry.setAttribute('aAlpha', new THREE.BufferAttribute(alphas, 1));

    if (!sharedStarTexture) sharedStarTexture = starTexture();
    if (!this.material) {
      this.material = new THREE.ShaderMaterial({
        uniforms: {
          uTexture: { value: sharedStarTexture },
          uScale: { value: 1.0 },
        },
        vertexShader: `
          attribute float aSize;
          attribute float aAlpha;
          varying float vAlpha;
          uniform float uScale;
          void main() {
            vAlpha = aAlpha;
            vec4 mv = modelViewMatrix * vec4(position, 1.0);
            gl_PointSize = aSize * uScale;
            gl_Position = projectionMatrix * mv;
          }`,
        fragmentShader: `
          uniform sampler2D uTexture;
          varying float vAlpha;
          void main() {
            vec4 c = texture2D(uTexture, gl_PointCoord);
            gl_FragColor = vec4(c.rgb, c.a * vAlpha);
            if (gl_FragColor.a < 0.02) discard;
          }`,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
    }

    this.points = new THREE.Points(geometry, this.material);
    this.points.frustumCulled = false;
    this.scene.add(this.points);
  }

  /** При увеличении звёзды не должны раздуваться вместе с полем. */
  setZoom(fovDeg, baseFovDeg) {
    if (this.material) {
      this.material.uniforms.uScale.value =
        THREE.MathUtils.clamp(baseFovDeg / Math.max(fovDeg, 1), 0.6, 2.4);
    }
  }
}

export class Constellations {
  constructor(scene, labels) {
    this.scene = scene;
    this.labels = labels;
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.labelKeys = [];
  }

  update(figures, showLines, showLabels) {
    this.group.clear();
    this.labels.removeGroup('constellation');
    if (!showLines && !showLabels) return;

    const vertices = [];
    for (const figure of figures) {
      if (showLines) {
        for (const [az1, alt1, az2, alt2] of figure.segments) {
          const a = skyPoint(az1, alt1);
          const b = skyPoint(az2, alt2);
          vertices.push(a.x, a.y, a.z, b.x, b.y, b.z);
        }
      }
      if (showLabels && figure.label && figure.label.alt > 3) {
        this.labels.add('constellation', figure.label.text,
                        figure.label.az, figure.label.alt,
                        { color: '#6f86b8', size: 13 });
      }
    }
    if (!vertices.length) return;

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(vertices), 3));
    const material = new THREE.LineBasicMaterial({
      color: 0x3f5a8a, transparent: true, opacity: 0.55,
    });
    const lines = new THREE.LineSegments(geometry, material);
    lines.frustumCulled = false;
    this.group.add(lines);
  }
}

/** Сетка сторон света и кругов равной высоты — чтобы понимать, куда смотришь. */
export function buildGrid(scene, labels) {
  const group = new THREE.Group();
  const material = new THREE.LineBasicMaterial({
    color: 0x2b3a55, transparent: true, opacity: 0.5,
  });

  for (const alt of [0, 15, 30, 45, 60, 75]) {
    const points = [];
    for (let az = 0; az <= 360; az += 3) points.push(skyPoint(az, alt));
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const line = new THREE.Line(geometry, alt === 0
      ? new THREE.LineBasicMaterial({ color: 0x54708f, transparent: true, opacity: 0.85 })
      : material);
    line.frustumCulled = false;
    group.add(line);
  }
  for (let az = 0; az < 360; az += 15) {
    const points = [];
    for (let alt = 0; alt <= 90; alt += 5) points.push(skyPoint(az, alt));
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const line = new THREE.Line(geometry, material);
    line.frustumCulled = false;
    group.add(line);
  }

  const cardinals = [[0, 'С'], [45, 'СВ'], [90, 'В'], [135, 'ЮВ'],
                     [180, 'Ю'], [225, 'ЮЗ'], [270, 'З'], [315, 'СЗ']];
  for (const [az, text] of cardinals) {
    labels.add('cardinal', text, az, 2.5,
               { color: '#9fb6d8', size: text.length > 1 ? 16 : 22 });
  }

  scene.add(group);
  return group;
}
