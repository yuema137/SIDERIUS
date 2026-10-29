/** Quick start (operator decision 2026-10-28): Home -> Quick start -> choose a task ->
 * the default research-loop template opens as an unsaved editor draft whose loop and
 * training parameters are visible in the ordinary panel. Nothing is written before Save. */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdir, readFile, rename} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {join, resolve, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) {
  assert.ok(process.env[name], `Set ${name}`);
}
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-quick-start');
await mkdir(evidence, {recursive: true});
// One runnable project, listed after edit-only ones in configuration order: Quick start must preselect it.
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: {...process.env, EDITOR_RUNNABLE_PROJECTS: 'five_node'}});
let serverErrors = '';
server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
const metadata = await new Promise((resolveMetadata, reject) => {
  lines.once('line', line => resolveMetadata(JSON.parse(line)));
  server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`)));
  setTimeout(() => reject(new Error(`server startup timeout: ${serverErrors}`)), 15000);
});
let browser;
async function waitUntil(predicate, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (!(await predicate())) {
    if (Date.now() > deadline) throw new Error('Browser condition timed out');
    await new Promise(resolveWait => setTimeout(resolveWait, 50));
  }
}
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push(new URL(request.url()).pathname); });
  await page.goto(metadata.origin + '/#home');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  // The configured-task quick Prepare form is not a beginner entry (advanced only).
  assert.equal(await page.locator('#configured-task').isVisible(), false);
  const before = await readFile(metadata.reusable_source);
  await page.locator('#home-quick-start').click();
  const dialog = page.locator('#quick-start-dialog');
  await waitUntil(() => dialog.evaluate(el => el.open));
  assert.equal(new URL(page.url()).hash, '#workflow');
  await page.locator('#quick-start-project option[value="reusable"]').waitFor({state: 'attached'});
  // A new user's first action is runnable: the first runnable project is preselected and listed first.
  assert.equal(await page.locator('#quick-start-project').inputValue(), 'five_node', 'Quick start preselects a runnable project');
  assert.equal(await page.locator('#quick-start-project option').first().getAttribute('value'), 'five_node');
  assert.equal(await page.locator('#quick-start-warning').textContent(), '');
  await page.locator('#quick-start-project').selectOption('reusable');
  await page.screenshot({path: join(evidence, 'quick-start-dialog.png')});
  // L-3: an unopenable project fails in the dialog with its reason and can be retried.
  await rename(metadata.reusable_source, metadata.reusable_source + '.aside');
  await page.locator('#quick-start-open').click();
  await page.locator('#quick-start-status').filter({hasText: "Couldn't open reusable"}).waitFor();
  assert.equal(await page.locator('#quick-start-open').isEnabled(), true, 'Retry stays available');
  assert.equal(await dialog.evaluate(el => el.open), true);
  await rename(metadata.reusable_source + '.aside', metadata.reusable_source);
  await page.locator('#quick-start-open').click();
  await waitUntil(async () => !(await dialog.evaluate(el => el.open)), 20000);
  for (const id of ['interpret', 'propose', 'implement', 'validate', 'train']) await page.locator(`#circuit-node-${id}`).waitFor();
  assert.equal(await page.locator('#editor-project').inputValue(), 'reusable');
  assert.ok((await readFile(metadata.reusable_source)).equals(before), 'Quick start never writes before Save');
  assert.ok(posts.every(path => path.endsWith('/template') || path.endsWith('/review')), 'Only the template import and its review: ' + posts);
  // The loop's rounds and stop conditions are visible in the ordinary panel.
  await page.locator('#editor-loop-final-iteration').waitFor({state: 'visible'});
  assert.equal(await page.locator('#editor-loop-final-iteration').inputValue(), '1');
  await page.locator('#editor-loop-stop-conditions').waitFor({state: 'visible'});
  // Training settings are on the Train & tune module.
  await page.locator('#circuit-node-train').click();
  // The author's choice wins over Quick start's bounded advice re-focus (L-6): the clicked
  // module stays selected after that window has passed.
  await page.waitForTimeout(1600);
  assert.equal(await page.locator('#circuit-node-train').getAttribute('aria-pressed'), 'true', 'Train & tune stays selected');
  await page.locator('#editor-training-settings').waitFor({state: 'visible'});
  assert.ok(await page.locator('#editor-training-settings [data-training="trial_max_epochs"]').count() === 1);
  await page.screenshot({path: join(evidence, 'quick-start-draft.png'), fullPage: true});
  assert.deepEqual(faults, []);
  console.log('PASS: Home Quick start opens the default research loop as an unsaved draft with loop and training parameters');
} finally {
  await browser?.close();
  server.kill();
}
