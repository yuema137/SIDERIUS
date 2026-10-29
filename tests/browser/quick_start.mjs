/** Home Quick start witness (#1131): the task list's loading, failed (Retry), empty and
 * loaded states; "Create a setup from the research-loop template" creates and opens it in
 * Workflow with the advice field focused; a second Quick start opens the existing setup;
 * a refused creation keeps the dialog open with the reason. Real init workspace fixture
 * (tests/browser/setups_fixture.py); only /api/tasks is held or failed by the witness.
 * Requires EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE, CONSOLE_EVIDENCE_DIR.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir, readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_EVIDENCE_DIR']) assert.ok(process.env[name], `Set ${name}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR; await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.setups_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = ''; server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
let browser;
async function waitUntil(predicate, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error('Browser condition timed out'); await new Promise(done => setTimeout(done, 50)); }
}
try {
  const metadata = await new Promise((accept, reject) => {
    lines.once('line', line => accept(JSON.parse(line)));
    server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`)));
    setTimeout(() => reject(new Error(`server startup timeout: ${serverErrors}`)), 30000);
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push(new URL(request.url()).pathname); });
  // The task list: first held (loading), then failed, then empty, then the real list.
  let mode = 'hold', release;
  const held = new Promise(done => { release = done; });
  await page.route('**/api/tasks', async route => {
    if (mode === 'hold') { await held; return route.fulfill({status: 500, json: {error: {message: 'Fixture task list unavailable'}}}); }
    if (mode === 'empty') return route.fulfill({json: {tasks: []}});
    return route.continue();
  });
  for (let attempt = 0; attempt < 50; attempt++) { try { await page.goto(metadata.origin + '/#home'); break; } catch { await page.waitForTimeout(200); } }
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  assert.equal(await page.locator('#configured-task').isVisible(), false, 'The configured-task Prepare form is not a beginner entry');
  const dialog = page.locator('#quick-start-dialog'), state = page.locator('#quick-start-task-state');
  await page.locator('#home-quick-start').click();
  await waitUntil(() => dialog.evaluate(el => el.open));
  assert.equal(await state.textContent(), 'Loading tasks…');
  release();
  await state.filter({hasText: 'Tasks could not be loaded: Fixture task list unavailable'}).waitFor();
  assert.equal(await page.locator('#quick-start-open').isDisabled(), true);
  mode = 'empty'; await page.locator('#quick-start-task-retry').click();
  await state.filter({hasText: 'No task is registered. Put your task package in siderius_workspace/tasks/<id>/ and run add-task (see the README), then restart the console'}).waitFor();
  assert.match(await state.locator('a').getAttribute('href'), /README.md#set-up-and-open-the-console$/);
  assert.equal(await page.locator('#quick-start-task-retry').isHidden(), true);
  mode = 'real'; await page.evaluate(() => window.consoleTask.reload());
  await page.locator('#quick-start-task option[value="synthetic"]').waitFor({state: 'attached'});
  assert.equal(await page.locator('label[for="quick-start-task"]').textContent(), 'Choose a task');
  assert.equal(await page.locator('body').evaluate(body => body.textContent.includes('Project (its task and data)')), false);

  // No setup yet: the only choice creates one from the research-loop template.
  await waitUntil(async () => (await page.locator('#quick-start-setup option').count()) === 1);
  assert.equal(await page.locator('#quick-start-setup option').textContent(), 'Create a setup from the research-loop template');
  assert.equal(await page.locator('#quick-start-label').inputValue(), 'Synthetic task research loop');
  assert.equal(await page.locator('#quick-start-open').textContent(), 'Create and open');
  await page.screenshot({path: join(evidence, 'quick-start-dialog.png')});

  // A refused creation keeps the dialog and names the reason.
  await page.route('**/api/tasks/synthetic/setups', route => route.request().method() === 'POST'
    ? route.fulfill({status: 403, json: {error: {code: 'read_only', message: 'this console does not create experiment setups'}}}) : route.continue());
  await page.locator('#quick-start-open').click();
  await page.locator('#quick-start-status').filter({hasText: 'browser_creatable'}).waitFor();
  assert.equal(await dialog.evaluate(el => el.open), true);
  await page.unroute('**/api/tasks/synthetic/setups');

  await page.locator('#quick-start-open').click();
  await waitUntil(async () => !(await dialog.evaluate(el => el.open)), 30000);
  assert.equal(new URL(page.url()).hash, '#workflow');
  for (const id of ['interpret', 'propose', 'implement', 'validate', 'train']) await page.locator(`#circuit-node-${id}`).waitFor();
  assert.equal(await page.locator('#editor-project').inputValue(), 'synthetic-task-research-loop');
  await waitUntil(() => page.evaluate(() => document.activeElement?.classList.contains('advice-input')), 5000);
  assert.ok((await readFile(join(metadata.workspace, 'projects', 'synthetic-task-research-loop', 'workflow.py'), 'utf8')).length > 0);
  assert.deepEqual(posts.filter(path => path.endsWith('/setups')), ['/api/tasks/synthetic/setups', '/api/tasks/synthetic/setups']);
  await page.locator('#editor-loop-final-iteration').waitFor({state: 'visible'});
  // Cold-start guidance belongs only to inputs managed by the run.
  await page.locator('#circuit-node-interpret').click();
  const managedHelp = page.locator('#editor-inspector .managed-input-help');
  await managedHelp.waitFor({state: 'visible'});
  assert.match(await managedHelp.textContent(), /first round starts cold/);
  assert.ok((await managedHelp.textContent()).includes("previous round's training results"));
  // Exercise the same unbound interpretation form in v1 and reusable contexts.
  const forms = await page.evaluate(() => {
    const option = {socket_contract: {id: 'interpretation.input'}, bound: false, choices: []};
    return [false, true].map(reusable => {
      const parent = document.createElement('div');
      window.editorExternalInputs.render(parent, {option, nodeId: 'interpret', reusable,
        taken: new Set(), enabled: true, ready: () => {}}, () => {});
      return {help: parent.querySelector('.external-input-help').textContent,
        pathHidden: parent.querySelector('[name="external-location"]').parentElement.hidden};
    });
  });
  assert.ok(!forms[0].help.includes('cold'));
  assert.equal(forms[0].pathHidden, false, 'v1 asks for a file without promising managed input');
  assert.ok(forms[1].help.includes('first round starts cold'));
  assert.equal(forms[1].pathHidden, true);
  await page.screenshot({path: join(evidence, 'quick-start-opened.png'), fullPage: true});

  // A second Quick start offers the existing setup and opens it without creating another.
  const before = posts.length;
  await page.locator('nav a[href="#home"]').click();
  await page.locator('#home-quick-start').click();
  await page.locator('#quick-start-setup option[value="synthetic-task-research-loop"]').waitFor({state: 'attached'});
  await page.locator('#quick-start-setup').selectOption('synthetic-task-research-loop');
  assert.equal(await page.locator('#quick-start-label').isHidden(), true);
  await page.locator('#quick-start-open').click();
  await waitUntil(async () => !(await dialog.evaluate(el => el.open)), 30000);
  assert.equal(await page.locator('#editor-project').inputValue(), 'synthetic-task-research-loop');
  assert.equal(posts.length, before, 'Opening an existing setup creates nothing');
  assert.deepEqual(faults, []);
  console.log('PASS: Quick start states (loading, failed + Retry, empty, loaded), create from the research-loop template, open an existing setup, refused creation');
} finally {
  await browser?.close();
  server.kill();
}
