/** Real source-save/profile/review and retained family launch, using local fake HTTP provider. */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdtemp, readFile, writeFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
const checkout = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR || await mkdtemp(join(tmpdir(), 'siderius-families-browser-'));
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
async function completed(child) { await until(() => child.exitCode !== null, 100000); assert.equal(child.exitCode, 0, child.errors); return child.output; }
async function stop(child) { if (!child || child.exitCode !== null || child.signalCode !== null) return; child.kill('SIGTERM'); await until(() => child.exitCode !== null || child.signalCode !== null); }
const probe = createServer(); await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${probe.address().port}`; await new Promise(resolve => probe.close(resolve));
let browser, server, provider;
try {
  provider = start('provider', root);
  const lines = createInterface({input: provider.stdout});
  const endpoint = await new Promise(resolve => lines.once('line', line => resolve(JSON.parse(line).endpoint))); lines.close();
  const metadata = JSON.parse((await completed(start('setup', root, '--origin', origin, '--endpoint', endpoint, '--captures-count', '0', '--families'))).trim().split('\n').at(-1));
  server = start('serve', root);
  await until(async () => {try {return (await fetch(origin + '/')).ok;} catch {return false;}});
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const context = await browser.newContext(), page = await context.newPage();
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(origin + '/#workflow');
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#editor-status').filter({hasText: 'Opened supported declaration'}).waitFor();
  assert.equal(await page.locator('.editor-node').count(), 8);
  await page.locator('[data-node="alternate"].editor-node').click();
  assert.match(await page.locator('#editor-edges').textContent(), /alternate.result → build_other.output/);
  await page.locator('#editor-advanced').evaluate(el => {el.open = true;});
  const before = await page.locator('#editor-source').inputValue();
  assert.match(before, /native-proposal-families\/v1/);
  await page.locator('#editor-source').fill(before.replace('Prefer a small interpretable baseline', 'Preserve the explicit family advice'));
  await page.locator('#editor-review').click(); await page.locator('#editor-save').click();
  await page.locator('#editor-status').filter({hasText: 'Saved reviewed bytes'}).waitFor();
  const inspect = () => JSON.parse(execFileSync(process.env.EDITOR_PYTHON, ['-c', 'import sys; from pathlib import Path; from workflows.definition import parse_workflow_source; print(parse_workflow_source(Path(sys.argv[1]).read_text()).model_dump_json())', metadata.source], {cwd: checkout, encoding: 'utf8'}));
  const saved = inspect();
  assert.equal(saved.execution_profile, 'native-proposal-families/v1');
  assert.equal(saved.definition.nodes.length, 8);
  assert.equal(saved.preparation_options.proposal_advice, 'Preserve the explicit family advice');
  await page.locator('#editor-refresh').click();
  await page.locator('#editor-status').filter({hasText: 'Opened supported declaration'}).waitFor();
  assert.equal(await page.locator('.editor-node').count(), 8);
  assert.match(await page.locator('#editor-source').inputValue(), /native-proposal-families\/v1/);
  await page.locator('#workflow-next-run').click(); await page.locator('#view-run').waitFor(); // Saved version hands off to Run.
  await page.locator('#new-run-task').selectOption('synthetic');
  await page.locator('#new-run-review').click();
  await page.locator('#new-run-status').filter({hasText: 'Preparation reviewed'}).waitFor();
  await page.locator('#new-run-prepare').click();
  await until(async () => {if (await page.locator('#new-run-check').isVisible()) await page.locator('#new-run-check').click(); return (await page.locator('#new-run-operation-status').textContent()).includes('Native prepared');}, 90000);
  const intent = await page.evaluate(() => JSON.parse(localStorage.getItem('siderius.reusable-preparation.v1')));
  const envelope = join(root, 'runs', intent.payload.selection.run_id);
  const native = JSON.parse(await readFile(join(envelope, 'inputs/preparation/receipt.json')));
  assert.equal(native.status, 'prepared'); assert.equal(native.proposal_path, null);
  const index = JSON.parse(await readFile(join(envelope, 'inputs/preparation/child.json')));
  assert.equal(index.files.length, 10);
  await until(() => page.locator('#new-run-open').isEnabled()); await page.locator('#new-run-open').click();
  await page.locator('#capture-status').filter({hasText: 'Prepared run opened'}).waitFor();
  await page.locator('#capture-review').click(); await page.locator('#capture-status').filter({hasText: 'Capture reviewed'}).waitFor();
  const summary = await page.locator('#capture-summary').textContent();
  assert.match(summary, /Independent proposal instances executed serially/);
  assert.ok(!await page.locator('#capture-summary').evaluate(element => element.firstChild.textContent.includes('→'))); assert.match(summary, /alternate/);
  await page.screenshot({path: join(evidence, 'family-review.png'), fullPage: true});
  await until(async () => {await page.locator('#new-run-check').click(); return page.locator('#capture-launch').isEnabled();});
  await page.locator('#capture-launch').click();
  await until(async () => {if (await page.locator('#capture-check').isVisible()) await page.locator('#capture-check').click(); return (await page.locator('#capture-operation-status').textContent()).includes('completed');}, 120000);
  assert.match(await page.locator('#capture-operation-status').textContent(), /Native accepted/);
  const operationId = (await page.locator('#capture-operation-id').textContent()).trim();
  await page.close(); // Independent HTTP observation has no editor/browser page authority.
  const response = await fetch(origin + '/api/operations/' + operationId, {headers: {Authorization: 'Bearer ' + metadata.token}});
  assert.equal(response.status, 200); const observed = await response.json();
  assert.equal(observed.graph_trace.nodes.length, 8);
  const records = Object.fromEntries(await Promise.all(observed.graph_trace.nodes.map(async node => [node.node_id, JSON.parse(await readFile(node.record_path))])));
  assert.notEqual(records.hypothesis.candidate_id, records.alternate.candidate_id);
  assert.equal(records.build_left.candidate_id, records.hypothesis.candidate_id);
  assert.equal(records.build_right.candidate_id, records.hypothesis.candidate_id);
  assert.equal(records.build_other.candidate_id, records.alternate.candidate_id);
  assert.deepEqual(faults, []);
  await writeFile(join(evidence, 'result.json'), JSON.stringify({result: 'PASS', root, operationId, summary, graphTrace: observed.graph_trace, faults}, null, 2));
  console.log(JSON.stringify({result: 'PASS', evidence}));
} finally {
  if (browser) await browser.close(); await stop(server); await stop(provider);
  await writeFile(join(evidence, 'processes.json'), JSON.stringify(children.map(child => ({mode: child.mode, exitCode: child.exitCode, signal: child.signalCode, errors: child.errors})), null, 2));
}
