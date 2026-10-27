/** Focused GUI source round-trip for the saved reusable five-node profile. */
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
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-reusable-interpretation-editor');
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
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/editor.html');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'));
  await page.locator('#editor-project').selectOption('interpretation');
  const source = page.locator('#editor-source');
  await waitUntil(async () => (await source.inputValue()).includes('native-interpretation-candidate/v1'));
  await page.locator('#editor-advanced > summary').click();
  const original = JSON.parse(execFileSync(
    process.env.EDITOR_PYTHON,
    ['-c', 'import sys; from pathlib import Path; from workflows.definition import parse_workflow_source; print(parse_workflow_source(Path(sys.argv[1]).read_text()).model_dump_json())', metadata.interpretation_source],
    {cwd: root, encoding: 'utf8'},
  ));
  assert.equal(original.execution_profile, 'native-interpretation-candidate/v1');
  assert.equal(original.definition.nodes.length, 5);
  assert.equal(original.definition.task.data_root, 'data');

  await page.getByText('References', {exact: true}).click();
  await page.getByLabel('task.manifest', {exact: true}).fill('edited-task.yaml');
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Saved reviewed'));
  await page.locator('#editor-refresh').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'));

  const saved = JSON.parse(execFileSync(
    process.env.EDITOR_PYTHON,
    ['-c', 'import sys; from pathlib import Path; from workflows.definition import parse_workflow_source; print(parse_workflow_source(Path(sys.argv[1]).read_text()).model_dump_json())', metadata.interpretation_source],
    {cwd: root, encoding: 'utf8'},
  ));
  assert.equal(saved.definition.task.manifest, 'edited-task.yaml');
  assert.equal(saved.execution_profile, original.execution_profile);
  assert.equal(saved.definition.task.data_root, original.definition.task.data_root);
  assert.equal(saved.definition.nodes.length, 5);
  assert.deepEqual(saved.definition.nodes, original.definition.nodes);
  assert.deepEqual(saved.definition.loop, original.definition.loop);
  assert.deepEqual(saved.definition.externals, original.definition.externals);
  assert.deepEqual(saved.preparation_options, original.preparation_options);
  assert.deepEqual(saved.training_settings, original.training_settings);
  assert.deepEqual(saved.positions, original.positions);
  assert.deepEqual(faults, []);
  await page.screenshot({path: join(evidence, 'reusable-interpretation-source.png'), fullPage: true});
  console.log(JSON.stringify({result: 'PASS', evidence}));
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  await new Promise(resolveExit => server.once('exit', resolveExit));
}
