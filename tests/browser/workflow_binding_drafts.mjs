/** Browser witness for selectable SVG disconnect, incomplete drafts, and promotion. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';

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
const hitPoint = async locator => locator.evaluate(element => {
  const total = element.getTotalLength();
  for (let distance = 2; distance < total; distance += 2) {
    const point = element.getPointAtLength(distance), screen = new DOMPoint(point.x, point.y).matrixTransform(element.getScreenCTM());
    if (document.elementFromPoint(screen.x, screen.y) === element) return {x: screen.x, y: screen.y};
  }
  return null;
});
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Fixture startup timeout: ${errors}`)), 30000);
    lines.once('line', line => { clearTimeout(timer); accept(JSON.parse(line)); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${errors}`)); });
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push({url: request.url(), body: request.postDataJSON()}); });
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'));
  const original = await readFile(metadata.source, 'utf8');
  const wire = page.locator('path.circuit-wire-target[data-from="propose"][data-to="implement"][data-argument="output"]');
  const output = page.locator('#circuit-output-propose'), input = page.locator('#circuit-input-implement-output');
  assert.equal(await wire.count(), 1);

  // A user scrolls the canvas into view before pointing at a wire; off-screen points have no hit target.
  await page.locator('.circuit-viewport').scrollIntoViewIfNeeded();
  await wire.scrollIntoViewIfNeeded();
  const wirePoint = await hitPoint(wire);
  assert.ok(wirePoint);
  assert.equal(await page.evaluate(({x, y}) => document.elementFromPoint(x, y)?.classList.contains('circuit-wire-target'), wirePoint), true, 'A visible wire stroke receives pointer hits');
  await page.mouse.click(wirePoint.x, wirePoint.y);
  assert.equal(await wire.getAttribute('aria-label'), 'Connection propose.result to implement.output');
  assert.equal(await wire.getAttribute('aria-pressed'), 'true');
  assert.ok(await page.locator('.circuit-wire.selected').count());
  await page.locator('.circuit-disconnect').click();
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()).includes('incomplete'));
  assert.match(await input.textContent(), /Required · unbound/);
  assert.equal(await page.locator('#editor-review').isDisabled(), true);
  assert.equal(await page.locator('#editor-save').isDisabled(), true);
  assert.equal(await page.evaluate(() => window.workflowEditor.state.dirty), true);
  assert.equal(await page.locator('#new-run-review').isDisabled(), true);
  assert.equal(await page.locator('#new-run-prepare').isDisabled(), true);
  assert.equal(await readFile(metadata.source, 'utf8'), original, 'Disconnect only changes the local draft');

  await output.click(); await input.click();
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()) === 'No pending edits.');
  const restoredWire = page.locator('path.circuit-wire-target[data-from="propose"][data-to="implement"][data-argument="output"]');
  await restoredWire.focus(); await page.keyboard.press('Enter'); await page.keyboard.press('Delete');
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()).includes('incomplete'));
  await output.click(); await input.click();
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()) === 'No pending edits.');
  assert.ok(posts.some(item => item.url.endsWith('/draft') && item.body.draft.bindings.some(binding => binding.node === 'implement' && binding.argument === 'output' && binding.source === null)));

  await writeFile(metadata.source, original + '\n# external edit\n');
  const staleWire = page.locator('path.circuit-wire-target[data-from="propose"][data-to="implement"][data-argument="output"]');
  const stalePoint = await hitPoint(staleWire);
  assert.ok(stalePoint);
  await page.mouse.click(stalePoint.x, stalePoint.y);
  await page.locator('.circuit-disconnect').click();
  await page.locator('#editor-conflict').waitFor({state: 'visible'});
  assert.equal(await page.locator('#editor-review').isDisabled(), true);
  assert.equal(await page.locator('#editor-save').isDisabled(), true);
  assert.equal(await page.locator('#editor-rebase').isDisabled(), true);
  assert.match(await page.locator('#editor-conflict-diff').textContent(), /Disconnect implement.output/);
  await page.locator('#editor-discard').click();
  await waitUntil(async () => !(await page.locator('#editor-pending').textContent()).includes('Pending binding draft'));
  assert.match(await page.locator('#editor-source').inputValue(), /external edit/);

  await page.locator('#circuit-node-validate').click();
  const stableSource = await page.locator('#editor-source').inputValue();
  const savedBytes = await readFile(metadata.source, 'utf8');
  const reviewsBeforeCancel = posts.filter(item => item.url.endsWith('/review')).length;
  const savesBeforeCancel = posts.filter(item => item.url.endsWith('/save')).length;
  await page.locator('button[aria-label="Disconnect validate.llm_provider"]').click();
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()).includes('complete'));
  await page.locator('#editor-discard-draft').click();
  assert.equal(await page.locator('#editor-source').inputValue(), stableSource);
  assert.equal(await readFile(metadata.source, 'utf8'), savedBytes);
  assert.equal(posts.filter(item => item.url.endsWith('/review')).length, reviewsBeforeCancel);
  assert.equal(posts.filter(item => item.url.endsWith('/save')).length, savesBeforeCancel);
  await page.locator('button[aria-label="Disconnect validate.llm_provider"]').click();
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()).includes('complete'));
  assert.equal(await page.locator('#editor-review').isDisabled(), false);
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  assert.match(await page.locator('#editor-diff').textContent(), /llm_provider/);
  assert.equal(await readFile(metadata.source, 'utf8'), original + '\n# external edit\n', 'Review has no disk side effect');
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Saved reviewed'));
  assert.doesNotMatch(await readFile(metadata.source, 'utf8'), /llm_provider/);
  await page.locator('#editor-refresh').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'));
  assert.match(await page.locator('#editor-inspector').textContent(), /llm_provider.*Optional · unbound/);
  assert.deepEqual(faults, []);
  console.log('PASS SVG pointer selection/button disconnect, keyboard Delete, required incomplete gate, stale-base refusal/discard, optional disconnect, valid review/save and disk reload.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors) process.stderr.write(errors);
}
