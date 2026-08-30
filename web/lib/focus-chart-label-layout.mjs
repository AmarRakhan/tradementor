/** Collision-resolve chart labels without moving their underlying price lines. */
export function layoutFocusLabelYs(realByKey, height, minGap = 24, pad = 16) {
  const h = Math.max(1, Number(height) || 1);
  const gap = Math.max(1, Number(minGap) || 24);
  const edge = Math.max(0, Number(pad) || 0);
  const points = Object.entries(realByKey || {})
    .map(([key, y]) => ({ key, realY: Number(y), labelY: Number(y) }))
    .filter((p) => Number.isFinite(p.realY))
    .sort((a, b) => a.realY - b.realY);
  if (!points.length) return {};

  // Forward pass guarantees the minimum vertical separation.
  points[0].labelY = Math.max(edge, points[0].labelY);
  for (let i = 1; i < points.length; i++) {
    points[i].labelY = Math.max(points[i].realY, points[i - 1].labelY + gap);
  }

  // Shift the group upward if it would leave the bottom edge.
  const maxY = Math.max(edge, h - edge);
  const overflow = points[points.length - 1].labelY - maxY;
  if (overflow > 0) for (const p of points) p.labelY -= overflow;

  // Backward pass preserves spacing after clamping the bottom.
  for (let i = points.length - 2; i >= 0; i--) {
    points[i].labelY = Math.min(points[i].labelY, points[i + 1].labelY - gap);
  }

  // If the whole cluster is too high, move it down as one unit.
  const underflow = edge - points[0].labelY;
  if (underflow > 0) for (const p of points) p.labelY += underflow;

  const result = {};
  for (const p of points) result[p.key] = Math.max(edge, Math.min(maxY, p.labelY));
  return result;
}
