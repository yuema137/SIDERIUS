/** Issue 961: no-op, reference, training and drag saves preserve untouched source bytes. */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdir, readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {join, resolve, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {waitForMetadata} from './fixture_metadata.mjs';
import {showAllConsoleSections} from './console_view_flags.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) {
  assert.ok(process.env[name], `Set ${name}`);
}
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-literal-preservation');
await mkdir(evidence, {recursive: true});
const server = spawn(
  process.env.EDITOR_PYTHON,
  ['-m', 'tests.browser.workflow_editor_server'],
  {cwd: root, stdio: ['ignore', 'pipe', 'pipe']},
);
server.stderr.resume();
const metadata = await waitForMetadata(server);
let browser;
async function waitUntil(predicate) {
  const deadline = Date.now() + 15000;
  while (!(await predicate())) {
    if (Date.now() > deadline) throw new Error('Browser condition timed out');
    await new Promise(resolveWait => setTimeout(resolveWait, 50));
  }
}
// A Professional-authored training source with noncanonical literals.
execFileSync(process.env.EDITOR_PYTHON, ['-c',
  'import sys; from pathlib import Path; from tests.unit.tools.test_workflow_literal_preservation import literal_source; Path(sys.argv[1]).write_text(literal_source())',
  metadata.reusable_source], {cwd: root});
const originalBytes = await readFile(metadata.reusable_source, 'utf8');
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
  const faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/editor.html');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#editor-status').filter({hasText: 'Opened '}).waitFor();
  await page.locator('#editor-project').selectOption('reusable');
  await waitUntil(async () => (await page.locator('#editor-source').inputValue()).includes('9007199254740993'));
  const save = async (unchanged = false) => {
    await page.locator('#editor-review').click();
    await page.locator('#editor-save').click();
    await page.locator('#editor-status').filter({hasText: unchanged ? 'Nothing to save:' : 'Saved as "'}).waitFor();
  };
  await save(true);
  assert.equal(await readFile(metadata.reusable_source, 'utf8'), originalBytes);

  await page.getByText('References', {exact: true}).click();
  await page.getByLabel('task.manifest', {exact: true}).fill('edited-task.yaml');
  await save();
  let expected = originalBytes.replace('"task.yaml"', "'edited-task.yaml'");
  assert.equal(await readFile(metadata.reusable_source, 'utf8'), expected);

  await page.getByText('Selection', {exact: true}).click();
  await page.locator('[data-node="fit"].editor-node').click();
  await page.locator('#editor-training-settings').evaluate(el => { el.open = true; });
  await page.locator('[data-training="formal_time_budget_minutes"]').fill('7');
  await save();
  expected = expected.replace('"formal_time_budget_minutes": 5.0', '"formal_time_budget_minutes": 7.0');
  assert.equal(await readFile(metadata.reusable_source, 'utf8'), expected);

  await page.locator('[data-training="trial_time_budget_minutes"]').fill('3');
  await save();
  expected = expected.replace('"trial_time_budget_minutes": 2.0', '"trial_time_budget_minutes": 3.0');
  assert.equal(await readFile(metadata.reusable_source, 'utf8'), expected);

  await page.locator('#circuit-fit').click();
  const card = page.locator('#circuit-node-build');
  await card.scrollIntoViewIfNeeded();
  const box = await card.boundingBox();
  assert.ok(box);
  await page.mouse.move(box.x + box.width / 2, box.y + 15);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 45, box.y + 45, {steps: 8});
  await page.mouse.up();
  await save();
  const dragged = await readFile(metadata.reusable_source, 'utf8');
  assert.notEqual(dragged, expected, 'the drag must produce an actual source edit');
  const withoutPosition = value => value.replace(/NodePosition\(node="build", x=[^,]+, y=[^)]+\)/, 'POSITION');
  assert.equal(withoutPosition(dragged), withoutPosition(expected));
  await page.locator('#editor-refresh').click();
  await page.locator('#editor-status').filter({hasText: 'Opened '}).waitFor();
  assert.equal(await page.locator('#editor-source').inputValue(), dragged);
  assert.deepEqual(faults, []);
  await page.screenshot({path: join(evidence, 'literal-preservation.png')});
  console.log(JSON.stringify({result: 'PASS', evidence}));
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  await new Promise(resolveExit => server.once('exit', resolveExit));
}
