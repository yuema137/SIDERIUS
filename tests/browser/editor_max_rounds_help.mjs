/** #1221: native schema help reaches the editor, and a refused one-round edit
 * offers a control-based remedy without raw CLI diagnostics. Raising the budget
 * reviews successfully and preserves the Trial override; no training is launched. */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {readFile, writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {waitForMetadata} from './fixture_metadata.mjs';
import {showAllConsoleSections} from './console_view_flags.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
server.stderr.resume();
const metadata = await waitForMetadata(server, {timeoutMs: 15000}).catch(error => {
  server.kill('SIGTERM'); throw error;
});
const source = execFileSync(process.env.EDITOR_PYTHON, ['-c',
  'from tests.unit.workflows.test_reusable_training import training_document; from workflows.definition import render_workflow_source; print(render_workflow_source(training_document({"launch":{"max_rounds":2,"trial_portion":0.2}})), end="")'],
{cwd: root, encoding: 'utf8'});
await writeFile(metadata.reusable_source, source);
let browser;
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1440, height: 900}});
  const faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/editor.html');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#editor-project').selectOption('reusable');
  await page.locator('#circuit-node-fit').click();
  await page.locator('#editor-training-settings').evaluate(element => { element.open = true; });
  const help = page.locator('#editor-training-help-max_rounds');
  assert.match(await help.textContent(), /Tuning rounds per iteration.*Use at least 2.*Range: ≥ 1/);
  assert.equal(await help.isVisible(), true);
  const rounds = page.locator('[data-training="max_rounds"]');
  await rounds.fill('1');
  const reviewResponse = () => page.waitForResponse(response => response.url().endsWith('/reusable/review') && response.request().method() === 'POST');
  const refusal = reviewResponse();
  await page.locator('#editor-review').click();
  const refused = await refusal;
  assert.equal(refused.status(), 422);
  assert.equal((await refused.json()).error.code, 'trial_override_schedule');
  await page.locator('#editor-status').filter({hasText: 'invalid request fields'}).waitFor();
  const status = await page.locator('#editor-status').textContent();
  assert.match(status, /Training settings.*Use at least 2 to allow Trial before Formal/);
  assert.doesNotMatch(status, /--max_rounds|--no-force_formal_round|--is_trial/);
  assert.equal(await readFile(metadata.reusable_source, 'utf8'), source, 'Refusal never saves');
  assert.equal(await page.evaluate(() => window.workflowEditor.state.dirty), true, 'The refused edit is retained');
  await page.locator('#editor-training-settings').evaluate(element => { element.open = true; });
  await page.locator('[data-training="max_rounds"]').fill('2');
  const accepted = reviewResponse();
  await page.locator('#editor-review').click();
  const response = await accepted;
  assert.equal(response.status(), 200, await response.text());
  const review = await response.json();
  assert.equal(review.document.training_settings.launch.max_rounds, 2);
  assert.equal(review.document.training_settings.launch.trial_portion, 0.2);
  assert.equal(await readFile(metadata.reusable_source, 'utf8'), source, 'Review does not save');
  // Unrelated errors do not earn tuning advice; native settings help is the one text owner.
  const hints = await page.evaluate(() => {
    const training = {controls: [{name: 'max_rounds', label: 'Tuning rounds per iteration', help: {description: 'native help'}}]};
    return [
      window.editorNodeParameters.reviewHint(training, {max_rounds: 1}, {status: 409, code: 'conflict'}),
      window.editorNodeParameters.reviewHint(training, {max_rounds: 1}, {status: 422, code: 'source', value: {diagnostics: [{code: 'syntax'}]}}),
      window.editorNodeParameters.reviewHint(training, {max_rounds: 1}, {status: 422, code: 'validation'}),
    ];
  });
  assert.deepEqual(hints, ['', '', '']);
  const typedHints = await page.evaluate(() => {
    const training = {controls: [{name: 'max_rounds', label: 'Tuning rounds per iteration', help: {description: 'native help'}}]};
    return [
      window.editorNodeParameters.reviewHint(training, {}, {status: 422, code: 'trial_override_schedule'}),
      window.editorNodeParameters.reviewHint(training, {}, {status: 422, code: 'source', value: {diagnostics: [{code: 'trial_override_schedule'}]}}),
    ];
  });
  for (const hint of typedHints) assert.match(hint, /Check Tuning rounds per iteration/);
  assert.deepEqual(faults, []);
  console.log('PASS: schema help and minimum; refused one-round remedy; two-round correction; no saves or launches');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  await new Promise(done => server.once('exit', done));
}
