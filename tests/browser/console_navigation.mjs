/** Persistent-shell regression witnesses. Synthetic GET observations only;
 * real temporary static/API fixture, no provider/GPU/native execution.
 * Requires EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE.
 */
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
let browser;
const operation = '22222222-2222-4222-8222-222222222222', remembered = '33333333-3333-4333-8333-333333333333';
async function waitUntil(predicate) {
  const deadline = Date.now() + 15000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error('Condition timed out'); await new Promise(resolve => setTimeout(resolve, 50)); }
}
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error('Server startup timeout')), 15000);
    lines.once('line', line => {clearTimeout(timer); accept(JSON.parse(line));});
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Server ${code}: ${errors}`));});
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const context = await browser.newContext();
  await context.addInitScript(id => {
    localStorage.setItem('siderius.operation_id', id);
    window.pollTimers = 0; const interval = window.setInterval.bind(window);
    window.setInterval = (...args) => {window.pollTimers++; return interval(...args);};
  }, remembered);
  const page = await context.newPage(), faults = [], requests = [], offsets = [], logReads = [];
  page.on('pageerror', error => faults.push(error.message));
  let failEditor = true, unauthorized = false, unavailable = true;
  const synthetic = {task_id: 'synthetic', label: 'Synthetic task', revision: null};
  let tasks = [synthetic];
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    requests.push({path: url.pathname, method: request.method(), body: request.postData()});
    assert.equal(request.method(), 'GET', 'Navigation and reconnect must never mutate');
    assert.equal(request.headers().authorization, 'Bearer ' + metadata.token);
    assert.equal(request.postData(), null);
    const reply = (json, status = 200) => route.fulfill({status, json});
    if (unauthorized) return reply({error: {message: 'Fixture access expired'}}, 401);
    if (url.pathname.startsWith('/api/editor/')) {
      if (failEditor) return reply({error: {message: 'Fixture project unavailable'}}, 409);
      return route.continue();
    }
    if (url.pathname === '/api/choices') return reply({operations_store_id: '0123456789abcdef0123456789abcdef', tasks: []});
    // The selected task's experiment setups (Workflow and Run read them): none.
    if (url.pathname.endsWith('/setups') && url.pathname.startsWith('/api/tasks/')) return reply({setups: []});
    if (url.pathname === '/api/tasks') return reply({tasks});
    if (url.pathname.startsWith('/api/tasks/')) return reply({task_id: 'synthetic', label: 'Synthetic task', state: 'unavailable', data_root: '/fixture/data',
      run_policy: {preparation_timeout_seconds: 300, candidate_timeout_seconds: 3600, candidate_network: false, candidate_devices: [], candidate_environment_names: [], allowed_output_types: null},
      unavailable: {reason: 'sandbox_missing', hint: 'Fixture hint.'}});
    if (['/api/native-chain/choices', '/api/recorded-examples'].includes(url.pathname)) return reply([]);
    if (url.pathname === '/api/operations') return reply({operations: [], unreadable: 0, examined: 0, incomplete: false});
    assert.ok(url.pathname.startsWith('/api/operations/' + operation), 'URL UUID wins over remembered ID');
    if (unavailable) return reply({error: {message: 'Fixture unavailable operation'}}, 404);
    if (url.pathname.endsWith('/tokens')) return reply({reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []});
    if (url.pathname.endsWith('/log')) {
      const offset = Number(url.searchParams.get('offset')), kind = url.searchParams.get('kind');
      assert.ok(['native', 'operation'].includes(kind));
      offsets.push(offset); logReads.push({kind, offset});
      return reply({text: offset === 0 ? `${kind} stream\n` : '', next_offset: 73, observed_size: 73, truncated: false, missing: false});
    }
    return reply({operation_id: operation, kind: 'candidate', state: 'active', observed_at: 'fixture observation', process: {status: 'alive'}, receipt_available: false});
  });
  const connect = async () => {
    // Connected pages collapse the token form; reconnecting reopens it explicitly.
    if (await page.locator('#access-change').isVisible()) await page.locator('#access-change').click(); 
    await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
    await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
    assert.equal(await page.locator('#token').inputValue(), '');
  };
  // The former Slow control route is a bookmark-compatible alias: it is rewritten to Monitor.
  await page.goto(metadata.origin + '/#slow-control/' + operation);
  assert.equal(new URL(page.url()).hash, '#monitor/' + operation, 'Old #slow-control/<UUID> redirects to #monitor/<UUID>');
  assert.equal(await page.locator('nav a[aria-current="page"]').textContent(), 'Monitor');
  assert.equal(await page.locator('#operation-id').inputValue(), operation);
  assert.equal(await page.locator('#editor-source').isVisible(), false);
  assert.equal(requests.length, 0, 'Fresh routes do not request before Connect');
  await page.locator('nav a[href="#monitor"]').focus();
  for (let step = 0; step < 20; step++) {
    await page.keyboard.press('Tab');
    const focusedView = await page.evaluate(() => document.activeElement.closest('[data-view]')?.dataset.view);
    assert.ok(!focusedView || focusedView === 'monitor', 'Inactive views cannot receive keyboard focus');
  }
  await connect();
  assert.equal(requests.some(item => item.path.startsWith('/api/editor') || item.path === '/api/choices'), false);
  assert.match(await page.locator('#monitor-status').textContent(), /unavailable/);
  unavailable = false;
  await page.locator('#monitor-status').filter({hasText: 'Run in progress.'}).waitFor();
  await waitUntil(() => offsets.includes(73));
  await page.getByText('Activity and logs', {exact: true}).click();
  assert.equal(await page.locator('#log').textContent(), 'native stream\n');
  for (const kind of ['operation', 'native', 'operation']) {
    const before = logReads.length;
    await page.locator('#log-kind').selectOption(kind);
    await waitUntil(() => logReads.slice(before).some(item => item.kind === kind));
    const changedReads = logReads.slice(before).filter(item => item.kind === kind);
    assert.equal(changedReads[0]?.offset, 0, 'Changing log source must restart its byte cursor');
    await waitUntil(async () => (await page.locator('#log').textContent()) === `${kind} stream\n`);
    await waitUntil(() => logReads.slice(before).some(item => item.kind === kind && item.offset === 73));
  }
  const documentId = await page.evaluate(() => {window.documentId = 'same-shell'; return window.documentId;});
  const routeOffset = offsets.length;
  await page.locator('nav a[href="#home"]').click();
  await page.goBack(); // Return to explicit operation route without resetting its cursor.
  await page.locator('#view-monitor').waitFor();
  await page.goForward();
  await page.locator('#view-home').waitFor();
  // Task route; without a selected task Workflow and Run are closed (aria-disabled links,
  // and a typed route shows the "Choose a task" state instead of a task-less editor).
  tasks = []; await page.evaluate(() => window.consoleTask.reload());
  await waitUntil(async () => (await page.locator('nav a[href="#workflow"]').getAttribute('aria-disabled')) === 'true');
  for (const link of ['nav a[href="#workflow"]', 'nav a[href="#run"]', '#step-indicator a[href="#run"]']) {
    assert.equal(await page.locator(link).getAttribute('title'), 'Choose a task first', link);
  }
  await page.locator('nav a[href="#workflow"]').dispatchEvent('click');
  assert.equal(new URL(page.url()).hash, '#home', 'A disabled link does not navigate');
  await page.evaluate(() => {location.hash = 'run';});
  await page.locator('#task-required-state').waitFor();
  assert.equal(await page.locator('#task-required-heading').textContent(), 'Run');
  assert.equal(await page.locator('#view-run').isHidden(), true);
  await page.locator('#task-required-choose').click();
  assert.equal(new URL(page.url()).hash, '#task');
  assert.equal(await page.title(), 'SIDERIUS · Task');
  assert.equal(await page.locator('nav a[aria-current="page"]').textContent(), 'Task');
  assert.equal(await page.locator('#step-indicator li[data-step="task"] a').getAttribute('aria-current'), 'step');
  // Exactly one configured task is selected automatically and reopens Workflow and Run.
  tasks = [synthetic]; await page.evaluate(() => window.consoleTask.reload());
  await page.locator('.task-item[aria-pressed="true"]').waitFor();
  assert.equal(await page.locator('nav a[href="#workflow"]').getAttribute('aria-disabled'), null);
  await page.locator('#task-summary-state[data-state="unavailable"]').waitFor();
  await page.locator('nav a[href="#workflow"]').click();
  await page.locator('#setup-state').filter({hasText: 'Fixture project unavailable'}).waitFor();
  // Run preparation has its own route; an unavailable project keeps its handoff closed.
  await page.locator('nav a[href="#run"]').click();
  assert.equal(await page.title(), 'SIDERIUS · Run');
  assert.equal(await page.locator('#view-workflow').isHidden(), true);
  assert.equal(await page.locator('#view-run').isVisible(), true);
  assert.equal(await page.locator('#workflow-next-run').isDisabled(), true);
  await page.locator('nav a[href="#monitor"]').click();
  await waitUntil(() => offsets.length > routeOffset);
  assert.ok(offsets.slice(routeOffset).every(value => value === 73), 'Same UUID/back-forward must retain log cursor');
  assert.equal(await page.locator('#log-kind').inputValue(), 'operation');
  assert.equal(await page.locator('#log').textContent(), 'operation stream\n');
  assert.equal(await page.evaluate(() => window.documentId), documentId);
  // Monitor status poll, operation-list refresh, Run preparation and launch polls (each idle
  // unless its condition holds); no reachability probe since the server stayed reachable.
  assert.equal(await page.evaluate(() => window.pollTimers), 4);
  assert.equal(await page.locator('nav a[aria-current="page"]').textContent(), 'Monitor');
  assert.equal(await page.locator('#view-workflow').isHidden(), true);
  assert.equal(await page.evaluate(secret => document.body.textContent.includes(secret) || location.href.includes(secret) || JSON.stringify({...localStorage, ...sessionStorage}).includes(secret), metadata.token), false);
  // A later 401 disables effectful controls; reconnect preserves the selected ID.
  unauthorized = true;
  await page.locator('#access-status').filter({hasText: 'Connection unavailable'}).waitFor();
  assert.equal(await page.locator('#prepare-button').isDisabled(), true);
  unauthorized = false;
  await page.evaluate(id => {location.hash = 'monitor/' + id;}, operation);
  await connect();
  assert.equal(await page.locator('#operation-id').inputValue(), operation);
  assert.equal(await page.locator('#log-kind').inputValue(), 'operation');
  assert.equal(await page.locator('#log').textContent(), 'operation stream\n');
  await page.reload();
  assert.equal(await page.locator('#token').inputValue(), '');
  assert.equal(await page.locator('#monitor-button').isDisabled(), true);
  await page.goto(metadata.origin + '/#monitor/not-a-uuid');
  const beforeInvalid = requests.length;
  await page.locator('#route-status').filter({hasText: 'Invalid operation UUID'}).waitFor();
  await connect();
  assert.ok(requests.slice(beforeInvalid).every(item => !item.path.startsWith('/api/operations/')), 'Invalid UUID never reaches operation API');
  console.log('PASS: direct monitor, history, isolation, invalid route and reconnect witnesses');
  await page.locator('#operation-id').fill(operation);
  await page.locator('#monitor-button').click();
  await page.locator('#monitor-status').filter({hasText: 'Run in progress.'}).waitFor();
  assert.equal(new URL(page.url()).hash, '#monitor/' + operation, 'Valid form repairs an invalid route');
  // Initial editor project list in flight across reconnect: old 401 cannot revoke
  // the new session, and the new connection must load without another view change.
  await page.goto(metadata.origin + '/#workflow');
  await page.reload();
  await page.unroute('**/api/**');
  let releaseOld, oldSeen;
  const oldBlocked = new Promise(resolve => {releaseOld = resolve;});
  const seen = new Promise(resolve => {oldSeen = resolve;});
  let lists = 0;
  await page.route('**/api/editor/projects', async route => {
    lists++;
    if (lists === 1) {oldSeen(); await oldBlocked; return route.fulfill({status: 401, json: {error: {message: 'Old connection'}}});}
    await route.continue();
  });
  await connect(); await Promise.race([seen, new Promise((_, reject) => setTimeout(() => reject(new Error('Initial projects request not observed')), 15000))]);
  await connect();
  await page.locator('#editor-status').filter({hasText: 'Opened '}).waitFor();
  console.log('PASS: current project loaded while old response pending');
  releaseOld(); await page.waitForTimeout(100);
  assert.ok(lists >= 2);
  assert.match(await page.locator('#access-status').textContent(), /^Connected/);
  await page.locator('#editor-advanced > summary').click();
  const source = page.locator('#editor-source');
  await source.fill((await source.inputValue()) + '# retained reconnect draft\n');
  const draft = await source.inputValue();
  await connect();
  assert.equal(await source.inputValue(), draft, 'Reconnect never replaces pending source');
  // Browser-supported real-exit guard; internal routes did not invoke it.
  let guarded = false; page.once('dialog', async dialog => {guarded = dialog.type() === 'beforeunload'; await dialog.dismiss();});
  await page.reload({timeout: 3000}).catch(() => {});
  assert.equal(guarded, true);
  assert.equal(await source.inputValue(), draft);
  assert.deepEqual(faults, []);
  await context.close();
  console.log('PASS: independent direct operation connection, unavailable auth, UUID validation/precedence, one shell/poller, history cursor retention, project failure isolation, 401/reconnect, stale initial project load, pending draft and exit guard; Authorization-only credentials and GET-only navigation.');
} finally { if (browser) await browser.close(); server.kill('SIGTERM'); lines.close(); }
