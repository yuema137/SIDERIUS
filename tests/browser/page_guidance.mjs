/** Page guidance witness: real Chromium + real authoring API + temporary ordinary Python project.
 * Covers the separate #run page, the "Next: prepare a run" handoff gated only by the
 * New run gate (window.newRunGate), the first-run "Start from a task example" guide,
 * the Task > Workflow > Run > Results step indicator and the collapsed secondary detail.
 * The empty-canvas start state names the next action; the tour itself is layout_onboarding.mjs.
 * The fixture configures no runnable project, so one projects reply is rewritten to mark
 * `reusable` runnable; no preparation, launch, provider call or file write is performed.
 * Explicit env: EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = ''; server.stderr.on('data', chunk => {errors += chunk;});
const lines = createInterface({input: server.stdout});
let browser;
async function waitUntil(predicate) { const deadline = Date.now() + 15000; while (!(await predicate())) { if (Date.now() > deadline) throw new Error('Browser condition timed out'); await new Promise(r => setTimeout(r, 50)); } }
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Server startup timeout: ${errors}`)), 15000);
    lines.on('line', line => {
      try { const value = JSON.parse(line); if (!value.origin || !value.token) return; clearTimeout(timer); lines.close(); accept(value); }
      catch { /* Native plugin registration may write one informational line first. */ }
    });
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Server ${code}: ${errors}`));});
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push(new URL(request.url()).pathname); });
  await page.route('**/api/editor/projects', async route => {
    const response = await route.fetch(), json = await response.json();
    await route.fulfill({response, json: json.map(item => ({...item, candidate_run_enabled: item.project_id === 'reusable'}))});
  });
  const nav = async view => { await page.locator(`nav a[href="#${view}"]`).click(); await page.locator(`#view-${view}`).waitFor(); };
  const current = () => page.locator('#step-indicator a[aria-current="step"]').textContent();
  const next = page.locator('#workflow-next-run');

  // Inventory: Run preparation is its own page, not part of Workflow.
  await page.goto(metadata.origin + '/#workflow');
  assert.equal(await page.locator('#view-workflow #new-run-task, #view-workflow #capture-run').count(), 0, 'Workflow page carries no run preparation');
  assert.equal(await page.locator('#view-run #new-run-task').count(), 1);
  assert.equal(await page.locator('#view-run #capture-launch').count(), 1);
  assert.deepEqual(await page.locator('nav.actions a').allTextContents(), ['Home', 'Workflow Editor', 'Run', 'Monitor']);

  // First run, before Connect: the task-example guide and the Task step lead.
  assert.equal(await page.locator('#workflow-start-guide').isVisible(), true);
  assert.match(await page.locator('#start-guide-heading').textContent(), /Build your research loop/);
  assert.equal(await page.locator('#workflow-start-guide button').count(), 1, 'The empty canvas offers one action');
  assert.match(await page.locator('#workflow-start-state').textContent(), /Connect/);
  assert.equal(await current(), 'Task');
  assert.equal(await next.isDisabled(), true);

  // Secondary detail is collapsed; Save is the only primary editor action.
  for (const id of ['workflow-details', 'editor-advanced', 'editor-review-disclosure']) assert.equal(await page.locator('#' + id).getAttribute('open'), null, id);
  assert.equal(await page.locator('#editor-advanced > summary').textContent(), 'Advanced source');
  assert.equal(await page.locator('#workflow-details > summary').textContent(), 'Details');
  assert.equal(await page.locator('#workflow-details').getByText('Cooperating API writers', {exact: false}).isVisible(), false);
  assert.deepEqual(await page.locator('.workflow-actions .actions button:not(.secondary)').evaluateAll(items => items.map(item => item.id)), ['editor-save']);

  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'));
  assert.equal(await page.locator('#workflow-start-guide').isHidden(), true, 'The empty-canvas start state yields to the workflow');
  assert.equal(await current(), 'Workflow');
  assert.match(await page.locator('#step-indicator li[data-step="task"]').getAttribute('class') || '', /done/);
  // The first project is not runnable: the handoff stays closed and says why.
  assert.equal(await next.isDisabled(), true);
  assert.match(await page.locator('#workflow-next-state').textContent(), /not enabled for runs.*saved version/);
  assert.equal(await page.evaluate(() => window.newRunGate.ready), false);

  // A runnable, saved, unchanged reusable workflow opens the gate; Next goes to #run.
  await page.locator('#editor-project').selectOption('reusable');
  await waitUntil(async () => !(await next.isDisabled()));
  assert.equal(await page.evaluate(() => window.newRunGate.ready), true, 'Next follows the New run gate');
  const saved = await page.evaluate(() => window.workflowEditor.state.savedSha256);
  assert.match(await page.locator('#workflow-next-state').textContent(), new RegExp(`Saved version ${saved.slice(0, 12)} of reusable is ready to run`));
  await next.click(); await page.locator('#view-run').waitFor();
  assert.equal(new URL(page.url()).hash, '#run');
  assert.equal(await page.title(), 'SIDERIUS · Run');
  assert.equal(await page.locator('nav a[aria-current="page"]').textContent(), 'Run');
  assert.equal(await current(), 'Run');
  assert.match(await page.locator('#step-indicator li[data-step="workflow"]').getAttribute('class') || '', /done/);
  assert.match(await page.locator('#run-source-state').textContent(), /ready to run/);
  assert.equal(await page.locator('#view-workflow').isHidden(), true);
  await page.locator('#new-run-task').waitFor();

  // Any unsaved edit closes the gate on both pages without a request.
  await nav('workflow');
  await page.locator('#editor-advanced > summary').click();
  const source = page.locator('#editor-source');
  await source.fill((await source.inputValue()) + '\n# unsaved page guidance edit\n');
  await waitUntil(async () => next.isDisabled());
  assert.equal(await page.evaluate(() => window.newRunGate.ready), false);
  assert.match(await page.locator('#workflow-next-state').textContent(), /Save first/);
  await nav('run');
  assert.match(await page.locator('#run-source-state').textContent(), /Save first/);
  assert.equal(await page.locator('#new-run-review').isDisabled(), true);
  await page.locator('#view-run').getByRole('link', {name: 'Back to workflow'}).click();
  await page.locator('#view-workflow').waitFor();
  assert.match(await source.inputValue(), /unsaved page guidance edit/, 'Route changes keep the draft');

  // Home keeps the journey without the step indicator; Monitor is the Results step.
  await nav('home');
  assert.equal(await page.locator('#step-indicator').isHidden(), true);
  await nav('monitor');
  assert.equal(await current(), 'Results');

  assert.equal(await readFile(metadata.reusable_source, 'utf8').then(text => text.includes('unsaved page guidance edit')), false);
  assert.deepEqual(posts.filter(path => !path.endsWith('/draft')), [], 'Guidance and navigation never review, save, prepare or launch');
  assert.deepEqual(faults, []);
  console.log('PASS: separate Run page, gate-owned Next handoff, task-example first-run guide, step indicator, collapsed detail');
} finally {
  await browser?.close();
  server.kill();
}
