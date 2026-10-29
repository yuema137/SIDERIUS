/** Issue #1203: native default -> browser edit -> saved source -> prepared Run review.
 * No candidate launch. Missing editor or review projections fail explicit assertions.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {chooseFirstConfiguredTask} from './console_task_choice.mjs';
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
  chooseFirstConfiguredTask(browser);
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
  // The generic inspector must expose the native default without authoring it.
  await page.locator('[data-node="fit"].editor-node').click();
  await page.locator('#editor-training-settings').evaluate(el => { el.open = true; });
  const rounds = page.locator('[data-training="max_rounds"]');
  assert.equal(await rounds.count(), 1, 'Tuning rounds control must be exposed');
  assert.match(await page.locator('[data-training-field="max_rounds"]').textContent(), /Tuning rounds per body/);
  assert.equal(await rounds.inputValue(), '10');
  assert.equal(await page.locator('[data-training-mode="max_rounds"]').inputValue(), 'unset');
  assert.ok(!(await readFile(metadata.source, 'utf8')).includes("'max_rounds'"));
  await page.locator('nav a[href="#run"]').click();
  await page.locator('#capture-earlier').evaluate(el => {el.open = true;});
  await page.locator('#capture-task').selectOption('synthetic');
  await open(metadata.captures[0]);
  assert.match(await page.locator('#capture-summary').textContent(), /Tuning rounds per body: 10/);

  await page.locator('nav a[href="#workflow"]').click();
  await page.locator('[data-training-mode="max_rounds"]').selectOption('supplied');
  await rounds.fill('3');
  await page.locator('#editor-review').click();
  await page.locator('#editor-save').click();
  await page.locator('#editor-status').filter({hasText: 'Saved as "'}).waitFor();
  assert.match(await readFile(metadata.source, 'utf8'), /['"]max_rounds['"]:\s*3/);
  await page.locator('nav a[href="#run"]').click();
  assert.equal(await page.locator('#new-run-task').inputValue(), 'synthetic');
  await page.locator('#new-run-name').fill('three-tuning-rounds');
  await page.locator('#new-run-review').click();
  await page.locator('#new-run-status').filter({hasText: 'Inputs checked'}).waitFor();
  await page.locator('#new-run-prepare').click();
  await until(() => page.locator('#new-run-open').isEnabled(), 90000);
  await page.locator('#new-run-open').click();
  await page.locator('#capture-status').filter({hasText: 'Prepared run opened'}).waitFor();
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/reusable-captures/review') && response.request().method() === 'POST');
  await page.locator('#capture-review').click();
  const review = await (await responsePromise).json();
  assert.equal(review.facts.training.max_rounds, 3);
  await page.locator('#capture-status').filter({hasText: 'Reviewed.'}).waitFor();
  assert.match(await page.locator('#capture-summary').textContent(), /Tuning rounds per body: 3/);
  // Preparation polling may precede creation of this exact operation record.
  const operationId = await page.locator('#new-run-operation-id').textContent();
  const operationUrl = `${origin}/api/operations/${operationId}`;
  assert.ok(missing.every(url => url === operationUrl), JSON.stringify(missing));
  assert.ok(faults.every(text => text.includes('404 (Not Found)') && text.endsWith(operationUrl)), JSON.stringify(faults));
  await page.screenshot({path: join(evidence, 'tuning-rounds.png'), fullPage: true});
  console.log(JSON.stringify({result: 'PASS', evidence}));
} finally {
  if (browser) await browser.close();
  await stop(server); await stop(provider);
  await writeFile(join(evidence, 'processes.json'), JSON.stringify(children.map(child => ({mode: child.mode, exitCode: child.exitCode, errors: child.errors})), null, 2));
}
