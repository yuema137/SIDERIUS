/** Delete every module with the advertised mouse + Delete shortcut, then add one module:
 * the problems list names only what remains (red-team E-1, E-2).
 * Fails if click-then-Delete does nothing (focus lost on the select re-render), if the empty
 * canvas lists anything but "Add at least one module", if a problem names a deleted module,
 * if the loop problem disappears once a module is added although the loop still points at
 * deleted modules, or if the Research loop panel keeps offering stop-condition edits. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[key], `Set ${key}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => { errors += chunk; });
const waitUntil = async (predicate, what) => {
  const deadline = Date.now() + 20000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error(`${what} timed out`); await new Promise(next => setTimeout(next, 50)); }
};
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Fixture startup timeout: ${errors}`)), 30000);
    createInterface({input: server.stdout}).once('line', line => { clearTimeout(timer); accept(JSON.parse(line)); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${errors}`)); });
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#editor-project option[value="interpretation"]').waitFor({state: 'attached'});
  await page.locator('#editor-project').selectOption('interpretation');
  await page.locator('#circuit-node-fit').waitFor();
  await page.locator('#editor-loop-final-iteration').waitFor();
  const problems = () => page.locator('#editor-problems .editor-problem-text').allTextContents();
  const cards = () => page.locator('.circuit-card').evaluateAll(items => items.map(item => item.dataset.node));
  const deleted = [];

  // Mouse click on a card heading, then Delete: the shortcut the canvas help advertises.
  for (let left = (await cards()).length; left > 0; left--) {
    const id = (await cards())[0];
    await page.locator(`#circuit-node-${id}`).click();
    assert.equal(await page.evaluate(() => document.activeElement?.id), `circuit-node-${id}`, 'the clicked card keeps keyboard focus');
    await page.keyboard.press('Delete');
    await waitUntil(async () => !(await cards()).includes(id), `delete ${id} by mouse + Delete`);
    deleted.push(id);
    await waitUntil(async () => !/checking/.test(await page.locator('#editor-pending').textContent()), 'inspection');
    for (const text of await problems()) assert.ok(!deleted.some(gone => text.includes(gone)), `no problem names a deleted module: ${text}`);
  }
  await waitUntil(async () => JSON.stringify(await problems()) === JSON.stringify(['Add at least one module.']), 'empty canvas: one problem');
  // B8-5: one count everywhere; the loop panel notes the waiting loop without a second
  // problem, and the status line names the empty workflow (nothing is red).
  assert.equal(await page.locator('#editor-loop-broken').count(), 0, 'an empty canvas has one problem, not a second loop problem');
  assert.equal(await page.locator('#editor-loop-waiting').count(), 1);
  assert.match(await page.locator('#problems-chip').textContent(), /^1 problem$/);
  assert.match(await page.locator('#editor-status').textContent(), /The workflow is empty/);
  assert.doesNotMatch(await page.locator('#editor-status').textContent(), /marked in red/);
  assert.equal(await page.locator('#editor-loop-add-metric-threshold').count(), 0, 'no stop-condition edits on a broken loop');
  assert.equal(await page.locator('#editor-loop-remove').isEnabled(), true, 'the loop can still be removed');

  // One new module: its own missing input and the still-broken loop, nothing else.
  const palette = page.locator('#editor-palette');
  await palette.locator('.palette-search').fill('implementation');
  await palette.locator('.palette-entry[data-protocol="proposal-to-implementation"]').click();
  await waitUntil(async () => (await cards()).length === 1, 'one module added');
  const added = (await cards())[0];
  await waitUntil(async () => (await problems()).length >= 2, 'problems of the new draft');
  const listed = await problems();
  assert.ok(listed.some(text => /research loop feeds back between deleted modules/i.test(text)), `loop problem kept: ${listed}`);
  assert.ok(listed.some(text => /^Implement: .+ is not connected$/.test(text)), `the new module's input: ${listed}`);
  assert.ok(!listed.includes('Add at least one module.'), 'the canvas is no longer empty');
  for (const text of listed) assert.ok(!deleted.some(gone => text.includes(gone)), `no problem names a deleted module: ${text}`);
  assert.ok(added && !deleted.includes(added));
  assert.equal(await page.locator('#editor-loop-broken').count(), 1, 'the loop stays broken until its modules return');
  assert.deepEqual(faults, []);
  console.log('PASS mouse + Delete removes every module; empty canvas lists only "Add at least one module"; one new module lists its own input plus the broken loop; no deleted module is named.');
} finally {
  await browser?.close();
  server.kill();
}
