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
  metadata = JSON.parse((await completed(start('setup', root, '--origin', origin, '--endpoint', endpoint))).trim().split('\n').at(-1));
  server = start('serve', root);
  async function ready() { await until(async () => { try {return (await fetch(origin + '/')).ok;} catch {return false;} }); }
  await ready();
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  let context = await browser.newContext(), page = await context.newPage();
  const connect = async () => { await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click(); await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor(); };
  const open = async run => {
    await page.locator('#capture-run option[value="' + run.run_id + '"]').waitFor({state: 'attached'});
    await page.locator('#capture-run').selectOption(run.run_id); await page.locator('#capture-open').click();
    await page.locator('#capture-status').filter({hasText: 'Prepared capture selected'}).waitFor();
    await page.locator('#capture-review').click(); await page.locator('#capture-status').filter({hasText: 'Capture reviewed'}).waitFor();
  };
  const requests = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => {if (request.method() === 'POST') requests.push(request.url());});
  await page.goto(origin + '/#workflow'); await connect();
  await page.locator('#editor-status').filter({hasText: 'Opened supported declaration'}).waitFor();
  assert.equal(requests.length, 0, 'Opening workflow must not prepare/review/launch');
  await page.locator('#editor-project').selectOption('disabled');
  await page.locator('#capture-status').filter({hasText: 'not enabled'}).waitFor();
  assert.equal(await page.locator('#capture-open').isDisabled(), true);
  await page.locator('#editor-project').selectOption('capture');
  await page.locator('#capture-task').selectOption('synthetic');
  await open(metadata.captures[0]);
  assert.match(await page.locator('#capture-summary').textContent(), /hypothesis → build → check/);
  assert.match(await page.locator('#capture-details').textContent(), /Prefer a small interpretable baseline/);
  // A late review for another selection cannot restore its launch affordance.
  let releaseReview, reviewWaiting = false;
  const reviewGate = new Promise(resolve => {releaseReview = resolve;});
  await page.route('**/reusable-captures/review', async route => {const response = await route.fetch(); reviewWaiting = true; await reviewGate; await route.fulfill({response});});
  await page.locator('#capture-review').click(); await until(() => reviewWaiting);
  await page.locator('#capture-run').selectOption(metadata.captures[1].run_id); releaseReview(); await delay(150);
  assert.equal(await page.locator('#capture-launch').isDisabled(), true);
  assert.equal(await page.locator('#capture-summary').textContent(), '');
  await page.unroute('**/reusable-captures/review'); await open(metadata.captures[0]);
  // Explicit fresh pre-admission refusal can be dismissed, never silently retried.
  const receiptPath = join(metadata.captures[0].envelope, 'receipt.json'), receipt = await readFile(receiptPath);
  await writeFile(receiptPath, 'changed after review'); await page.locator('#capture-launch').click();
  await page.locator('#capture-operation-status').filter({hasText: 'did not attempt admission'}).waitFor();
  await writeFile(receiptPath, receipt);
  await page.locator('#capture-finish').click(); await open(metadata.captures[0]);

  // A dirty source is visibly separate; Save guards still own file mutation.
  await page.locator('#editor-advanced').evaluate(el => {el.open = true;});
  const source = await page.locator('#editor-source').inputValue();
  await page.locator('#editor-source').fill(source + '\n# pending browser draft\n');
  assert.match(await page.locator('#capture-source').textContent(), /Unsaved draft edits/);
  assert.equal(await page.locator('#capture-launch').isEnabled(), true);
  await page.locator('nav a[href="#slow-control"]').click(); await page.locator('nav a[href="#workflow"]').click();
  assert.match(await page.locator('#editor-source').inputValue(), /pending browser draft/);
  // Storage refusal must prevent POST; it must not silently launch an unrecoverable UUID.
  await page.evaluate(() => {window.originalSetItem = Storage.prototype.setItem; Storage.prototype.setItem = function(key, value) {if (key === 'siderius.reusable-candidate.v1') throw new Error('offline storage fixture'); return window.originalSetItem.call(this, key, value);};});
  const beforeStorage = requests.length; await page.locator('#capture-launch').click();
  await page.locator('#capture-status').filter({hasText: 'Launch not sent'}).waitFor(); assert.equal(requests.length, beforeStorage);
  await page.evaluate(() => {Storage.prototype.setItem = window.originalSetItem;});
  // Capture survives authored source edit. GUI review does not re-read that source.
  await writeFile(metadata.source, source + '\n# saved future version\n');
  await writeFile(join(root, 'hold-review'), 'hold');
  let dropped = false, admitted;
  await page.route('**/reusable-captures/launch', async route => {
    const persisted = await page.evaluate(() => JSON.parse(localStorage.getItem('siderius.reusable-candidate.v1')));
    assert.deepEqual(JSON.parse(route.request().postData()), persisted.payload, 'Exact payload must be durable before POST');
    const response = await route.fetch(); assert.equal(response.status(), 202); admitted = await response.json(); dropped = true;
    await route.abort('failed');
  });
  await page.locator('#capture-launch').click(); await until(() => dropped);
  const intent = await page.evaluate(() => localStorage.getItem('siderius.reusable-candidate.v1'));
  assert.equal(JSON.parse(intent).payload.candidate_operation_id, admitted.operation_id);
  await page.route('**/api/operations/' + admitted.operation_id, route => route.fulfill({status: 401, json: {error: {message: 'Fixture token expired'}}}));
  await page.locator('#capture-check').click(); await page.locator('#access-status').filter({hasText: 'Connection unavailable'}).waitFor();
  assert.equal(await page.locator('#capture-retry').isDisabled(), true);
  assert.equal(await page.evaluate(() => localStorage.getItem('siderius.reusable-candidate.v1')), intent);
  assert.match(await page.locator('#editor-source').inputValue(), /pending browser draft/);
  await page.unroute('**/api/operations/' + admitted.operation_id); await connect();

  await until(async () => (await readFile(join(root, 'provider-calls.jsonl'), 'utf8')).includes('offline-review'));
  await context.close(); await stop(server);
  server = start('serve', root); await ready(); // Required configuration resources are intact at startup.
  await unlink(join(root, 'hold-review'));
  context = await browser.newContext(); await context.addInitScript(value => localStorage.setItem('siderius.reusable-candidate.v1', value), intent);
  page = await context.newPage(); page.on('pageerror', error => faults.push(error.message));
  await page.goto(origin + '/#workflow'); await connect();
  // Restored ambiguous intent must not gain dismissal from a later preclaim signal.
  await page.route('**/reusable-captures/launch', route => route.fulfill({status: 409, json: {error: {code: 'task_policy', message: 'Fixture later refusal', admission_not_attempted: true}}}));
  await page.locator('#capture-retry').click();
  await page.locator('#capture-operation-status').filter({hasText: 'Outcome unconfirmed'}).waitFor();
  assert.equal(await page.locator('#capture-finish').isHidden(), true);
  assert.equal(await page.evaluate(() => localStorage.getItem('siderius.reusable-candidate.v1')), intent);
  await page.unroute('**/reusable-captures/launch');
  await page.locator('#capture-check').click();
  await until(async () => {await page.locator('#capture-check').click(); return (await page.locator('#capture-operation-status').textContent()).includes('completed');}, 90000);
  assert.match(await page.locator('#capture-operation-status').textContent(), /Native accepted/);
  const callsBeforeRecovery = (await readFile(join(root, 'provider-calls.jsonl'), 'utf8')).trim().split('\n').length;
  await rename(metadata.captures[0].envelope, join(root, 'first-native-evidence'));
  await rename(metadata.source, metadata.source + '.saved'); await rename(metadata.credential, metadata.credential + '.saved');
  await page.locator('#capture-retry').click(); await page.locator('#capture-operation-status').filter({hasText: 'existing'}).waitFor();
  assert.equal((await readFile(join(root, 'provider-calls.jsonl'), 'utf8')).trim().split('\n').length, callsBeforeRecovery);
  // Restore native output location for monitor reads; exact-ID recovery above required no envelope.
  await rename(join(root, 'first-native-evidence'), metadata.captures[0].envelope);
  await page.locator('#capture-monitor').click(); await page.locator('#monitor-status').filter({hasText: 'completed'}).waitFor();
  await page.screenshot({path: join(evidence, 'recovered-monitor.png'), fullPage: true});
  // Restore configured resources for the other fresh admissions; recovery above ran without them.
  await rename(metadata.source + '.saved', metadata.source); await rename(metadata.credential + '.saved', metadata.credential);
  await page.locator('nav a[href="#workflow"]').click(); await page.locator('#capture-check').click();
  await page.locator('#capture-finish').waitFor(); await page.locator('#capture-finish').click();
  await page.locator('#capture-task').selectOption('synthetic');
  await page.locator('#capture-refresh').click(); await open(metadata.captures[1]);
  assert.match(await page.locator('#capture-source').textContent(), /differs/);
  await page.screenshot({path: join(evidence, 'capture-review.png'), fullPage: true});
  await writeFile(join(root, 'reject'), 'reject'); await page.locator('#capture-launch').click();
  await until(async () => {await page.locator('#capture-check').click(); return (await page.locator('#capture-operation-status').textContent()).includes('completed');}, 90000);
  assert.match(await page.locator('#capture-operation-status').textContent(), /Native rejected/);
  await unlink(join(root, 'reject'));
  const secondId = await page.locator('#capture-operation-id').textContent();
  const direct = JSON.parse(await completed(start('headless', root)));
  assert.equal(direct.receipt.status, 'accepted');
  const firstRecord = JSON.parse(await readFile(join(metadata.state, 'operations', admitted.operation_id, 'request.json')));
  const secondRecord = JSON.parse(await readFile(join(metadata.state, 'operations', secondId, 'request.json')));
  assert.notEqual(firstRecord.native_id, secondRecord.native_id);
  assert.notEqual(firstRecord.submission.request.preview.project_root, secondRecord.submission.request.preview.project_root);
  for (const [index, record] of [firstRecord, secondRecord].entries()) {
    const originalEnvelope = metadata.captures[index].envelope;
    const directory = originalEnvelope;
    assert.equal(record.submission.request.implementation_advice, 'Keep diagnostics explicit');
    assert.deepEqual(record.submission.request.preview.document.definition.nodes.map(node => node.id), ['hypothesis', 'build', 'check']);
    const proposal = JSON.parse(await readFile(join(directory, 'inputs/proposal.json')));
    assert.deepEqual(proposal.allowed_output_types, ['classifier']);
    assert.ok(proposal.storage.local.workspace.startsWith(metadata.captures[index].workspace));
    const native = JSON.parse(await readFile(join(directory, 'workspace/candidate_run/receipt.json')));
    assert.equal(native.native_output_paths.length, 3);
    const validationPath = native.native_output_paths[2].replace(originalEnvelope, directory);
    const validation = JSON.parse(await readFile(validationPath));
    assert.equal(validation.tests_passed, true); assert.equal(validation.gradient_check_passed, true);
  }
  assert.deepEqual(faults, []);
  assert.equal(await page.evaluate(secret => JSON.stringify({...localStorage, ...sessionStorage}).includes(secret), metadata.token), false);
  await writeFile(join(evidence, 'result.json'), JSON.stringify({result: 'PASS', root, operationIds: [admitted.operation_id, secondId, direct.operation_id], providerCalls: (await readFile(join(root, 'provider-calls.jsonl'), 'utf8')).trim().split('\n').length, faults}, null, 2));
  console.log(JSON.stringify({result: 'PASS', evidence}));
} finally {
  if (browser) await browser.close();
  await stop(server); await stop(provider);
  await writeFile(join(evidence, 'processes.json'), JSON.stringify(children.map(child => ({mode: child.mode, exitCode: child.exitCode, signal: child.signalCode, errors: child.errors})), null, 2));
}
