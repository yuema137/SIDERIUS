/** Browser witness for free node drafts: two pending nodes at once, both cards movable,
 * pending-to-pending wiring, an unbound storage input set through "Create external input",
 * undo/redo of that creation, the incomplete gate, and one byte-preserving review+save. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[key], `Set ${key}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.node_palette_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => { errors += chunk; });
const lines = createInterface({input: server.stdout});
const waitUntil = async (predicate, what = 'Browser condition') => {
  const deadline = Date.now() + 20000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error(`${what} timed out`); await new Promise(resolve => setTimeout(resolve, 50)); }
};
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Fixture startup timeout: ${errors}`)), 30000);
    lines.once('line', line => { clearTimeout(timer); accept(JSON.parse(line)); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${errors}`)); });
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}}), faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push({url: request.url(), body: request.postDataJSON()}); });
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  const statusText = () => page.locator('#editor-status').textContent();
  const pendingText = () => page.locator('#editor-pending').textContent();
  await waitUntil(async () => (await statusText()).includes('Opened supported'), 'open');
  const original = await readFile(metadata.source, 'utf8');
  assert.match(original, /# author note: keep me/);
  const palette = page.locator('#editor-palette');
  await waitUntil(async () => (await palette.locator('.palette-entry').count()) > 0, 'catalog');
  const drafts = () => posts.filter(item => item.url.endsWith('/nodes-draft'));

  // Two pending nodes in one draft: the palette stays active after the first.
  await palette.locator('.palette-search').fill('implementation');
  await palette.locator('.palette-entry[data-protocol="proposal-to-implementation"]').click();
  await page.locator('#circuit-node-implementation').waitFor();
  await palette.locator('.palette-search').fill('validation');
  const second = palette.locator('.palette-entry[data-protocol="implementation-to-validation"]');
  assert.equal(await second.getAttribute('aria-disabled'), 'false', 'a second node can be added while one is pending');
  await second.click();
  await page.locator('#circuit-node-validation').waitFor();
  await waitUntil(async () => (await pendingText()).includes('Pending new nodes implementation, validation · incomplete'), 'two incomplete nodes');
  assert.equal(await page.locator('#editor-review').isDisabled(), true, 'incomplete drafts block Review');
  const placed = Object.fromEntries(drafts().at(-1).body.proposal.nodes.map(item => [item.node, {x: item.x, y: item.y}]));

  // Move both cards (pointer drag and Alt+Arrow): pending nodes never freeze the canvas.
  const box = await page.locator('#circuit-node-implementation').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 90, box.y + box.height / 2 + 40, {steps: 5});
  await page.mouse.up();
  await page.locator('#circuit-node-validation').focus();
  await page.keyboard.press('Alt+ArrowDown');

  // Wire: saved -> pending and pending -> pending on the canvas.
  await page.locator('#circuit-output-propose').click();
  await page.locator('#circuit-input-implementation-output').click();
  await page.locator('#circuit-output-implementation').click();
  await page.locator('#circuit-input-validation-output').click();

  // The unbound storage input is explained and created in the inspector.
  await page.locator('#circuit-node-implementation').click();
  const help = page.locator('.external-input-help[data-socket="implementation.storage"]');
  await help.waitFor();
  assert.match(await help.textContent(), /^Storage folder: .+/, 'the contract_names name, not the id');
  const form = page.locator('.external-input-create[data-socket="implementation.storage"]');
  await form.locator('summary').click();
  assert.equal(await form.locator('input[name="external-id"]').inputValue(), 'implementation_storage');
  assert.equal(await form.locator('input[name="external-location"]').inputValue(), '', 'no location is guessed');
  await form.locator('button').click();
  assert.match(await form.locator('.external-input-error').textContent(), /path/, 'a file input needs its path');
  await form.locator('input[name="external-location"]').fill('inputs/build_store.json');
  await form.locator('button').click();
  await waitUntil(async () => (await pendingText()).includes('and input implementation_storage'), 'input created');

  // Undo/redo cover the creation.
  await page.locator('#editor-undo').click();
  await waitUntil(async () => !(await pendingText()).includes('implementation_storage'), 'undo creation');
  await page.locator('#editor-redo').click();
  await waitUntil(async () => (await pendingText()).includes('and input implementation_storage'), 'redo creation');

  // The second node reuses the new input from its select once the server offers it.
  await page.locator('#circuit-node-validation').click();
  const storage = page.locator('select[data-node="validation"][data-argument="storage"]');
  await waitUntil(async () => (await storage.locator('option', {hasText: 'implementation_storage'}).count()) === 1, 'new input offered');
  await storage.selectOption({label: 'implementation_storage'});
  await waitUntil(async () => (await pendingText()).includes('· complete'), 'complete draft');
  assert.equal(await readFile(metadata.source, 'utf8'), original, 'drafts never touch disk');

  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()), 'review');
  const proposal = posts.filter(item => item.url.endsWith('/review')).at(-1).body.proposal;
  assert.equal(proposal.kind, 'node_drafts');
  assert.equal(proposal.document, null, 'moving only new cards keeps the saved document unedited');
  for (const item of proposal.nodes) assert.notDeepEqual({x: item.x, y: item.y}, placed[item.node], `${item.node} moved`);
  const diff = await page.locator('#editor-diff').textContent();
  assert.doesNotMatch(diff, /^-(?!--)/m, 'the review only inserts lines');
  assert.match(diff, /\+\s+id='implementation_storage'/);
  assert.match(diff, /location='inputs\/build_store\.json'/);
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await statusText()).includes('Saved reviewed'), 'save');
  const saved = await readFile(metadata.source, 'utf8');
  for (const pattern of [/# author note: keep me/, /# implement keeps its comment/, /# trailing comment/, /id='implementation'/, /id='validation'/]) assert.match(saved, pattern);
  assert.deepEqual(faults, []);
  console.log('PASS two pending nodes, both moved, saved->pending and pending->pending wiring, storage created in the inspector with undo/redo, incomplete gate, byte-preserving review+save.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors) process.stderr.write(errors);
}
