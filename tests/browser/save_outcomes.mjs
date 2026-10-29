/** Save outcomes witness (red-team S-1..S-5, E-3..E-5, A-5, tour #9/#18), beginner view.
 * Real Chromium + real authoring API (workflow_editor_server) + temporary project files.
 * - S-1: a structured edit that re-renders the file names the removed comment in the Save
 *   step (server-computed), also after "Reapply my changes onto latest".
 * - E-3 / S-3 / S-4: read-only file, a 500 text/plain reply and a busy lock each give their
 *   own "Not saved" sentence; the checked proposal and the open Save step stay.
 * - S-2: a save whose follow-up reload fails says "Saved as …", and the next save is no conflict.
 * - S-5: the conflict card shows a line diff of what changed on disk, not two whole files.
 * - E-5: a failed draft check shows "check failed" and Check again, never "Checking…" forever.
 * - E-4: opening a missing file names the reason and the path.
 * Explicit env: EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE.
 * No provider calls, native launch, datasets or downloads. Server is cleaned up.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {chmod, readFile, rename, writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = ''; server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
const metadata = await Promise.race([new Promise((accept, reject) => { lines.once('line', line => accept(JSON.parse(line))); server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`))); }), new Promise((_, reject) => setTimeout(() => reject(new Error('server startup timeout')), 15000))]);
let browser;
async function waitUntil(predicate, what = 'condition') { const deadline = Date.now() + 15000; while (!(await predicate())) { if (Date.now() > deadline) throw new Error(`Browser condition timed out: ${what}`); await new Promise(resolve => setTimeout(resolve, 50)); } }
const file = metadata.five_node_source;
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const faults = []; page.on('pageerror', error => faults.push(error.message));
  for (let tries = 0; ; tries++) {
    try { await page.goto(metadata.origin + '/#workflow'); break; }
    catch (error) { if (tries >= 20) throw error; await new Promise(resolve => setTimeout(resolve, 100)); }
  }
  const status = () => page.locator('#editor-status').textContent();
  const pending = () => page.locator('#editor-pending').textContent();
  const strip = page.locator('#editor-save-confirm'), comments = page.locator('#editor-save-comments');
  const saveButton = page.locator('#editor-save');
  // A hand-written comment the canonical re-render drops.
  const original = await readFile(file, 'utf8');
  await writeFile(file, '# my note about this workflow\n' + original);
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await waitUntil(async () => (await status()).startsWith('Opened '), 'open');
  await page.locator('#editor-project').selectOption('five_node');
  await waitUntil(async () => (await status()) === 'Opened five_node.', 'open five_node (plain status sentence, tour #9)');
  assert.equal(await page.locator('#editor-history > summary').isVisible(), true, 'Version history is a beginner entry (A-3)');
  assert.match(await page.locator('#editor-discard-draft').textContent(), /Revert to saved/, 'A-5: one plain name per action');
  const move = async () => {
    const id = await page.locator('.circuit-card').first().getAttribute('data-node');
    await page.locator(`#circuit-node-${id}`).focus();
    await page.keyboard.press('Alt+ArrowDown');
    await waitUntil(async () => page.evaluate(() => window.workflowEditor.state.dirty), 'moved');
  };
  const check = async () => {
    await page.locator('#editor-review').click();
    await waitUntil(async () => (await strip.isVisible()) && !(await saveButton.isDisabled()), 'Save step open');
  };

  // S-1 + tour #18: one move re-renders the file; the Save step says which comment goes.
  await move();
  assert.equal(await page.locator('#editor-version-tag .dirty-dot').isVisible(), true, 'Dirty dot beside the workflow name');
  await check();
  assert.equal(await comments.isVisible(), true, 'Comment loss is shown in the beginner Save step');
  assert.match(await comments.textContent(), /1 comment will be removed \(# my note about this workflow\)/);
  assert.equal(await status(), 'Checked. Name the version, then save.');
  const checked = await readFile(file, 'utf8');

  // E-3: a read-only file is refused by the server; nothing is written; the step stays.
  await chmod(file, 0o444);
  await saveButton.click();
  await waitUntil(async () => (await status()).includes('This file is read-only on disk'), 'read-only refusal');
  assert.match(await status(), /^Not saved\. This file is read-only on disk: /);
  assert.equal(await readFile(file, 'utf8'), checked);
  assert.equal(await strip.isVisible(), true, 'The checked proposal stays ready after a refusal');
  await chmod(file, 0o644);

  // S-3 / S-4: a 500 text/plain reply is never a raw parse error; the file is re-read and unchanged.
  await page.route('**/api/editor/five_node/save', route => route.fulfill({status: 500, contentType: 'text/plain', body: 'Internal Server Error'}), {times: 1});
  await saveButton.click();
  await waitUntil(async () => (await status()).startsWith('Not saved: the server'), 'server failure sentence');
  assert.match(await status(), /The file on disk is unchanged and your changes are kept/);
  assert.doesNotMatch(await status(), /JSON|Unexpected token/);
  await page.route('**/api/editor/five_node/save', route => route.fulfill({status: 409, contentType: 'application/json',
    body: JSON.stringify({error: {code: 'busy', message: 'another cooperating writer holds the source lock'}})}), {times: 1});
  await saveButton.click();
  await waitUntil(async () => (await status()).startsWith('Not saved: another save of this workflow is in progress'), 'busy sentence');
  assert.equal(await readFile(file, 'utf8'), checked);

  // S-2: the save succeeds, the reload after it fails: "Saved as", and no false conflict next time.
  // Deterministic: the read block is armed only once the save POST's response has arrived,
  // and every GET of the source inside that window fails, so no unrelated earlier reader
  // can consume it (a parallel-load flake when only the first GET was blocked).
  let reloadArmed = false;
  await page.route('**/api/editor/five_node/save', async route => {
    const response = await route.fetch(); reloadArmed = true; await route.fulfill({response});
  }, {times: 1});
  await page.route('**/api/editor/five_node', route => (route.request().method() === 'GET' && reloadArmed ? route.abort('connectionreset') : route.continue()));
  await page.locator('#editor-version-name').fill('moved');
  await saveButton.click();
  await waitUntil(async () => (await status()).startsWith('Saved as "moved". Reloading the file afterwards failed'), 'saved, reload failed');
  reloadArmed = false;
  await page.unroute('**/api/editor/five_node');
  assert.doesNotMatch(await readFile(file, 'utf8'), /# my note/, 'The warned comment is gone after Save');
  await waitUntil(async () => (await page.locator('#editor-version-tag .version-tag-name').textContent()) === 'moved', 'version tag');
  await move(); await check();
  assert.equal(await comments.isHidden(), true, 'No comment left to lose');
  await saveButton.click();
  await waitUntil(async () => (await status()) === 'Saved as "v2".', 'second save is no conflict');
  assert.equal(await page.locator('#editor-conflict').isHidden(), true);

  // S-5 + the reapply path of S-1: another writer adds a comment while edits are pending.
  await move();
  const disk = await readFile(file, 'utf8');
  await writeFile(file, '# disk note\n' + disk);
  await page.locator('#editor-review').click();
  await page.locator('#editor-conflict').waitFor({state: 'visible'});
  assert.match(await page.locator('#editor-conflict-summary').textContent(), /saved from another tab or changed on disk .* Your unsaved changes are kept/);
  const diff = await page.locator('#editor-conflict-diff').textContent();
  assert.match(diff, /^\+ # disk note$/m);
  assert.ok(diff.split('\n').length < 12, `A line diff, not two whole files (${diff.split('\n').length} lines)`);
  assert.equal(await page.locator('#editor-current').isVisible(), false, 'The whole file is advanced detail');
  assert.equal(await page.locator('#editor-discard').textContent(), 'Reload from disk');
  await page.locator('#editor-rebase').click();
  await waitUntil(async () => (await status()).startsWith('Your changes are reapplied onto the latest version.'), 'reapplied');
  await check();
  assert.match(await comments.textContent(), /1 comment will be removed \(# disk note\)/, 'Reapply path warns too');
  await page.locator('#editor-save-cancel').click();

  // E-5: a non-JSON 502 during the draft check leaves a failed state with Check again.
  await page.locator('#editor-discard-draft').click();
  await waitUntil(async () => !(await page.evaluate(() => window.workflowEditor.state.dirty)), 'reverted');
  assert.match(await status(), /^Reverted to the saved version\. Undo brings your changes back\.$/);
  await page.route('**/api/editor/five_node/nodes-draft', route => route.fulfill({status: 502, contentType: 'text/html', body: '<html>Bad gateway</html>'}));
  const card = page.locator('.circuit-card').last();
  await card.click({position: {x: 20, y: 12}});
  await page.keyboard.press('Delete');
  await waitUntil(async () => (await pending()).includes('check failed'), 'check failed');
  assert.equal(await page.locator('#editor-check-again').isVisible(), true);
  assert.match(await status(), /^Couldn't check your changes: .* They are kept\. Press Check again\.$/);
  assert.equal(await page.locator('#editor-save-reason').textContent(), 'Check failed: press Check again');
  await page.unroute('**/api/editor/five_node/nodes-draft');
  await page.locator('#editor-check-again').click();
  await waitUntil(async () => !(await pending()).includes('check'), 'checked again');
  assert.equal(await page.locator('#editor-check-again').isHidden(), true);
  await page.locator('#editor-discard-draft').click();

  // E-4: a missing file names the reason and its path.
  await page.locator('#editor-project').selectOption('example');
  await waitUntil(async () => (await status()) === 'Opened example.', 'open example');
  await rename(file, file + '.aside');
  await page.locator('#editor-project').selectOption('five_node');
  await waitUntil(async () => (await status()).startsWith("Can't open five_node:"), 'missing file');
  assert.equal(await status(), `Can't open five_node: Workflow file not found: ${file}.`);
  await rename(file + '.aside', file);

  assert.deepEqual(faults, []);
  console.log('PASS save outcomes: comment-loss warning (save + reapply), read-only/500/busy refusals keep the checked step, saved-but-reload-failed, line-diff conflict, failed check with Check again, missing-file path.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
