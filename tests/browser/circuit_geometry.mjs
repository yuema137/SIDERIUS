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
], 300);
assert.ok(positions.get('proposal').y < positions.get('builder').y);
assert.ok(positions.get('builder').y < positions.get('validator').y, 'Default display order follows actual edges even when source nodes are interleaved');
