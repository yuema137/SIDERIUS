/** Host-ledger outcomes and controls over a stubbed API (B3-4c UI; no provider/GPU effects):
 * a queued run reads as queued in the list and Monitor and keeps being refreshed; a run
 * cancelled while queued reads as "cancelled before start", never as a failure (#1074);
 * the native-chain card states native chains are serial-only; without a host ledger the
 * Run lane hides the host resources panel and says why; with one, the panel starts empty
 * and refuses an incomplete declaration in the browser.
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
const queued = '13131313-1313-4313-8313-131313131313';
const cancelled = '24242424-2424-4424-8424-242424242424';
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
  const lists = [];
  let hostLedger = false;
  const base = (id, fields) => ({operation_id: id, kind: 'candidate', request_digest: 'a'.repeat(64), observed_at: '2026-10-28T16:15:41.432Z',
    process: {status: 'alive', reason: 'observed'}, finishing: false, receipt_available: false, native_status: null,
    native_id: null, validation_passed: null, ...fields});
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    const reply = (json, status = 200) => route.fulfill({status, json});
    if (url.pathname.startsWith('/api/editor/')) return reply({error: {message: 'Fixture project unavailable'}}, 409);
    if (url.pathname.startsWith('/api/settings')) return reply({error: {message: 'Fixture settings unavailable'}}, 409);
    if (url.pathname === '/api/choices') return reply({operations_store_id: '0123456789abcdef0123456789abcdef', tasks: [], ...(hostLedger ? {host_ledger: true} : {})});
    // One configured task: selected automatically, so Workflow and Run stay open.
    if (url.pathname === '/api/tasks') return reply({tasks: [{task_id: 'synthetic', label: 'Synthetic task', revision: null}]});
    if (['/api/native-chain/choices', '/api/recorded-examples'].includes(url.pathname)) return reply([]);
    if (url.pathname === '/api/operations') {
      lists.push(Date.now());
      return reply({operations: [
        {operation_id: queued, kind: 'candidate', run_name: 'capture-queued', project_id: 'capture', admitted_at: '2026-10-28T16:15:00+00:00', state: 'queued', native_status: null},
        {operation_id: cancelled, kind: 'candidate', run_name: 'capture-cancelled', project_id: 'capture', admitted_at: '2026-10-28T16:01:00+00:00', state: 'operation_failed', native_status: null, reason: 'cancelled_while_queued'},
      ], unreadable: 0, examined: 2, incomplete: false});
    }
    const id = url.pathname.split('/')[3];
    if (url.pathname.endsWith('/tokens')) return reply({reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []});
    if (url.pathname.endsWith('/graph-results')) return reply({operation_id: id, available: false, bodies: []});
    if (url.pathname.endsWith('/log')) return reply({text: '', next_offset: 0, observed_size: 0, truncated: false, missing: true});
    if (id === queued) return reply(base(queued, {state: 'queued', reason: 'host_queued', cancellable: true}));
    if (id === cancelled) return reply(base(cancelled, {state: 'operation_failed', process: {status: 'exited', reason: 'observed'}, cancel_requested: true, reason: 'cancelled_while_queued'}));
    throw new Error('unexpected path ' + url.pathname);
  });

  await page.goto(metadata.origin + '/#monitor');
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  const items = page.locator('#operations-list li');
  await items.nth(1).waitFor();
  assert.match(await items.nth(0).textContent(), /Run is queued: it starts by itself/);
  assert.match(await items.nth(1).textContent(), /Run cancelled before start: it never ran/);
  assert.ok(!/failed/i.test(await items.nth(1).textContent()), 'A cancelled queued run is not a failure');
  // A queued row is unfinished: the list keeps refreshing by itself.
  const before = lists.length, deadline = Date.now() + 13000;
  while (lists.length === before && Date.now() < deadline) await new Promise(done => setTimeout(done, 200));
  assert.ok(lists.length > before, 'List refreshes while a run is queued');

  await page.evaluate(id => { location.hash = 'monitor/' + id; }, queued);
  await page.locator('#monitor-status').filter({hasText: 'Run is queued'}).waitFor();
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, cancelled);
  await page.locator('#monitor-status').filter({hasText: 'Run cancelled before start'}).waitFor();
  assert.equal(await page.locator('#monitor-cause').isVisible().catch(() => false), false, 'No failure cause for a cancelled queued run');

  // Native chains say they are serial-only rather than silently ignoring the ledger.
  assert.match(await page.locator('#native-chain-serial').textContent(), /never reserved in the host ledger/);

  // The panel lives on the Run view; visibility below is only meaningful there.
  await page.locator('nav a[href="#run"]').click();
  // Without a host ledger the panel is hidden and nothing is sent; the reason is shown.
  await page.evaluate(() => window.consoleSession.choices());
  await page.locator('#scheduling-unavailable').waitFor({state: 'visible'});
  assert.match(await page.locator('#scheduling-unavailable').textContent(), /host ledger that the operator configures/);
  assert.equal(await page.locator('#scheduling').isHidden(), true, 'No ledger: no resources panel');
  assert.deepEqual(await page.evaluate(() => window.runScheduling.read()), {value: {}});
  // With a ledger (the stub's choices now declare one) the panel appears, starts empty
  // and validates in the browser.
  hostLedger = true;
  await page.evaluate(() => window.consoleSession.choices());
  await page.locator('#scheduling').waitFor({state: 'visible'});
  assert.equal(await page.locator('#scheduling-unavailable').isHidden(), true);
  await page.evaluate(() => { document.getElementById('scheduling').open = true; });
  await page.locator('#scheduling-declare').waitFor({state: 'visible'});
  for (const id of ['scheduling-vram', 'scheduling-memory', 'scheduling-cpus']) {
    assert.equal(await page.locator('#' + id).inputValue(), '', `${id} is not prefilled`);
  }
  assert.equal(await page.locator('#scheduling-gpu').inputValue(), '');
  assert.equal(await page.locator('#scheduling-declare').isChecked(), false);
  assert.equal(await page.locator('#scheduling-parallel tbody tr').count(), 6);
  const read = () => page.evaluate(() => window.runScheduling.read());
  assert.deepEqual(await read(), {value: {}}, 'An empty panel sends nothing');
  await page.locator('#scheduling-declare').check();
  assert.match((await read()).error, /GPU/);
  await page.locator('#scheduling-gpu').selectOption('1');
  await page.locator('#scheduling-memory').fill('8'); await page.locator('#scheduling-cpus').fill('2');
  assert.match((await read()).error, /GPU memory/);
  await page.locator('#scheduling-vram').fill('3');
  await page.locator('#scheduling-validation-on').check();
  await page.locator('#scheduling-validation-memory').fill('1'); await page.locator('#scheduling-validation-cpus').fill('1');
  assert.deepEqual(await read(), {value: {
    resources: {gpu_count: 1, host_memory_gib: 8, cpu_slots: 2, time_budgeted: false, vram_gib: 3, vram_source: 'configured_cap'},
    parallel: {capabilities: {validation: {gpu: false, host_memory_gib: 1, cpu_slots: 1}}},
  }});
  assert.match(await page.evaluate(selection => window.runScheduling.describe(selection), (await read()).value),
    /Reserves one GPU with 3 GiB, 8 GiB host memory and 2 CPU slots\. Runs these node kinds in parallel: validation\./);
  assert.deepEqual(faults, []);
  console.log('PASS: queued and cancelled-before-start outcomes, list refresh, native serial note, ledger-gated empty validated scheduling panel');
} finally {
  await browser?.close();
  server.kill();
}
