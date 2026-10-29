/** Monitor witnesses over a stubbed API (red-team report 4; no provider/GPU/native effects):
 * M-2 one plain outcome sentence (raw enums only in developer facts), M-3 typed
 * unknown_operation reads as "no operation with this ID" and stops polling, M-5 a
 * finished operation is read once and then left alone, M-6 ANSI codes are stripped from
 * the displayed log, M-4 list entries carry name plus local time and refresh while one
 * is running, SEC-1 the log carries a not-redacted notice.
 * Required: EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = ''; server.stderr.on('data', chunk => {errors += chunk;});
const lines = createInterface({input: server.stdout});
const rejected = '56565656-5656-4656-8656-565656565656';
const running = '78787878-7878-4878-8878-787878787878';
const unknown = '9a9a9a9a-9a9a-4a9a-8a9a-9a9a9a9a9a9a';
const crashed = 'bcbcbcbc-bcbc-4cbc-8cbc-bcbcbcbcbcbc';
const paused = 'dededede-dede-4ede-8ede-dededededede';
const delay = ms => new Promise(done => setTimeout(done, ms));
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
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), faults = [];
  page.on('pageerror', error => faults.push(error.message));
  const reads = {}, lists = [];
  let runningState = 'active';
  const base = (id, fields) => ({operation_id: id, kind: 'candidate', request_digest: 'a'.repeat(64), observed_at: '2026-10-28T16:15:41.432Z',
    state: 'completed', process: {status: 'exited', reason: 'observed'}, finishing: false, receipt_available: true, native_status: 'rejected',
    native_id: 'fixture-run', validation_passed: false, reason: 'native_terminal', ...fields});
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    assert.equal(request.method(), 'GET', 'Monitor never mutates');
    const reply = (json, status = 200) => route.fulfill({status, json});
    if (url.pathname.startsWith('/api/editor/')) return reply({error: {message: 'Fixture project unavailable'}}, 409);
    if (url.pathname === '/api/choices') return reply({operations_store_id: '0123456789abcdef0123456789abcdef', tasks: []});
    // One configured task: selected automatically, so Workflow and Run stay open.
    // The selected task's experiment setups (Workflow and Run read them): none.
    if (url.pathname.endsWith('/setups') && url.pathname.startsWith('/api/tasks/')) return reply({setups: []});
    if (url.pathname === '/api/tasks') return reply({tasks: [{task_id: 'synthetic', label: 'Synthetic task', revision: null}]});
    if (['/api/native-chain/choices', '/api/recorded-examples'].includes(url.pathname)) return reply([]);
    if (url.pathname === '/api/operations') {
      lists.push(Date.now());
      return reply({operations: [
        {operation_id: running, kind: 'candidate', run_name: 'capture-20261028-0915', project_id: 'capture', admitted_at: '2026-10-28T16:15:00+00:00', state: runningState, native_status: runningState === 'completed' ? 'accepted' : null},
        {operation_id: rejected, kind: 'candidate', run_name: 'capture-20261028-0901', project_id: 'capture', admitted_at: '2026-10-28T16:01:00+00:00', state: 'completed', native_status: 'rejected'},
      ], unreadable: 1, examined: 3, incomplete: false});
    }
    const id = url.pathname.split('/')[3];
    reads[id] = (reads[id] || 0) + 1;
    if (url.pathname.endsWith('/tokens')) return reply({reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []});
    if (url.pathname.endsWith('/graph-results')) return reply({operation_id: id, available: false, bodies: []});
    if (url.pathname.endsWith('/log')) {
      const offset = Number(url.searchParams.get('offset'));
      if (id === crashed) {
        const text = 'Traceback (most recent call last):\n  File "worker.py", line 1\nexecute_tools.health_checks.launch_policy.FormalLaunchPolicyError: a formal launch must declare --healthgate_mode\n';
        return reply({text: offset === 0 ? text : '', next_offset: text.length, observed_size: text.length, truncated: false, missing: false});
      }
      return reply({text: offset === 0 ? '\u001b[31mred error\u001b[0m and <b>markup</b>\n' : '', next_offset: 42, observed_size: 42, truncated: false, missing: false});
    }
    if (id === unknown) return reply({error: {code: 'unknown_operation', message: 'this operation store has no operation with this ID'}}, 404);
    if (id === rejected) return reply(base(rejected, {}));
    if (id === crashed) return reply(base(crashed, {native_status: 'failed', validation_passed: null, loop: {final_iteration: 1, attempted_iterations: 1}}));
    if (id === paused) return reply(base(paused, {native_status: 'paused', validation_passed: null, loop: {final_iteration: 3, attempted_iterations: 1}}));
    if (id === running) return reply(base(running, {state: 'active', process: {status: 'alive', reason: 'observed'}, receipt_available: false, native_status: null, validation_passed: null}));
    throw new Error('unexpected path ' + url.pathname);
  });

  await page.goto(metadata.origin + '/#monitor');
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  // M-4: name + local time tells repeated runs apart; ISO on hover; next step for unverified records.
  const items = page.locator('#operations-list li');
  await items.nth(1).waitFor();
  const first = items.nth(0).locator('a');
  assert.match(await first.textContent(), /^capture · capture-20261028-0915 · /);
  assert.ok(!(await first.textContent()).includes('2026-10-28T'), 'List time is local, not ISO');
  assert.match(await first.getAttribute('title'), /admitted 2026-10-28T16:15:00/);
  assert.match(await items.nth(1).textContent(), /Finished: validation rejected the candidate\./);
  assert.match(await items.nth(0).textContent(), /Run in progress\./);
  assert.equal(await page.locator('#operations-unreadable').isVisible(), true);
  // The list refreshes by itself while a listed operation is still running.
  const before = lists.length;
  runningState = 'completed';
  const deadline = Date.now() + 13000;
  while (lists.length === before && Date.now() < deadline) await delay(200);
  assert.ok(lists.length > before, 'List refreshed without a click');
  await items.nth(0).filter({hasText: 'passed validation'}).waitFor();

  // M-2: one plain outcome sentence; raw enums only in developer facts. SEC-1 notice.
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, rejected);
  await page.locator('#monitor-status').filter({hasText: 'Finished: validation rejected the candidate.'}).waitFor();
  assert.ok(!(await page.locator('#monitor-status').textContent()).includes('Native'), 'No raw enum in the beginner sentence');
  assert.match(await page.locator('#operation-facts').textContent(), /Statecompleted.*Native statusrejected/);
  assert.match(await page.locator('#operation-observed').textContent(), /^Final status · observed /);
  assert.match(await page.locator('#operation-observed').getAttribute('title'), /2026-10-28T16:15:41\.432Z/);
  assert.match(await page.locator('#log-notice').textContent(), /not redacted/);
  // M-6: ANSI escape sequences are not displayed; markup stays text.
  await page.getByText('Activity and logs', {exact: true}).click().catch(() => {});
  await page.locator('#log').filter({hasText: 'red error'}).waitFor({state: 'attached'});
  const log = await page.locator('#log').textContent();
  assert.ok(!log.includes('\u001b') && !log.includes('[31m'), 'ANSI codes stripped: ' + JSON.stringify(log));
  assert.ok(log.includes('<b>markup</b>'));
  // M-5: after the final read no further status, token or log request for this operation.
  const settled = reads[rejected];
  await delay(4500);
  assert.equal(reads[rejected], settled, 'Polling stops after a terminal state');

  // L-2: a failed run says so plainly and names its cause from the log.
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, crashed);
  await page.locator('#monitor-status').filter({hasText: 'Failed: the run stopped with an error before finishing.'}).waitFor();
  await page.locator('#monitor-cause').filter({hasText: 'Cause (from the log): execute_tools.health_checks.launch_policy.FormalLaunchPolicyError: a formal launch must declare'}).waitFor();
  assert.match(await page.locator('#loop-state').textContent(), /after 1 of 1 body\./, 'Singular body');
  // N2: a long cause (the launch guard's GPU refusal) is cut at a word boundary with an ellipsis.
  const refusal = 'core.runtime_control.launch_guard.LaunchGuardFailure: SIDERIUS real training needs an NVIDIA GPU with CUDA: NVIDIA device nodes were passed, but /sys is not mounted here, so CUDA cannot start (CUDA error 304). The console run sandbox mounts /sys read-only by itself for a task that lists a /dev/nvidia<N> device node; check that the task lists one, then run check --gpu (see GPU runs in the console README) (quickstart: not measurable — no CUDA device is visible: NVIDIA device nodes are present but /sys is not mounted).';
  const shown = await page.evaluate(text => window.operationOutcome.cause('Traceback\n' + text + '\n'), refusal);
  assert.ok(shown.length <= 300 && shown.endsWith('…'), shown);
  const kept = shown.slice(0, -1);
  assert.ok(refusal.startsWith(kept) && refusal[kept.length] === ' ', `cut inside a word: ${JSON.stringify(shown)}`);
  assert.match(shown, /CUDA error 304/);

  // A paused loop is settled for this read but may be resumed: never "Final status".
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, paused);
  await page.locator('#monitor-status').filter({hasText: 'Paused at a completed body boundary.'}).waitFor();
  await page.locator('#operation-observed').filter({hasText: /^Current status · observed /}).waitFor();
  assert.ok(!(await page.locator('#operation-observed').textContent()).includes('Final status'), 'A paused loop does not read as final');

  // M-3: a typed unknown_operation says so and stops polling.
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, unknown);
  await page.locator('#monitor-status').filter({hasText: 'This console has no operation with this ID'}).waitFor();
  const unknownReads = reads[unknown];
  await delay(4500);
  assert.ok(reads[unknown] <= unknownReads + 1, `No polling of an unknown operation (${unknownReads} -> ${reads[unknown]})`);
  assert.ok(!(await page.locator('#monitor-status').textContent()).includes('stale'));
  assert.deepEqual(faults, []);
  console.log('PASS: plain outcome sentence, unknown operation stops polling, terminal read once, ANSI stripped, list name+time and self-refresh, log notice');
} finally {
  await browser?.close();
  server.kill();
}
