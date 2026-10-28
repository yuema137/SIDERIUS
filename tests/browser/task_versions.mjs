/** Real native offline observation + authenticated HTTP authoring, no providers/data/training.
 * Metadata drift and delayed responses are isolated transport-fence witnesses.
 * Uses existing EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE,
 * and a fresh CONSOLE_EVIDENCE_DIR for screenshots.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_EVIDENCE_DIR']) assert.ok(process.env[key], `Set ${key}`);
await mkdir(process.env.CONSOLE_EVIDENCE_DIR, {recursive: false});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.task_versions_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => {errors += chunk;});
const lines = createInterface({input: server.stdout});
const waitUntil = async predicate => {
  const deadline = Date.now() + 30000;
  while (!(await predicate())) {if (Date.now() > deadline) throw new Error('Condition timed out'); await new Promise(resolve => setTimeout(resolve, 50));}
};
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture startup timeout: ' + errors)), 45000);
    lines.once('line', line => {clearTimeout(timer); accept(JSON.parse(line));});
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Fixture exit ${code}: ${errors}`));});
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}}), faults = [], requests = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => {if (request.method() === 'POST') requests.push({path: new URL(request.url()).pathname, body: request.postDataJSON()});});
  await page.goto(metadata.origin + '/#workflow');
  const connect = async token => {if (await page.locator('#access-change').isVisible()) await page.locator('#access-change').click(); await page.locator('#token').fill(token); await page.locator('#access-form button').click();};
  await connect(metadata.token);
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  await page.waitForFunction(() => document.querySelector('#editor-source').value.length > 0 && document.querySelector('#editor-task-choice').options.length === 3);
  const choice = page.locator('#editor-task-choice'), update = page.locator('#editor-task-update'), save = page.locator('#editor-save'), source = page.locator('#editor-source');
  assert.equal(await choice.inputValue(), '', 'No automatic selection');
  const original = await readFile(metadata.source, 'utf8');
  await choice.selectOption('synthetic');
  assert.equal(await source.inputValue(), original, 'Choosing alone never rewrites source');
  // Existing unbound edits save as unbound even while a task choice is selected.
  await page.locator('#editor-advanced').evaluate(element => {element.open = true;});
  await source.fill(original + '\n# unbound edit first\n');
  assert.ok(await update.isDisabled());
  assert.match(await page.locator('#editor-task-message').textContent(), /Save existing edits first/);
  await page.locator('#editor-review').click(); await waitUntil(async () => save.isEnabled());
  assert.equal(requests.at(-1).body.task_reference_selection, undefined);
  await save.click(); await waitUntil(async () => (await readFile(metadata.source, 'utf8')).includes('# unbound edit first') && !(await page.evaluate(() => window.workflowEditor.state.dirty)));
  assert.ok(!(await readFile(metadata.source, 'utf8')).includes('TaskBinding('));
  await choice.selectOption('synthetic'); await update.click();
  await page.locator('#editor-task-adopt').waitFor();
  assert.match(await page.locator('#editor-task-message').textContent(), /reviewed, not saved/);
  assert.ok(await save.isDisabled());
  const updateRequest = requests.at(-1).body;
  assert.equal(updateRequest.proposal.kind, 'task_references');
  assert.equal(updateRequest.task_reference_selection, undefined);
  await page.locator('#editor-task-acknowledge').focus(); await page.keyboard.press('Space');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'editor-task-acknowledge', 'Rerender preserves keyboard focus');
  assert.ok(await save.isDisabled());
  await page.screenshot({path: resolve(process.env.CONSOLE_EVIDENCE_DIR, 'adoption-light.png'), fullPage: true});
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'editor-task-adopt');
  await page.keyboard.press('Space'); assert.ok(await save.isEnabled());
  await save.click(); await waitUntil(async () => !(await page.evaluate(() => window.workflowEditor.state.dirty)) && (await readFile(metadata.source, 'utf8')).includes('TaskBinding('));
  const accepted = requests.findLast(item => item.path.endsWith('/save')).body.task_reference_acceptance;
  assert.deepEqual(accepted.selection.expected_task_binding, metadata.binding);
  assert.match(await readFile(metadata.source, 'utf8'), /native-proposal-fanout\/v1/);
  assert.equal(accepted.adopt_current_snapshot, true);
  assert.deepEqual(accepted.acknowledged_findings, [{code: 'identity_verified', reference: 'task_binding'}, {code: 'current_snapshot_adoption', reference: 'task_binding'}]);
  // A dirty bound edit can recover a matching choice and use ordinary Review/Save.
  await source.fill((await source.inputValue()) + '\n# bound source edit\n');
  const dirty = await source.inputValue();
  await choice.selectOption('changed'); assert.ok(await update.isDisabled());
  await choice.selectOption('synthetic'); assert.equal(await source.inputValue(), dirty);
  const before = requests.length;
  const forbiddenUpdate = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/review') && request.postDataJSON()?.proposal?.kind === 'task_references', {timeout: 250}).then(() => true, () => false);
  await update.evaluate(element => {element.dispatchEvent(new MouseEvent('click', {bubbles: true}));});
  assert.equal(await forbiddenUpdate, false, 'Dirty Update must not reach HTTP');
  assert.equal(requests.length, before, 'Callback guard forbids dirty Update even on dispatched click');
  await page.locator('#editor-review').click(); await page.locator('#editor-task-acknowledge').waitFor();
  assert.equal(requests.at(-1).body.task_reference_selection.selected_choice_id, 'synthetic');
  await page.locator('#editor-task-acknowledge').check(); await save.click();
  await waitUntil(async () => !(await page.evaluate(() => window.workflowEditor.state.dirty)) && (await readFile(metadata.source, 'utf8')).includes('# bound source edit'));
  const boundAcceptance = requests.findLast(item => item.path.endsWith('/save')).body.task_reference_acceptance;
  assert.equal(boundAcceptance.adopt_current_snapshot, false);
  assert.deepEqual(boundAcceptance.acknowledged_findings, [{code: 'identity_verified', reference: 'task_binding'}, {code: 'authored_changes', reference: 'source'}]);
  // Inspector edits cannot be replaced by Update; a no-op document review still verifies.
  await page.locator('#editor-task-use-saved').click();
  const reference = page.locator('#editor-references input').first();
  await reference.evaluate(element => {element.dispatchEvent(new Event('input', {bubbles: true}));});
  assert.ok(await update.isDisabled()); assert.ok(await source.isDisabled());
  await page.locator('#editor-review').click(); await page.locator('#editor-task-acknowledge').waitFor();
  assert.equal(requests.at(-1).body.proposal.kind, 'document');
  assert.equal(requests.at(-1).body.proposal.document.execution_profile, 'native-proposal-fanout/v1');
  await page.locator('#editor-task-acknowledge').check();
  await choice.selectOption('changed'); assert.ok(await save.isDisabled(), 'Selection invalidates old acceptance');
  await choice.selectOption('synthetic'); await page.locator('#editor-review').click();
  await page.locator('#editor-task-acknowledge').waitFor(); await page.locator('#editor-task-acknowledge').check();
  await page.screenshot({path: resolve(process.env.CONSOLE_EVIDENCE_DIR, 'bound-review-light.png'), fullPage: true});
  await page.locator('#theme-preference').selectOption('dark');
  await page.screenshot({path: resolve(process.env.CONSOLE_EVIDENCE_DIR, 'bound-review-dark.png'), fullPage: true});
  await page.locator('#theme-preference').selectOption('light');
  await save.click(); await waitUntil(async () => !(await page.evaluate(() => window.workflowEditor.state.dirty)) && (await choice.inputValue()) === '');
  // Unsupported identity stays blocked and canonical source never changes.
  const canonical = await readFile(metadata.source, 'utf8');
  assert.match(canonical, /native-proposal-fanout\/v1/);
  await choice.selectOption('changed'); await update.click();
  await page.locator('#editor-task-findings').filter({hasText: 'compatibility_unresolved'}).waitFor();
  assert.ok(await save.isDisabled()); assert.equal(await page.locator('#editor-task-acknowledge').count(), 0);
  assert.equal(await readFile(metadata.source, 'utf8'), canonical);
  // Refresh explicitly discards the blocked proposal; stale review replies cannot replace edits.
  page.once('dialog', dialog => dialog.accept()); await page.locator('#editor-refresh').click();
  await waitUntil(async () => (await source.inputValue()) === canonical && (await choice.inputValue()) === '');
  await choice.selectOption('synthetic');
  let release, started, forwarded;
  const held = new Promise(resolve => {release = resolve;}), captured = new Promise(resolve => {started = resolve;});
  const continued = new Promise(resolve => {forwarded = resolve;});
  // Exactly one handling call per route: unrouting while a held handler is still in flight lets
  // Playwright auto-continue the request, and the handler's own continue() then fails with
  // 'Route is already handled!'. So the handler is single-use and unroute waits for it.
  await page.route('**/api/editor/versioned/review', async route => {started(); await held; await route.continue(); forwarded();}, {times: 1});
  await page.locator('#editor-review').click(); await captured;
  const delayedReview = page.waitForResponse(response => response.url().endsWith('/versioned/review'));
  await source.fill(canonical + '\n# newer than delayed review\n'); release();
  await continued; await page.unroute('**/api/editor/versioned/review');
  await delayedReview;
  assert.match(await source.inputValue(), /newer than delayed review/); assert.ok(await save.isDisabled());
  // Disconnect/reconnect and project conflict preserve the draft and require a fresh review.
  await connect('invalid-token'); await page.locator('#access-status').filter({hasText: /Connection failed|Connection unavailable/}).waitFor();
  assert.match(await source.inputValue(), /newer than delayed review/);
  await connect(metadata.token); await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  await waitUntil(async () => (await choice.inputValue()) === 'synthetic');
  assert.match(await source.inputValue(), /newer than delayed review/); assert.ok(await save.isDisabled());
  await writeFile(metadata.source, canonical + '\n# external conflict\n');
  await page.locator('#editor-review').click(); await page.locator('#editor-conflict').waitFor();
  assert.match(await source.inputValue(), /newer than delayed review/);
  await page.locator('#editor-rebase').click(); assert.ok(await save.isDisabled());
  await page.locator('#editor-review').click(); await page.locator('#editor-task-acknowledge').waitFor();
  await page.locator('#editor-task-acknowledge').check(); assert.ok(await save.isEnabled());
  // Metadata drift is a separate synthetic transport witness, never a mocked review/save.
  await page.route('**/api/editor/task-choices', async route => {
    const response = await route.fetch(), value = await response.json();
    value.choices[0].binding.revision = 'changed-config'; await route.fulfill({response, json: value});
  });
  await page.getByRole('button', {name: 'Refresh task choices', exact: true}).click();
  await waitUntil(async () => (await choice.inputValue()) === '');
  assert.ok(await save.isDisabled()); assert.match(await source.inputValue(), /newer than delayed review/);
  await page.setViewportSize({width: 390, height: 844});
  await page.screenshot({path: resolve(process.env.CONSOLE_EVIDENCE_DIR, 'dirty-narrow.png'), fullPage: true});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
  assert.deepEqual(faults, []);
  console.log('PASS task version adoption, exact acceptance, bound source/document save, dirty recovery, blocked identity, async/reconnect/conflict/catalog fences');
} finally {if (browser) await browser.close(); server.kill('SIGTERM'); lines.close();}
