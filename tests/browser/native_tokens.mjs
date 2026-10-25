/** Chromium -> real authenticated HTTP -> durable native root/successor token owner.
 * No API interception, provider calls, native execution or training. Explicit external
 * EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE and
 * CONSOLE_EVIDENCE_DIR are required; only a fresh fixture directory is written.
 */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir, writeFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_EVIDENCE_DIR']) assert.ok(process.env[key], `Set ${key}`);
const evidence = resolve(process.env.CONSOLE_EVIDENCE_DIR);
await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.native_tokens_fixture', resolve(evidence, 'fixture')], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let browser, stderr = '';
server.stderr.on('data', data => {stderr += data;});
const timer = setTimeout(() => {console.error('Native token witness timed out'); server.kill('SIGTERM'); process.exit(2);}, 60000);
try {
  const lines = createInterface({input: server.stdout});
  const metadata = await new Promise((accept, reject) => {
    lines.once('line', line => accept(JSON.parse(line)));
    server.once('exit', code => reject(new Error(`Fixture exited ${code}: ${stderr}`)));
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage();
  const faults = [], calls = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', req => {if (new URL(req.url()).pathname.startsWith('/api/')) calls.push({method: req.method(), path: new URL(req.url()).pathname});});
  await page.goto(metadata.origin);
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  const snapshots = [];
  for (const id of [metadata.root_id, metadata.successor_id]) {
    await page.goto(`${metadata.origin}/#slow-control/${id}`);
    await page.locator('#token').fill(metadata.token);
    await page.locator('#access-form button').click();
    await page.locator('#tokens-status').filter({hasText: 'Whole-run cumulative usage.'}).waitFor();
    await page.locator('#token-rows tr').first().waitFor({state: 'attached'});
    const text = await page.locator('#token-rows').textContent();
    assert.match(text, /100.*1 missing/); assert.match(text, /25/); assert.match(text, /130.*1 missing/);
    assert.equal(await page.locator('#token-rows tr').count(), 2);
    assert.match(await page.locator('#tokens-provenance').textContent(), /Scientific result files were not reverified/);
    assert.match(await page.locator('#tokens-provenance').textContent(), /matches retained records/);
    const cli = JSON.parse(execFileSync(process.env.EDITOR_PYTHON, ['-m', 'tools.candidate_operations', 'tokens', '--store-config', resolve(evidence, 'fixture/store.json'), '--operation-id', id], {cwd: root, encoding: 'utf8'}));
    assert.deepEqual(cli.groups, metadata.expected.groups);
    snapshots.push({id, text, cli});
  }
  assert.equal(snapshots[0].text, snapshots[1].text);
  assert.deepEqual(faults, []);
  assert.ok(calls.filter(call => call.path.endsWith('/tokens')).length >= 2);
  assert.ok(calls.every(call => call.method === 'GET'), 'Monitor must not execute a POST');
  await page.screenshot({path: resolve(evidence, 'native-tokens.png'), fullPage: true});
  await writeFile(resolve(evidence, 'receipt.json'), JSON.stringify({head: execFileSync('git', ['rev-parse', 'HEAD'], {cwd: root, encoding: 'utf8'}).trim(), snapshots, calls, faults}, null, 2));
  console.log('PASS: actual browser/HTTP/CLI native root and successor show identical cumulative reported tokens; no execution POST.');
} finally {
  clearTimeout(timer);
  if (browser) await browser.close();
  if (server.exitCode === null) {const done = new Promise(resolve => server.once('exit', resolve)); server.kill('SIGTERM'); await done;}
}
