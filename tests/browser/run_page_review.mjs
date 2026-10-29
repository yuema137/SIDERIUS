/** Real Chromium → B3 HTTP → detached operation → native sandbox CPU validation.
 * Provider URL and non-forwarding proxy are checked by the fixture before launch.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, writeFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';
const checkout = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR || await mkdtemp(join(tmpdir(), 'siderius-reusable-browser-'));
await mkdir(evidence, {recursive: true});
const root = await mkdtemp(join(evidence, 'project-')), children = [], faults = [];
function start(...args) {
  const child = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.reusable_candidate_fixture', ...args], {cwd: checkout, stdio: ['ignore', 'pipe', 'pipe']});
  child.output = ''; child.errors = ''; child.mode = args[0];
  child.stdout.on('data', chunk => {child.output += chunk;}); child.stderr.on('data', chunk => {child.errors += chunk;});
  children.push(child); return child;
}
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, timeout = 20000) { const end = Date.now() + timeout; while (!(await predicate())) {if (Date.now() > end) throw new Error('Condition timed out'); await delay(50);} }
async function completed(child, timeout = 100000) { await until(() => child.exitCode !== null, timeout); assert.equal(child.exitCode, 0, child.errors); return child.output; }
async function stop(child) { if (!child || child.exitCode !== null || child.signalCode !== null) return; child.kill('SIGTERM'); await until(() => child.exitCode !== null || child.signalCode !== null); }
const probe = createServer(); await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${probe.address().port}`; await new Promise(resolve => probe.close(resolve));
let browser, server, provider, metadata;
try {
  provider = start('provider', root);
  const lines = createInterface({input: provider.stdout});
  const endpoint = await new Promise(resolve => lines.once('line', line => resolve(JSON.parse(line).endpoint))); lines.close();
  metadata = JSON.parse((await completed(start('setup', root, '--origin', origin, '--endpoint', endpoint, '--captures-count', '1', '--training'))).trim().split('\n').at(-1));
  server = start('serve', root);
  async function ready() { await until(async () => { try {return (await fetch(origin + '/')).ok;} catch {return false;} }); }
  await ready();
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  let context = await browser.newContext(), page = await context.newPage();
  const connect = async () => { if (await page.locator('#access-change').isVisible()) await page.locator('#access-change').click(); await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click(); await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  };
  const open = async run => {
    await page.locator('#capture-run option[value="' + run.run_id + '"]').waitFor({state: 'attached'});
    await page.locator('#capture-run').selectOption(run.run_id); await page.locator('#capture-open').click();
    await page.locator('#capture-status').filter({hasText: 'Prepared run opened'}).waitFor();
    await page.locator('#capture-review').click(); await page.locator('#capture-status').filter({hasText: 'Reviewed.'}).waitFor();
  };
  const missing = [];
  page.on('response', response => { if (response.status() === 404) missing.push(response.url()); });
  page.on('console', message => { if (message.type() === 'error') faults.push(message.text() + ' ' + message.location().url); });
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(origin + '/#workflow'); await connect();
  await page.locator('#editor-status').filter({hasText: 'Opened '}).waitFor();
  await page.locator('nav a[href="#run"]').click();
  assert.equal(await page.locator('#capture-status').textContent(), 'Prepare a run in step 1, or open an earlier prepared run below.');
  await page.locator('#capture-earlier').evaluate(el => {el.open = true;});
  await page.locator('#capture-task').selectOption('synthetic');
  await open(metadata.captures[0]);
  const summary = await page.locator('#capture-summary').textContent();
  for (const text of ['Proposal advice: Prefer a small interpretable baseline', 'Implementation advice: Keep diagnostics explicit',
    'Validation advice: Inspect held-out residuals', 'Health mode: Record only',
    'Trial training: Time budget: 7 minutes; epoch ceiling: 3', 'Formal training: Time budget: 19 minutes; epoch ceiling: 8',
    'train_config.lr_schedule: {"exact":null}']) assert.ok(summary.includes(text), text);
  // Presentation variants use the same review response; no launch of a synthetic request.
  let bodies = 1;
  await page.route('**/reusable-captures/review', async route => {
    const response = await route.fetch(), value = await response.json();
    value.loop = {final_iteration: 4, feedback: {source: {node: 'check'}, target: 'hypothesis'},
      stop_conditions: [{kind: 'no_improvement', completed_bodies: bodies}]};
    value.facts.task_parameter_rules = {rules: {'train_config.batch_size': {exact: 32}}};
    value.facts.training.healthgate_mode = 'blocking';
    await route.fulfill({response, json: value});
  });
  for (bodies of [1, 2]) {
    await page.locator('#capture-review').click();
    const phrase = bodies === 1 ? '1 completed body passes without improvement' : '2 completed bodies pass without improvement';
    await page.locator('#capture-loop').filter({hasText: phrase}).waitFor();
    const text = await page.locator('#capture-summary').textContent();
    assert.ok(text.includes('Health mode: Block on failure'));
    assert.ok(text.includes('Task locked parameters: train_config.batch_size: {"exact":32}'));
  }
  await page.unroute('**/reusable-captures/review');
  await page.locator('#capture-review').click();
  await page.locator('#capture-summary').filter({hasText: 'Health mode: Record only'}).waitFor();
  await page.locator('#setup-runs-status').filter({hasText: 'No runs of this setup yet.'}).waitFor();
  assert.deepEqual(missing, [], 'Page load and review have no missing requests');
  assert.deepEqual(faults, [], 'Page load and review have no console errors');
  // Recovery may query a retained launch UUID before admission has written its record.
  await page.locator('#capture-launch').click();
  await page.locator('#capture-operation-id').filter({hasText: /[a-f0-9-]{36}/}).waitFor();
  const launched = await page.locator('#capture-operation-id').textContent();
  await page.locator(`#setup-runs-list a[href="#monitor/${launched}"]`).waitFor();
  assert.equal(await page.locator('#setup-runs-list a').count(), 1, 'Launch refreshes the list without a click');
  await page.locator('#capture-finish').waitFor({timeout: 180000});
  assert.ok(missing.every(url => url.endsWith('/api/operations/' + launched)), JSON.stringify(missing));
  assert.ok(faults.every(text => text.includes('/api/operations/' + launched)), JSON.stringify(faults));
  await writeFile(join(evidence, 'result.json'), JSON.stringify({result: 'PASS', launched, missing, faults}));
  console.log(JSON.stringify({result: 'PASS', evidence}));
  await page.screenshot({path: join(evidence, 'review.png'), fullPage: true});
} finally {
  if (browser) await browser.close();
  await stop(server); await stop(provider);
  await writeFile(join(evidence, 'processes.json'), JSON.stringify(children.map(child => ({mode: child.mode, exitCode: child.exitCode, errors: child.errors})), null, 2));
}
