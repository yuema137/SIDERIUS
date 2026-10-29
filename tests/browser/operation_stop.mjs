/** "Stop run" on Monitor: server-owned `cancellable`, confirmation, one cancel POST, honest "Stopping" until the cancelled receipt, "Last observed" while unreachable. Stubbed API; no provider/GPU/native effects. */
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
  let cancelRecorded = false, runningTerminal = false, loopCancelled = false, unreachable = false;
  // `cancellable` is the server's verdict; the page must not derive it from kind or state.
  const status = (operation, fields) => ({operation_id: operation, kind: 'candidate', request_digest: 'a'.repeat(64), observed_at: 'fixture',
    state: 'active', process: {status: 'alive', reason: 'observed'}, finishing: false, receipt_available: false, native_status: null,
    native_id: null, validation_passed: null, reason: 'fixture', cancellable: true, ...fields});
  const cancelled = (operation, fields) => status(operation, {state: 'completed', process: {status: 'exited', reason: 'observed'},
    receipt_available: true, native_status: 'cancelled', native_id: 'fixture-run', cancel_requested: true, cancellable: false, ...fields});
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
    if (unreachable && url.pathname.startsWith('/api/operations/')) return route.abort('connectionrefused');
    if (url.pathname === '/api/choices' || url.pathname === '/api/native-chain/choices' || url.pathname === '/api/recorded-examples') return reply([]);
    // One configured task: selected automatically, so Workflow and Run stay open.
    if (url.pathname === '/api/tasks') return reply({tasks: [{task_id: 'synthetic', label: 'Synthetic task', revision: null}]});
    if (url.pathname === '/api/operations') {
      // The Slow-control operations list (operations-list.js) polls this; no assertion below reads it.
      assert.equal(url.searchParams.get('limit'), '50');
      return reply({operations: [
        {operation_id: running, kind: 'candidate', run_name: 'candidate', project_id: 'five_node', admitted_at: '2026-10-28T10:00:00+00:00',
          state: runningTerminal ? 'completed' : 'active', native_status: runningTerminal ? 'cancelled' : null},
        {operation_id: finished, kind: 'candidate', run_name: 'candidate', project_id: 'five_node', admitted_at: '2026-10-27T09:00:00+00:00',
          state: 'completed', native_status: 'accepted'},
      ], unreadable: 0, examined: 2, incomplete: false});
    }
    if (url.pathname.endsWith('/tokens')) return reply({reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []});
    if (url.pathname.endsWith('/log')) return reply({text: '', next_offset: 0, observed_size: 0, truncated: false, missing: false});
    if (url.pathname.endsWith('/graph-results')) return reply({operation_id: url.pathname.split('/')[3], available: false, bodies: []});
    if (url.pathname === `/api/operations/${running}`) return reply(runningTerminal ? cancelled(running, {}) : status(running, cancelRecorded ? {cancel_requested: true, cancellable: false} : {}));
    if (url.pathname === `/api/operations/${loop}`) {
      const declared = {loop: {final_iteration: 3, attempted_iterations: null}};
      return reply(loopCancelled ? cancelled(loop, declared) : status(loop, declared));
    }
    if (url.pathname === `/api/operations/${finished}`) return reply(status(finished, {state: 'completed', process: {status: 'exited', reason: 'observed'}, receipt_available: true, native_status: 'accepted', cancellable: false}));
    // An active candidate the server does not offer (e.g. an unverified record): no button despite kind and state.
    if (url.pathname === `/api/operations/${preparing}`) return reply(status(preparing, {cancellable: false}));
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
  assert.equal(dialogs.length, 1);
  for (const phrase of ['cannot be undone or resumed', 'produces no candidate result', 'Files written so far stay in the run folder', 'may still be billed', 'token report']) {
    assert.ok(dialogs[0].includes(phrase), `confirmation states: ${phrase}`);
  }
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
  // A failed poll keeps the last line but marks it as an old observation. Monitor stops
  // polling an operation once it is settled (M-4), so this is shown while it still runs.
  unreachable = true;
  await said.filter({hasText: 'Last observed: Stopping the run…'}).waitFor();
  await page.locator('#monitor-status').filter({hasText: 'Last displayed facts are retained'}).waitFor();
  unreachable = false;
  await said.filter({hasText: /^Stopping the run…/}).waitFor();
  await page.screenshot({path: resolve(tmpdir(), 'siderius-operation-stopping.png'), fullPage: true});
  runningTerminal = true;
  await said.filter({hasText: 'Run stopped. Files written so far stay in the run folder; no candidate result is produced.'}).waitFor();
  await page.locator('#monitor-status').filter({hasText: 'Stopped on request before finishing'}).waitFor();
  assert.ok(await stop.isHidden());
  await page.screenshot({path: resolve(tmpdir(), 'siderius-operation-stopped.png'), fullPage: true});

  // Operations the server marks not cancellable offer no Stop run; state does not leak across operations.
  for (const id of [finished, preparing]) {
    await page.evaluate(value => { location.hash = 'slow-control/' + value; }, id);
    await page.locator(`#operation-observed[title*="${id}"]`).waitFor(); // M-2: the UUID is in the observed line's title
    await page.locator('#monitor-status').filter({hasText: /in progress\.|^Finished/}).waitFor();
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
  await page.locator('#loop-state').filter({hasText: 'Research loop stopped by you before it finished. Files written so far stay in the run folder; this run cannot be resumed.'}).waitFor();
  assert.ok(await page.locator('#loop-stop').isHidden() && await page.locator('#loop-pause').isHidden() && await page.locator('#loop-resume-group').isHidden());
  assert.deepEqual(posts, [`/api/operations/${running}/cancel`, `/api/operations/${loop}/cancel`]);
  assert.deepEqual(faults, []);
  console.log('PASS: Stop run follows the server cancellable flag, states its consequences before confirming, posts once, reads "Stopping" until the cancelled receipt, then says what is kept; a failed poll prefixes "Last observed:"; a cancelled loop hides boundary controls and reads as not resumable.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM'); lines.close();
}
