/** Store-scoped operation memory through production browser controllers.
 * Synthetic HTTP observations only; no launches reach a worker or provider.
 */
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve, basename} from 'node:path';
import {fileURLToPath} from 'node:url';
import {showAllConsoleSections} from './console_view_flags.mjs';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../src/tools/candidate_console/static');
const server = createServer(async (request, response) => {
  try {
    const name = basename(new URL(request.url, 'http://fixture').pathname) || 'index.html';
    const body = await readFile(resolve(root, name));
    response.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html');
    response.end(body);
  } catch { response.writeHead(404); response.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const stores = ['a'.repeat(32), 'b'.repeat(32)];
const ids = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'];
const key = store => 'siderius.operation_id.v1/' + store;
let browser, store = stores[0];
const operations = [], faults = [];
async function until(predicate) {
  const deadline = Date.now() + 10000;
  while (!(await predicate())) {
    assert.ok(Date.now() < deadline, 'Browser condition timed out');
    await new Promise(resolve => setTimeout(resolve, 25));
  }
}
async function connect(page) {
  if (await page.locator('#access-change').isVisible()) await page.locator('#access-change').click();
  await page.locator('#token').fill('synthetic-token');
  await page.locator('#access-form button').click();
  await until(() => page.evaluate(() => window.consoleSession.connected));
}
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage();
  page.on('pageerror', error => faults.push(error.message));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const reply = (json, status = 200) => route.fulfill({json, status});
    if (path === '/api/choices') return reply({operations_store_id: store, tasks: []});
    if (path === '/api/tasks') return reply({tasks: []});
    if (path === '/api/native-chain/choices') return reply([{choice_id: 'native', label: 'Synthetic capture'}]);
    if (path === '/api/native-chain/review') return reply({choice_id: 'native', request_digest: 'digest',
      admission: {input_files: []}, read_only: [], devices: [], environment_names: [],
      credential_readiness: {ready: true, required_names: [], present_names: [], missing_names: [], omitted_names: [], instructions: []}});
    if (path === '/api/native-chain/launch') return reply({observation: 'synthetic'});
    if (path.startsWith('/api/operations/')) {
      operations.push({store, path});
      return reply({error: {code: 'unknown_operation', message: 'Synthetic unknown operation'}}, 404);
    }
    if (path === '/api/operations') return reply({operations: [], unreadable: 0, examined: 0, incomplete: false});
    if (path === '/api/recorded-examples') return reply([]);
    return reply({error: {message: 'Unused fixture endpoint'}}, 404);
  });
  await page.goto(origin + '/#monitor');
  await page.evaluate(id => localStorage.setItem('siderius.operation_id', id), ids[0]);
  await page.reload();
  assert.equal(await page.locator('#operation-id').inputValue(), '', 'Unattributable legacy UUID is ignored before Connect');
  await connect(page);
  await until(() => page.evaluate(() => window.consoleSession.operationsStoreId !== null));
  assert.equal(await page.locator('#operation-id').inputValue(), '', 'Legacy UUID is not migrated');
  await page.locator('#operation-id').fill(ids[0]);
  await page.locator('#monitor-button').click();
  await until(() => page.evaluate(k => localStorage.getItem(k), key(stores[0])));
  assert.equal(await page.evaluate(k => localStorage.getItem(k), key(stores[0])), ids[0]);
  // Same browser origin, different operations store after a reload.
  await page.locator('#access-disconnect').click();
  store = stores[1];
  await page.goto(origin + '/#monitor'); await page.reload();
  await connect(page);
  await until(() => page.evaluate(() => window.consoleSession.operationsStoreId !== null));
  assert.equal(await page.locator('#operation-id').inputValue(), '', 'Store B cannot restore A');
  assert.equal(operations.some(item => item.store === stores[1]), false, 'Restoration must never read another store operation');
  await page.locator('#operation-id').fill(ids[1]); await page.locator('#monitor-button').click();
  await until(() => page.evaluate(k => localStorage.getItem(k), key(stores[1])));
  for (const [index, current] of stores.entries()) {
    store = current;
    await page.goto(origin + '/#monitor'); await page.reload(); await connect(page);
  await page.evaluate(() => window.uiSettings.set("advanced", true));
    await until(async () => (await page.locator('#operation-id').inputValue()) === ids[index]);
    assert.match(await page.locator('#remembered-operation').textContent(), /this operations store/);
  }
  // Change connection in the same document: no old convenience value remains.
  store = stores[0]; await connect(page);
  await until(async () => (await page.locator('#operation-id').inputValue()) === ids[0]);
  // A direct URL works without choices, and cannot write under a stale store id.
  await page.locator("#access-disconnect").click();
  await page.goto(origin + '/#monitor/' + ids[1]); await connect(page);
  assert.equal(await page.locator('#operation-id').inputValue(), ids[1]);
  assert.equal(await page.evaluate(() => window.consoleSession.operationsStoreId), null);
  assert.equal(await page.evaluate(k => localStorage.getItem(k), key(stores[0])), ids[0]);
  // Native launch uses exactly the same scoped memory owner as Monitor/Prepare.
  await page.goto(origin + '/#home'); await connect(page);
  await until(() => page.locator('#native-chain-choice option[value="native"]').count());
  await page.locator('#native-chain-choice').selectOption('native');
  await page.locator('#native-chain-review').click();
  await until(() => page.locator('#native-chain-launch').isEnabled());
  await page.locator('#native-chain-launch').click();
  const nativeId = (await page.locator('#native-chain-operation-id').textContent()).replace('Operation UUID: ', '');
  assert.equal(await page.evaluate(k => localStorage.getItem(k), key(stores[0])), nativeId);
  assert.equal(await page.evaluate(k => localStorage.getItem(k), key(stores[1])), ids[1]);
  // Storage exceptions affect neither connecting nor explicit monitoring.
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => { throw new Error('Storage blocked'); };
    Storage.prototype.setItem = () => { throw new Error('Storage blocked'); };
  });
  await page.goto(origin + '/#monitor'); await page.reload(); await connect(page);
  await page.evaluate(() => window.uiSettings.set("advanced", true));
  await page.locator('#operation-id').fill(ids[0]); await page.locator('#monitor-button').click();
  await until(() => page.locator('#monitor-status').textContent().then(text => text.includes('no operation')));
  assert.deepEqual(faults, []);
  console.log('PASS: two stores, reload restoration, legacy isolation, reconnect, explicit URL, native launch and blocked storage');
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
