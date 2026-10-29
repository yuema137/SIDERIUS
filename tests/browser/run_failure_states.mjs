/** Issue #1145 witness: after a preparation or launch ends without success, the Run page's
 * next-step line (#run-next) says what happened and where to look, never "Preparing…" or
 * "The run has finished"; the step's status line names the cause from the log and, for a
 * preparation, its worker log location. Monitor reads a failed preparation as "Failed: …".
 * Real console server (reusable_candidate_fixture); retained intents are seeded in this
 * browser and their operation status/log reads are stubbed, so nothing is prepared or
 * launched. Required: EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';
import {chooseFirstConfiguredTask} from './console_task_choice.mjs';

const checkout = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR || await mkdtemp(join(tmpdir(), 'siderius-run-failures-'));
await mkdir(evidence, {recursive: true});
const root = await mkdtemp(join(evidence, 'project-')), children = [], faults = [];
function start(...args) {
  const child = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.reusable_candidate_fixture', ...args], {cwd: checkout, stdio: ['ignore', 'pipe', 'pipe']});
  child.output = ''; child.errors = '';
  child.stdout.on('data', chunk => {child.output += chunk;}); child.stderr.on('data', chunk => {child.errors += chunk;});
  children.push(child); return child;
}
const delay = ms => new Promise(done => setTimeout(done, ms));
async function until(predicate, timeout = 20000) { const end = Date.now() + timeout; while (!(await predicate())) {if (Date.now() > end) throw new Error('Condition timed out'); await delay(50);} }
async function completed(child, timeout = 100000) { await until(() => child.exitCode !== null, timeout); assert.equal(child.exitCode, 0, child.errors); return child.output; }
const probe = createServer(); await new Promise(done => probe.listen(0, '127.0.0.1', done));
const origin = `http://127.0.0.1:${probe.address().port}`; await new Promise(done => probe.close(done));

const prepId = '11451145-1145-4145-8145-114511451145', runId = '22452245-2245-4245-8245-224522452245';
const runFolder = '33453345-3345-4345-8345-334533453345';
const prepDigest = 'c'.repeat(64), runDigest = 'd'.repeat(64);
const prepLog = 'Traceback (most recent call last):\n  File "child.py", line 1\n' +
  'workflows.task_composition.TaskCompositionError: plugin file /task/plugins/model.py does not exist\n';
const runLog = 'Traceback (most recent call last):\n  File "worker.py", line 1\nRuntimeError: CUDA is required for native training\n';
const status = (id, kind, digest, fields) => ({operation_id: id, kind, request_digest: digest, observed_at: '2026-10-29T10:00:00Z',
  state: 'completed', process: {status: 'exited', reason: 'observed'}, finishing: false, receipt_available: true,
  native_status: 'failed', native_id: 'fixture', validation_passed: null, reason: 'native_terminal', seed: 'Seed 7 (generated)', ...fields});
let browser;
try {
  const provider = start('provider', root);
  const lines = createInterface({input: provider.stdout});
  const endpoint = await new Promise(done => lines.once('line', line => done(JSON.parse(line).endpoint))); lines.close();
  const metadata = JSON.parse((await completed(start('setup', root, '--origin', origin, '--endpoint', endpoint, '--captures-count', '0'))).trim().split('\n').at(-1));
  start('serve', root);
  await until(async () => { try {return (await fetch(origin + '/')).ok;} catch {return false;} });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  chooseFirstConfiguredTask(browser);
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}}), page = await context.newPage();
  page.on('pageerror', error => faults.push(error.message));
  // The stubbed observation of each seeded operation; everything else reaches the server.
  const observed = {[prepId]: null, [runId]: null};
  await page.route('**/api/operations/**', route => {
    const url = new URL(route.request().url()), [, , , id, sub] = url.pathname.split('/');
    if (!(id in observed)) return route.continue();
    assert.equal(route.request().method(), 'GET', 'A failed operation is only read');
    if (sub === 'log') {
      const text = url.searchParams.get('kind') === 'native' ? (id === prepId ? prepLog : runLog) : '';
      const offset = Number(url.searchParams.get('offset')), max = Number(url.searchParams.get('max_bytes'));
      const chunk = text.slice(offset, offset + max);
      return route.fulfill({json: {operation_id: id, kind: url.searchParams.get('kind'), offset, next_offset: offset + chunk.length,
        observed_size: text.length, missing: !text, truncated: false, text: chunk}});
    }
    if (sub === 'tokens') return route.fulfill({json: {reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []}});
    if (sub === 'graph-results') return route.fulfill({status: 404, json: {error: {message: 'fixture'}}});
    return route.fulfill({json: observed[id]});
  });
  const connect = async () => { if (await page.locator('#access-change').isVisible()) await page.locator('#access-change').click(); await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click(); await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor(); };
  await page.goto(origin + '/#workflow'); await connect();
  await page.locator('#editor-status').filter({hasText: 'Opened '}).waitFor();
  const project = await page.evaluate(() => window.workflowEditor.state.projectId);
  const records = {
    preparation: {version: 1, origin, project, source_version: {name: null, sha256: 'a'.repeat(64)}, payload: {
      selection: {task_id: 'synthetic', run_name: 'failed-preparation', run_id: runFolder, preparation_operation_id: prepId, expected_source_sha256: 'b'.repeat(64)},
      expectation: {request_digest: prepDigest, observations: {}}}},
    candidate: {version: 1, origin, project, payload: {candidate_operation_id: runId, expected_request_digest: runDigest,
      selection: {preparation: {envelope: 'fixture', expected_receipt_sha256: 'e'.repeat(64)}}}},
  };
  // Seed exactly one retained intent, then reopen Run as after a reload.
  async function retained(kind) {
    await page.evaluate(([kind, value]) => {
      for (const other of ['preparation', 'candidate']) localStorage.removeItem(window.reusableIntents.key(other));
      localStorage.setItem(window.reusableIntents.key(kind), JSON.stringify(value));
    }, [kind, records[kind]]);
    await page.goto(origin + '/#workflow'); await page.reload(); await connect();
    await page.locator('#editor-status').filter({hasText: 'Opened '}).waitFor();
    await page.locator('nav a[href="#run"]').click(); await page.locator('#view-run').waitFor();
  }
  const next = async text => { await page.locator('#run-next').filter({hasText: text}).waitFor(); return page.locator('#run-next').textContent(); };
  const shot = name => page.screenshot({path: join(evidence, name + '.png'), fullPage: true});

  // A preparation still running keeps the "Preparing…" line (no false failure).
  observed[prepId] = status(prepId, 'prepare_reusable', prepDigest, {state: 'active', process: {status: 'alive', reason: 'observed'}, receipt_available: false, native_status: null, reason: 'observed_wrapper'});
  await retained('preparation');
  await next('Preparing… this page updates by itself.');
  // Item 2+3: a failed preparation says so, names the cause from its log and the log location.
  observed[prepId] = status(prepId, 'prepare_reusable', prepDigest, {});
  let line = await next('The preparation failed.');
  assert.ok(!/Preparing/.test(line), line);
  const prepStatus = page.locator('#new-run-operation-status');
  await prepStatus.filter({hasText: 'Cause (from the log): workflows.task_composition.TaskCompositionError: plugin file /task/plugins/model.py does not exist'}).waitFor();
  const prepText = await prepStatus.textContent();
  assert.match(prepText, /^Failed: the preparation stopped with an error before finishing\./);
  assert.match(prepText, /inputs\/preparation\/worker\.log/);
  assert.ok(!/finished without/.test(prepText), prepText);
  assert.equal(await page.locator('#new-run-dismiss').isVisible(), true, 'Start over is offered');
  await shot('preparation-failed');
  // The same class: time limit and a failure before any result.
  observed[prepId] = status(prepId, 'prepare_reusable', prepDigest, {native_status: 'timed_out'});
  await retained('preparation');
  await next('The preparation reached its time limit and was stopped.');
  assert.match(await prepStatus.textContent(), /^Failed: the preparation reached its time limit/);
  observed[prepId] = status(prepId, 'prepare_reusable', prepDigest, {state: 'operation_failed', receipt_available: false, native_status: null, reason: 'pre_dispatch_failure'});
  await retained('preparation');
  await next('The preparation failed before reporting a result.');
  // Monitor reads the failed preparation as a failure with its cause, not "finished".
  observed[prepId] = status(prepId, 'prepare_reusable', prepDigest, {});
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, prepId);
  await page.locator('#monitor-status').filter({hasText: 'Failed: the preparation stopped with an error before finishing.'}).waitFor();
  await page.locator('#monitor-cause').filter({hasText: 'TaskCompositionError: plugin file'}).waitFor();

  // Item 4: a failed launch says the run failed, with the cause; never "has finished".
  observed[runId] = status(runId, 'candidate', runDigest, {});
  await retained('candidate');
  line = await next('The run failed.');
  assert.ok(!/has finished/.test(line), line);
  const runStatus = page.locator('#capture-operation-status');
  await runStatus.filter({hasText: 'Cause (from the log): RuntimeError: CUDA is required for native training'}).waitFor();
  assert.match(await runStatus.textContent(), /^Failed: the run stopped with an error before finishing\. Details and logs are in Monitor\./);
  await shot('launch-failed');
  for (const [fields, text] of [
    [{native_status: 'timed_out'}, 'The run reached its time limit and was stopped.'],
    [{native_status: 'interrupted'}, 'The run was interrupted before finishing.'],
    [{native_status: 'cancelled'}, 'The run was stopped on request before finishing'],
    [{state: 'operation_failed', receipt_available: false, native_status: null, reason: 'cancelled_while_queued'}, 'The run was cancelled before it started'],
    [{state: 'operation_failed', receipt_available: false, native_status: null, reason: 'spawn_failed'}, 'The run did not start'],
  ]) {
    observed[runId] = status(runId, 'candidate', runDigest, fields);
    await retained('candidate');
    line = await next(text);
    assert.ok(!/has finished/.test(line), line);
  }
  // A successful run still reads as finished.
  observed[runId] = status(runId, 'candidate', runDigest, {native_status: 'accepted', validation_passed: true});
  await retained('candidate');
  await next('The run has finished. Open it in Monitor for results and logs.');
  assert.deepEqual(faults, []);
  console.log('PASS: failed/timed-out/not-started preparation and failed/timed-out/interrupted/cancelled/not-started launch headlines say what happened and where to look; causes from the log; running and accepted states unchanged');
} finally {
  await browser?.close();
  for (const child of children) if (child.exitCode === null) child.kill('SIGTERM');
}
