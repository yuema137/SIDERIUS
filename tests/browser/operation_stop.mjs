/** "Stop run" on Monitor: confirmation, one cancel POST, honest "Stopping" until the cancelled receipt. Stubbed API; no provider/GPU/native effects. */
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
const loop = '44444444-4444-4444-8444-444444444444';
const finished = '55555555-5555-4555-8555-555555555555';
const preparing = '66666666-6666-4666-8666-666666666666';
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
  const page = await browser.newPage(), posts = [], faults = [], dialogs = [];
  page.on('pageerror', error => faults.push(error.message));
  let accept = false;
  page.on('dialog', async dialog => { dialogs.push(dialog.message()); await (accept ? dialog.accept() : dialog.dismiss()); });
  let cancelRecorded = false, runningTerminal = false, loopCancelled = false;
  const status = (operation, fields) => ({operation_id: operation, kind: 'candidate', request_digest: 'a'.repeat(64), observed_at: 'fixture',
    state: 'active', process: {status: 'alive', reason: 'observed'}, finishing: false, receipt_available: false, native_status: null,
    native_id: null, validation_passed: null, reason: 'fixture', ...fields});
  const cancelled = (operation, fields) => status(operation, {state: 'completed', process: {status: 'exited', reason: 'observed'},
    receipt_available: true, native_status: 'cancelled', native_id: 'fixture-run', cancel_requested: true, ...fields});
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    assert.equal(request.headers().authorization, 'Bearer ' + metadata.token);
    const reply = json => route.fulfill({status: 200, json});
    if (request.method() === 'POST') {
      assert.equal(request.headers()['content-type'], 'application/json');
      assert.equal(request.postData(), '{}');
      await new Promise(done => setTimeout(done, 400)); // Keep the request pending across a second click.
      assert.ok([running, loop].some(id => url.pathname === `/api/operations/${id}/cancel`), 'cancel is posted only for a running candidate');
      posts.push(url.pathname);
      cancelRecorded = true;
      return reply({operation_id: url.pathname.split('/')[3], outcome: 'requested'});
    }
    assert.equal(request.method(), 'GET');
    if (url.pathname === '/api/choices' || url.pathname === '/api/native-chain/choices' || url.pathname === '/api/recorded-examples') return reply([]);
    if (url.pathname.endsWith('/tokens')) return reply({reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []});
    if (url.pathname.endsWith('/log')) return reply({text: '', next_offset: 0, observed_size: 0, truncated: false, missing: false});
    if (url.pathname.endsWith('/graph-results')) return reply({operation_id: url.pathname.split('/')[3], available: false, bodies: []});
    if (url.pathname === `/api/operations/${running}`) return reply(runningTerminal ? cancelled(running, {}) : status(running, cancelRecorded ? {cancel_requested: true} : {}));
    if (url.pathname === `/api/operations/${loop}`) {
      const declared = {loop: {final_iteration: 3, attempted_iterations: null}};
      return reply(loopCancelled ? cancelled(loop, declared) : status(loop, declared));
    }
    if (url.pathname === `/api/operations/${finished}`) return reply(status(finished, {state: 'completed', process: {status: 'exited', reason: 'observed'}, receipt_available: true, native_status: 'accepted'}));
    if (url.pathname === `/api/operations/${preparing}`) return reply(status(preparing, {kind: 'prepare'}));
    throw new Error('unexpected path ' + url.pathname);
  });
  await page.goto(`${metadata.origin}/#slow-control/${running}`);
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  const stop = page.locator('#operation-stop-button'), said = page.locator('#operation-stop-status');
  await stop.waitFor({state: 'visible'});
  assert.equal(await stop.textContent(), 'Stop run');

  // Declining the confirmation sends nothing.
  await stop.click();
  assert.deepEqual(dialogs, ['Stop this run? Work done so far is kept.']);
  await page.waitForTimeout(500);
  assert.equal(posts.length, 0, 'a declined confirmation posts no cancel');
  assert.ok(await stop.isVisible());

  // Accepting posts exactly once, even on a double click, and reads "Stopping" (not stopped) until the receipt.
  accept = true;
  await stop.dblclick();
  await said.filter({hasText: 'Stopping the run…'}).waitFor();
  assert.equal(posts.length, 1, 'a double click issues exactly one cancel request');
  assert.ok(await stop.isHidden(), 'no second Stop run control after acknowledgement');
  await page.waitForTimeout(2500); // At least one further poll still reads an active operation.
  assert.equal(await said.textContent(), 'Stopping the run…');
  await page.screenshot({path: resolve(tmpdir(), 'siderius-operation-stopping.png'), fullPage: true});
  runningTerminal = true;
  await said.filter({hasText: 'Run stopped. Work done so far is kept.'}).waitFor();
  await page.locator('#monitor-status').filter({hasText: 'Native: cancelled'}).waitFor();
  assert.ok(await stop.isHidden());
  await page.screenshot({path: resolve(tmpdir(), 'siderius-operation-stopped.png'), fullPage: true});

  // Terminal and non-candidate operations offer no Stop run; state does not leak across operations.
  for (const id of [finished, preparing]) {
    await page.evaluate(value => { location.hash = 'slow-control/' + value; }, id);
    await page.locator('#operation-observed').filter({hasText: id}).waitFor();
    await page.locator('#monitor-status').filter({hasText: 'State:'}).waitFor();
    await page.waitForTimeout(300);
    assert.ok(await stop.isHidden(), `no Stop run for ${id}`);
    assert.equal(await said.textContent(), '');
  }

  // A running loop: Stop run hides the boundary Stop/Pause controls; the cancelled loop reads as not resumable.
  await page.evaluate(value => { location.hash = 'slow-control/' + value; }, loop);
  await page.locator('#loop-state').filter({hasText: 'Research loop: up to 3 bodies.'}).waitFor();
  await stop.waitFor({state: 'visible'});
  assert.ok(await page.locator('#loop-pause').isVisible());
  await stop.click();
  await said.filter({hasText: 'Stopping the run…'}).waitFor();
  assert.equal(posts.length, 2);
  loopCancelled = true;
  await page.locator('#loop-state').filter({hasText: 'Research loop stopped by you before it finished. Work done so far is kept; this run cannot be resumed.'}).waitFor();
  assert.ok(await page.locator('#loop-stop').isHidden() && await page.locator('#loop-pause').isHidden() && await page.locator('#loop-resume-group').isHidden());
  assert.deepEqual(posts, [`/api/operations/${running}/cancel`, `/api/operations/${loop}/cancel`]);
  assert.deepEqual(faults, []);
  console.log('PASS: Stop run asks for confirmation, posts once, reads "Stopping" until the cancelled receipt, then "Run stopped"; terminal and prepare operations offer no Stop run; a cancelled loop hides boundary controls and reads as not resumable.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM'); lines.close();
}
