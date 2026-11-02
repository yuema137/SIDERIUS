/** #1139: exercise the shipped controller, including persisted retries across tabs. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';

const source = readFileSync(new URL('../../src/tools/candidate_console/static/loop-control.js', import.meta.url), 'utf8');
const key = 'siderius.loop-resume.v2/store/predecessor';
const review = {predecessor_operation_id: 'predecessor', expected_receipt_digest: 'digest',
  completed_iterations: 1, final_iteration: 3, credential_readiness: {ready: true}};
const saved = {origin: 'http://console', expected_receipt_digest: 'digest', request_id: 'earlier', operator_advice: 'Earlier advice'};

function harness() {
  const elements = new Map(), storage = new Map(), posts = [];
  let failure = null, sequence = 0;
  const element = id => {
    if (!elements.has(id)) elements.set(id, {hidden: false, disabled: false, textContent: '', value: '', listeners: {},
      addEventListener(event, callback) { this.listeners[event] = callback; },
      removeAttribute() {}, replaceChildren() {}});
    return elements.get(id);
  };
  const window = {runScheduling: {fillResources() {}, readResources: () => ({}), describe: () => ''},
    consoleSession: {connected: true, operationsStoreId: 'store', request: async (path, body) => {
      if (path.endsWith('/loop-resume-review')) return review;
      assert.equal(path, 'loop-resumes');
      posts.push(JSON.parse(JSON.stringify(body)));
      if (failure) throw failure;
      return {operation_id: 'successor'};
    }}};
  runInNewContext(source, {window, document: {getElementById: element},
    location: {origin: saved.origin, hash: ''}, crypto: {randomUUID: () => `new-${++sequence}`},
    localStorage: {getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k)}});
  window.renderLoopControl({operation_id: 'predecessor', kind: 'candidate', state: 'completed', native_status: 'paused',
    receipt_available: true, loop: {final_iteration: 3, attempted_iterations: 1}});
  const click = async id => { element(id).listeners.click(); await new Promise(resolve => setImmediate(resolve)); };
  return {element, storage, posts, click, fail: value => { failure = value; }};
}

// Python owns canonical trimming. Enumerate its actual whitespace set, including C0/C1
// edges absent from JS trim; BOM is deliberately outside that set.
const whitespace = JSON.parse(execFileSync(fileURLToPath(new URL('../../.venv/bin/python', import.meta.url)),
  ['-c', 'import json; print(json.dumps("".join(chr(i) for i in range(0x110000) if chr(i).isspace())))'], {encoding: 'utf8'}));
for (const edge of [...whitespace, '\ufeff']) {
  test(`advice edge U+${edge.codePointAt(0).toString(16)} matches Python strip`, async () => {
    const h = harness(); await h.click('loop-resume-review');
    h.element('loop-resume-advice').value = edge + 'Advice' + edge;
    await h.click('loop-resume');
    const expected = edge === '\ufeff' ? edge + 'Advice' + edge : 'Advice';
    assert.equal(h.posts[0].operator_advice, expected);
    assert.equal(h.element('loop-resume-advice').value, expected);
    assert.equal(JSON.parse(h.storage.get(key)).operator_advice, expected);
  });
}
for (const code of ['credentials', 'loop_resume']) {
  test(`${code} refusal unlocks advice and gives the next attempt a fresh UUID`, async () => {
    const h = harness(); await h.click('loop-resume-review');
    h.element('loop-resume-advice').value = 'First'; h.fail({status: 409, code, message: 'refused'});
    await h.click('loop-resume');
    assert.equal(h.storage.has(key), false); assert.equal(h.element('loop-resume-advice').readOnly, false);
    h.fail(null); await h.click('loop-resume-review'); h.element('loop-resume-advice').value = 'Edited';
    await h.click('loop-resume');
    assert.notEqual(h.posts[0].request_id, h.posts[1].request_id);
    assert.equal(h.posts[1].operator_advice, 'Edited');
  });
}
for (const failure of [{message: 'network'}, {status: 409, code: 'integrity', message: 'uncertain'}, {status: 409, code: 'conflict', message: 'conflict'}]) {
  test(`${failure.code || 'transport'} preserves the admitted-or-uncertain request`, async () => {
    const h = harness(); await h.click('loop-resume-review');
    h.element('loop-resume-advice').value = 'First'; h.fail(failure); await h.click('loop-resume');
    assert.equal(h.element('loop-resume-advice').readOnly, true);
    h.fail(null); await h.click('loop-resume-review'); await h.click('loop-resume');
    assert.deepEqual(h.posts[1], h.posts[0]);
  });
}
for (const retainedKey of [key, 'siderius.loop-resume.v1:predecessor']) {
  test(`${retainedKey} cannot silently replace newly typed advice`, async () => {
    const h = harness(); await h.click('loop-resume-review');
    h.element('loop-resume-advice').value = 'New advice'; h.storage.set(retainedKey, JSON.stringify(saved));
    await h.click('loop-resume');
    assert.equal(h.posts.length, 0, 'show the earlier advice before sending it');
    assert.equal(h.element('loop-resume-advice').value, saved.operator_advice);
    assert.match(h.element('loop-resume-status').textContent, /earlier Resume request/);
    assert.equal(h.element('loop-resume-advice').readOnly, true);
    await h.click('loop-resume');
    assert.equal(h.posts[0].request_id, saved.request_id);
    assert.equal(h.posts[0].operator_advice, saved.operator_advice);
  });
}

for (const retainedKey of [key, 'siderius.loop-resume.v1:predecessor']) {
  test(`${retainedKey} replays old whitespace bytes after displaying canonical advice`, async () => {
    const h = harness(); await h.click('loop-resume-review');
    const old = {...saved, operator_advice: '\u0085Earlier advice\u001c'};
    h.element('loop-resume-advice').value = 'New advice'; h.storage.set(retainedKey, JSON.stringify(old));
    await h.click('loop-resume');
    assert.equal(h.posts.length, 0);
    assert.equal(h.element('loop-resume-advice').value, 'Earlier advice');
    await h.click('loop-resume');
    assert.equal(h.posts[0].request_id, old.request_id);
    assert.equal(h.posts[0].operator_advice, old.operator_advice, 'old uncertain body stays byte-identical');
  });
}
