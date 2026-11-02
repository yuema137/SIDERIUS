/** Regression witness for noisy/chunked startup and bounded metadata failures; no browser needed. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {waitForMetadata} from './fixture_metadata.mjs';

async function check(script, verify, timeoutMs = 2000) {
  const child = spawn(process.execPath, ['-e', script], {stdio: ['pipe', 'pipe', 'pipe']});
  try {
    await verify(waitForMetadata(child, {timeoutMs}));
    assert.equal(child.listenerCount('error'), 0);
    assert.equal(child.listenerCount('close'), 0);
  } finally { child.kill(); }
}
await check(`
  console.log('[PluginLoader] informational output');
  console.log('{"origin":"unmarked-decoy"}');
  process.stdout.write('SIDERIUS_BROWSER_META');
  setTimeout(() => process.stdout.write('DATA {"origin":"fixture","label":"雪"}\\r\\n'), 20);
  setInterval(() => {}, 1000);
`, async result => assert.deepEqual(await result, {origin: 'fixture', label: '雪'}));
await check(`console.log('SIDERIUS_BROWSER_METADATA {broken');`, result =>
  assert.rejects(result, /malformed metadata JSON/));
await check(`console.log('SIDERIUS_BROWSER_METADATA []');`, result =>
  assert.rejects(result, /must be an object/));
await check(`console.log('only noise');`, result =>
  assert.rejects(result, /before metadata/));
await check(`setInterval(() => {}, 1000);`, result =>
  assert.rejects(result, /startup timeout/), 50);
const missing = spawn('/nonexistent-siderius-metadata-fixture', [], {stdio: ['pipe', 'pipe', 'pipe']});
await assert.rejects(waitForMetadata(missing), /failed to start/);
// Exercise the actual Python producer, including stdout written before its import.
const python = spawn(process.env.EDITOR_PYTHON, ['-c',
  'print("startup noise", flush=True); from tests.browser.fixture_metadata import emit_metadata; emit_metadata({"endpoint": "offline"})'],
{stdio: ['pipe', 'pipe', 'pipe']});
assert.deepEqual(await waitForMetadata(python), {endpoint: 'offline'});
console.log('PASS metadata: noise, unmarked JSON, chunked record, malformed payload, EOF, timeout, spawn error, cleanup and Python producer');
