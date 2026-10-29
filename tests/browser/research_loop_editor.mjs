/** Research-loop GUI round trip: add, limit, stop conditions, review, save, reopen, remove on the five-node source. */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdir, readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {join, resolve, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) {
  assert.ok(process.env[name], `Set ${name}`);
}
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-research-loop-editor');
await mkdir(evidence, {recursive: true});
const server = spawn(
  process.env.EDITOR_PYTHON,
  ['-m', 'tests.browser.workflow_editor_server'],
  {cwd: root, stdio: ['ignore', 'pipe', 'pipe']},
);
let serverErrors = '';
server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
const metadata = await new Promise((resolveMetadata, reject) => {
  lines.once('line', line => resolveMetadata(JSON.parse(line)));
  server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`)));
  setTimeout(() => reject(new Error(`server startup timeout: ${serverErrors}`)), 15000);
});
const python = script => execFileSync(process.env.EDITOR_PYTHON, ['-c', script, metadata.interpretation_source], {cwd: root, encoding: 'utf8'});
const parsed = () => JSON.parse(python('import sys; from pathlib import Path; from workflows.definition import parse_workflow_source; print(parse_workflow_source(Path(sys.argv[1]).read_text()).model_dump_json())'));
// Start from the same five-node declaration without its loop (canonical bytes).
python([
  'import sys', 'from pathlib import Path',
  'from workflows.definition import parse_workflow_source, render_workflow_source',
  'path = Path(sys.argv[1]); document = parse_workflow_source(path.read_text())',
  'plain = document.model_copy(update={"definition": document.definition.model_copy(update={"loop": None})})',
  'path.write_text(render_workflow_source(plain))',
].join('\n'));
const plainBytes = await readFile(metadata.interpretation_source);
const original = parsed();
assert.equal(original.definition.loop, undefined);
assert.equal(original.definition.nodes.length, 5);
let browser;
async function waitUntil(predicate) {
  const deadline = Date.now() + 15000;
  while (!(await predicate())) {
    if (Date.now() > deadline) throw new Error('Browser condition timed out');
    await new Promise(resolveWait => setTimeout(resolveWait, 50));
  }
}
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/editor.html');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened '));
  const status = page.locator('#editor-status');
  const reopen = async () => {
    await page.locator('#editor-refresh').click();
    await waitUntil(async () => (await status.textContent()).includes('Opened '));
  };
  const reviewAndSave = async () => {
    await page.locator('#editor-review').click();
    await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
    const diff = await page.locator('#editor-diff').textContent();
    await page.locator('#editor-save').click();
    await waitUntil(async () => (await status.textContent()).includes('Saved as "'));
    return diff;
  };
  await page.locator('#editor-project').selectOption('interpretation');
  await waitUntil(async () => (await page.locator('#editor-source').inputValue()).includes('native-interpretation-candidate/v1'));

  // Source without a loop: explicit absence and an Add action, no limit control.
  await page.locator('#editor-loop-absent').waitFor();
  assert.equal(await page.locator('#editor-loop-final-iteration').count(), 0);
  assert.equal(await page.locator('#editor-loop-add').isDisabled(), false);

  // Add, try invalid limits, then set a valid one.
  await page.locator('#editor-loop-add').click();
  const limit = page.locator('#editor-loop-final-iteration');
  assert.equal(await limit.inputValue(), '1');
  const feedback = await page.locator('#editor-loop-feedback').textContent();
  assert.match(feedback, /^Train & tune fit → .+ interpret$/);
  for (const invalid of ['0', '2.5', '']) {
    await limit.fill(invalid);
    assert.equal(await page.locator('#editor-review').isDisabled(), true, `invalid limit ${JSON.stringify(invalid)} must block Review`);
  }
  await limit.fill('3');
  assert.equal(await page.locator('#editor-review').isDisabled(), false);
  await page.screenshot({path: join(evidence, 'research-loop-added.png'), fullPage: true});
  const addedDiff = await reviewAndSave();
  assert.match(addedDiff, /final_iteration=3/);
  assert.match(addedDiff, /protocol='tuning-to-interpretation'/);

  // Reopen from disk: the panel and the parsed source both carry the loop.
  await reopen();
  assert.equal(await page.locator('#editor-loop-final-iteration').inputValue(), '3');
  assert.equal(await page.locator('#editor-loop-absent').count(), 0);
  const looped = parsed();
  assert.deepEqual(looped.definition.loop, {
    final_iteration: 3,
    feedback: {source: {kind: 'result', node: 'fit', port: 'result'}, target: 'interpret', protocol: 'tuning-to-interpretation', history: 'native-research/v1'},
  });
  for (const key of ['nodes', 'externals', 'task']) assert.deepEqual(looped.definition[key], original.definition[key]);
  for (const key of ['execution_profile', 'training_settings', 'preparation_options', 'positions']) assert.deepEqual(looped[key], original[key]);
  await page.screenshot({path: join(evidence, 'research-loop-reopened.png'), fullPage: true});

  // Stop conditions: add both kinds, incomplete values block Review, review shows them.
  const loopedBytes = await readFile(metadata.interpretation_source);
  await page.locator('#editor-loop-stop-conditions').filter({hasText: 'None. The loop runs until its iteration limit.'}).waitFor();
  assert.equal(await page.locator('#editor-loop-add-judge').count(), 0, 'judge stopping is never offered');
  await page.locator('#editor-loop-add-metric-threshold').click();
  assert.equal(await page.locator('#editor-loop-add-metric-threshold').count(), 0, 'one condition per kind');
  assert.equal(await page.locator('#editor-review').isDisabled(), true, 'an incomplete threshold blocks Review');
  const metricId = page.locator('#editor-loop-stop-metric-id'), threshold = page.locator('#editor-loop-stop-threshold');
  await metricId.fill('accuracy');
  assert.equal(await page.locator('#editor-review').isDisabled(), true, 'a missing threshold blocks Review');
  await threshold.fill('0.85');
  assert.equal(await page.locator('#editor-review').isDisabled(), false);
  await metricId.fill(' accuracy');
  assert.equal(await page.locator('#editor-review').isDisabled(), true, 'a padded metric id blocks Review');
  await metricId.fill('accuracy');
  await page.locator('#editor-loop-add-no-improvement').click();
  const bodies = page.locator('#editor-loop-stop-completed-bodies');
  assert.equal(await bodies.inputValue(), '1');
  for (const invalid of ['0', '1.5', '']) {
    await bodies.fill(invalid);
    assert.equal(await page.locator('#editor-review').isDisabled(), true, `invalid bodies ${JSON.stringify(invalid)} must block Review`);
  }
  // A cross-field value the server owns: bodies must stay below final_iteration (3).
  await bodies.fill('3');
  assert.equal(await page.locator('#editor-review').isDisabled(), false);
  await page.locator('#editor-review').click();
  await waitUntil(async () => (await status.textContent()).startsWith('Review refused the research loop'));
  assert.match(await status.textContent(), /below the final iteration/);
  assert.match(await page.locator('#editor-diagnostics').textContent(), /validation: Declaration validation failed/);
  assert.ok((await readFile(metadata.interpretation_source)).equals(loopedBytes), 'a refused review writes nothing');
  await bodies.fill('2');
  await page.screenshot({path: join(evidence, 'research-loop-stop-conditions.png'), fullPage: true});
  const stopsDiff = await reviewAndSave();
  assert.match(stopsDiff, /MetricThresholdStop\(/);
  assert.match(stopsDiff, /metric_id='accuracy'/);
  assert.match(stopsDiff, /threshold=0\.85/);
  assert.match(stopsDiff, /NoImprovementStop\(/);
  assert.match(stopsDiff, /completed_bodies=2/);
  await reopen();
  assert.equal(await page.locator('#editor-loop-stop-metric-id').inputValue(), 'accuracy');
  assert.equal(await page.locator('#editor-loop-stop-threshold').inputValue(), '0.85');
  assert.equal(await page.locator('#editor-loop-stop-completed-bodies').inputValue(), '2');
  assert.deepEqual(parsed().definition.loop.stop_conditions, [
    {kind: 'metric_threshold', metric_id: 'accuracy', threshold: 0.85},
    {kind: 'no_improvement', completed_bodies: 2},
  ]);
  await page.screenshot({path: join(evidence, 'research-loop-stop-conditions-reopened.png'), fullPage: true});

  // Remove both conditions: the condition-free loop bytes return exactly.
  await page.locator('#editor-loop-remove-metric-threshold').click();
  await page.locator('#editor-loop-remove-no-improvement').click();
  await page.locator('#editor-loop-add-metric-threshold').waitFor();
  const unstopDiff = await reviewAndSave();
  assert.match(unstopDiff, /-\s+MetricThresholdStop\(/);
  await reopen();
  await page.locator('#editor-loop-stop-conditions').filter({hasText: 'None.'}).waitFor();
  assert.ok((await readFile(metadata.interpretation_source)).equals(loopedBytes), 'removing every stop condition must restore the condition-free bytes');

  // Remove, save, reopen: the original non-loop bytes return.
  await page.locator('#editor-loop-remove').click();
  await page.locator('#editor-loop-absent').waitFor();
  const removedDiff = await reviewAndSave();
  assert.match(removedDiff, /-\s+loop=AuthoredLoop\(/);
  await reopen();
  await page.locator('#editor-loop-absent').waitFor();
  assert.equal(await page.locator('#editor-loop-final-iteration').count(), 0);
  assert.ok((await readFile(metadata.interpretation_source)).equals(plainBytes), 'removing the loop must restore the original non-loop bytes');
  assert.deepEqual(faults, []);
  await page.screenshot({path: join(evidence, 'research-loop-removed.png'), fullPage: true});
  console.log(JSON.stringify({result: 'PASS', evidence}));
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  await new Promise(resolveExit => server.once('exit', resolveExit));
}
