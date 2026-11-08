// A* on the town grid with 8-way moves. cost(i) is the price of entering cell i (Infinity = blocked);
// walls are expensive rather than blocked, so troops weigh breaking through against walking around.
export function astar(size, sx, sy, isGoal, h, cost, maxNodes = 9000) {
  const N = size * size, g = new Float32Array(N).fill(Infinity), came = new Int32Array(N).fill(-1);
  const closed = new Uint8Array(N), heap = [], pri = [];
  const push = (i, p) => {
    heap.push(i); pri.push(p); let c = heap.length - 1;
    while (c > 0) { const par = (c - 1) >> 1; if (pri[par] <= pri[c]) break; [heap[c], heap[par]] = [heap[par], heap[c]]; [pri[c], pri[par]] = [pri[par], pri[c]]; c = par; }
  };
  const pop = () => {
    const top = heap[0], lastI = heap.pop(), lastP = pri.pop();
    if (heap.length) {
      heap[0] = lastI; pri[0] = lastP; let c = 0;
      for (;;) {
        const l = 2 * c + 1, r = l + 1; let m = c;
        if (l < heap.length && pri[l] < pri[m]) m = l; if (r < heap.length && pri[r] < pri[m]) m = r;
        if (m === c) break; [heap[c], heap[m]] = [heap[m], heap[c]]; [pri[c], pri[m]] = [pri[m], pri[c]]; c = m;
      }
    }
    return top;
  };
  sx = Math.max(0, Math.min(size - 1, sx)); sy = Math.max(0, Math.min(size - 1, sy));
  const start = sy * size + sx; g[start] = 0; push(start, h(sx, sy));
  let expanded = 0;
  while (heap.length) {
    const i = pop(); if (closed[i]) continue; closed[i] = 1;
    const x = i % size, y = (i / size) | 0;
    if (isGoal(x, y)) {
      const path = []; for (let c = i; c !== -1 && c !== start; c = came[c]) path.push([c % size, (c / size) | 0]);
      return path.reverse();
    }
    if (++expanded > maxNodes) break;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      if (!dx && !dy) continue;
      const nx = x + dx, ny = y + dy; if (nx < 0 || ny < 0 || nx >= size || ny >= size) continue;
      const ni = ny * size + nx; if (closed[ni]) continue;
      const c = cost(ni); if (!isFinite(c)) continue;
      if (dx && dy) { // no squeezing diagonally between two obstacles
        const a = cost(y * size + nx), b = cost(ny * size + x);
        if (!isFinite(a) || !isFinite(b) || a > 1.5 || b > 1.5) continue;
      }
      const ng = g[i] + (dx && dy ? 1.414 : 1) * c;
      if (ng < g[ni]) { g[ni] = ng; came[ni] = i; push(ni, ng + h(nx, ny)); }
    }
  }
  return null;
}

/** Distance from a point to a building footprint (0 inside). */
export function rectDist(px, py, b) {
  const dx = Math.max(b.x - px, 0, px - (b.x + b.size)), dy = Math.max(b.y - py, 0, py - (b.y + b.size));
  return Math.hypot(dx, dy);
}
