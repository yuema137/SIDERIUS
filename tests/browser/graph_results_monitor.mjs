/** GET-only authored training result rendering. No provider/GPU/native effects. */
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
const operation = '22222222-2222-4222-8222-222222222222';
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
  const page = await browser.newPage(), requests = [], faults = [];
  page.on('pageerror', error => faults.push(error.message));
  const headline = (score, id) => ({best_exp_id: id, best_score: score, best_formal_score: score, best_valid_exp_id: id, best_valid_score: score, best_valid_formal_score: score});
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    requests.push({path: url.pathname, method: request.method()});
    assert.equal(request.method(), 'GET');
    assert.equal(request.headers().authorization, 'Bearer ' + metadata.token);
    const reply = json => route.fulfill({status: 200, json});
    if (url.pathname === '/api/choices' || url.pathname === '/api/native-chain/choices' || url.pathname === '/api/recorded-examples') return reply([]);
    // Slow control lists this console's operations once per connection, also on UUID routes.
    if (url.pathname === '/api/operations') return reply({operations: [], unreadable: 0, examined: 0, incomplete: false});
    assert.ok(url.pathname.startsWith(`/api/operations/${operation}`));
    if (url.pathname.endsWith('/tokens')) return reply({reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []});
    if (url.pathname.endsWith('/log')) return reply({text: '', next_offset: 0, observed_size: 0, truncated: false, missing: false});
    if (url.pathname.endsWith('/graph-results')) return reply({operation_id: operation, available: true, bodies: [1, 2].map(iteration => ({iteration, tuning_state: 'succeeded', result: {
      run_name: `body-${iteration}`, model_type: 'fixture-model', status: 'completed', termination_reason: 'completed',
      started_at: `2026-01-0${iteration}T00:00:00Z`, finished_at: `2026-01-0${iteration}T00:00:01Z`, completed_rounds: 2,
      total_attempts: 3, metric: {metric_id: 'example_score', direction: 'higher', verb: 'maximize', comparative: 'higher', antonym: 'lower'},
      metric_source: 'run_output_metric_spec', ranking_refusal: null, secondary_metrics: [], headline: headline(iteration * 4, `exp-${iteration}`),
      status_counts: {success: 3},
    }}))});
    return reply({operation_id: operation, kind: 'candidate', request_digest: 'a'.repeat(64), observed_at: 'fixture', state: 'completed',
      process: {status: 'exited', reason: 'observed'}, finishing: false, receipt_available: true, native_status: 'completed',
      native_id: 'fixture-run', validation_passed: true, reason: 'native_terminal'});
  });
  await page.goto(`${metadata.origin}/#slow-control/${operation}`);
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  const panel = page.locator('#graph-results-observation');
  await panel.waitFor({state: 'visible'});
  assert.equal(await panel.locator('.graph-result-body').count(), 2);
  assert.ok(await panel.getByText('Iteration 1', {exact: true}).count());
  assert.ok(await panel.getByText('Iteration 2', {exact: true}).count());
  await panel.locator('.graph-result-body details').nth(0).locator('summary').click();
  await panel.locator('.graph-result-body details').nth(1).locator('summary').click();
  assert.ok(await panel.getByText('body-1', {exact: true}).count());
  assert.ok(await panel.getByText('body-2', {exact: true}).count());
  assert.ok(await panel.getByText('Best score').count());
  assert.equal(await panel.getByText('Train & tune state', {exact: true}).count(), 2, 'stage uses the paper capability label');
  assert.equal(await panel.locator('.graph-result-body').count(), 2, 'per-body summaries remain separate');
  assert.equal(requests.filter(item => item.path.endsWith('/graph-results')).length, 1, 'results are read once after terminal status');
  assert.ok(requests.every(item => item.method === 'GET'));
  assert.deepEqual(faults, []);
  await page.screenshot({path: resolve(tmpdir(), 'siderius-graph-results-monitor.png'), fullPage: true});
  console.log('PASS: terminal authored-run results render separate iteration summaries through one GET-only read.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM'); lines.close();
}
