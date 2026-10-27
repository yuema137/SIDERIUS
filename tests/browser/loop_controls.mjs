/** Authored-loop Stop control and honest loop state over a stubbed API. No provider/GPU/native effects. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {tmpdir} from 'node:os';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = ''; server.stderr.on('data', chunk => {errors += chunk;});
const lines = createInterface({input: server.stdout});
const running = '33333333-3333-4333-8333-333333333333';
const fixed = '44444444-4444-4444-8444-444444444444';
const finished = '55555555-5555-4555-8555-555555555555';
const thresholdStop = '66666666-6666-4666-8666-666666666666';
const patienceStop = '77777777-7777-4777-8777-777777777777';
let browser;
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Server startup timeout: ${errors}`)), 15000);
    lines.on('line', line => {
      try {
        const value = JSON.parse(line);
        if (!value.origin || !value.token) return;
        clearTimeout(timer); lines.close(); accept(value);
      } catch { /* Native plugin registration may write one informational line first. */ }
    });
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Server ${code}: ${errors}`));});
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage(), posts = [], faults = [];
  page.on('pageerror', error => faults.push(error.message));
  let runningTerminal = false;
  const status = (operation, fields) => ({operation_id: operation, kind: 'candidate', request_digest: 'a'.repeat(64), observed_at: 'fixture',
    state: 'active', process: {status: 'alive', reason: 'observed'}, finishing: false, receipt_available: false, native_status: null,
    native_id: null, validation_passed: null, reason: 'fixture', ...fields});
  const terminal = (operation, nativeStatus, attempted) => status(operation, {state: 'completed', process: {status: 'exited', reason: 'observed'},
    receipt_available: true, native_status: nativeStatus, native_id: 'fixture-run', loop: {final_iteration: 3, attempted_iterations: attempted}});
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    assert.equal(request.headers().authorization, 'Bearer ' + metadata.token);
    const reply = json => route.fulfill({status: 200, json});
    if (request.method() === 'POST') {
      assert.equal(url.pathname, `/api/operations/${running}/loop-stop`, 'Stop is posted only for the running loop');
      assert.equal(request.headers()['content-type'], 'application/json');
      assert.equal(request.postData(), '{}');
      posts.push(url.pathname);
      await new Promise(done => setTimeout(done, 400)); // Keep the request pending across a second click.
      return reply({operation_id: running, outcome: 'requested'});
    }
    assert.equal(request.method(), 'GET');
    if (url.pathname === '/api/choices' || url.pathname === '/api/native-chain/choices' || url.pathname === '/api/recorded-examples') return reply([]);
    if (url.pathname.endsWith('/tokens')) return reply({reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []});
    if (url.pathname.endsWith('/log')) return reply({text: '', next_offset: 0, observed_size: 0, truncated: false, missing: false});
    if (url.pathname.endsWith('/graph-results')) return reply({operation_id: url.pathname.split('/')[3], available: false, bodies: []});
    if (url.pathname === `/api/operations/${running}`) return reply(runningTerminal ? terminal(running, 'stopped', 1) : status(running, {loop: {final_iteration: 3, attempted_iterations: null}}));
    if (url.pathname === `/api/operations/${fixed}`) return reply(status(fixed, {}));
    if (url.pathname === `/api/operations/${finished}`) return reply(terminal(finished, 'completed', 3));
    if (url.pathname === `/api/operations/${thresholdStop}`) {
      const value = terminal(thresholdStop, 'completed', 3);
      value.loop = {final_iteration: 5, attempted_iterations: 3, stop_reason: {kind: 'metric_threshold', condition_index: 0, iteration: 3,
        metric_id: 'accuracy', direction: 'higher', threshold: 0.85, incumbent: 0.9, incumbent_iteration: 3}};
      return reply(value);
    }
    if (url.pathname === `/api/operations/${patienceStop}`) {
      const value = terminal(patienceStop, 'completed', 4);
      value.loop = {final_iteration: 6, attempted_iterations: 4, stop_reason: {kind: 'no_improvement', condition_index: 1, iteration: 4,
        k: 2, non_improving_bodies: 2, last_improvement_iteration: 2, incumbent: -1.25}};
      return reply(value);
    }
    throw new Error('unexpected path ' + url.pathname);
  });
  await page.goto(`${metadata.origin}/#slow-control/${running}`);
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  const state = page.locator('#loop-state'), stop = page.locator('#loop-stop');
  await state.filter({hasText: 'Research loop: up to 3 bodies.'}).waitFor();
  await stop.waitFor({state: 'visible'});
  assert.ok(!(await state.textContent()).includes('Stop requested'));

  await stop.dblclick();
  await state.filter({hasText: 'Stop requested'}).waitFor();
  assert.equal(posts.length, 1, 'a double click issues exactly one Stop request');
  assert.ok(await stop.isHidden(), 'no second Stop control after acknowledgement');
  await page.waitForTimeout(2500); // At least one further poll still reads an active operation.
  const requested = await state.textContent();
  assert.match(requested, /Not yet stopped\./);
  assert.ok(!/stopped at/i.test(requested), 'acknowledgement alone never reads as stopped');
  await page.screenshot({path: resolve(tmpdir(), 'siderius-loop-stop-requested.png'), fullPage: true});

  runningTerminal = true;
  await state.filter({hasText: 'Research loop stopped at a completed body boundary after 1 of 3 bodies.'}).waitFor();
  assert.ok(await stop.isHidden());
  assert.equal(posts.length, 1);

  await page.evaluate(id => { location.hash = 'slow-control/' + id; }, fixed);
  await page.locator('#monitor-status').filter({hasText: 'State: active'}).waitFor();
  await page.locator('#operation-observed').filter({hasText: fixed}).waitFor();
  assert.ok(await page.locator('#loop-control').isHidden(), 'a candidate without a declared loop has no loop control');

  await page.evaluate(id => { location.hash = 'slow-control/' + id; }, finished);
  await state.filter({hasText: 'Research loop finished after 3 of 3 bodies.'}).waitFor();
  assert.ok(await stop.isHidden(), 'a finished loop has no Stop');
  assert.ok(!(await state.textContent()).includes('Stop'), 'Stop state does not leak across operations');
  assert.equal(posts.length, 1);
  await page.screenshot({path: resolve(tmpdir(), 'siderius-loop-finished.png'), fullPage: true});

  // A declared stop condition completed the loop early: the receipt's reason reads in plain words.
  await page.evaluate(id => { location.hash = 'slow-control/' + id; }, thresholdStop);
  await state.filter({hasText: 'Research loop stopped early after body 3 of up to 5: accuracy reached 0.9 (threshold 0.85, higher is better; best at body 3).'}).waitFor();
  assert.ok(await stop.isHidden());
  await page.evaluate(id => { location.hash = 'slow-control/' + id; }, patienceStop);
  await state.filter({hasText: 'Research loop stopped early after body 4 of up to 6: no improvement for 2 bodies (condition: 2 bodies; best -1.25 at body 2).'}).waitFor();
  assert.ok(!(await state.textContent()).includes('finished after'), 'an early stop never reads as reaching the limit');
  await page.screenshot({path: resolve(tmpdir(), 'siderius-loop-stop-reason.png'), fullPage: true});
  assert.equal(posts.length, 1);
  assert.deepEqual(faults, []);
  console.log('PASS: Stop shows only for a running authored loop, posts once, reads "Stop requested" until the receipt says stopped; a receipt stop_reason reads in plain words.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM'); lines.close();
}
