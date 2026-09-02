/* Вид в бинокль: круглое поле с настоящим угловым масштабом.
 *
 * Единственное правило этого модуля: масштаб задаётся полем зрения прибора и
 * ничем больше. Если у бинокля поле 6.5°, а M31 занимает 3°, она обязана
 * занять примерно половину круга. Растянуть объект «чтобы было видно» здесь
 * нельзя — весь смысл режима в том, чтобы человек заранее понял, что увидит.
 *
 * Python присылает смещения объектов от центра поля в градусах; здесь они
 * только умножаются на «пикселей на градус».
 */

const KIND_COLOR = {
  MOON: '#efeade', PLANET: '#ffd9a0', JUPITER_MOON: '#dfe6f5',
  COMET: '#9ff2d8', OPEN_CLUSTER: '#a8d8ff', GLOBULAR_CLUSTER: '#ffd6a8',
  NEBULA: '#b9a8ff', PLANETARY_NEBULA: '#8ce0d0', GALAXY: '#ffb2c8',
  DOUBLE_STAR: '#d8e4ff', ASTERISM: '#b8e8c0',
};

function starRadius(mag, limit) {
  const t = Math.max(0, Math.min(1, (limit + 1 - mag) / (limit + 2.5)));
  return 0.6 + 3.4 * Math.pow(t, 2.0);
}

/** Пересчёт смещения в экранные координаты с учётом ориентации прибора. */
function place(x, y, pixelsPerDegree, orientation) {
  let sx = x;
  let sy = y;
  if (orientation === 'INVERTED') { sx = -x; sy = -y; }
  else if (orientation === 'MIRROR') { sx = -x; }
  // экранный Y растёт вниз, а высота — вверх
  return [sx * pixelsPerDegree, -sy * pixelsPerDegree];
}

export function drawBinocularView(canvas, data, options = {}) {
  const dpr = window.devicePixelRatio || 1;
  const size = options.size || Math.min(canvas.parentElement.clientWidth,
                                        canvas.parentElement.clientHeight) - 60;
  const side = Math.max(220, size);
  canvas.width = side * dpr;
  canvas.height = side * dpr;
  canvas.style.width = `${side}px`;
  canvas.style.height = `${side}px`;

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, side, side);

  const centre = side / 2;
  const margin = 14;
  const fieldRadius = centre - margin;
  // ключевая строка: масштаб определяется полем зрения прибора
  const pixelsPerDegree = fieldRadius / (data.fov_deg / 2);

  ctx.save();
  ctx.beginPath();
  ctx.arc(centre, centre, fieldRadius, 0, Math.PI * 2);
  ctx.fillStyle = '#04060c';
  ctx.fill();
  ctx.clip();

  for (const star of data.stars || []) {
    const [dx, dy] = place(star.x, star.y, pixelsPerDegree, data.orientation);
    ctx.beginPath();
    ctx.arc(centre + dx, centre + dy, starRadius(star.mag, data.limiting_mag),
            0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.globalAlpha = 0.95;
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  for (const item of data.objects || []) {
    const [dx, dy] = place(item.x, item.y, pixelsPerDegree, data.orientation);
    const px = centre + dx;
    const py = centre + dy;
    const colour = KIND_COLOR[item.kind] || '#c8d4e8';
    // настоящий угловой размер объекта, без масштабирования «для красоты»
    const radius = item.size ? (item.size / 60 / 2) * pixelsPerDegree : 0;

    // Скопления и астеризмы состоят из отдельных звёзд, а не из свечения:
    // рисовать их туманным пятном значит показать не то, что человек увидит.
    const resolved = item.kind === 'OPEN_CLUSTER' || item.kind === 'ASTERISM'
      || item.kind === 'DOUBLE_STAR';

    if (radius > 2.5 && !resolved) {
      const gradient = ctx.createRadialGradient(px, py, 0, px, py, radius);
      gradient.addColorStop(0, `${colour}cc`);
      gradient.addColorStop(0.6, `${colour}55`);
      gradient.addColorStop(1, `${colour}00`);
      ctx.beginPath();
      ctx.arc(px, py, radius, 0, Math.PI * 2);
      ctx.fillStyle = gradient;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(px, py, radius, 0, Math.PI * 2);
      ctx.strokeStyle = `${colour}88`;
      ctx.lineWidth = 1;
      ctx.stroke();
    } else if (radius > 2.5) {
      // граница скопления — пунктирной окружностью: она показывает, куда
      // смотреть, но не притворяется светящимся объектом
      ctx.save();
      ctx.setLineDash([4, 5]);
      ctx.beginPath();
      ctx.arc(px, py, radius, 0, Math.PI * 2);
      ctx.strokeStyle = `${colour}99`;
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.restore();
    } else {
      ctx.beginPath();
      ctx.arc(px, py, 2.6, 0, Math.PI * 2);
      ctx.fillStyle = colour;
      ctx.fill();
    }

    if (item.id === (data.target && data.target.id) || item.name) {
      ctx.fillStyle = colour;
      ctx.font = '600 12px "Segoe UI", system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(item.name, px, py - Math.max(radius, 4) - 7);
    }
  }
  ctx.restore();

  // обод поля и метка масштаба
  ctx.beginPath();
  ctx.arc(centre, centre, fieldRadius, 0, Math.PI * 2);
  ctx.strokeStyle = '#4d6386';
  ctx.lineWidth = 2;
  ctx.stroke();

  const scaleDeg = data.fov_deg >= 4 ? 1 : 0.5;
  const scalePx = scaleDeg * pixelsPerDegree;
  const baseY = side - 8;
  ctx.strokeStyle = '#7f8ea8';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(margin, baseY);
  ctx.lineTo(margin + scalePx, baseY);
  ctx.stroke();
  ctx.fillStyle = '#7f8ea8';
  ctx.font = '11px "Segoe UI", system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(`${scaleDeg}°`, margin + scalePx + 6, baseY + 4);

  return { pixelsPerDegree, fieldRadius };
}
