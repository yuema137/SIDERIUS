/** Browser witness: required-input flags, problems list jumps, training defaults/reset/help,
 * read-only model-hyperparameter owner and the loop pointer in the per-node inspector. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[key], `Set ${key}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => { errors += chunk; });
const lines = createInterface({input: server.stdout});
const waitUntil = async predicate => {
  const deadline = Date.now() + 20000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error('Browser condition timed out'); await new Promise(resolve => setTimeout(resolve, 50)); }
};
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Fixture startup timeout: ${errors}`)), 30000);
    lines.once('line', line => { clearTimeout(timer); accept(JSON.parse(line)); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${errors}`)); });
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'));
  await page.locator('#editor-project').selectOption('interpretation');
  await waitUntil(async () => (await page.locator('#editor-source').inputValue()).includes('native-interpretation-candidate/v1'));
  const pending = () => page.locator('#editor-pending').textContent();
  const problems = page.locator('#editor-problems'), buildCard = page.locator('.circuit-card[data-node="build"]');
  assert.equal(await problems.isHidden(), true, 'A valid saved source has no problems');
  assert.equal(await page.locator('.circuit-card.has-required-unbound').count(), 0);

  // U6/C5: disconnecting a required input flags its card and field and lists one located problem.
  await page.locator('#circuit-node-build').click();
  await page.locator('button[aria-label="Disconnect build.output"]').click();
  await waitUntil(async () => (await pending()).includes('incomplete'));
  assert.equal(await buildCard.evaluate(card => card.classList.contains('has-required-unbound')), true);
  assert.match(await buildCard.locator('.circuit-problem-badge').textContent(), /^1 required input missing$/);
  assert.equal(await page.locator('.circuit-card.has-required-unbound').count(), 1, 'Only the offending card is flagged');
  assert.equal(await problems.isVisible(), true);
  assert.equal(await problems.locator('h2').textContent(), '1 problem');
  const item = problems.locator('button.editor-problem');
  assert.equal(await item.count(), 1);
  assert.equal(await item.getAttribute('data-node'), 'build');
  assert.equal(await item.getAttribute('data-field'), 'output');
  assert.equal(await item.getAttribute('data-code'), 'required_unbound');
  assert.match(await item.textContent(), /build\.output: required input is unbound/);
  assert.equal(await page.locator('#editor-review').isDisabled(), true, 'An incomplete draft blocks Review');
  assert.equal(await page.locator('#editor-save').isDisabled(), true);

  // The problem jumps from another selection back to the node and focuses its field.
  await page.locator('#circuit-node-interpret').click();
  assert.equal(await page.locator('#circuit-node-build').getAttribute('aria-pressed'), 'false');
  await item.click();
  assert.equal(await page.locator('#circuit-node-build').getAttribute('aria-pressed'), 'true');
  assert.deepEqual(await page.evaluate(() => [document.activeElement?.dataset.node, document.activeElement?.dataset.argument]), ['build', 'output']);
  assert.equal(await page.locator('#editor-inspector label.field-problem').count(), 1);
  assert.equal(await page.locator('#circuit-input-build-output').evaluate(port => port.classList.contains('problem-focus')), true);

  // Rebinding clears the flag, the badge and the list.
  await page.locator('#circuit-output-hypothesis').click(); await page.locator('#circuit-input-build-output').click();
  await waitUntil(async () => (await pending()) === 'No pending edits.');
  assert.equal(await page.locator('.circuit-card.has-required-unbound').count(), 0);
  assert.equal(await page.locator('.circuit-problem-badge').count(), 0);
  assert.equal(await problems.isHidden(), true);

  // U7/U8/C8: the tuning inspector lists every training setting expanded, with help and reset.
  await page.locator('#circuit-node-fit').click();
  const settings = page.locator('#editor-training-settings');
  assert.equal(await settings.evaluate(details => details.open), true, 'Defaults are listed expanded on selection');
  const rows = settings.locator('[data-training-field]');
  assert.ok((await rows.count()) > 5);
  assert.equal(await rows.count(), await settings.locator('[data-training-mode]').count());
  assert.equal(await rows.count(), await settings.locator('[data-training-reset]').count(), 'Each field has its own reset');
  const row = name => settings.locator(`[data-training-field="${name}"]`);
  const badge = name => settings.locator(`[data-training-badge="${name}"]`);
  assert.equal(await badge('trial_time_budget_minutes').textContent(), 'Modified', 'Authored value differs from the native default');
  assert.equal(await badge('trial_max_epochs').textContent(), 'Default');
  assert.equal(await settings.locator('[data-training-reset="trial_max_epochs"]').isDisabled(), true);
  // Help comes from the native schema: the launch-config default, not a browser copy.
  assert.match(await row('formal_portion').locator('.field-help').textContent(), /Schema default: 0\.1/);
  assert.match(await row('trial_time_budget_minutes').locator('.field-help').textContent(), /Native preview: 2 /);

  await settings.locator('[data-training-mode="trial_max_epochs"]').selectOption('supplied');
  await settings.locator('[data-training="trial_max_epochs"]').fill('4');
  assert.equal(await badge('trial_max_epochs').textContent(), 'Changed, not saved');
  assert.equal(await row('trial_max_epochs').getAttribute('data-modified'), 'true');
  assert.equal(await settings.locator('[data-training-reset="trial_max_epochs"]').isDisabled(), false);
  await settings.locator('[data-training-reset="trial_time_budget_minutes"]').click();
  assert.equal(await settings.locator('[data-training-mode="trial_time_budget_minutes"]').inputValue(), 'unset');
  assert.equal(await settings.locator('[data-training="trial_time_budget_minutes"]').isDisabled(), true);
  assert.equal(await row('trial_time_budget_minutes').getAttribute('data-modified'), 'false');
  assert.equal(await badge('trial_time_budget_minutes').textContent(), 'Changed, not saved', 'Reset differs from the saved value until saved');
  // Parameter edits are unified-draft operations: one Reset is one undo step, redo reapplies it.
  assert.match(await page.locator('#editor-undo').getAttribute('title'), /^Undo: Reset /);
  await page.locator('#editor-undo').click();
  assert.equal(await settings.locator('[data-training-mode="trial_time_budget_minutes"]').inputValue(), 'supplied', 'Undo restores the reset value');
  assert.equal(await badge('trial_max_epochs').textContent(), 'Changed, not saved', 'Undo reverts only the last operation');
  await page.locator('#editor-redo').click();
  assert.equal(await settings.locator('[data-training-mode="trial_time_budget_minutes"]').inputValue(), 'unset');
  // An invalid field being typed blocks undo/redo: restoring a state would drop the typed text.
  await settings.locator('[data-training="trial_max_epochs"]').fill('');
  assert.equal(await page.locator('#editor-undo').isDisabled(), true, 'Undo waits for the invalid field');
  await page.locator('#view-workflow h1').focus(); await page.keyboard.press('Control+z');
  assert.equal(await settings.locator('[data-training="trial_max_epochs"]').inputValue(), '', 'Ctrl+Z keeps the invalid typed text');
  assert.equal(await settings.locator('[data-training-mode="trial_time_budget_minutes"]').inputValue(), 'unset', 'Ctrl+Z did not undo');
  assert.match(await page.locator('#editor-status').textContent(), /Correct or reset the invalid field first/);
  await settings.locator('[data-training="trial_max_epochs"]').fill('4');
  assert.equal(await page.locator('#editor-undo').isDisabled(), false, 'A valid value re-enables undo');

  // Read-only model hyperparameters name their task-manifest owner; the loop endpoint points to loop settings.
  const owner = page.locator('#editor-model-hyperparameters');
  assert.match(await owner.textContent(), /read-only/);
  assert.equal(await page.locator('#editor-model-owner').textContent(), 'task.yaml');
  assert.equal(await owner.locator('input, select').count(), 0);
  assert.match(await page.locator('#editor-node-loop-settings').textContent(), /up to 2 iterations/);

  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  const diff = await page.locator('#editor-diff').textContent();
  assert.match(diff, /trial_max_epochs/); assert.match(diff, /-.*trial_time_budget_minutes/);
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Saved reviewed'));
  const saved = await readFile(metadata.interpretation_source, 'utf8');
  assert.match(saved, /'trial_max_epochs': 4/); assert.doesNotMatch(saved, /trial_time_budget_minutes/);
  await page.locator('#circuit-node-fit').click();
  assert.equal(await page.locator('[data-training-badge="trial_time_budget_minutes"]').textContent(), 'Default');
  assert.equal(await page.locator('[data-training-badge="trial_max_epochs"]').textContent(), 'Modified');
  await page.locator('#editor-node-loop-settings button').click();
  assert.equal(await page.evaluate(() => !!document.activeElement?.closest('#editor-loop')), true);

  // A refused source review lists its server diagnostic; selecting it opens the source.
  await page.locator('#editor-advanced').evaluate(details => { details.open = true; });
  await page.locator('#editor-source').fill(saved + '\nbroken = (\n');
  await page.locator('#editor-review').click();
  await waitUntil(async () => await problems.isVisible());
  await page.locator('#editor-advanced').evaluate(details => { details.open = false; });
  const sourceItem = problems.locator('button.editor-problem').first();
  assert.equal(await sourceItem.getAttribute('data-node'), null);
  await sourceItem.click();
  assert.equal(await page.locator('#editor-advanced').evaluate(details => details.open), true);
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'editor-source');
  assert.equal(await readFile(metadata.interpretation_source, 'utf8'), saved, 'Problems never write');
  assert.deepEqual(faults, []);
  console.log('PASS required-input card flag and located problem jump, expanded training defaults with per-field reset/help, read-only model owner, loop pointer, source-diagnostic jump.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors) process.stderr.write(errors);
}
