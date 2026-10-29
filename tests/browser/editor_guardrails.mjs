/** Beginner guardrails of the Workflow editor (red-team A-2, A-4, SEC-2, SEC-6).
 * Fails if: a reusable project offers "A JSON file in the project" (reusable preparation
 * accepts only managed inputs) or a file path for a new input; the advice field does not say
 * where advice goes; Ctrl+Z changes the canvas behind an open template dialog; or typed
 * Python hidden by turning advanced tools off leaves no beginner explanation (Show / Discard)
 * and the Save step does not say it writes typed text. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[key], `Set ${key}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => { errors += chunk; });
const waitUntil = async (predicate, what) => {
  const deadline = Date.now() + 20000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error(`${what} timed out`); await new Promise(next => setTimeout(next, 50)); }
};
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Fixture startup timeout: ${errors}`)), 30000);
    createInterface({input: server.stdout}).once('line', line => { clearTimeout(timer); accept(JSON.parse(line)); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${errors}`)); });
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  const status = () => page.locator('#editor-status').textContent();
  await waitUntil(async () => (await status()).includes('Opened supported'), 'open');
  const open = async id => {
    await page.locator('#editor-project').selectOption(id);
    await waitUntil(async () => (await page.locator('#editor-path').textContent()).endsWith(id === 'reusable' ? 'reusable.py' : 'reusable_interpretation.py'), `${id} opened`);
  };

  // SEC-6: a reusable project only offers inputs the run manages.
  await open('reusable');
  const palette = page.locator('#editor-palette');
  await palette.locator('.palette-search').fill('implementation');
  await palette.locator('.palette-entry[data-protocol="proposal-to-implementation"]').click();
  const added = await page.locator('.circuit-card[data-capability="implementation"]').last().getAttribute('data-node');
  await page.locator(`#circuit-node-${added}`).click();
  const forms = page.locator('#editor-inspector .external-input-create');
  await forms.first().waitFor({state: 'attached'});
  assert.ok(await forms.count() > 0, 'the new module has an input to create');
  for (const form of await forms.all()) {
    await form.locator('summary').click();
    assert.equal(await form.locator('select[name="external-mode"]').count(), 0, 'no file-or-managed choice');
    assert.ok(!(await form.textContent()).includes('A JSON file in the project'));
    assert.equal(await form.locator('input[name="external-location"]').isVisible(), false, 'no file path to type');
    assert.match(await form.locator('.external-input-note').textContent(), /reusable workflows accept only/i);
  }

  // SEC-2: the advice field says where the text goes.
  await page.locator('#editor-discard-draft').click();
  await open('interpretation');
  await page.locator('#circuit-node-build').click();
  assert.equal(await page.locator('#editor-inspector .advice-privacy').textContent(),
    "Advice is sent to the model provider and kept in version history; don't paste secrets.");

  // A-4: Ctrl+Z does nothing to the canvas behind an open modal.
  await page.locator('#circuit-node-build').focus();
  await page.keyboard.press('Alt+ArrowRight');
  await waitUntil(async () => !(await page.locator('#editor-undo').isDisabled()), 'a move to undo');
  await page.locator('#editor-template-open').click();
  await page.locator('#editor-template-gallery h2').click();
  await page.keyboard.press('Control+z');
  assert.equal(await page.evaluate(() => window.workflowEditor.state.dirty), true, 'the move stays while the dialog is open');
  await page.keyboard.press('Escape');
  await page.locator('#editor-discard-draft').click();

  // A-2: typed Python, then advanced tools off: the beginner view explains it.
  await page.evaluate(() => window.uiSettings.set('advanced', true));
  await page.locator('#editor-advanced summary').click();
  await page.locator('#editor-source').fill((await page.locator('#editor-source').inputValue()) + '\n# typed in advanced\n');
  await page.evaluate(() => window.uiSettings.set('advanced', false));
  const line = page.locator('#editor-hidden-source');
  assert.equal(await line.isVisible(), true, 'hidden typed source is announced');
  assert.match(await line.textContent(), /unsaved Python edits from advanced mode/);
  await page.locator('#editor-review').click();
  await page.locator('#editor-save-confirm').waitFor();
  assert.match(await page.locator('#editor-save-summary').textContent(), /Python text you typed/);
  await page.locator('#editor-save-cancel').click();
  await page.locator('#editor-hidden-source-discard').click();
  await waitUntil(async () => !(await page.locator('#editor-source').inputValue()).includes('# typed in advanced'), 'discarded');
  assert.equal(await line.isVisible(), false);
  assert.deepEqual(faults, []);
  console.log('PASS reusable inputs are managed-only, advice privacy sentence, Ctrl+Z ignored behind a dialog, hidden typed Python announced with Show/Discard and named in the Save step.');
} finally {
  await browser?.close();
  server.kill();
}
