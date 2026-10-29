/** Scenario (a), operator first-use flow: Workflow page -> Start from a template -> preview ->
 * import "Single research loop" -> change a training parameter -> Review -> Save. */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdir, readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {join, resolve, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) {
  assert.ok(process.env[name], `Set ${name}`);
}
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-scenario_template_parameters');
await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = '';
server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
const metadata = await new Promise((resolveMetadata, reject) => {
  lines.once('line', line => resolveMetadata(JSON.parse(line)));
  server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`)));
  setTimeout(() => reject(new Error(`server startup timeout: ${serverErrors}`)), 15000);
});
// The fixture's "reusable" project: an unbound reusable source with its own task references.
const parsed = () => JSON.parse(execFileSync(process.env.EDITOR_PYTHON, ['-c',
  'import sys; from pathlib import Path; from workflows.definition import parse_workflow_source; print(parse_workflow_source(Path(sys.argv[1]).read_text()).model_dump_json())',
  metadata.reusable_source], {cwd: root, encoding: 'utf8'}));
const original = parsed();
async function waitUntil(predicate) {
  const deadline = Date.now() + 15000;
  while (!(await predicate())) {
    if (Date.now() > deadline) throw new Error('Browser condition timed out');
    await new Promise(resolveWait => setTimeout(resolveWait, 50));
  }
}
let browser;
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  const status = page.locator('#editor-status');
  await waitUntil(async () => (await status.textContent()).includes('Opened supported'));
  await page.locator('#editor-project').selectOption('reusable');
  await waitUntil(async () => (await page.locator('#editor-path').textContent()) === metadata.reusable_source);

  // Beginner entry: compact cards (icon, title, one sentence); the graph preview opens on demand.
  const importTemplate = async (id, title) => {
    // Compare exact bytes on disk before/after import (a prior Save may have changed them).
    const before = await readFile(metadata.reusable_source);
    await page.locator('#editor-template-open').click();
    const gallery = page.locator('#editor-template-gallery');
    await gallery.locator(`.template-card[data-template="${id}"]`).click();
    await page.screenshot({path: join(evidence, `gallery-${id}.png`)});
    assert.equal(await gallery.locator('.template-card .template-thumbnail').count(), 0, 'Cards stay compact');
    assert.equal(await gallery.locator('#editor-template-detail h3').textContent(), title);
    assert.equal(await gallery.locator('#editor-template-detail svg.template-thumbnail').count(), 1, 'Preview shown before import');
    await gallery.locator('#editor-template-import').click();
    await waitUntil(async () => !(await gallery.evaluate(dialog => dialog.open)));
    await waitUntil(async () => (await status.textContent()).includes('Declaration validated'));
    assert.ok((await readFile(metadata.reusable_source)).equals(before), 'Import never writes before Save');
  };
  // Human advice is the first input of the inspector, labelled and multi-line.
  const adviceFirst = async () => {
    const first = page.locator('#editor-inspector').locator('textarea, input, select').first();
    assert.equal(await first.getAttribute('class'), 'advice-input');
    assert.equal(await page.locator('#editor-inspector .advice-label').first().textContent(), 'Your advice to the agents');
    assert.ok((await first.getAttribute('placeholder')).startsWith('e.g. '));
  };
  const reviewAndSave = async () => {
    await page.locator('#editor-review').click();
    await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
    await page.locator('#editor-save').click();
    await waitUntil(async () => (await status.textContent()).includes('Saved reviewed'));
  };
  // Typed Advanced source is not a draft state: a template import is refused (it would be
  // lost beyond Undo), the typed text survives, and Discard (undoable) clears the way.
  await page.locator('#settings-toggle').click();
  await page.locator('#settings-panel input[data-ui-setting="advanced"]').check();
  await page.keyboard.press('Escape');
  await page.locator('#editor-advanced').evaluate(el => {el.open = true;});
  const typed = (await page.locator('#editor-source').inputValue()) + '\n# typed by the author\n';
  await page.locator('#editor-source').fill(typed);
  await page.locator('#editor-template-open').click();
  await page.locator('#editor-template-gallery').locator('.template-card[data-template="single-research-loop"]').click();
  assert.equal(await page.locator('#editor-template-import').isDisabled(), true, 'Import is refused while typed source is unsaved');
  assert.match(await page.locator('#editor-template-status').textContent(), /typed Python text/);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#editor-source').inputValue(), typed, 'Typed source survives the refused import');
  await page.locator('#editor-discard-draft').click();
  await waitUntil(async () => !(await page.locator('#editor-source').inputValue()).includes('# typed by the author'));
  await page.locator('#settings-toggle').click();
  await page.locator('#settings-panel input[data-ui-setting="advanced"]').uncheck();
  await page.keyboard.press('Escape');
  // Scenario (a): import the single research loop, change a training parameter, review, save.
  await importTemplate('single-research-loop', 'Single research loop');
  for (const id of ['interpret', 'propose', 'implement', 'validate', 'train']) await page.locator(`#circuit-node-${id}`).waitFor();
  await page.locator('#circuit-node-train').click();
  await adviceFirst();
  const settings = page.locator('#editor-training-settings');
  if (!(await settings.evaluate(details => details.open))) await settings.locator('summary').click();
  await settings.locator('[data-training-mode="trial_max_epochs"]').selectOption('supplied');
  await settings.locator('[data-training="trial_max_epochs"]').fill('3');
  await reviewAndSave();
  await page.screenshot({path: join(evidence, 'saved.png'), fullPage: true});
  const saved = parsed();
  assert.equal(saved.execution_profile, 'native-interpretation-candidate/v1');
  assert.equal(saved.definition.loop.final_iteration, 1, 'Finite iteration limit from the template');
  assert.deepEqual(saved.training_settings, {launch: {trial_max_epochs: 3}}, 'Only the edited parameter is authored');
  assert.deepEqual(saved.definition.task, original.definition.task, 'The project task references are kept');
  assert.equal(saved.task_binding, undefined, 'No task is chosen by the template');
  assert.deepEqual(faults, []);
} finally {
  await browser?.close();
  server.kill();
}
