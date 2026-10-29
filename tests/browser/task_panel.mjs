/** Task tab witness: the task list states, every read-only panel section, Count samples,
 * failed/unavailable states and the Workflow/Run gate without a selected task.
 * The real console fixture serves the page and authenticates; /api/tasks* replies are
 * synthetic task-summary fixtures (the sandboxed composition child is not run here).
 * Screenshots: /tmp/task-panel-<width>-<theme>.png (1280 and 900, light and dark).
 * Requires EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = ''; server.stderr.on('data', chunk => {errors += chunk;});
const lines = createInterface({input: server.stdout});
let browser;

const POLICY = {preparation_timeout_seconds: 300, candidate_timeout_seconds: 3600, candidate_network: true,
  candidate_devices: ['/dev/nvidia0', '/dev/nvidiactl', '/dev/nvidia-uvm'], candidate_environment_names: ['OPENAI_API_KEY'], allowed_output_types: null};
const BINDING = {schema_version: 'siderius.task-binding/v1', package_id: 'pets-segmentation', revision: 'r3', task_data_path_id: 'pets-data', semantic_fingerprint: 'f'.repeat(64)};
const PACKAGE = {
  identity: {semantic_fingerprint: 'f'.repeat(64), task_data_path_id: 'pets-data', task_revision: BINDING, revision_matches: true},
  description: 'Segment pets from the background in RGB photographs.',
  model_io: {input_shape: '[B, 3, 256, 256] float32', input_description: 'RGB image, normalized', output_shape: '[B, 3, 256, 256] float32', output_description: 'per-pixel class logits'},
  partition_count: 4,
  main_score: {metric_id: 'mean_iou', direction: 'higher', aggregation: 'mean_over_images'},
  observational_metrics: [{metric_id: 'pixel_accuracy', direction: 'higher', aggregation: 'fraction_correct_over_pixels'}],
  locked_parameters: [{path: 'training.batch_size', rule: 'exact', value: 32}, {path: 'training.epochs', rule: 'range', value: {min: 1, max: 40}}, {path: 'model.dropout', rule: 'exact', value: null}],
  objective: {loss_type: 'ce', alpha: null, gamma: null, beta: null, reduction: 'mean', use_class_weights: true, loss_name: null},
  objective_source: 'task',
  deliverable: {prefix: 'mask_', extension: '.png', index_width: 4},
  health: {declaration: 'declared', gates: [
    {gate_id: 'output_shape', checks: ['shape_matches_contract', 'finite_values'], role: 'blocking'},
    {gate_id: 'prediction_diversity', checks: ['class_balance'], role: 'observational'}]},
  plugins: [
    {configured_ref: 'plugins/pets_task.py', symbol: 'PetsTaskDataPath', roles: ['task_data_path']},
    {configured_ref: 'plugins/pets_metric.py', symbol: 'MeanIoUMetric', roles: ['primary_metric']},
    {configured_ref: 'plugins/unet.py', symbol: 'unet_small', roles: ['model_plugin']}],
  model_types: ['unet_small'],
  scopes: {state: 'declared', basis: "The task's full declared split before any run-level sampling (formal snapshot, portion 1.0, no sampling seed).",
    training: {file_count: 5880, expected_on_disk_bytes: 412345678}, evaluation: {file_count: 1469, expected_on_disk_bytes: 103456789}, message: null},
  sample_counts: null
};
const TASKS = [{task_id: 'pets', label: 'Oxford pets segmentation', revision: 'r3'}, {task_id: 'quickstart', label: 'Quickstart rows', revision: null},
  {task_id: 'broken', label: 'Broken package', revision: null}];
const view = (task, state, extra = {}) => ({schema_version: 'siderius.console-task-summary/v1', task_id: task.task_id, label: task.label, state,
  data_root: `/data/siderius_workspace/data/${task.task_id}`, run_policy: POLICY, data_volume: {files: 7349, bytes: 515802467, complete: true, entry_cap: 100000},
  package: null, failure: null, unavailable: null, ...extra});

try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error('Server startup timeout')), 15000);
    lines.once('line', line => {clearTimeout(timer); accept(JSON.parse(line));});
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Server ${code}: ${errors}`));});
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const context = await browser.newContext({viewport: {width: 1280, height: 900}});
  const page = await context.newPage(), faults = [], summaries = [];
  page.on('pageerror', error => faults.push(error.message));
  let listMode = 'fail', observing = 1, countObserving = 1, sandbox = 'missing';
  await page.route('**/api/tasks**', async route => {
    const url = new URL(route.request().url());
    assert.equal(route.request().method(), 'GET', 'The Task tab never mutates');
    assert.equal(route.request().headers().authorization, 'Bearer ' + metadata.token);
    if (url.pathname === '/api/tasks') {
      if (listMode === 'fail') return route.fulfill({status: 500, json: {error: {message: 'Fixture task list unavailable'}}});
      return route.fulfill({json: {tasks: listMode === 'empty' ? [] : TASKS}});
    }
    const id = decodeURIComponent(url.pathname.split('/')[3]), task = TASKS.find(item => item.task_id === id);
    summaries.push(url.pathname + url.search);
    if (id === 'broken') return route.fulfill({json: view(task, 'failed', {failure: {stage: 'composition', message: 'ImportError: cannot import name "PetsTaskDataPath" from plugins/pets_task.py'}})});
    if (id === 'quickstart') {
      if (sandbox === 'missing') return route.fulfill({json: view(task, 'unavailable', {data_volume: null, unavailable: {reason: 'sandbox_missing', hint: 'Install bubblewrap (bwrap) and enable user namespaces, then Refresh.'}})});
      return route.fulfill({json: view(task, 'ready', {package: {...PACKAGE, identity: {...PACKAGE.identity, task_revision: null, revision_matches: null},
        observational_metrics: [], locked_parameters: [], objective: null, objective_source: 'planner_chooses', deliverable: null,
        health: {declaration: 'explicit_none', gates: []}, scopes: {state: 'not_declared', basis: 'No storage_read_scope.', training: null, evaluation: null, message: null}},
      run_policy: {...POLICY, candidate_devices: ['/dev/nvidiactl'], candidate_network: false, candidate_environment_names: []}})});
    }
    if (url.searchParams.get('count_samples') === '1') {
      if (countObserving-- > 0) return route.fulfill({json: view(task, 'observing')});
      return route.fulfill({json: view(task, 'ready', {package: {...PACKAGE, sample_counts: {state: 'counted', training: 5880, evaluation: 1469, message: null}}})});
    }
    if (observing-- > 0) return route.fulfill({json: view(task, 'observing')});
    return route.fulfill({json: view(task, 'ready', {package: PACKAGE})});
  });

  // Before Connect the Task tab says what to do; Workflow is not yet gated.
  await page.goto(metadata.origin + '/#task');
  assert.equal(await page.locator('nav a[aria-current="page"]').textContent(), 'Task');
  assert.deepEqual(await page.locator('nav a').allTextContents(), ['Home', 'Task', 'Workflow', 'Run', 'Monitor', 'Settings']);
  assert.equal(await page.locator('#step-indicator li[data-step="task"] a').getAttribute('href'), '#task');
  assert.match(await page.locator('#task-list').textContent(), /Connect to see the configured tasks/);
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();

  // List error with Retry, then the empty state; both keep Workflow and Run closed.
  await page.locator('#task-list-error').filter({hasText: 'Fixture task list unavailable'}).waitFor();
  assert.equal(await page.locator('nav a[href="#workflow"]').getAttribute('aria-disabled'), 'true');
  listMode = 'empty'; await page.locator('#task-list-retry').click();
  await page.locator('#task-list-empty').waitFor();
  assert.match(await page.locator('#task-list-empty').textContent(), /siderius_workspace\/tasks\/<id>\/ and register it \(see the README\)/);
  for (const link of ['nav a[href="#workflow"]', 'nav a[href="#run"]', '#step-indicator a[href="#workflow"]', '#step-indicator a[href="#run"]']) {
    assert.equal(await page.locator(link).getAttribute('aria-disabled'), 'true', link);
    assert.equal(await page.locator(link).getAttribute('title'), 'Choose a task first', link);
  }
  await page.evaluate(() => { location.hash = 'workflow'; });
  await page.locator('#task-required-state').waitFor();
  assert.equal(await page.locator('#task-required-heading').textContent(), 'Workflow');
  assert.equal(await page.locator('#view-workflow').isVisible(), false, 'No task-less editor');
  await page.locator('#task-required-choose').click();
  assert.equal(new URL(page.url()).hash, '#task');

  // Three tasks: nothing is chosen automatically; choosing one opens Workflow.
  listMode = 'ok';
  await page.evaluate(() => window.consoleTask.reload());
  await page.locator('.task-item').first().waitFor();
  assert.deepEqual(await page.locator('.task-item-revision').allTextContents(), ['Version r3', 'unversioned', 'unversioned']);
  assert.equal(await page.locator('.task-item[aria-pressed="true"]').count(), 0, 'Several tasks: no automatic choice');
  await page.locator('.task-item[data-task-id="pets"]').click();
  assert.equal(await page.locator('nav a[href="#workflow"]').getAttribute('aria-disabled'), null);
  await page.locator('#task-summary-state[data-state="ready"]').waitFor({state: 'attached'});
  assert.ok(summaries.filter(item => item === '/api/tasks/pets/summary').length >= 2, 'observing is polled on the plain URL');

  // Every section in the contract's order, with human units.
  assert.deepEqual(await page.locator('#task-panel-body .task-section h3').allTextContents(),
    ['Identity', 'Data', 'Model input and output', 'Objective', 'Main score', 'Health checks', 'Evaluation and model plugins', 'Locked parameters', 'Deliverable', 'Run policy']);
  const text = id => page.locator(id).textContent();
  assert.match(await text('#task-identity'), /pets-segmentation · r3/);
  assert.equal(await page.locator('#task-identity details').getAttribute('open'), null, 'Fingerprint starts collapsed');
  assert.match(await text('#task-data'), /7,349.*516 MB/s);
  assert.match(await text('#task-data'), /Training split5,880 files · 412 MB/);
  assert.match(await text('#task-data'), /Evaluation split1,469 files · 103 MB/);
  assert.match(await text('#task-model-io'), /\[B, 3, 256, 256\] float32/);
  assert.match(await text('#task-objective'), /Loss typece/);
  assert.doesNotMatch(await text('#task-objective'), /null/, 'Unset objective fields are omitted');
  assert.match(await text('#task-main-score'), /mean_iou.*Higher is better.*mean_over_images/s);
  assert.match(await text('#task-observational-metrics'), /pixel_accuracy.*Recording/s);
  assert.deepEqual(await page.locator('#task-health-gates tbody tr td:last-child').allTextContents(), ['Blocking', 'Recording']);
  assert.match(await text('#task-plugin-table'), /MeanIoUMetric.*Main score/s);
  assert.match(await text('#task-locked-table'), /training\.batch_size.*Fixed to.*32/s);
  assert.match(await text('#task-locked-table'), /model\.dropout.*Fixed to.*null/s, 'An exact-null lock is shown');
  assert.match(await text('#task-deliverable'), /mask_/);
  assert.match(await text('#task-run-policy'), /5 min \(300 s\).*1 h \(3,600 s\).*Allowed.*Passed into the run sandbox \(\/dev\/nvidia0\).*OPENAI_API_KEY/s);

  // Count samples: an explicit, polled request.
  assert.equal(summaries.some(item => item.includes('count_samples')), false, 'Samples are counted only on request');
  await page.locator('#task-count-samples').click();
  await page.locator('#task-sample-counts').filter({hasText: 'Training samples'}).waitFor();
  assert.match(await text('#task-sample-counts'), /Training samples5,880.*Evaluation samples1,469/s);
  assert.ok(summaries.filter(item => item.endsWith('?count_samples=1')).length >= 2);

  // Light and dark, wide and narrow.
  for (const width of [1280, 900]) for (const theme of ['light', 'dark']) {
    await page.setViewportSize({width, height: 900});
    await page.locator('#theme-preference').selectOption(theme);
    await page.waitForTimeout(100);
    await page.screenshot({path: `/tmp/task-panel-${width}-${theme}.png`, fullPage: true});
  }
  await page.setViewportSize({width: 1280, height: 900}); await page.locator('#theme-preference').selectOption('light');

  // Failed and unavailable states name their stage, message and hint.
  await page.locator('.task-item[data-task-id="broken"]').click();
  await page.locator('#task-summary-state[data-state="failed"]').waitFor();
  assert.match(await text('#task-summary-state'), /stage: composition.*cannot import name.*Refresh/s);
  await page.screenshot({path: '/tmp/task-panel-failed.png', fullPage: true});
  await page.locator('.task-item[data-task-id="quickstart"]').click();
  await page.locator('#task-summary-state[data-state="unavailable"]').waitFor();
  assert.match(await text('#task-summary-state'), /sandbox is not available.*Install bubblewrap/s);
  await page.screenshot({path: '/tmp/task-panel-unavailable.png', fullPage: true});
  sandbox = 'ok'; await page.locator('#task-refresh').click();
  await page.locator('#task-summary-state[data-state="ready"]').waitFor({state: 'attached'});
  assert.ok(summaries.includes('/api/tasks/quickstart/summary?refresh=1'));
  assert.match(await text('#task-identity'), /Unversioned/);
  assert.match(await text('#task-data'), /not declared by this task/);
  assert.match(await text('#task-health'), /This task declares no Health checks/);
  assert.match(await text('#task-objective'), /planner chooses/);
  assert.match(await text('#task-run-policy'), /does not pass a GPU into the run sandbox; the run will be refused/);

  // The selection is remembered per store and survives a reload.
  await page.reload();
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('.task-item[aria-pressed="true"]').filter({hasText: 'Quickstart rows'}).waitFor();
  assert.deepEqual(faults, []);
  console.log('task panel witness: passed');
} finally {
  await browser?.close();
  server.kill();
}
