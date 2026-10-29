/** Real Chromium → B3 HTTP → detached operation → native sandbox CPU validation.
 * Provider URL and non-forwarding proxy are checked by the fixture before launch.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, mkdir, unlink, rename} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';
const training = process.env.CONSOLE_TRAINING === '1';
// Deliberately differ from both fixture settings and native defaults.
const editedTraining = {
  trial_max_epochs: 5, formal_max_epochs: 11,
  trial_portion: 0.25, train_portion: 0.45, formal_portion: 0.65,
  retain_training_checkpoints: true, retain_model_outputs: true
};
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
  metadata = JSON.parse((await completed(start('setup', root, '--origin', origin, '--endpoint', endpoint, '--captures-count', '0', ...(training ? ['--training'] : [])))).trim().split('\n').at(-1));
  server = start('serve', root);
  async function ready() { await until(async () => { try {return (await fetch(origin + '/')).ok;} catch {return false;} }); }
  await ready();
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  let context = await browser.newContext(), page = await context.newPage();
  const connect = async () => { if (await page.locator('#access-change').isVisible()) await page.locator('#access-change').click(); await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click(); await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor(); };
  // Run preparation lives on its own #run page; authoring stays on #workflow.
  const view = async name => { await page.locator(`nav a[href="#${name}"]`).click(); await page.locator(`#view-${name}`).waitFor(); };
  const requests = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => {if (request.method() === 'POST') requests.push(request.url());});
  await page.goto(origin + '/#workflow'); await connect();
  await page.locator('#editor-status').filter({hasText: 'Opened '}).waitFor();
  await page.locator('#new-run-task option[value="synthetic"]').waitFor({state: 'attached'});
  assert.equal(await page.locator('#new-run-task').inputValue(), '', 'No implicit first task');
  assert.equal(requests.length, 0);
  await page.locator('#editor-advanced').evaluate(el => {el.open = true;});
  if (training) {
    await page.locator('[data-node="fit"].editor-node').click();
    await page.locator('#editor-training-settings').evaluate(details => { details.open = true; }); // collapsed by default (spec §8.1)
    assert.ok((await page.locator('#editor-inspector pre').textContent()).includes('"exact": null'));
    await page.locator('[data-training-mode="sampling_seed"]').selectOption('supplied');
    await page.locator('[data-training="sampling_seed"]').fill('31');
    await page.locator('[data-training-mode="formal_time_budget_minutes"]').selectOption('null');
    await page.locator('[data-training-mode="formal_time_budget_minutes"]').selectOption('supplied');
    await page.locator('[data-training="formal_time_budget_minutes"]').fill('');
    await page.locator('.editor-node').first().click();
    assert.equal(await page.locator('#editor-review').isDisabled(), true, 'Supplied-from-null invalid draft survives navigation');
    await page.locator('[data-node="fit"].editor-node').click();
    assert.equal(await page.locator('[data-training-mode="formal_time_budget_minutes"]').inputValue(), 'supplied');
    assert.equal(await page.locator('[data-training="formal_time_budget_minutes"]').inputValue(), '');
    await page.locator('[data-training="formal_time_budget_minutes"]').fill('19');
    await page.locator('[data-training="trial_time_budget_minutes"]').fill('');
    assert.equal(await page.locator('#editor-review').isDisabled(), true, 'Blank is not zero or null');
    await page.locator('.editor-node').first().click();
    assert.equal(await page.locator('#editor-review').isDisabled(), true, 'Invalid draft survives node navigation');
    await page.locator('[data-node="fit"].editor-node').click();
    assert.equal(await page.locator('[data-training="trial_time_budget_minutes"]').inputValue(), '');
    await page.locator('[data-training="trial_time_budget_minutes"]').fill('7');
    for (const [name, value] of Object.entries(editedTraining)) {
      await page.locator(`[data-training-mode="${name}"]`).selectOption('supplied');
      const input = page.locator(`[data-training="${name}"]`);
      if (typeof value === 'boolean') await input.setChecked(value);
      else await input.fill(String(value));
    }
    await page.locator('.editor-node').first().click();
    await page.locator('[data-node="fit"].editor-node').click();
    for (const [name, value] of Object.entries(editedTraining)) {
      const input = page.locator(`[data-training="${name}"]`);
      assert.equal(await page.locator(`[data-training-mode="${name}"]`).inputValue(), 'supplied');
      assert.equal(typeof value === 'boolean' ? await input.isChecked() : Number(await input.inputValue()), value, name);
    }
    await page.locator('#editor-review').click(); await page.locator('#editor-save').click();
    await page.locator('#editor-status').filter({hasText: 'Saved as "'}).waitFor();
    const coded = (await readFile(metadata.source, 'utf8')).replace("'train_base_seed': 23", "'train_base_seed': 29");
    await writeFile(metadata.source, coded);
    await page.locator('#editor-refresh').click();
    await page.locator('#editor-status').filter({hasText: 'Opened '}).waitFor();
    assert.equal(await page.locator('[data-training="train_base_seed"]').inputValue(), '29');
    for (const [name, value] of Object.entries(editedTraining)) {
      const input = page.locator(`[data-training="${name}"]`);
      assert.equal(await page.locator(`[data-training-mode="${name}"]`).inputValue(), 'supplied');
      assert.equal(typeof value === 'boolean' ? await input.isChecked() : Number(await input.inputValue()), value, `Reopened ${name}`);
    }
  }
  const source = await page.locator('#editor-source').inputValue();
  await page.locator('#editor-source').fill(source + '\n# saved by new run browser\n');
  if (training) assert.equal(await page.locator('[data-training="sampling_seed"]').isDisabled(), true);
  assert.equal(await page.locator('#workflow-next-run').isDisabled(), true, 'Unsaved edits keep the Run handoff closed');
  await view('run');
  assert.match(await page.locator('#run-source-state').textContent(), /Save first/);
  await page.locator('#new-run-task').selectOption('synthetic');
  assert.equal(await page.locator('#new-run-review').isDisabled(), true);
  await view('workflow');
  await page.locator('#editor-review').click(); await page.locator('#editor-save').click();
  await page.locator('#editor-status').filter({hasText: 'Saved as "'}).waitFor();
  await page.locator('#workflow-next-run').click(); await page.locator('#view-run').waitFor();
  assert.match(await page.locator('#run-source-state').textContent(), /ready to run/);
  let saved = await readFile(metadata.source);
  // Delayed review cannot survive task change, source change, or a new session.
  let release, waiting = false;
  const gate = new Promise(resolve => {release = resolve;});
  await page.route('**/reusable-preparations/review', async route => {const response = await route.fetch(); waiting = true; await gate; await route.fulfill({response});});
  await page.locator('#new-run-review').click(); await until(() => waiting);
  await page.locator('#new-run-task').selectOption(''); release(); await delay(100);
  assert.equal(await page.locator('#new-run-prepare').isDisabled(), true);
  await page.unroute('**/reusable-preparations/review');
  await page.locator('#new-run-task').selectOption('synthetic');
  await page.locator('#new-run-review').click(); await page.locator('#new-run-status').filter({hasText: 'Inputs checked'}).waitFor();
  // Saved-source and connection revisions independently fence delayed reviews.
  for (const change of ['source', 'session']) {
    let releaseDelayed, delayed = false;
    const responseGate = new Promise(resolve => {releaseDelayed = resolve;});
    await page.route('**/reusable-preparations/review', async route => {
      const response = await route.fetch(); delayed = true;
      await responseGate; await route.fulfill({response});
    });
    await page.locator('#new-run-review').click(); await until(() => delayed);
    if (change === 'source') {
      await view('workflow');
      await page.locator('#editor-source').fill(saved.toString() + '\n# changed while reviewing\n');
      await page.locator('#editor-review').click(); await page.locator('#editor-save').click();
      await page.locator('#editor-status').filter({hasText: 'Saved as "'}).waitFor();
      saved = await readFile(metadata.source);
      await view('run');
    } else {
      await connect();
    }
    releaseDelayed(); await delay(100);
    assert.equal(await page.locator('#new-run-prepare').isDisabled(), true, change + ' must invalidate old review');
    await page.unroute('**/reusable-preparations/review');
    await page.locator('#new-run-review').click();
    await page.locator('#new-run-status').filter({hasText: 'Inputs checked'}).waitFor();
  }
  const previewText = await page.locator('#new-run-details').textContent();
  assert.ok(previewText.includes('Saved source version verified'));
  // R-5: the name-only credential precheck is shown before Prepare, read by the server.
  assert.equal(await page.locator('#new-run-credentials').isVisible(), true);
  assert.match(await page.locator('#new-run-credentials').textContent(), /Credentials|No credentials/);
  // The review names where its resolved model profile and data folder come from. The run
  // lane keeps these review details collapsed (step 2 of the stepper); open them as a user would.
  await page.locator('#new-run-details').evaluate(pre => { pre.closest('details').open = true; });
  await page.locator('#new-run-details').filter({hasText: 'Model profile source: Set in console.json'}).waitFor();
  assert.match(await page.locator('#new-run-details').textContent(), /Data folder source: Set in console\.json/);
  // An unrelated unresolved candidate survives editing and blocks preparation.
  // Intents are keyed by operations store and project (R-3), never per origin.
  const candidateKey = await page.evaluate(() => window.reusableIntents.key('candidate'));
  assert.match(candidateKey, /^siderius\.reusable-candidate\.v2\/[0-9a-f]{32}\/capture$/);
  const syntheticCandidate = {version: 1, origin, project: 'capture', payload: {
    selection: {task_id: 'synthetic', run_id: '11111111-1111-4111-8111-111111111111', preparation: {envelope: '/retained/capture', expected_receipt_sha256: 'a'.repeat(64)}},
    expected_request_digest: 'b'.repeat(64), candidate_operation_id: '22222222-2222-4222-8222-222222222222'
  }};
  await page.evaluate(({key, value}) => {
    localStorage.setItem(key, JSON.stringify(value));
    window.dispatchEvent(new StorageEvent('storage', {key}));
  }, {key: candidateKey, value: syntheticCandidate});
  assert.equal(await page.locator('#new-run-prepare').isDisabled(), true);
  await page.locator('#new-run-name').fill('reviewed-name');
  assert.deepEqual(await page.evaluate(key => JSON.parse(localStorage.getItem(key)), candidateKey), syntheticCandidate);
  await page.evaluate(key => {localStorage.removeItem(key); window.dispatchEvent(new StorageEvent('storage', {key}));}, candidateKey);
  await page.locator('#new-run-review').click();
  await page.locator('#new-run-status').filter({hasText: 'Inputs checked'}).waitFor();
  // A live pre-submit refusal can be explicitly discarded, without a native effect.
  await page.route('**/reusable-preparations/prepare', route => route.fulfill({status: 409, json: {error: {code: 'task_policy', message: 'fixture initial refusal', admission_not_attempted: true}}}));
  await page.locator('#new-run-prepare').click();
  await page.locator('#new-run-operation-status').filter({hasText: 'did not attempt admission'}).waitFor();
  assert.equal(await page.locator('#new-run-dismiss').isEnabled(), true);
  await page.locator('#new-run-dismiss').click();
  await page.unroute('**/reusable-preparations/prepare');
  await page.locator('#new-run-review').click();
  await page.locator('#new-run-status').filter({hasText: 'Inputs checked'}).waitFor();
  // Storage failure cannot send preparation, and does not affect the candidate key.
  await page.evaluate(() => {window.originalSetItem = Storage.prototype.setItem; Storage.prototype.setItem = function(key, value) {if (key.startsWith('siderius.reusable-preparation.v2/')) throw Error('fixture storage failure'); return window.originalSetItem.call(this, key, value);};});
  const before = requests.length; await page.locator('#new-run-prepare').click();
  await page.locator('#new-run-status').filter({hasText: 'Prepare not sent'}).waitFor(); assert.equal(requests.length, before);
  await page.evaluate(() => {Storage.prototype.setItem = window.originalSetItem;});
  let admitted, dropped = false;
  await page.route('**/reusable-preparations/prepare', async route => {
    const retained = await page.evaluate(() => JSON.parse(localStorage.getItem(window.reusableIntents.key('preparation'))));
    assert.deepEqual(JSON.parse(route.request().postData()), retained.payload);
    const response = await route.fetch(); assert.equal(response.status(), 202); admitted = await response.json(); dropped = true; await route.abort('failed');
  });
  await page.locator('#new-run-prepare').click(); await until(() => dropped);
  const retained = await page.evaluate(() => localStorage.getItem(window.reusableIntents.key('preparation')));
  const selection = JSON.parse(retained).payload.selection;
  await page.unroute('**/reusable-preparations/prepare');
  // Status reads are stubbed across the reload so the restored-intent rules are exercised
  // deterministically; the page itself checks status without any click.
  let statusFixture = {status: 404, json: {error: {code: 'not_found', message: 'fixture missing'}}};
  await page.route('**/api/operations/' + admitted.operation_id, route => statusFixture ? route.fulfill(statusFixture) : route.continue());
  await page.reload(); await connect();
  await page.locator('#new-run-operation-status').filter({hasText: 'Keep it'}).waitFor();
  // B8-2: the store's `unknown` state before the worker records its outcome is not a
  // finished preparation; it reads as preparing or checking, never "start over".
  const unknownStatus = reason => ({status: 200, json: {operation_id: admitted.operation_id, kind: 'prepare_reusable',
    request_digest: JSON.parse(retained).payload.expectation.request_digest, observed_at: 'fixture', state: 'unknown',
    process: {status: 'unknown', reason}, finishing: false, receipt_available: false, native_status: null, native_id: null,
    validation_passed: null, reason: 'outcome_unresolved'}});
  statusFixture = unknownStatus('missing_identity');
  await page.locator('#new-run-operation-status').filter({hasText: 'Preparing…'}).waitFor();
  statusFixture = unknownStatus('process_gone');
  await page.locator('#new-run-operation-status').filter({hasText: 'Checking status…'}).waitFor();
  assert.doesNotMatch(await page.locator('#new-run-operation-status').textContent(), /finished without|start over/i);
  statusFixture = {status: 404, json: {error: {code: 'not_found', message: 'fixture missing'}}};
  await page.locator('#new-run-operation-status').filter({hasText: 'Keep it'}).waitFor();
  // A restored request cannot become discardable through a later refusal or plain 404.
  await page.route('**/reusable-preparations/prepare', route => route.fulfill({status: 409, json: {error: {message: 'fixture restored refusal', admission_not_attempted: true}}}));
  await page.locator('#new-run-retry').click();
  await page.locator('#new-run-operation-status').filter({hasText: 'outcome is unconfirmed'}).waitFor();
  assert.equal(await page.locator('#new-run-dismiss').isDisabled(), true);
  await page.unroute('**/reusable-preparations/prepare');
  await page.locator('#new-run-operation-status').filter({hasText: 'Keep it'}).waitFor();
  assert.equal(await page.locator('#new-run-dismiss').isDisabled(), true, 'not_found never proves absence');
  // SEC-4: browser data cannot be forgotten while this project's run is unconfirmed.
  assert.equal(await page.locator('#forget-browser-data').isDisabled(), true);
  // A typed unknown_operation after this page's Retry offers Forget (R-3), and stops polling.
  statusFixture = {status: 404, json: {error: {code: 'unknown_operation', message: 'fixture unknown'}}};
  // L-5: one unknown read is not enough; a second read at least 5 s later is required.
  await page.locator('#new-run-operation-status').filter({hasText: 'Checking once more'}).waitFor();
  assert.equal(await page.locator('#new-run-dismiss').isHidden(), true, 'No Forget after a single unknown read');
  await page.locator('#new-run-operation-status').filter({hasText: 'still has no record'}).waitFor();
  assert.equal(await page.locator('#new-run-dismiss').textContent(), 'Forget this operation');
  assert.equal(await page.locator('#new-run-dismiss').isEnabled(), true);
  assert.equal(await page.locator('#new-run-retry').isVisible(), true, 'Retry stays offered beside Forget');
  statusFixture = null;
  // Exact recovery after live removal of original source and credential; no second operation.
  const {access, readdir} = await import('node:fs/promises');
  await rename(metadata.source, metadata.source + '.saved'); await rename(metadata.credential, metadata.credential + '.saved');
  await page.locator('#new-run-retry').click(); await page.locator('#new-run-operation-status').filter({hasText: 'already exists'}).waitFor();
  assert.equal((await readdir(join(metadata.state, 'operations'))).length, 1);
  await rename(metadata.source + '.saved', metadata.source); await rename(metadata.credential + '.saved', metadata.credential);
  // R-1: the status advances by itself; no "Check status" click anywhere below.
  await page.locator('#new-run-operation-status').filter({hasText: 'Prepared.'}).waitFor({timeout: 90000});
  assert.equal(await page.locator('#new-run-dismiss').isVisible(), true);
  assert.equal(await page.locator('#new-run-dismiss').textContent(), 'Start over', 'Forget is never offered for a known, finished operation');
  const envelope = join(root, 'runs', selection.run_id);
  assert.deepEqual(await readFile(join(envelope, 'workflow.py.snapshot')), saved);
  await assert.rejects(access(join(envelope, 'workspace')), 'Preparation must not launch candidate');
  assert.equal((await readdir(join(metadata.state, 'operations'))).length, 1);
  // R-2 (and the red team's restart observation): after a reload the finished preparation
  // is observed without a click, so Open is enabled and no stale "starting" text remains.
  await page.reload(); await connect(); await view('run');
  await until(() => page.locator('#new-run-open').isEnabled());
  assert.doesNotMatch(await page.locator('#new-run-operation-status').textContent(), /starting|Checking/);
  await page.screenshot({path: join(evidence, 'run-prepared-after-reload.png'), fullPage: true});
  await page.locator('#capture-earlier').evaluate(el => {el.open = true;});
  // A delayed old capture-list reply cannot reset the explicit handoff selection.
  await page.locator('#capture-task').selectOption('synthetic');
  await page.locator('#capture-run option[value="' + selection.run_id + '"]').waitFor({state: 'attached'});
  let releaseList, listWaiting = false;
  const listGate = new Promise(resolve => {releaseList = resolve;});
  await page.route(/\/reusable-captures\?/, async route => {const response = await route.fetch(); listWaiting = true; await listGate; await route.fulfill({response});});
  await page.locator('#capture-refresh').click(); await until(() => listWaiting);
  await page.locator('#new-run-open').click(); await page.locator('#capture-status').filter({hasText: 'Prepared run opened'}).waitFor();
  releaseList(); await delay(100); await page.unroute(/\/reusable-captures\?/);
  await page.locator('#capture-task option[value="alternative"]').waitFor({state: 'attached'});
  assert.equal(await page.locator('#capture-run').inputValue(), selection.run_id);
  assert.equal(await page.locator('#capture-launch').isDisabled(), true, 'Open never reviews or launches implicitly');
  // Old selection/review replies cannot override a later explicit handoff.
  for (const suffix of ['select', 'review']) {
    let oldWaiting = false, releaseOld;
    const oldGate = new Promise(resolve => {releaseOld = resolve;});
    await page.route('**/reusable-captures/' + suffix, async route => {
      if (oldWaiting) {await route.continue(); return;}
      const response = await route.fetch(); oldWaiting = true;
      await oldGate;
      if (suffix === 'select') {
        const body = await response.json(); body.run_id = '99999999-9999-4999-8999-999999999999';
        await route.fulfill({response, json: body});
      } else {await route.fulfill({response});}
    });
    await page.locator(suffix === 'select' ? '#capture-open' : '#capture-review').click();
    await until(() => oldWaiting);
    await page.locator('#new-run-open').click();
    await page.locator('#capture-status').filter({hasText: 'Prepared run opened'}).waitFor();
    releaseOld(); await delay(100);
    assert.equal(await page.locator('#capture-run').inputValue(), selection.run_id);
    assert.equal(await page.locator('#capture-launch').isDisabled(), true);
    await page.unroute('**/reusable-captures/' + suffix);
  }
  // Reconnect task choices arriving after handoff cannot clear its task or run.
  let choiceCalls = 0, choicesWaiting = false, releaseChoices;
  const choicesGate = new Promise(resolve => {releaseChoices = resolve;});
  await page.route('**/api/choices', async route => {
    const response = await route.fetch();
    if (++choiceCalls > 1) {choicesWaiting = true; await choicesGate;}
    await route.fulfill({response});
  });
  await connect(); await until(() => choicesWaiting);
  await page.locator('#new-run-open').click();
  await page.locator('#capture-status').filter({hasText: 'Prepared run opened'}).waitFor();
  releaseChoices(); await delay(150); await page.unroute('**/api/choices');
  assert.equal(await page.locator('#capture-task').inputValue(), 'synthetic');
  assert.equal(await page.locator('#capture-run').inputValue(), selection.run_id);
  await rename(metadata.credential, metadata.credential + '.saved');
  await page.locator('#capture-review').click();
  await page.locator('#capture-status').filter({hasText: 'Cannot launch yet'}).waitFor();
  assert.equal(await page.locator('#capture-launch').isDisabled(), true, 'Preparation does not imply credential readiness');
  // R-5: a missing file is named as missing, with the missing names (never values).
  assert.match(await page.locator('#capture-credentials').textContent(), /missing .*does not exist/);
  assert.match(await page.locator('#capture-launch-reason').textContent(), /Cannot launch: credentials/);
  await rename(metadata.credential + '.saved', metadata.credential);
  await page.locator('#capture-review').click(); await page.locator('#capture-status').filter({hasText: 'Reviewed.'}).waitFor();
  await until(() => page.locator('#capture-launch').isEnabled());
  await page.locator('#capture-launch').click();
  await delay(500);
  assert.ok(!(await page.locator('#capture-operation-status').textContent()).includes('admission'), await page.locator('#capture-operation-status').textContent());
  await page.locator('#capture-operation-status').filter({hasText: /Finished/}).waitFor({timeout: 90000});
  assert.match(await page.locator('#capture-operation-status').textContent(), /passed validation/);
  assert.equal(await page.locator('#run-stepper [aria-current="step"]').getAttribute('data-run-step'), 'follow');
  assert.equal((await readdir(join(metadata.state, 'operations'))).length, 2);
  assert.equal(await page.evaluate(() => localStorage.getItem(window.reusableIntents.key('preparation'))), retained);
  await page.screenshot({path: join(evidence, 'new-run-completed.png'), fullPage: true});
  if (training) {
    const observed = JSON.parse(await readFile(join(envelope, 'workspace/candidate_run/offline_training_observed.json')));
    assert.equal(observed.proposal.sampling_seed, 31);
    assert.equal(observed.tuner.sampling_seed, 31);
    assert.equal(observed.tuner.train_base_seed, 29);
    assert.equal(observed.tuner.trial_time_budget_minutes, 7);
    assert.equal(observed.tuner.formal_time_budget_minutes, 19);
    assert.equal(observed.proposal.trial_portion, 0.25);
    assert.equal(observed.proposal.train_portion, 0.45);
    for (const [name, value] of Object.entries(editedTraining)) {
      assert.equal(observed.tuner[name], value, `Native tuner ${name}`);
    }
    const captured = JSON.parse(await readFile(join(envelope, 'inputs/training_settings.json')));
    for (const [name, value] of Object.entries(editedTraining)) {
      assert.equal(captured.launch[name], value, `Captured ${name}`);
    }
    assert.deepEqual(captured.launch.workflow_parameter_rules.rules['train_config.lr_schedule'], {exact: null});
  }
  // Both controllers use exact-record conservative release evidence.
  const coordinatorResult = await page.evaluate(() => {
    const c = window.reusableIntents;
    const results = [];
    for (const kind of ['preparation', 'candidate']) {
      const exact = c.read(kind).value, p = exact.payload;
      const status = {kind: kind === 'candidate' ? 'candidate' : 'prepare_reusable', operation_id: kind === 'candidate' ? p.candidate_operation_id : p.selection.preparation_operation_id, request_digest: kind === 'candidate' ? p.expected_request_digest : p.expectation.request_digest, state: 'completed', process: {status: 'alive'}, finishing: false};
      c.observe(kind, exact, status); results.push(!c.dismissible(kind, exact));
      c.observe(kind, exact, {...status, process: {status: 'unknown'}}); results.push(!c.dismissible(kind, exact));
      c.observe(kind, exact, {...status, process: {status: 'exited'}, finishing: true}); results.push(!c.dismissible(kind, exact));
      c.observe(kind, exact, {...status, state: 'operation_failed', reason: 'spawn_failed'}); results.push(c.dismissible(kind, exact));
      const replacement = structuredClone(exact);
      if (kind === 'candidate') replacement.payload.candidate_operation_id = crypto.randomUUID(); else replacement.payload.selection.preparation_operation_id = crypto.randomUUID();
      const key = c.key(kind);
      localStorage.setItem(key, JSON.stringify(replacement));
      results.push(!c.same(kind, exact), !c.observe(kind, exact, {...status, process: {status: 'exited'}}));
      try {c.dismiss(kind, exact); results.push(false);} catch {results.push(localStorage.getItem(key) === JSON.stringify(replacement));}
      localStorage.setItem(key, JSON.stringify(exact));
    }
    return results;
  });
  assert.ok(coordinatorResult.every(Boolean));
  assert.deepEqual(faults, []);
  if (training) { await context.close(); await completed(start("verify-training", root)); }
  await writeFile(join(evidence, 'result.json'), JSON.stringify({result: 'PASS', root, preparation: admitted.operation_id, run: selection.run_id, checks: coordinatorResult.length, faults}, null, 2));
  console.log(JSON.stringify({result: 'PASS', evidence}));
} catch (error) {
  if (browser) {
    const pages = browser.contexts().flatMap(context => context.pages());
    for (const page of pages) {
      await writeFile(join(evidence, 'failure-ui.json'), JSON.stringify(await page.evaluate(() => ({
        editor: window.workflowEditor?.state,
        capture: document.getElementById('capture-status')?.textContent,
        operation: document.getElementById('capture-operation-status')?.textContent,
        preparation: document.getElementById('new-run-operation-status')?.textContent,
        status: document.getElementById('new-run-status')?.textContent
      })), null, 2));
    }
  }
  throw error;
} finally {
  if (browser) await browser.close();
  await stop(server); await stop(provider);
  await writeFile(join(evidence, 'processes.json'), JSON.stringify(children.map(child => ({mode: child.mode, exitCode: child.exitCode, signal: child.signalCode, errors: child.errors})), null, 2));
}
