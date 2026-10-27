/* Pure obstacle routing adapted from the approved circuit prototype; no graph semantics. */
(() => {
'use strict';
class RouteQueue {
  constructor() {
    this.items = [];
  }
  push(item) {
    let i = this.items.push(item) - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (this.items[parent].priority <= item.priority) break;
      this.items[i] = this.items[parent];
      i = parent;
    }
    this.items[i] = item;
  }
  pop() {
    const first = this.items[0],
      last = this.items.pop();
    if (this.items.length) {
      let i = 0;
      while (2 * i + 1 < this.items.length) {
        let child = 2 * i + 1;
        if (
          child + 1 < this.items.length &&
          this.items[child + 1].priority < this.items[child].priority
        )
          child++;
        if (this.items[child].priority >= last.priority) break;
        this.items[i] = this.items[child];
        i = child;
      }
      this.items[i] = last;
    }
    return first;
  }
}
function segmentClear(a, b, boxes) {
  return !boxes.some((box) =>
    a.x === b.x
      ? a.x > box.left &&
        a.x < box.right &&
        Math.max(a.y, b.y) > box.top &&
        Math.min(a.y, b.y) < box.bottom
      : a.y > box.top &&
        a.y < box.bottom &&
        Math.max(a.x, b.x) > box.left &&
        Math.min(a.x, b.x) < box.right,
  );
}
function simplifyRoute(points) {
  return points.filter(
    (point, index) =>
      index === 0 ||
      index === points.length - 1 ||
      !(
        (points[index - 1].x === point.x && point.x === points[index + 1].x) ||
        (points[index - 1].y === point.y && point.y === points[index + 1].y)
      ),
  );
}
function routeOnGrid(start, end, boxes, occupied) {
  const unique = (values) => [...new Set(values)].sort((a, b) => a - b);
  const xs = unique([
    20,
    start.x,
    end.x,
    ...boxes.flatMap((b) => [b.left - 18, b.right + 18]),
    Math.max(...boxes.map((b) => b.right)) + 65,
  ]);
  const ys = unique([
    20,
    start.y,
    end.y,
    ...boxes.flatMap((b) => [b.top - 18, b.bottom + 18]),
    Math.max(...boxes.map((b) => b.bottom)) + 65,
  ]);
  const startX = xs.indexOf(start.x),
    startY = ys.indexOf(start.y),
    endX = xs.indexOf(end.x),
    endY = ys.indexOf(end.y);
  const key = (x, y, d) => `${x},${y},${d}`,
    dist = new Map(),
    previous = new Map(),
    queue = new RouteQueue();
  const first = key(startX, startY, 1);
  dist.set(first, 0);
  queue.push({ x: startX, y: startY, d: 1, id: first, priority: 0 });
  let finish = null;
  while (queue.items.length) {
    const current = queue.pop();
    if (current.x === endX && current.y === endY) {
      finish = current.id;
      break;
    }
    const a = { x: xs[current.x], y: ys[current.y] };
    [
      [1, 0, 0],
      [-1, 0, 0],
      [0, 1, 1],
      [0, -1, 1],
    ].forEach(([dx, dy, d]) => {
      const x = current.x + dx,
        y = current.y + dy;
      if (x < 0 || y < 0 || x >= xs.length || y >= ys.length) return;
      const b = { x: xs[x], y: ys[y] };
      if (!segmentClear(a, b, boxes)) return;
      const id = key(x, y, d),
        cost =
          dist.get(current.id) +
          Math.abs(b.x - a.x) +
          Math.abs(b.y - a.y) +
          (d === current.d ? 0 : 25) +
          (occupied.has(`${b.x},${b.y}`) ? 35 : 0);
      if (cost >= (dist.get(id) ?? Infinity)) return;
      dist.set(id, cost);
      previous.set(id, current.id);
      queue.push({
        x,
        y,
        d,
        id,
        priority: cost + Math.abs(end.x - b.x) + Math.abs(end.y - b.y),
      });
    });
  }
  if (!finish) return null;
  const points = [];
  for (let id = finish; id; id = previous.get(id)) {
    const [x, y] = id.split(",").map(Number);
    points.push({ x: xs[x], y: ys[y] });
    occupied.add(`${xs[x]},${ys[y]}`);
  }
  return simplifyRoute(points.reverse());
}
// Display ranks from declared edges only; this does not admit or execute a graph.
function arrange(nodes, spacing, column) {
  const remaining = new Set(nodes.map(node => node.id)), ranks = new Map();
  const parents = id => {
    const request = nodes.find(node => node.id === id).request;
    return request.kind === 'external' ? [] : request.arguments.filter(arg => arg.source.kind === 'result').map(arg => arg.source.node);
  };
  while (remaining.size) {
    const ready = [...remaining].filter(id => parents(id).every(parent => !remaining.has(parent))).sort();
    // Unsupported pending forms can still be inspected; server Review owns refusal.
    if (!ready.length) ready.push(remaining.values().next().value);
    for (const id of ready) { ranks.set(id, Math.max(0, ...parents(id).map(parent => (ranks.get(parent) ?? -1) + 1))); remaining.delete(id); }
  }
  const rows = new Map(), positions = new Map();
  for (const [id, rank] of ranks) { const index = rows.get(rank) || 0; positions.set(id, {x: index * column, y: rank * spacing}); rows.set(rank, index + 1); }
  return positions;
}
// Saved positions stay exact. Unsaved nodes keep their ranked layout, shifted
// right of every saved card, so a fallback card never covers a stored one.
// `size` is the largest rendered card; `gap` separates cards on both axes.
function place(nodes, saved, size, gap) {
  const arranged = arrange(nodes, size.height + gap.y, size.width + gap.x);
  const stored = nodes.filter(node => saved.has(node.id)), fallback = nodes.filter(node => !saved.has(node.id));
  const shift = stored.length && fallback.length
    ? Math.max(...stored.map(node => saved.get(node.id).x)) + size.width + gap.x - Math.min(...fallback.map(node => arranged.get(node.id).x))
    : 0;
  return new Map(nodes.map(node => {
    const position = saved.get(node.id) || {x: arranged.get(node.id).x + shift, y: arranged.get(node.id).y};
    return [node.id, {x: position.x, y: position.y}];
  }));
}
function route(a, b, boxes, source, target, occupied = new Set()) {
  const start = {x: a.x + 24, y: a.y}, end = {x: b.x - 24, y: b.y};
  if (!segmentClear(a, start, boxes.filter((_, i) => i !== source)) ||
      !segmentClear(end, b, boxes.filter((_, i) => i !== target))) return null;
  const points = routeOnGrid(start, end, boxes, occupied);
  if (!points) return null;
  return simplifyRoute([a, ...points, b]);
}
// View-only zoom: the largest scale (never above 1, never below `min`) at which
// `content` fits `available`. Positions stay in document coordinates; only the
// rendered view is scaled, so fitting never changes a saved position.
function fitScale(content, available, min = 0.4) {
  if (!(content.width > 0 && content.height > 0 && available.width > 0 && available.height > 0)) return 1;
  const scale = Math.min(1, available.width / content.width, available.height / content.height);
  return Math.max(min, Math.floor(scale * 100) / 100);
}
// Index pairs of boxes ({left, right, top, bottom}) whose interiors intersect.
function overlaps(boxes) {
  const pairs = [];
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) pairs.push([i, j]);
  }
  return pairs;
}
function path(points) { return points.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' '); }
globalThis.editorCircuitGeometry = Object.freeze({route, path, segmentClear, arrange, place, fitScale, overlaps});
})();
