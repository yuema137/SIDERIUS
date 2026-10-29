/** A wire must reach its real socket endpoints without crossing unrelated cards. */
import assert from 'node:assert/strict';
import '../../src/tools/candidate_console/static/editor-circuit-geometry.js';

const {route, segmentClear} = globalThis.editorCircuitGeometry;
const cards = [
  {left: 0, top: 0, right: 100, bottom: 100},
  {left: 160, top: 20, right: 240, bottom: 80},
  {left: 300, top: 0, right: 400, bottom: 100},
];
const start = {x: 100, y: 50}, end = {x: 300, y: 50};
const points = route(start, end, cards, 0, 2);
assert.ok(points, 'A direct line crosses the middle card; the router must find a detour');
assert.deepEqual(points[0], start);
assert.deepEqual(points.at(-1), end);
for (let i = 1; i < points.length; i++) {
  assert.ok(points[i].x === points[i - 1].x || points[i].y === points[i - 1].y);
  assert.ok(segmentClear(points[i - 1], points[i], [cards[1]]));
}
assert.equal(route(start, end, [cards[0], {...cards[1], left: 105, right: 130}, cards[2]], 0, 2), null,
  'An unrelated card covering the socket exit cannot be silently crossed');
console.log('PASS circuit geometry endpoints, orthogonal obstacle detour and blocked socket exit');

const positions = globalThis.editorCircuitGeometry.arrange([
  {id: 'validator', request: {kind: 'protocol', arguments: [{source: {kind: 'result', node: 'builder'}}]}},
  {id: 'builder', request: {kind: 'protocol', arguments: [{source: {kind: 'result', node: 'proposal'}}]}},
  {id: 'proposal', request: {kind: 'external'}},
], 300, 350);
assert.ok(positions.get('proposal').y < positions.get('builder').y);
assert.ok(positions.get('builder').y < positions.get('validator').y, 'Default display order follows actual edges even when source nodes are interleaved');

// Fallback placement (G5). Fails if an unsaved card lands on a stored one, two
// unsaved cards share a point, stored positions move, or an empty stored set
// yields non-finite coordinates.
const {place} = globalThis.editorCircuitGeometry;
const chain = ['interpret', 'hypothesis', 'build', 'check', 'fit'].map((id, index, ids) => ({
  id, request: index ? {kind: 'protocol', arguments: [{source: {kind: 'result', node: ids[index - 1]}}]} : {kind: 'external'},
}));
const size = {width: 215, height: 180}, gap = {x: 135, y: 90};
const disjoint = (placed, label) => {
  const boxes = [...placed].map(([id, p]) => ({id, left: p.x, top: p.y, right: p.x + size.width, bottom: p.y + size.height}));
  for (const box of boxes) assert.ok(Number.isFinite(box.left) && Number.isFinite(box.top), `${label}: ${box.id} is finite`);
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    assert.ok(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top, `${label}: ${a.id} overlaps ${b.id}`);
  }
};
disjoint(place(chain, new Map(), size, gap), 'no stored positions');
const partial = new Map([['build', {x: 120, y: -30}], ['check', {x: 400, y: 300}]]);
const placedPartial = place(chain, partial, size, gap);
assert.deepEqual(placedPartial.get('build'), {x: 120, y: -30}, 'Stored positions are exact');
assert.deepEqual(placedPartial.get('check'), {x: 400, y: 300}, 'Stored positions are exact');
disjoint(placedPartial, 'partial stored positions');
const fanout = [{id: 'seed', request: {kind: 'external'}}, ...['a', 'b', 'c'].map(id => ({id, request: {kind: 'protocol', arguments: [{source: {kind: 'result', node: 'seed'}}]}}))];
disjoint(place(fanout, new Map([['seed', {x: 0, y: 0}]]), size, gap), 'same-rank unsaved siblings');
console.log('PASS fallback placement keeps stored positions exact and every card disjoint');

// View fit (UX walkthrough 2026-10-27: 2 of 5 cards off-screen at 1440x900). Fails if
// fitting ever enlarges past 100 %, overshoots the available box, ignores the
// legibility floor, or returns a non-finite scale for an unmeasured (hidden) view.
const {fitScale, overlaps} = globalThis.editorCircuitGeometry;
assert.equal(fitScale({width: 600, height: 400}, {width: 800, height: 700}), 1, 'A graph that already fits is shown at 100 %');
const scale = fitScale({width: 1635, height: 700}, {width: 800, height: 700});
assert.ok(scale < 1 && 1635 * scale <= 800 && 700 * scale <= 700, `fit scale ${scale} shows the whole width`);
assert.equal(fitScale({width: 4000, height: 4000}, {width: 800, height: 700}), 0.4, 'Fit never shrinks below the legibility floor; the view scrolls instead');
assert.equal(fitScale({width: 0, height: 0}, {width: 0, height: 0}), 1, 'An unmeasured view keeps 100 %');
// Saved-layout overlap detection drives the non-destructive Arrange view offer.
assert.deepEqual(overlaps([{left: -80, right: 135, top: 20, bottom: 200}, {left: 120, right: 335, top: -30, bottom: 300}, {left: 520, right: 735, top: 20, bottom: 200}]), [[0, 1]],
  'The interpretation fixture regression (interpret at x=-80 under build at x=120) is reported');
assert.deepEqual(overlaps([{left: 0, right: 100, top: 0, bottom: 100}, {left: 100, right: 200, top: 0, bottom: 100}]), [], 'Touching edges are not an overlap');
console.log('PASS view fit scale bounds and saved-layout overlap detection');

// Tidy up: columns follow the longest path from a source (a skip edge cannot pull a node
// left), rows follow the mean row of the sources, and every position is on the 16px grid.
{
  const {tidy} = globalThis.editorCircuitGeometry;
  const result = from => ({kind: 'result', node: from, port: 'result'});
  const node = (id, sources) => ({id, request: {kind: 'protocol', protocol: 'p', arguments: sources.map((from, i) => ({name: 'a' + i, source: result(from)}))}});
  const nodes = [node('validate', ['implement', 'propose']), node('implement', ['propose']), {id: 'propose', request: {kind: 'external', binding: 'x'}}, node('side', ['propose']), node('lone', [])];
  const placed = tidy(nodes, {width: 215, height: 150});
  const column = Math.ceil((215 + 80) / 16) * 16, row = Math.ceil((150 + 32) / 16) * 16;
  assert.equal(placed.get('propose').x, 0, 'Sources start the first column');
  assert.equal(placed.get('lone').x, 3 * column, 'A module with no wire takes the column after the connected ones');
  assert.equal(placed.get('implement').x, column, 'One step after its source');
  assert.equal(placed.get('validate').x, 2 * column, 'Longest path, not the shortest (propose -> validate skip edge)');
  assert.deepEqual([placed.get('implement').y, placed.get('side').y].sort(), [0, row], 'Siblings share a column on separate rows');
  for (const {x, y} of placed.values()) assert.ok(x % 16 === 0 && y % 16 === 0, 'On the 16px grid');
  const keys = [...placed.values()].map(({x, y}) => `${x},${y}`);
  assert.equal(new Set(keys).size, keys.length, 'No two modules share a slot');
  // Tour #12: with no wire at all, modules form one row in pipeline order (never backwards).
  const stages = {validate: 4, implement: 3, propose: 2};
  const row1 = tidy([{id: 'validate', request: {kind: 'external'}}, {id: 'implement', request: {kind: 'external'}}, {id: 'propose', request: {kind: 'external'}}], {width: 215, height: 150}, undefined, undefined, id => stages[id]);
  assert.deepEqual(['propose', 'implement', 'validate'].map(id => row1.get(id).x), [0, column, 2 * column], 'Pipeline order left to right');
  console.log('PASS tidy layout: longest-path columns, loose modules after them, pipeline order, grid-aligned disjoint slots');
}
