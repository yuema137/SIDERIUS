/** Browser witness: palette search/add (click and drag), draft-only incomplete node, bind,
 * review/save with author comments preserved, refused removal with dependants, and
 * byte-identical removal of the added node. */
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

  // Catalog-driven palette: categories per capability, search narrows entries.
  const palette = page.locator('#editor-palette');
  await waitUntil(async () => (await palette.locator('.palette-entry').count()) > 0, 'catalog');
  assert.equal(await palette.locator('.palette-category').count(), 6);
  await palette.locator('.palette-search').fill('validation');
  await waitUntil(async () => (await palette.locator('.palette-category').count()) === 1, 'search');
  const entry = palette.locator('.palette-entry[data-protocol="implementation-to-validation"]');
  assert.equal(await entry.count(), 1);

  // Click to add: a draft-only node with required inputs flagged; nothing is written.
  await entry.click();
  await page.locator('#circuit-node-validation').waitFor();
  await waitUntil(async () => (await pendingText()).includes('Pending new node validation · incomplete'), 'incomplete draft');
  assert.match(await page.locator('#circuit-input-validation-output').textContent(), /Required · unbound/);
  assert.equal(await entry.getAttribute('aria-disabled'), 'true', 'Palette is inactive while a new node is pending');
  assert.equal(await page.locator('#editor-review').isDisabled(), true);
  assert.equal(await page.locator('#editor-save').isDisabled(), true);
  assert.equal(await readFile(metadata.source, 'utf8'), original, 'A draft node never touches disk');
  assert.ok(posts.some(item => item.url.endsWith('/node-draft') && item.body.proposal.capability === 'validation' && item.body.proposal.arguments.length === 0));

  // Bind its inputs on the canvas and in Selection; the draft becomes complete.
  await page.locator('#circuit-output-implement').click();
  await page.locator('#circuit-input-validation-output').click();
  await waitUntil(async () => (await pendingText()).includes('incomplete'), 'still incomplete after one input');
  await page.locator('select[data-node="validation"][data-argument="storage"]').selectOption({label: 'storage'});
  await waitUntil(async () => (await pendingText()).includes('Pending new node validation · complete'), 'complete draft');
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()), 'review');
  const diff = await page.locator('#editor-diff').textContent();
  assert.match(diff, /\+\s+id='validation'/);
  assert.doesNotMatch(diff, /^-(?!--)/m, 'Adding a node only inserts lines');
  assert.match(await statusText(), /Adds validation node 'validation'/);
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await statusText()).includes('Saved reviewed'), 'save add');
  const added = await readFile(metadata.source, 'utf8');
  assert.match(added, /# author note: keep me/);
  assert.match(added, /# implement keeps its comment/);
  assert.match(added, /id='validation'/);

  // Delete key on a capability that others read: refused with an explanation, no write.
  await page.locator('#circuit-node-implement').focus();
  await page.keyboard.press('Delete');
  await waitUntil(async () => (await statusText()).includes('Cannot remove implement'), 'dependants refusal');
  assert.match(await statusText(), /validate\.output reads implement\.result/);
  assert.equal(await readFile(metadata.source, 'utf8'), added);

  // Context menu offers removal and closes on Escape.
  await page.locator('#circuit-node-validate').click({button: 'right'});
  assert.equal(await page.locator('.node-context-menu [role="menuitem"]').textContent(), 'Remove validate');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.node-context-menu').count(), 0);

  // Inspector removal of the added node restores the original bytes exactly.
  await page.locator('#circuit-node-validation').click();
  await page.locator('button[aria-label="Remove validation"]').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()), 'review removal');
  assert.match(await statusText(), /Removes validation with its layout position/);
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await statusText()).includes('Saved reviewed'), 'save removal');
  assert.equal(await readFile(metadata.source, 'utf8'), original, 'add then remove is byte-identical');

  // Drag a palette entry onto the canvas, then cancel the draft without a request to review.
  await palette.locator('.palette-search').fill('');
  assert.equal(await palette.locator('.palette-entry[data-capability="proposal"][data-protocol=""]').getAttribute('aria-disabled'), 'false');
  const reviews = posts.filter(item => item.url.endsWith('/review')).length;
  await palette.locator('.palette-entry[data-capability="proposal"][data-protocol=""]').dragTo(page.locator('.circuit-viewport'));
  await page.locator('#circuit-node-proposal').waitFor();
  await waitUntil(async () => (await pendingText()).includes('Pending new node proposal'), 'drag draft');
  await palette.locator('.palette-cancel').click();
  await waitUntil(async () => (await pendingText()) === 'No pending edits.', 'cancel');
  assert.equal(await page.locator('#circuit-node-proposal').count(), 0);
  assert.equal(posts.filter(item => item.url.endsWith('/review')).length, reviews);
  assert.equal(await readFile(metadata.source, 'utf8'), original);
  assert.deepEqual(faults, []);
  console.log('PASS palette search/click/drag add, incomplete draft gate, bind+review+save with comments, refused dependant removal, context menu, byte-identical removal, cancel.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors) process.stderr.write(errors);
}
