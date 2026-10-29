/** Named versions witness: real Chromium + real authoring API + temporary project.
 * Save records a name/time/SHA-256 beside the source; history lists versions,
 * marks the current one, shows a diff and opens old bytes read-only. The name field
 * flags a used name and an invisible character as typed (red-team S-6); "Restore this
 * version as a draft" turns old bytes into unsaved changes without writing (A-3); a file
 * the console never saved is never called a saved version (A-6/A-7, page-bar tag).
 * Explicit env: EDITOR_PYTHON (this checkout .venv/bin/python),
 * CONSOLE_PLAYWRIGHT_MODULE and CONSOLE_BROWSER_EXECUTABLE (existing installs).
 * No provider calls, native launch, datasets or downloads. Server is cleaned up.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = ''; server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
const metadata = await Promise.race([new Promise((accept, reject) => { lines.once('line', line => accept(JSON.parse(line))); server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`))); }), new Promise((_, reject) => setTimeout(() => reject(new Error('server startup timeout')), 15000))]);
let browser;
async function waitUntil(predicate) { const deadline = Date.now() + 15000; while (!(await predicate())) { if (Date.now() > deadline) throw new Error('Browser condition timed out'); await new Promise(resolve => setTimeout(resolve, 50)); } }
const recordPath = metadata.source + '.versions.json';
const record = async () => JSON.parse(await readFile(recordPath, 'utf8'));
try {
  const require = createRequire(import.meta.url);
  const {chromium} = require(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
  const faults = []; page.on('pageerror', error => faults.push(error.message));
  for (let tries = 0; ; tries++) {
    try { await page.goto(metadata.origin + '/#workflow'); break; }
    catch (error) { if (tries >= 20) throw error; await new Promise(resolve => setTimeout(resolve, 100)); }
  }
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened '));
  const rows = page.locator('#editor-history-list > li');
  const nameInput = page.locator('#editor-version-name');
  const status = () => page.locator('#editor-status').textContent();
  const source = page.locator('#editor-source');
  await page.locator('#editor-history > summary').click();
  await page.locator('#editor-advanced > summary').click();

  // Backward compatibility: no record file yet; the current file is one unnamed version.
  await waitUntil(async () => (await rows.count()) === 1);
  assert.match(await rows.first().textContent(), /Current file \(not saved in the console yet\).*Current/);
  assert.doesNotMatch(await rows.first().textContent(), /saved version/i);
  assert.match(await page.locator('#editor-history-status').textContent(), /No saved versions yet/);
  const tag = page.locator('#editor-version-tag');
  await waitUntil(async () => await tag.isVisible());
  const tagName = () => tag.locator('.version-tag-name').textContent();
  assert.equal(await tagName(), 'Not saved here yet', 'A never-saved file shows no version name');
  assert.equal(await nameInput.inputValue(), 'v1', 'Save offers an automatic name');
  await assert.rejects(readFile(recordPath), 'Opening the editor writes no record');

  async function checkEdit(line) {
    await source.fill((await source.inputValue()) + line);
    await page.locator('#editor-review').click();
    await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  }
  async function saveEdit(line, name) {
    await checkEdit(line);
    if (name !== undefined) await nameInput.fill(name);
    await page.locator('#editor-save').click();
  }

  // Named Save: record beside the source holds the observed base and the named version.
  await saveEdit('# first named edit\n', 'baseline');
  await waitUntil(async () => (await status()).includes('Saved as "baseline"'));
  let saved = await record();
  assert.equal(saved.schema_id, 'siderius.workflow-versions/v1');
  assert.deepEqual(saved.versions.map(v => [v.origin, v.name]), [['observed', null], ['saved', 'baseline']]);
  await waitUntil(async () => (await rows.count()) === 2);
  assert.match(await rows.first().textContent(), /baseline.*Current/, 'Newest first and marked current');
  await waitUntil(async () => (await tagName()) === 'baseline');
  assert.equal(await tag.locator('.dirty-dot').isHidden(), true, 'Clean after Save: no dirty dot');
  assert.equal(await nameInput.inputValue(), 'v2', 'Name field resets to the next suggestion');

  // Default name, then diff vs previous from the history panel.
  await saveEdit('# second edit\n');
  await waitUntil(async () => (await status()).includes('Saved as "v2"'));
  await waitUntil(async () => (await rows.count()) === 3);
  assert.match(await rows.first().textContent(), /v2.*Current/);
  assert.doesNotMatch(await rows.nth(1).textContent(), /Current/);
  const disk = await readFile(metadata.source);
  const posts = []; page.on('request', request => { if (request.method() === 'POST') posts.push(request.url()); });
  await rows.first().getByRole('button', {name: 'View v2'}).click();
  await page.locator('#editor-history-diff').waitFor({state: 'attached'});
  assert.match(await page.locator('#editor-history-detail h3').textContent(), /^v2 \(read-only\) · [0-9a-f]{12}$/);
  assert.match(await page.locator('#editor-history-diff').textContent(), /\+# second edit/);
  assert.match(await page.locator('#editor-history-detail').textContent(), /Changes since baseline/);
  assert.equal(await page.locator('#editor-history-restore').count(), 0, 'The current version offers no restore');
  // Opening an older version is read-only: no POST, no file change, current editor state intact.
  await rows.nth(1).getByRole('button', {name: 'View baseline'}).click();
  await waitUntil(async () => (await page.locator('#editor-history-detail h3').textContent()).startsWith('baseline'));
  assert.doesNotMatch(await page.locator('#editor-history-source').textContent(), /# second edit/);
  assert.equal(posts.length, 0, 'History never submits');
  assert.deepEqual(await readFile(metadata.source), disk);
  assert.match(await source.inputValue(), /# second edit/);

  // S-6: a used name and an invisible character are flagged as typed; Save waits for a fix.
  await checkEdit('# third edit\n');
  const problem = page.locator('#editor-version-problem');
  await nameInput.fill('baseline');
  assert.match(await problem.textContent(), /"baseline" is already used/);
  assert.equal(await page.locator('#editor-save').isDisabled(), true, 'A used name cannot be saved');
  await nameInput.fill('third\u200b');
  assert.match(await problem.textContent(), /invisible character/);
  assert.equal(await page.locator('#editor-save').isDisabled(), true, 'An invisible character cannot be saved');
  assert.deepEqual(await readFile(metadata.source), disk);
  await nameInput.fill('third');
  assert.equal(await problem.isHidden(), true);
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await status()).includes('Saved as "third"'));
  await waitUntil(async () => (await rows.count()) === 4);

  // A-3: restore an older version as unsaved changes; nothing is written until Save.
  const beforeRestore = await readFile(metadata.source);
  await rows.nth(2).getByRole('button', {name: 'View baseline'}).click();
  await waitUntil(async () => (await page.locator('#editor-history-detail h3').textContent()).startsWith('baseline'));
  await page.locator('#editor-history-restore').click();
  await waitUntil(async () => (await status()).includes('Version "baseline" is restored as unsaved changes'));
  assert.deepEqual(await readFile(metadata.source), beforeRestore, 'Restore writes nothing');
  assert.doesNotMatch(await source.inputValue(), /# second edit|# third edit/);
  assert.match(await source.inputValue(), /# first named edit/);
  assert.equal(await page.locator('#editor-save-confirm').isVisible(), true, 'The Save step opens for the restored bytes');
  assert.equal(await tag.locator('.dirty-dot').isVisible(), true, 'Restored but unsaved: the dirty dot shows');
  await nameInput.fill('back-to-baseline');
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await status()).includes('Saved as "back-to-baseline"'));
  assert.doesNotMatch(await readFile(metadata.source, 'utf8'), /# third edit/);
  await waitUntil(async () => (await rows.count()) === 5);
  assert.deepEqual(faults, []);
  console.log('named versions witness passed');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
