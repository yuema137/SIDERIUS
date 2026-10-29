/** Experiment setups witness: the Workflow setup select lists only the selected task's
 * setups; "New setup…" creates one from a template or blank (real POST into an init
 * workspace, tests/browser/setups_fixture.py); the created setup opens, is saved and runs
 * with its task as a read-only fact; a drifted setup shows the reference banner; a console
 * that does not create setups explains who turns it on. No preparation is started.
 * Requires EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE, CONSOLE_EVIDENCE_DIR.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir, readFile, stat} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_EVIDENCE_DIR']) assert.ok(process.env[name], `Set ${name}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR; await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.setups_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = ''; server.stderr.on('data', chunk => {errors += chunk;});
const lines = createInterface({input: server.stdout});
let browser;
async function waitUntil(predicate, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error('Condition timed out'); await new Promise(done => setTimeout(done, 50)); }
}
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error('Server startup timeout')), 30000);
    lines.once('line', line => {clearTimeout(timer); accept(JSON.parse(line));});
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Server ${code}: ${errors}`));});
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1280, height: 900}}), faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push(new URL(request.url()).pathname); });
  // A ready task summary (the sandboxed observation is not run here) declares the metrics.
  const policy = {preparation_timeout_seconds: 300, candidate_timeout_seconds: 3600, candidate_network: false, candidate_devices: [], candidate_environment_names: [], allowed_output_types: null};
  const summary = {schema_version: 'siderius.console-task-summary/v1', task_id: 'synthetic', label: 'Synthetic task', state: 'ready', data_root: '/fixture/data', run_policy: policy,
    data_volume: {files: 1, bytes: 10, complete: true, entry_cap: 100000}, failure: null, unavailable: null,
    package: {identity: {semantic_fingerprint: 'a'.repeat(64), task_data_path_id: 'synthetic', task_revision: null, revision_matches: null}, description: null, model_io: null, partition_count: null,
      main_score: {metric_id: 'accuracy', direction: 'higher', aggregation: 'mean'}, observational_metrics: [{metric_id: 'loss', direction: 'lower', aggregation: 'mean'}],
      locked_parameters: [], objective: null, objective_source: 'planner_chooses', deliverable: null, health: {declaration: 'explicit_none', gates: []}, plugins: [], model_types: [],
      scopes: {state: 'not_declared', basis: 'fixture', training: null, evaluation: null, message: null}, sample_counts: null}};
  await page.route('**/api/tasks/synthetic/summary**', route => route.fulfill({json: summary}));
  for (let attempt = 0; attempt < 50; attempt++) { try { await page.goto(metadata.origin + '/#workflow'); break; } catch { await page.waitForTimeout(200); } }
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();

  // One configured task is chosen automatically; it has no setup yet.
  await page.locator('#editor-status').filter({hasText: 'This task has no experiment setup yet'}).waitFor();
  assert.equal(await page.locator('#editor-project option').count(), 0);
  assert.equal(await page.locator('label[for="editor-project"]').textContent(), 'Experiment setup');

  // New setup…: templates and Blank; a label is required.
  const dialog = page.locator('#setup-new-dialog');
  await page.locator('#setup-new').click();
  await page.locator('.setup-new-shape').filter({hasText: 'Blank'}).waitFor();
  assert.match(await page.locator('#setup-new-intro').textContent(), /Synthetic task/);
  assert.equal(await page.locator('.setup-new-shape input[value="single-loop-with-advice"]').isChecked(), true, 'The research loop starts selected');
  await page.locator('#setup-new-create').click();
  assert.match(await page.locator('#setup-new-status').textContent(), /Enter a label/);
  assert.deepEqual(posts, [], 'No request without a label');
  await page.locator('#setup-new-label').fill('My loop');
  assert.equal(await page.locator('#setup-new-status').textContent(), '', 'The label hint hides once a label is typed');
  await page.screenshot({path: join(evidence, 'setup-new-light.png')});
  await page.locator('#theme-preference').evaluate(select => { select.value = 'dark'; select.dispatchEvent(new Event('change', {bubbles: true})); });
  await page.screenshot({path: join(evidence, 'setup-new-dark.png')});
  await page.locator('#theme-preference').evaluate(select => { select.value = 'light'; select.dispatchEvent(new Event('change', {bubbles: true})); });
  await page.locator('#setup-new-create').click();
  await waitUntil(async () => !(await dialog.evaluate(element => element.open)));
  await page.locator('#editor-status').filter({hasText: 'Opened '}).waitFor();
  assert.equal(await page.locator('#editor-project').inputValue(), 'my-loop');
  assert.equal(await page.locator('#editor-project option:checked').textContent(), 'My loop');
  assert.deepEqual(posts, ['/api/tasks/synthetic/setups']);
  const source = join(metadata.workspace, 'projects', 'my-loop', 'workflow.py');
  assert.match(await readFile(source, 'utf8'), /advice/i, 'The research-loop template was rendered into the setup');
  assert.equal((await stat(source)).mode & 0o777, 0o600);

  // N1: the page bar names the setup's own task, never "not bound"; a version pin is a
  // separate, optional note shown only when the task declares versions.
  await waitUntil(async () => (await page.locator('#editor-task-chip').textContent()) === 'Task: Synthetic task');
  assert.equal(await page.locator('#editor-task-version').isHidden(), true, 'An unversioned task needs no pin note');
  await page.route('**/api/tasks', async route => {
    const response = await route.fetch(), json = await response.json();
    await route.fulfill({response, json: {...json, tasks: json.tasks.map(task => ({...task, revision: 'r1', package_id: 'synthetic-package'}))}});
  });
  await page.evaluate(() => window.consoleTask.reload());
  await page.locator('#editor-task-version').filter({hasText: 'Task version: not pinned'}).waitFor();
  assert.match(await page.locator('#editor-task-version').getAttribute('title'), /Task versions are optional/);
  assert.equal(await page.locator('#editor-task-chip').textContent(), 'Task: Synthetic task');
  await page.screenshot({path: join(evidence, 'page-bar-task.png')});
  await page.unroute('**/api/tasks');
  await page.evaluate(() => window.consoleTask.reload());
  await waitUntil(async () => page.locator('#editor-task-version').isHidden());

  // F11: a new metric-threshold stop starts with the task's main score metric id, and the
  // field suggests the task's declared metric ids.
  await page.locator('#editor-loop-add-metric-threshold').click();
  assert.equal(await page.locator('#editor-loop-stop-metric-id').inputValue(), 'accuracy');
  assert.equal(await page.locator('#editor-loop-stop-metric-id').getAttribute('list'), 'task-metric-ids');
  assert.deepEqual(await page.locator('#task-metric-ids option').evaluateAll(options => options.map(option => option.value)), ['accuracy', 'loss']);
  await page.locator('#editor-loop-stop-threshold').fill('0.9');

  // Save an edit, then Run: the setup's task is a read-only fact on the Run page.
  await page.locator('#editor-advanced').evaluate(element => { element.open = true; });
  const editor = page.locator('#editor-source');
  await page.locator('#editor-review').click();
  await waitUntil(async () => page.locator('#editor-save').isEnabled());
  await page.locator('#editor-version-name').fill('with stop');
  await page.locator('#editor-save').click();
  await waitUntil(async () => /metric_id='accuracy'/.test(await readFile(source, 'utf8')) && !(await page.evaluate(() => window.workflowEditor.state.dirty)));
  await editor.fill((await editor.inputValue()) + '\n# first saved edit\n');
  await page.locator('#editor-review').click();
  await waitUntil(async () => page.locator('#editor-save').isEnabled());
  await page.locator('#editor-version-name').fill('first');
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await readFile(source, 'utf8')).includes('# first saved edit') && !(await page.evaluate(() => window.workflowEditor.state.dirty)));
  await waitUntil(async () => page.locator('#workflow-next-run').isEnabled());
  await page.locator('#workflow-next-run').click(); await page.locator('#view-run').waitFor();
  assert.equal(await page.locator('#run-setup-header').textContent(), 'Setup: My loop · Task: Synthetic task');
  await page.locator('#new-run-task-fact').filter({hasText: 'Task: Synthetic task'}).waitFor();
  assert.equal(await page.locator('#new-run-task').isHidden(), true, 'The task is not a choice for a setup');
  await waitUntil(async () => (await page.locator('#new-run-task').inputValue()) === 'synthetic');
  // Runs of this setup: the store's attribution, newest first, honest about the scan limit.
  await page.locator('#setup-runs-status').filter({hasText: 'No runs of this setup yet.'}).waitFor();
  const runs = [{operation_id: '44444444-4444-4444-8444-444444444444', kind: 'candidate', run_name: 'my-loop-b', project_id: 'my-loop', admitted_at: '2026-10-29T10:00:00+00:00', state: 'completed', native_status: 'completed'},
    {operation_id: '55555555-5555-4555-8555-555555555555', kind: 'prepare_reusable', run_name: 'my-loop-a', project_id: 'my-loop', admitted_at: '2026-10-29T09:00:00+00:00', state: 'completed', native_status: 'prepared'}];
  const listed = [];
  await page.route('**/api/operations?**', route => { const url = new URL(route.request().url()); listed.push(url.searchParams.get('project_id'));
    return url.searchParams.get('project_id') ? route.fulfill({json: {operations: runs, unreadable: 0, examined: 4096, incomplete: true}}) : route.continue(); });
  await page.locator('#setup-runs-refresh').click();
  await page.locator('#setup-runs-list a').first().waitFor();
  assert.deepEqual(listed, ['my-loop']);
  assert.deepEqual(await page.locator('#setup-runs-list a').evaluateAll(links => links.map(link => link.getAttribute('href'))),
    ['#monitor/44444444-4444-4444-8444-444444444444', '#monitor/55555555-5555-4555-8555-555555555555']);
  assert.match(await page.locator('#setup-runs-status').textContent(), /2 runs of this setup, most recent first\..*older runs may be missing/);
  await page.unroute('**/api/operations?**');
  await page.screenshot({path: join(evidence, 'run-setup-header.png'), fullPage: true});

  // A second, blank setup; both are listed for the task, newest opened.
  await page.locator('nav a[href="#workflow"]').click();
  await page.locator('#setup-new').click();
  await page.locator('.setup-new-shape').filter({hasText: 'Blank'}).click();
  await page.locator('#setup-new-label').fill('Blank one');
  await page.locator('#setup-new-create').click();
  await waitUntil(async () => (await page.locator('#editor-project').inputValue()) === 'blank-one');
  assert.deepEqual(await page.locator('#editor-project option').allTextContents(), ['My loop', 'Blank one']);

  // Pending edits are never dropped silently: declining keeps the open setup, listed as it
  // was (its own label and task, not "Other workflows"); accepting switches.
  await page.locator('#editor-source').fill((await page.locator('#editor-source').inputValue()) + '\n# unsaved blank edit\n');
  await waitUntil(() => page.evaluate(() => window.workflowEditor.state.dirty));
  const confirms = [];
  page.once('dialog', dialog => { confirms.push(dialog.message()); void dialog.dismiss(); });
  await page.evaluate(() => window.experimentSetups.load('my-loop', true));
  assert.match(confirms[0], /Discard pending edits and open another experiment setup/);
  assert.equal(await page.locator('#editor-project').inputValue(), 'blank-one');
  assert.deepEqual(await page.locator('#editor-project option').allTextContents(), ['My loop', 'Blank one (unsaved edits)']);
  assert.equal(await page.locator('#editor-project optgroup').count(), 0, 'The kept setup stays in its task group');
  assert.equal(await page.evaluate(() => window.experimentSetups.current?.taskId), 'synthetic');
  assert.match(await page.locator('#editor-source').inputValue(), /unsaved blank edit/);
  page.once('dialog', dialog => void dialog.accept());
  await page.evaluate(() => window.experimentSetups.load('my-loop', true));
  await waitUntil(async () => (await page.locator('#editor-project').inputValue()) === 'my-loop' && !(await page.evaluate(() => window.workflowEditor.state.dirty)));

  // Drift: a setup whose references differ from the task offers the reference update.
  await page.route('**/api/tasks/synthetic/setups', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch(), json = await response.json();
    await route.fulfill({response, json: {...json, setups: json.setups.map(item => ({...item, refs_match_task: item.setup_id !== 'my-loop'}))}});
  });
  await page.evaluate(() => window.experimentSetups.load('my-loop', true));
  await page.locator('#setup-drift').waitFor();
  await page.screenshot({path: join(evidence, 'setup-drift.png')});
  await page.locator('#setup-drift-update').click();
  await page.locator('#view-task').waitFor();
  assert.equal(await page.locator('#editor-task-panel').evaluate(element => element.open), true);
  await page.unroute('**/api/tasks/synthetic/setups');

  // A 409 (for example an identity mismatch) shows the server message and its finding.
  await page.route('**/api/tasks/synthetic/setups', route => route.request().method() === 'POST'
    ? route.fulfill({status: 409, json: {error: {code: 'identity_mismatch', message: 'task identity does not match task_revision'}, finding: {state: 'blocked', code: 'identity_mismatch', message: 'The package changed since task_revision was recorded.', reference: 'task_binding'}}})
    : route.continue());
  await page.locator('nav a[href="#workflow"]').click();
  await page.locator('#setup-new').click();
  await page.locator('#setup-new-label').fill('Mismatch');
  await page.locator('#setup-new-label').press('Enter');
  await page.locator('#setup-new-status').filter({hasText: 'task identity does not match task_revision The package changed'}).waitFor();
  assert.equal(await dialog.evaluate(element => element.open), true);
  await page.locator('#setup-new-dialog .actions button.secondary').click();
  await page.unroute('**/api/tasks/synthetic/setups');

  // A console that does not create setups says who turns it on; nothing is created.
  await page.route('**/api/tasks/synthetic/setups', route => route.request().method() === 'POST'
    ? route.fulfill({status: 403, json: {error: {code: 'read_only', message: 'this console does not create experiment setups'}}})
    : route.continue());
  await page.locator('nav a[href="#workflow"]').click();
  await page.locator('#setup-new').click();
  await page.locator('#setup-new-label').fill('Refused');
  await page.locator('#setup-new-create').click();
  await page.locator('#setup-new-status').filter({hasText: 'browser_creatable'}).waitFor();
  assert.match(await page.locator('#setup-new-status').textContent(), /console operator.*restarts the console/);
  assert.equal(await dialog.evaluate(element => element.open), true);
  await page.locator('#setup-new-dialog .actions button.secondary').click();
  await page.unroute('**/api/tasks/synthetic/setups');

  // Creation turned off is said before any click; existing setups still open.
  await page.route('**/api/tasks/synthetic/setups', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch(), json = await response.json();
    await route.fulfill({response, json: {...json, browser_creatable: false}});
  });
  const before = posts.length;
  await page.evaluate(() => window.experimentSetups.load(null, true));
  await waitUntil(async () => (await page.locator('#setup-new').getAttribute('title') || '').includes('browser_creatable'));
  await page.locator('#setup-new').click();
  await page.locator('#setup-new-status').filter({hasText: 'You can still open existing setups'}).waitFor();
  assert.equal(await page.locator('#setup-new-create').isDisabled(), true);
  await page.locator('#setup-new-label').press('Enter');
  assert.equal(posts.length, before, 'Nothing is sent while creation is off');
  await page.locator('#setup-new-dialog .actions button.secondary').click();
  assert.equal(await page.locator('#editor-project option').count(), 2, 'Existing setups stay listed');
  assert.deepEqual(faults, []);
  console.log('PASS experiment setups: task-scoped list, template and blank creation, save then Run with the task fixed, pending-edit confirm, drift banner, 409 and 403 refusals, creation off');
} finally {
  await browser?.close();
  server.kill();
}
