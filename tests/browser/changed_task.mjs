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
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.changed_task_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
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
  const connect = async token => {await page.locator('#token').fill(token); await page.locator('#access-form button').click();};
  await connect(metadata.token);
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  await page.locator('#editor-source').waitFor({state: 'attached'});
  await waitUntil(async () => (await page.locator('#editor-source').inputValue()).length > 0 && await page.locator('#editor-task-choice option').count() === 3);
  const choice = page.locator('#editor-task-choice'), save = page.locator('#editor-save');
  page.setDefaultTimeout(30000);
  const original = await readFile(metadata.source, 'utf8');
  const inspectTraining = async () => {
    const tuning = page.locator('[data-node="fit"].editor-node');
    await tuning.click();
    assert.equal(await page.locator('[data-training="trial_max_epochs"]').inputValue(), '3');
    assert.equal(await page.locator('[data-training="sampling_seed"]').inputValue(), '17');
    assert.equal(await page.locator('[data-training-mode="trial_max_epochs"]').inputValue(), 'supplied');
  };
  if (metadata.training) await inspectTraining();
  await choice.selectOption('new');
  assert.equal(await readFile(metadata.source, 'utf8'), original);
  await page.locator('#editor-task-update').click();
  await page.locator('#editor-task-acknowledge').waitFor();
  if (metadata.training) await inspectTraining();
  assert.ok(await save.isDisabled());
  assert.match(await page.locator('#editor-task-message').textContent(), /reviewed, not saved/);
  assert.match(await page.locator('#editor-task-controls').textContent(), /fresh candidate|fresh target proposal/);
  if (metadata.profile === 'families') {
    assert.match(await page.locator('#editor-task-findings').textContent(), /2 proposal families and 3 implementation branches/);
  }
  await page.screenshot({path: resolve(process.env.CONSOLE_EVIDENCE_DIR, 'changed-reviewed.png'), fullPage: true});
  await page.locator('#editor-task-acknowledge').check();
  if (metadata.training) await inspectTraining();
  assert.ok(await save.isEnabled());
  const plugin = await readFile(metadata.plugin, 'utf8');
  await writeFile(metadata.plugin, plugin + '\n# changed after browser review\n');
  await save.click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('blocked'));
  assert.equal(await readFile(metadata.source, 'utf8'), original, 'Drift never partially saves');
  assert.ok(await save.isDisabled());
  assert.equal(await page.locator('#editor-conflict').isVisible(), false, 'Task drift is not a source conflict');
  assert.match(await page.locator('#editor-task-message').textContent(), /blocked/);
  assert.equal(await page.locator('#editor-source').inputValue(), requests.findLast(item => item.path.endsWith('/save')).body.source);
  await page.screenshot({path: resolve(process.env.CONSOLE_EVIDENCE_DIR, 'changed-drift-blocked.png'), fullPage: true});
  await writeFile(metadata.plugin, plugin);
  // Re-review the retained draft after restoring the selected task source.
  await page.locator('#editor-review').click();
  await page.locator('#editor-task-acknowledge').waitFor();
  await page.locator('#editor-task-acknowledge').check();
  await save.click();
  await waitUntil(async () => !(await page.evaluate(() => window.workflowEditor.state.dirty)) && (await readFile(metadata.source, 'utf8')) !== original);
  if (metadata.training) await inspectTraining();
  const accepted = requests.findLast(item => item.path.endsWith('/save')).body.task_reference_acceptance;
  assert.deepEqual(accepted.selection.expected_task_binding, metadata.binding);
  assert.equal(accepted.adopt_current_snapshot, false);
  assert.match(await readFile(metadata.source, 'utf8'), /revision='new'/);
  if (metadata.profile) assert.match(await readFile(metadata.source, 'utf8'), new RegExp(`native-proposal-${metadata.profile === 'fanout' ? 'fanout' : 'families'}/v1`));
  assert.deepEqual(faults, []);
  await page.screenshot({path: resolve(process.env.CONSOLE_EVIDENCE_DIR, 'changed-saved.png'), fullPage: true});
  if (metadata.training) {
    await page.locator('#editor-refresh').click();
    await page.locator('#editor-status').filter({hasText: 'Opened supported declaration'}).waitFor();
    await inspectTraining();
    assert.match(await page.locator('#editor-source').inputValue(), /trial_max_epochs.*3/s);
  }
  console.log('PASS real checked changed-reference review, acknowledgement, drift refusal, save; no API/GPU');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors) process.stderr.write(errors);
}
