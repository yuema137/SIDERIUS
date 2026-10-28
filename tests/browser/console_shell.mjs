/** Console shell witnesses over a stubbed API (no provider/GPU/native effects):
 * the connect card collapses to one line on every view, Monitor lists operations
 * and opens one in Status and logs, metric values are display-rounded with the exact
 * value kept, Home leads with three entry cards, and nav/content share one edge.
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
const loopRun = '12121212-1212-4212-8212-121212121212';
const prepared = '34343434-3434-4434-8434-343434343434';
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
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}, colorScheme: 'light'});
  await context.addInitScript(() => {
    window.pollTimers = 0; const interval = window.setInterval.bind(window);
    window.setInterval = (...args) => {window.pollTimers++; return interval(...args);};
  });
  const page = await context.newPage(), faults = [], requests = [];
  page.on('pageerror', error => faults.push(error.message));
  const headline = score => ({best_exp_id: 'exp-1', best_score: score, best_formal_score: score, best_valid_exp_id: 'exp-1', best_valid_score: score, best_valid_formal_score: score});
  let fault = null;
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    if (fault === 'down') return route.abort('connectionrefused');
    if (fault === 'text500') return route.fulfill({status: 500, contentType: 'text/plain', body: 'Internal Server Error'});
    requests.push({path: url.pathname, search: url.search, method: request.method()});
    assert.equal(request.method(), 'GET', 'The shell never mutates');
    assert.equal(request.headers().authorization, 'Bearer ' + metadata.token);
    const reply = (json, status = 200) => route.fulfill({status, json});
    if (url.pathname.startsWith('/api/editor/')) return reply({error: {message: 'Fixture project unavailable'}}, 409);
    if (url.pathname === '/api/choices') return reply({operations_store_id: '0123456789abcdef0123456789abcdef', tasks: []});
    if (['/api/native-chain/choices', '/api/recorded-examples'].includes(url.pathname)) return reply([]);
    if (url.pathname === '/api/operations') {
      assert.equal(url.searchParams.get('limit'), '50');
      return reply({operations: [
        {operation_id: loopRun, kind: 'candidate', run_name: 'candidate', project_id: 'five_node', admitted_at: '2026-10-27T15:00:00+00:00',
          state: 'completed', native_status: 'completed', loop: {final_iteration: 3, attempted_iterations: 3}},
        {operation_id: prepared, kind: 'prepare', run_name: 'example', project_id: null, admitted_at: '2026-10-26T09:00:00+00:00',
          state: 'completed', native_status: 'prepared'},
      ], unreadable: 1, examined: 3, incomplete: false});
    }
    if (url.pathname.endsWith('/tokens')) return reply({reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []});
    if (url.pathname.endsWith('/log')) return reply({text: '', next_offset: 0, observed_size: 0, truncated: false, missing: false});
    if (url.pathname === `/api/operations/${loopRun}/graph-results`) return reply({operation_id: loopRun, available: true, bodies: [{iteration: 1, tuning_state: 'succeeded', result: {
      run_name: 'body-1', model_type: 'fixture-model', status: 'completed', termination_reason: 'completed', started_at: 'fixture', finished_at: 'fixture',
      completed_rounds: 2, total_attempts: 3, metric: {metric_id: 'accuracy', direction: 'higher', verb: 'maximize', comparative: 'higher', antonym: 'lower'},
      metric_source: 'run_output_metric_spec', ranking_refusal: null, secondary_metrics: [], headline: headline(0.7999999999999999), status_counts: {success: 3}}}]});
    const id = url.pathname.split('/')[3];
    assert.ok([loopRun, prepared].includes(id), 'Only listed operations are opened: ' + url.pathname);
    return reply({operation_id: id, kind: id === loopRun ? 'candidate' : 'prepare', request_digest: 'a'.repeat(64), observed_at: 'fixture', state: 'completed',
      process: {status: 'exited', reason: 'observed'}, finishing: false, receipt_available: true, native_status: id === loopRun ? 'completed' : 'prepared',
      native_id: 'fixture-run', validation_passed: true, reason: 'native_terminal', ...(id === loopRun ? {loop: {final_iteration: 3, attempted_iterations: 3}} : {})});
  });
  const left = selector => page.locator(selector).first().evaluate(element => element.getBoundingClientRect().left);

  // Home before connecting: full connect card; the workflow journey leads, native chain follows.
  await page.goto(metadata.origin + '/#home');
  assert.equal(await page.locator('#token').isVisible(), true);
  assert.equal(await page.locator('#access-connected').isHidden(), true);
  const order = await page.evaluate(() => [...document.querySelectorAll('#view-home h2')].map(h => h.id || h.textContent));
  assert.ok(order.indexOf('journey-heading') === 0 && order.indexOf('journey-heading') < order.indexOf('native-chain-heading'), 'Entry cards precede the native chain: ' + order);
  // Home leads with at most three entry cards (template, workflow, monitor).
  assert.deepEqual(await page.locator('#view-home .entry-card .button-link').evaluateAll(links => links.map(link => link.getAttribute('href'))), ['#workflow', '#workflow', '#monitor']);
  // One shell: header, nav and content start on the same edge.
  const card = await left('#view-home .entry-card');
  for (const selector of ['header .brand', 'nav.actions a']) assert.ok(Math.abs((await left(selector)) - card) <= 2, `${selector} is not aligned with content`);

  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  for (const view of ['home', 'workflow', 'run', 'monitor']) {
    await page.locator(`nav a[href="#${view}"]`).click();
    assert.equal(await page.locator('#token').isHidden(), true, `${view}: token field collapses after connecting`);
    assert.equal(await page.locator('#access-heading').isHidden(), true, `${view}: connect heading collapses`);
    assert.equal(await page.locator('#access-change').isVisible(), true, `${view}: Change token available`);
    assert.equal(await page.locator('#access-disconnect').isVisible(), true, `${view}: Disconnect available`);
    assert.ok((await page.locator('#access-section').boundingBox()).height < 90, `${view}: connected line stays compact`);
  }

  // Monitor without a selected operation lists this console's operations.
  const items = page.locator('#operations-list li');
  await items.nth(1).waitFor();
  assert.equal(await items.count(), 2);
  assert.match(await items.nth(0).textContent(), /five_node · candidate/);
  assert.match(await items.nth(0).textContent(), /3 of 3 bodies/);
  assert.match(await page.locator('#operations-status').textContent(), /1 record could not be verified/);
  assert.ok(Math.abs((await left('#view-monitor .operations-panel')) - (await left('nav.actions a'))) <= 2, 'Monitor content aligns with nav');
  await items.nth(0).locator('a').click();
  assert.equal(new URL(page.url()).hash, '#monitor/' + loopRun);
  await page.locator('#monitor-status').filter({hasText: 'Finished: the candidate passed validation.'}).waitFor();
  assert.equal(await page.locator('#operation-id').inputValue(), loopRun);
  assert.equal(await items.nth(0).locator('a').getAttribute('aria-current'), 'true');

  // Display rounding with the exact reported value kept as a tooltip.
  const panel = page.locator('#graph-results-observation');
  await panel.waitFor({state: 'visible'});
  await panel.locator('.graph-result-body details summary').first().click();
  const score = panel.locator('dd[data-exact="0.7999999999999999"]').first();
  assert.equal(await score.textContent(), '0.8');
  assert.match(await score.getAttribute('title'), /0\.7999999999999999/);
  assert.ok(!(await panel.textContent()).includes('0.7999999999999999'), 'No unrounded score is displayed');

  // E-6: a failed fetch turns the header chip to "Server unreachable"; the next success restores it.
  fault = 'down';
  // The selected operation is finished, so Monitor no longer polls it (M-5); any request
  // that fails to reach the server flips the chip.
  await page.evaluate(() => window.consoleSession.request('choices').catch(() => {}));
  await page.locator('#access-status').filter({hasText: 'Server unreachable'}).waitFor();
  assert.equal(await page.locator('#access-section').evaluate(el => el.classList.contains('access-unreachable')), true);
  assert.equal(await page.locator('#token').isHidden(), true, 'Unreachable keeps the token and drafts; it is not a disconnect');
  fault = null;
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor({timeout: 8000});
  // S-3/E-5: a non-JSON server error is a plain sentence, never a JavaScript parse error.
  fault = 'text500';
  const message = await page.evaluate(() => window.consoleSession.request('choices').catch(error => error.message));
  fault = null;
  assert.equal(message, 'Server error (500).');

  // Change token reopens the form; Disconnect returns to the full card.
  await page.locator('#access-change').click();
  assert.equal(await page.locator('#token').isVisible(), true);
  await page.locator('#access-disconnect').click();
  await page.locator('#access-status').filter({hasText: 'Disconnected.'}).waitFor();
  assert.equal(await page.locator('#token').isVisible(), true);
  assert.equal(await page.locator('#access-connected').isHidden(), true);
  assert.equal(await page.locator('#monitor-button').isDisabled(), true);

  assert.equal(await page.evaluate(() => window.pollTimers), 5, 'Monitor status poll, operation-list refresh, Run preparation and launch polls (idle without their condition), and one reachability probe');
  assert.equal(requests.filter(item => item.path === '/api/operations').length >= 1, true);
  assert.deepEqual(faults, []);
  console.log('PASS: compact connection, operation list opens Status and logs, rounded scores, journey-first Home, aligned shell');
} finally {
  await browser?.close();
  server.kill();
}
