/** Browser witness for the unified editor draft (editor-draft.js): wiring, layout and
 * inspector edits share one draft with undo/redo, Discard to the loaded state, a dirty
 * title/header mark, confirmed Refresh, a beforeunload guard and one reviewed save; an undoable
 * Discard of typed Source text; and Rebase re-applying a layout edit onto a newer disk source.
 * Uses EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE and CONSOLE_BROWSER_EXECUTABLE; no API/GPU.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[key], `Set ${key}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_binding_drafts_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
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
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push({path: new URL(request.url()).pathname, body: request.postDataJSON()}); });
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'));
  const original = await readFile(metadata.source, 'utf8');
  const source = page.locator('#editor-source');
  const loadedSource = await source.inputValue();
  const authored = () => posts.filter(item => !item.path.endsWith('/draft')).map(item => item.path.split('/').at(-1));
  const dirty = () => page.evaluate(() => window.workflowEditor.state.dirty);
  const position = () => page.locator('.circuit-card[data-node="validate"]').evaluate(element => ({...element._position}));
  const manifest = page.getByLabel('task.manifest', {exact: true});
  const disconnect = page.locator('button[aria-label="Disconnect validate.llm_provider"]');
  const mark = async () => ({title: await page.title(), badge: await page.locator('#editor-dirty').isVisible()});
  // Ctrl+Z belongs to text controls while they have focus; shortcuts act from the page.
  const shortcut = async keys => { await page.locator('#view-workflow h1').focus(); await page.keyboard.press(keys); };

  // Loaded state: clean title/header, nothing to undo or discard.
  assert.equal(await dirty(), false);
  assert.deepEqual(await mark(), {title: 'SIDERIUS · Workflow', badge: false});
  for (const id of ['undo', 'redo', 'discard-draft']) assert.equal(await page.locator(`#editor-${id}`).isDisabled(), true, `${id} starts disabled`);
  const loadedPosition = await position(), loadedManifest = await manifest.inputValue();

  // Wiring, then a layout move, then an inspector edit: one draft, never refused as modal.
  await page.locator('#circuit-node-validate').click();
  await disconnect.click();
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()) === 'Pending binding draft · complete');
  assert.equal(await dirty(), true);
  assert.deepEqual(await mark(), {title: '* SIDERIUS · Workflow', badge: true});
  // The fixture stores no positions: cards use the display-only fallback layout, which follows
  // card sizes, and the disconnection folds a row. Undo targets this pre-move display, not the loaded one.
  const beforeMovePosition = await position();
  await page.locator('#circuit-node-validate').focus(); await page.keyboard.press('Alt+ArrowDown');
  const movedPosition = await position();
  assert.notDeepEqual(movedPosition, beforeMovePosition, 'A move is accepted while a connection edit is pending');
  assert.match(await page.locator('#editor-pending').textContent(), /Pending binding draft · complete/, 'A move keeps the keyed inspection');
  await page.getByText('References', {exact: true}).click();
  await manifest.fill('edited-task.json');
  assert.equal(await page.locator('#editor-review').isDisabled(), false, 'Mixed edits are reviewable together');
  assert.deepEqual(authored(), [], 'Editing never reviews or saves');

  // Undo/redo over draft operations, newest first, by keyboard and buttons.
  await shortcut('Control+z');
  assert.equal(await manifest.inputValue(), loadedManifest, 'Ctrl+Z undoes the inspector edit');
  assert.deepEqual(await position(), movedPosition);
  await page.locator('#editor-undo').click();
  assert.deepEqual(await position(), beforeMovePosition, 'Undo restores the card position');
  assert.equal(await disconnect.isVisible(), false, 'The disconnection is still pending after two undos');
  await shortcut('Control+Shift+z');
  assert.deepEqual(await position(), movedPosition, 'Ctrl+Shift+Z redoes the move');
  assert.equal(await page.locator('#editor-redo').isDisabled(), false);
  await page.locator('#editor-redo').click();
  assert.equal(await manifest.inputValue(), 'edited-task.json');
  assert.equal(await page.locator('#editor-redo').isDisabled(), true);
  await shortcut('Control+z');
  assert.equal(await manifest.inputValue(), loadedManifest);

  // Discard restores the loaded state locally (no disk read) and is itself undoable.
  const getsBefore = [];
  page.on('request', request => { if (request.method() === 'GET' && new URL(request.url()).pathname === '/api/editor/example') getsBefore.push(request.url()); });
  await page.locator('#editor-discard-draft').click();
  assert.equal(await dirty(), false);
  assert.deepEqual(await mark(), {title: 'SIDERIUS · Workflow', badge: false});
  assert.deepEqual(await position(), loadedPosition);
  assert.equal(await disconnect.isVisible(), true, 'Discard restores the loaded connection');
  assert.equal(await source.inputValue(), loadedSource);
  assert.equal(await page.locator('#editor-pending').textContent(), 'No pending edits.');
  assert.deepEqual(getsBefore, [], 'Discard is not a re-read from disk');
  await page.locator('#editor-undo').click();
  assert.equal(await dirty(), true, 'Undo after Discard restores the draft');
  assert.deepEqual(await position(), movedPosition);
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()) === 'Pending binding draft · complete');

  // Refresh from disk is separate from Discard and confirms when dirty.
  let confirmText = null;
  page.once('dialog', dialog => { confirmText = dialog.message(); void dialog.dismiss(); });
  await page.locator('#editor-refresh').click();
  await waitUntil(async () => confirmText !== null);
  assert.match(confirmText, /refresh from disk/i);
  assert.equal(await dirty(), true, 'A declined refresh keeps the draft');
  assert.deepEqual(await position(), movedPosition);

  // One review and one save carry the connection patch and the layout together, as reviewed bytes.
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  const review = posts.findLast(item => item.path.endsWith('/review'));
  assert.equal(review.body.proposal.kind, 'draft');
  assert.deepEqual(review.body.proposal.draft.bindings, [{node: 'validate', argument: 'llm_provider', source: null}]);
  assert.deepEqual(review.body.proposal.draft.base_document.positions.find(item => item.node === 'validate'), {node: 'validate', ...movedPosition});
  const reviewedSource = await source.inputValue();
  assert.equal(await readFile(metadata.source, 'utf8'), original, 'Review has no disk side effect');
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Saved reviewed'));
  assert.deepEqual(authored(), ['review', 'save']);
  const saved = await readFile(metadata.source, 'utf8');
  assert.equal(saved, reviewedSource, 'Save writes exactly the reviewed bytes');
  assert.doesNotMatch(saved, /llm_provider/);
  assert.equal(await dirty(), false);
  assert.deepEqual(await mark(), {title: 'SIDERIUS · Workflow', badge: false});
  assert.equal(await page.locator('#editor-undo').isDisabled(), true, 'Saving starts a new loaded state');
  assert.deepEqual(await position(), movedPosition, 'The saved layout reloads from disk');

  // Discarding typed Source text is undoable too: Undo brings the text back as dirty Source text.
  const sourceDirty = () => page.evaluate(() => window.workflowEditor.state.sourceDirty);
  await page.locator('#editor-advanced').evaluate(details => { details.open = true; });
  const typedSource = saved + '# typed, not reviewed\n';
  await source.fill(typedSource);
  assert.equal(await sourceDirty(), true);
  assert.equal(await page.locator('#editor-undo').isDisabled(), true, 'Undo waits while Source text is dirty');
  assert.equal(await page.locator('#editor-discard-draft').isDisabled(), false);
  await page.locator('#editor-discard-draft').click();
  assert.equal(await source.inputValue(), saved);
  assert.equal(await dirty(), false);
  assert.match(await page.locator('#editor-status').textContent(), /typed source text discarded.*Undo restores them/);
  await page.locator('#editor-undo').click();
  assert.equal(await source.inputValue(), typedSource, 'Undo after Discard restores the typed Source text');
  assert.equal(await sourceDirty(), true);
  assert.equal(await dirty(), true);
  await page.locator('#editor-discard-draft').click();
  assert.equal(await source.inputValue(), saved);
  await page.locator('#editor-advanced').evaluate(details => { details.open = false; });

  // Rebase after a conflict re-applies structured edits onto the newer disk source:
  // the next proposal keeps the disk change instead of silently reverting it.
  await page.locator('#circuit-node-validate').focus(); await page.keyboard.press('Alt+ArrowDown');
  const rebasedPosition = await position();
  const diskSource = saved.replace("manifest='task/manifest.json'", "manifest='task/disk-manifest.json'");
  assert.notEqual(diskSource, saved);
  await writeFile(metadata.source, diskSource);
  await page.locator('#editor-review').click();
  await page.locator('#editor-conflict').waitFor({state: 'visible'});
  await page.locator('#editor-rebase').click();
  assert.match(await page.locator('#editor-status').textContent(), /edits were re-applied/);
  assert.equal(await manifest.inputValue(), 'task/disk-manifest.json', 'The draft now carries the disk change');
  assert.deepEqual(await position(), rebasedPosition, 'The draft keeps the layout edit');
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  const rebasedReview = posts.findLast(item => item.path.endsWith('/review'));
  assert.equal(rebasedReview.body.proposal.kind, 'document');
  assert.equal(rebasedReview.body.proposal.document.definition.task.manifest, 'task/disk-manifest.json');
  assert.match(await source.inputValue(), /task\/disk-manifest\.json/);
  await page.locator('#editor-discard-draft').click();
  assert.equal(await source.inputValue(), diskSource, 'Discard after Rebase restores the chosen disk version');
  assert.equal(await dirty(), false);

  // An unsaved edit arms the beforeunload guard.
  await page.locator('#circuit-node-validate').focus(); await page.keyboard.press('Alt+ArrowUp');
  assert.equal(await dirty(), true);
  assert.deepEqual(faults, []);
  // Same real-exit pattern as console_navigation.mjs: a dismissed reload keeps the draft.
  let unloadDialog = null;
  page.once('dialog', async dialog => { unloadDialog = dialog.type(); await dialog.dismiss(); });
  await page.reload({timeout: 3000}).catch(() => {});
  assert.equal(unloadDialog, 'beforeunload');
  assert.equal(await dirty(), true, 'Declining the exit keeps the unsaved draft');
  console.log('PASS unified draft: wire+move+inspector edit in one draft, keyboard/button undo/redo, local undoable Discard (including typed Source text), Rebase re-applying edits onto the disk source, dirty title/header, confirmed refresh, beforeunload guard and one reviewed byte-exact save.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors) process.stderr.write(errors);
}
