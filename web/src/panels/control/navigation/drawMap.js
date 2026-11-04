import { world as toWorld, screen as toScreen } from './geometry.js';

// Map PNGs have a top-left origin; ROS occupancy grids have a bottom-left origin.
export function drawMap(canvas, { state, view, size, mapImage, imageVersion, online, selected, tool, layers }, palette) {
  const ctx = canvas.getContext('2d');
  if (!ctx || !size.w) return;
  const screen = point => toScreen(point, view, size);
  const world = point => toWorld(point, view, size);
  function line(points, color, width = 2) {
    if (!points?.length) return;
    ctx.beginPath();
    points.forEach((point, index) => {
      const [x, y] = screen(point);
      if (index) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    });
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.stroke();
  }
  function arrow(pose, color, fill = true) {
    const [x, y] = screen(pose);
    ctx.save(); ctx.translate(x, y); ctx.rotate(-pose[2]);
    ctx.beginPath(); ctx.moveTo(14, 0); ctx.lineTo(-10, -8);
    ctx.lineTo(-6, 0); ctx.lineTo(-10, 8); ctx.closePath();
    ctx.fillStyle = color; ctx.strokeStyle = color; ctx.lineWidth = 2;
    if (fill) ctx.fill(); else ctx.stroke();
    ctx.restore();
  }
  const ratio = window.devicePixelRatio || 1;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, size.w, size.h);
  if (state?.map && mapImage && imageVersion === state.map.version) {
    const map = state.map, [x, y, angle] = map.origin, [sx, sy] = screen([x, y]);
    ctx.save(); ctx.translate(sx, sy); ctx.scale(view.scale, -view.scale);
    ctx.rotate(angle); ctx.translate(0, map.height * map.resolution);
    ctx.scale(map.resolution, -map.resolution);
    ctx.imageSmoothingEnabled = false; ctx.drawImage(mapImage, 0, 0); ctx.restore();
  }
  if (layers.grid) {
    const spacing = view.scale > 25 ? 1 : 5, lo = world([0, size.h]), hi = world([size.w, 0]);
    ctx.strokeStyle = palette.grid; ctx.lineWidth = 1; ctx.beginPath();
    for (let x = Math.ceil(lo[0] / spacing) * spacing; x < hi[0]; x += spacing) {
      const px = screen([x, 0])[0]; ctx.moveTo(px, 0); ctx.lineTo(px, size.h);
    }
    for (let y = Math.ceil(lo[1] / spacing) * spacing; y < hi[1]; y += spacing) {
      const py = screen([0, y])[1]; ctx.moveTo(0, py); ctx.lineTo(size.w, py);
    }
    ctx.stroke();
  }
  if (online && layers.path) {
    line(state?.paths?.plan, palette.path);
    line(state?.paths?.local_plan, palette.localPath, 1.5);
  }
  if (online && layers.scan) {
    ctx.fillStyle = palette.scan;
    for (const point of state?.scan || []) {
      const [x, y] = screen(point); ctx.fillRect(x - 1, y - 1, 2, 2);
    }
  }
  if (state?.robot) {
    const age = state?.sensors?.odom?.age;
    ctx.globalAlpha = online && Number.isFinite(age) && age < .5 ? 1 : .3;
    const [x, y] = screen(state.robot);
    ctx.beginPath(); ctx.arc(x, y, Math.max(5, .3 * view.scale), 0, 2 * Math.PI);
    ctx.fillStyle = palette.robotFill; ctx.strokeStyle = palette.robotBorder;
    ctx.fill(); ctx.stroke(); arrow(state.robot, palette.robot); ctx.globalAlpha = 1;
  }
  for (const goal of state?.destinations || []) {
    const [x, y] = screen([goal.x, goal.y]);
    ctx.fillStyle = palette.text; ctx.beginPath(); ctx.arc(x, y, 4, 0, 2 * Math.PI);
    ctx.fill(); ctx.font = '11px system-ui'; ctx.fillText(goal.name, x + 7, y - 7);
  }
  if (state?.goal) arrow(state.goal, palette.path, false);
  if (selected) arrow(selected, tool === 'initial_pose' ? palette.scan : palette.robot);
}
