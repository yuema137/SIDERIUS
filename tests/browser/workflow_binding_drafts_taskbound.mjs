/** Task-bound workflow witness: select review context without editing references. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[key], `Set ${key}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_binding_drafts_task_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => { errors += chunk; });
const lines = createInterface({input: server.stdout});
const waitUntil = async predicate => {
  const deadline = Date.now() + 30000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error('Browser condition timed out'); await new Promise(resolve => setTimeout(resolve, 50)); }
};
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Fixture startup timeout: ${errors}`)), 45000);
    lines.once('line', line => { clearTimeout(timer); accept(JSON.parse(line)); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${errors}`)); });
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}}), faults = [], posts = [], gets = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST') posts.push({path, body: request.postDataJSON()});
    else if (request.method() === 'GET' && path === '/api/editor/task-choices') gets.push(path);
  });
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'));
  await page.locator('.workflow-task-details').evaluate(element => { element.open = true; });
  const source = page.locator('#editor-source'), taskChoice = page.locator('#editor-task-choice');
  const original = await readFile(metadata.source, 'utf8');
  assert.equal(await taskChoice.inputValue(), '', 'Opening a task-bound workflow does not select a version implicitly');
  assert.equal(await page.locator('#editor-review').isDisabled(), true);
  await page.locator('#circuit-node-check').click();
  const disconnect = page.locator('button[aria-label="Disconnect check.llm_provider"]');
  assert.equal(await disconnect.count(), 1);
  await disconnect.click();
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()).includes('complete'));
  assert.match(await page.locator('#editor-edges').textContent(), /Optional · unbound → check\.llm_provider/,
    'Connection mappings show the draft inventory, not the saved graph');
  assert.equal(await readFile(metadata.source, 'utf8'), original);
  assert.equal(await page.evaluate(() => window.workflowEditor.state.dirty), true);

  assert.equal(await taskChoice.isEnabled(), true, 'A saved binding draft may select its review task');
  await taskChoice.selectOption(metadata.choice_id);
  assert.equal(await taskChoice.inputValue(), metadata.choice_id);
  assert.equal(await page.locator('#editor-task-update').isDisabled(), true, 'Task-reference mutation stays disabled during a binding draft');
  assert.equal(await page.locator('#editor-review').isDisabled(), false);
  const beforeUpdate = posts.length;
  await page.locator('#editor-task-update').evaluate(element => element.dispatchEvent(new MouseEvent('click', {bubbles: true})));
  assert.equal(posts.length, beforeUpdate, 'Even a dispatched Update click cannot mutate task references during a draft');

  const beforeRefresh = gets.length;
  await page.locator('#editor-task-refresh').click();
  await waitUntil(async () => gets.length > beforeRefresh);
  assert.equal(await taskChoice.inputValue(), metadata.choice_id, 'Choice refresh preserves the selected saved identity');
  assert.equal(await page.locator('#editor-pending').textContent(), 'Pending binding draft · complete', 'Refresh does not stale the independent draft inspection');
  await page.locator('#editor-review').click();
  await waitUntil(async () => posts.some(item => item.path.endsWith('/review')));
  const review = posts.findLast(item => item.path.endsWith('/review'));
  assert.equal(review.body.proposal.kind, 'draft');
  assert.equal(review.body.task_reference_selection.selected_choice_id, metadata.choice_id);
  assert.deepEqual(review.body.task_reference_selection.expected_task_binding, metadata.saved_binding);
  await waitUntil(async () => await page.locator('#editor-task-acknowledge').count() > 0 || !(await page.locator('#editor-save').isDisabled()));
  if (await page.locator('#editor-task-acknowledge').count()) await page.locator('#editor-task-acknowledge').check();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  assert.match(await page.locator('#editor-diff').textContent(), /llm_provider/);
  assert.equal(await readFile(metadata.source, 'utf8'), original, 'Review does not publish the bound draft');
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Saved reviewed'));
  const saved = await readFile(metadata.source, 'utf8');
  assert.doesNotMatch(saved, /name='llm_provider'/);
  assert.match(saved, /TaskBinding\(/, 'Saving a port draft preserves the existing task identity');
  const save = posts.findLast(item => item.path.endsWith('/save'));
  assert.deepEqual(save.body.task_reference_acceptance.selection.expected_task_binding, metadata.saved_binding);
  assert.deepEqual(faults, []);
  console.log('PASS task-bound optional disconnect review/save with matching task selection and refresh; task-reference Update remains unavailable and draft mappings reflect inventory.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors) process.stderr.write(errors);
}
