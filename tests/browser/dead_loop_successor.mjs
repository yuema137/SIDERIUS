/** #1206: execute the shipped Monitor renderer with an in-memory DOM and API. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const elements = new Map(), posts = [];
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    hidden: false, disabled: false, textContent: '', value: '', listeners: {},
    addEventListener(event, callback) { this.listeners[event] = callback; },
    removeAttribute() {}, replaceChildren() {}
  });
  return elements.get(id);
}
const window = {
  consoleSession: {connected: true, operationsStoreId: 'store', request: async (...args) => { posts.push(args); }},
  confirm: () => true, dispatchEvent() {}
};
const context = {window, document: {getElementById: element}, localStorage: {removeItem() {}}, CustomEvent: class {}};
for (const name of ['operation-outcome.js', 'loop-control.js']) {
  runInNewContext(readFileSync(new URL(`../../src/tools/candidate_console/static/${name}`, import.meta.url), 'utf8'), context);
}
const paused = {
  operation_id: 'predecessor', kind: 'candidate', state: 'completed', native_status: 'paused',
  receipt_available: true, successor_operation_id: 'successor', process: {status: 'exited'},
  reason: 'loop_successor_failed', loop: {final_iteration: 3, attempted_iterations: 1}
};
window.renderLoopControl(paused);
assert.equal(element('loop-resume-group').hidden, false, 'End must remain available after a dead successor');
assert.equal(element('loop-resume-review').hidden, true, 'Reservation cannot be recycled');
assert.equal(element('loop-resume').hidden, true);
assert.equal(element('loop-successor').href, '#monitor/successor');
assert.match(element('loop-state').textContent, /interrupted without a result/);
element('loop-end').listeners.click();
await new Promise(resolve => setImmediate(resolve));
assert.equal(posts.length, 1);
assert.equal(posts[0][0], 'operations/predecessor/loop-stop');
window.renderLoopControl({...paused, loop: {...paused.loop, stop_requested: true}});
assert.equal(element('loop-resume-group').hidden, true);
assert.match(element('loop-state').textContent, /Ended by you after the resumed segment was interrupted/);
window.renderLoopControl({...paused, reason: 'native_terminal'});
assert.equal(element('loop-resume-group').hidden, true, 'Live or uncertain successors still block End');
const dead = {
  operation_id: 'successor', kind: 'candidate_loop_resume', state: 'operation_failed',
  reason: 'loop_process_exited', process: {status: 'exited'}, loop: {final_iteration: 3}
};
window.renderLoopControl(dead);
assert.match(window.operationOutcome.sentence(dead), /was interrupted/);
assert.match(element('loop-state').textContent, /No final body count is available/);
assert.doesNotMatch(element('loop-state').textContent, /count is reported by the native receipt/);
const exiting = {...dead, state: 'unknown', reason: 'loop_process_exiting'};
window.renderLoopControl(exiting);
assert.match(window.operationOutcome.sentence(exiting), /not confirmed stopped/);
assert.equal(window.operationOutcome.failed(exiting), false);
assert.equal(window.operationOutcome.terminal(exiting), false);
assert.match(element('loop-state').textContent, /result is still unresolved/);
assert.equal(element('loop-resume-group').hidden, true);
console.log('Dead successor Monitor recovery passed');
