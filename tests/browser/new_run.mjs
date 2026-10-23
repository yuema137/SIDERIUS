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
  metadata = JSON.parse((await completed(start('setup', root, '--origin', origin, '--endpoint', endpoint, '--captures-count', '0'))).trim().split('\n').at(-1));
  server = start('serve', root);
  async function ready() { await until(async () => { try {return (await fetch(origin + '/')).ok;} catch {return false;} }); }
  await ready();
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  let context = await browser.newContext(), page = await context.newPage();
  const connect = async () => { await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click(); await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor(); };
  const requests = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => {if (request.method() === 'POST') requests.push(request.url());});
  await page.goto(origin + '/#workflow'); await connect();
  await page.locator('#editor-status').filter({hasText: 'Opened supported declaration'}).waitFor();
  await page.locator('#new-run-task option[value="synthetic"]').waitFor({state: 'attached'});
  assert.equal(await page.locator('#new-run-task').inputValue(), '', 'No implicit first task');
  assert.equal(requests.length, 0);
  await page.locator('#editor-advanced').evaluate(el => {el.open = true;});
  const source = await page.locator('#editor-source').inputValue();
  await page.locator('#editor-source').fill(source + '\n# saved by new run browser\n');
  await page.locator('#new-run-task').selectOption('synthetic');
  assert.equal(await page.locator('#new-run-review').isDisabled(), true);
  await page.locator('#editor-review').click(); await page.locator('#editor-save').click();
  await page.locator('#editor-status').filter({hasText: 'Saved reviewed bytes'}).waitFor();
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
  await page.locator('#new-run-review').click(); await page.locator('#new-run-status').filter({hasText: 'Preparation reviewed'}).waitFor();
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
      await page.locator('#editor-source').fill(saved.toString() + '\n# changed while reviewing\n');
      await page.locator('#editor-review').click(); await page.locator('#editor-save').click();
      await page.locator('#editor-status').filter({hasText: 'Saved reviewed bytes'}).waitFor();
      saved = await readFile(metadata.source);
    } else {
      await connect();
    }
    releaseDelayed(); await delay(100);
    assert.equal(await page.locator('#new-run-prepare').isDisabled(), true, change + ' must invalidate old review');
    await page.unroute('**/reusable-preparations/review');
    await page.locator('#new-run-review').click();
    await page.locator('#new-run-status').filter({hasText: 'Preparation reviewed'}).waitFor();
  }
  const previewText = await page.locator('#new-run-details').textContent();
  assert.ok(previewText.includes('Saved source version verified'));
  // An unrelated unresolved candidate survives editing and blocks preparation.
  const candidateKey = 'siderius.reusable-candidate.v1';
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
  await page.locator('#new-run-status').filter({hasText: 'Preparation reviewed'}).waitFor();
  // A live pre-submit refusal can be explicitly discarded, without a native effect.
  await page.route('**/reusable-preparations/prepare', route => route.fulfill({status: 409, json: {error: {code: 'task_policy', message: 'fixture initial refusal', admission_not_attempted: true}}}));
  await page.locator('#new-run-prepare').click();
  await page.locator('#new-run-operation-status').filter({hasText: 'did not attempt admission'}).waitFor();
  assert.equal(await page.locator('#new-run-dismiss').isEnabled(), true);
  await page.locator('#new-run-dismiss').click();
  await page.unroute('**/reusable-preparations/prepare');
  await page.locator('#new-run-review').click();
  await page.locator('#new-run-status').filter({hasText: 'Preparation reviewed'}).waitFor();
  // Storage failure cannot send preparation, and does not affect the candidate key.
  await page.evaluate(() => {window.originalSetItem = Storage.prototype.setItem; Storage.prototype.setItem = function(key, value) {if (key === 'siderius.reusable-preparation.v1') throw Error('fixture storage failure'); return window.originalSetItem.call(this, key, value);};});
  const before = requests.length; await page.locator('#new-run-prepare').click();
  await page.locator('#new-run-status').filter({hasText: 'Prepare not sent'}).waitFor(); assert.equal(requests.length, before);
  await page.evaluate(() => {Storage.prototype.setItem = window.originalSetItem;});
  let admitted, dropped = false;
  await page.route('**/reusable-preparations/prepare', async route => {
    const retained = await page.evaluate(() => JSON.parse(localStorage.getItem('siderius.reusable-preparation.v1')));
    assert.deepEqual(JSON.parse(route.request().postData()), retained.payload);
    const response = await route.fetch(); assert.equal(response.status(), 202); admitted = await response.json(); dropped = true; await route.abort('failed');
  });
  await page.locator('#new-run-prepare').click(); await until(() => dropped);
  const retained = await page.evaluate(() => localStorage.getItem('siderius.reusable-preparation.v1'));
  const selection = JSON.parse(retained).payload.selection;
  await page.unroute('**/reusable-preparations/prepare');
  await page.reload(); await connect();
  await page.locator('#new-run-check').waitFor();
  // A restored request cannot become discardable through a later refusal or 404.
  await page.route('**/reusable-preparations/prepare', route => route.fulfill({status: 409, json: {error: {message: 'fixture restored refusal', admission_not_attempted: true}}}));
  await page.locator('#new-run-retry').click();
  await page.locator('#new-run-operation-status').filter({hasText: 'Outcome unresolved'}).waitFor();
  assert.equal(await page.locator('#new-run-dismiss').isDisabled(), true);
  await page.unroute('**/reusable-preparations/prepare');
  await page.route('**/api/operations/' + admitted.operation_id, route => route.fulfill({status: 404, json: {error: {message: 'fixture missing'}}}));
  await page.locator('#new-run-check').click();
  await page.locator('#new-run-operation-status').filter({hasText: 'absence does not'}).waitFor();
  assert.equal(await page.locator('#new-run-dismiss').isDisabled(), true);
  await page.unroute('**/api/operations/' + admitted.operation_id);

  await until(async () => {await page.locator('#new-run-check').click(); return (await page.locator('#new-run-operation-status').textContent()).includes('Native prepared');}, 90000);
  const envelope = join(root, 'runs', selection.run_id);
  assert.deepEqual(await readFile(join(envelope, 'workflow.py.snapshot')), saved);
  const {access, readdir} = await import('node:fs/promises');
  await assert.rejects(access(join(envelope, 'workspace')), 'Preparation must not launch candidate');
  assert.equal((await readdir(join(metadata.state, 'operations'))).length, 1);
  // Exact recovery after live removal of original source and credential; no second operation.
  await rename(metadata.source, metadata.source + '.saved'); await rename(metadata.credential, metadata.credential + '.saved');
  await page.locator('#new-run-retry').click(); await page.locator('#new-run-operation-status').filter({hasText: 'existing'}).waitFor();
  assert.equal((await readdir(join(metadata.state, 'operations'))).length, 1);
  await rename(metadata.source + '.saved', metadata.source); await rename(metadata.credential + '.saved', metadata.credential);
  await page.locator('#new-run-check').click(); await page.locator('#new-run-open').waitFor();
  await until(() => page.locator('#new-run-open').isEnabled());
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
  await page.locator('#capture-status').filter({hasText: 'Capture reviewed'}).waitFor();
  assert.equal(await page.locator('#capture-launch').isDisabled(), true, 'Preparation does not imply credential readiness');
  await rename(metadata.credential + '.saved', metadata.credential);
  await page.locator('#capture-review').click(); await page.locator('#capture-status').filter({hasText: 'Capture reviewed'}).waitFor();
  await until(() => page.locator('#capture-launch').isEnabled());
  await page.locator('#capture-launch').click();
  await until(async () => {await page.locator('#capture-check').click(); return (await page.locator('#capture-operation-status').textContent()).includes('Native accepted');}, 90000);
  assert.equal((await readdir(join(metadata.state, 'operations'))).length, 2);
  assert.equal(await page.evaluate(() => localStorage.getItem('siderius.reusable-preparation.v1')), retained);
  await page.screenshot({path: join(evidence, 'new-run-completed.png'), fullPage: true});
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
      const key = 'siderius.reusable-' + kind + '.v1';
      localStorage.setItem(key, JSON.stringify(replacement));
      results.push(!c.same(kind, exact), !c.observe(kind, exact, {...status, process: {status: 'exited'}}));
      try {c.dismiss(kind, exact); results.push(false);} catch {results.push(localStorage.getItem(key) === JSON.stringify(replacement));}
      localStorage.setItem(key, JSON.stringify(exact));
    }
    return results;
  });
  assert.ok(coordinatorResult.every(Boolean));
  assert.deepEqual(faults, []);
  await writeFile(join(evidence, 'result.json'), JSON.stringify({result: 'PASS', root, preparation: admitted.operation_id, run: selection.run_id, checks: coordinatorResult.length, faults}, null, 2));
  console.log(JSON.stringify({result: 'PASS', evidence}));
} catch (error) {
  if (browser) {
    const pages = browser.contexts().flatMap(context => context.pages());
    for (const page of pages) {
      await writeFile(join(evidence, 'failure-ui.json'), JSON.stringify(await page.evaluate(() => ({
        editor: window.workflowEditor?.state,
        capture: document.getElementById('capture-status')?.textContent,
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
