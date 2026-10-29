/** Chromium -> authenticated GET-only historical view; no native execution. */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_EVIDENCE_DIR', 'HISTORICAL_WORKSPACE', 'HISTORICAL_RUN_ID']) assert.ok(process.env[key], `Set ${key}`);
const evidence = resolve(process.env.CONSOLE_EVIDENCE_DIR);
await mkdir(evidence, {recursive: true});
const fixtureDir = resolve(evidence, 'recorded-example-fixture');
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.recorded_example_fixture', process.env.HISTORICAL_WORKSPACE, process.env.HISTORICAL_RUN_ID, fixtureDir], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let browser, page, metadata, stderr = '';
const faults = [], calls = [], responses = [];
server.stderr.on('data', data => {stderr += data;});
const timer = setTimeout(() => {console.error('Recorded example witness timed out'); server.kill('SIGTERM'); process.exit(2);}, 60000);
try {
  const lines = createInterface({input: server.stdout});
  metadata = await new Promise((accept, reject) => {
    lines.once('line', line => accept(JSON.parse(line)));
    server.once('exit', code => reject(new Error(`Fixture exited ${code}: ${stderr}`)));
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  page = await browser.newPage();
  page.on('response', response => {if (new URL(response.url()).pathname.startsWith('/api/')) responses.push({path: new URL(response.url()).pathname, status: response.status()});});
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => {if (new URL(request.url()).pathname.startsWith('/api/')) calls.push({method: request.method(), path: new URL(request.url()).pathname});});
  await page.goto(metadata.origin);
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  await page.goto(`${metadata.origin}/#monitor`);
  await page.locator('#recorded-example-choice option[value="tess-recorded"]').waitFor({state: 'attached'});
  await page.locator('#recorded-example-open').click();
  await page.locator('#recorded-example-status').filter({hasText: 'Candidate validation evidence verified'}).waitFor();
  assert.equal(await page.locator('#recorded-example-content').isVisible(), true);
  const content = await page.locator('#recorded-example-content').textContent();
  assert.match(await page.locator('#recorded-example-heading').locator('..').textContent(), /Candidate validation evidence only/);
  assert.match(content, /accepted/);
  assert.match(content, /Validation passed/);
  assert.match(content, /Propose model: tiny_pooled_conv_regressor/);
  assert.match(content, /Implement: tiny_pooled_conv_regressor/);
  assert.match(content, /Validate: tiny_pooled_conv_regressor · passed: true/);
  assert.doesNotMatch(content, /(PROPOSAL|IMPLEMENTATION|VALIDATION):/, 'Stages use the editor display names, not upper-cased IDs');
  assert.match(content, /Editable source snapshot.*Unavailable in the captured request/);
  assert.match(content, /Observed provider reports; missing or unrecorded usage may exist/);
  assert.match(await page.locator('#recorded-token-rows').textContent(), /26942/);
  assert.match(await page.locator('#recorded-token-rows').textContent(), /7346/);
  assert.equal(await page.locator('#recorded-token-rows tr').count(), 1);
  await page.locator('#recorded-token-table').locator('xpath=..').locator('summary').click();

  // A delayed A response must not leave the reader disabled or its old view visible after B is selected.
  let delayNextA = false;
  await page.route('**/api/recorded-examples/tess-recorded', async route => {
    if (delayNextA) {
      delayNextA = false;
      await new Promise(resolve => setTimeout(resolve, 1200));
    }
    await route.continue();
  });
  delayNextA = true;
  await page.locator('#recorded-example-open').click();
  await page.locator('#recorded-example-status').filter({hasText: 'Verifying captured candidate records'}).waitFor();
  await page.locator('#recorded-example-choice').selectOption('tess-recorded-b');
  assert.equal(await page.locator('#recorded-example-content').isVisible(), false, 'changing selection clears stale evidence');
  assert.equal(await page.locator('#recorded-example-open').isEnabled(), true, 'changing selection restores the read control while A is pending');
  await page.locator('#recorded-example-open').click();
  await page.locator('#recorded-example-status').filter({hasText: 'Candidate validation evidence verified'}).waitFor();
  await page.waitForTimeout(1400);
  assert.equal(await page.locator('#recorded-example-content').isVisible(), true, 'late A response does not replace B');
  assert.match(await page.locator('#recorded-example-status').textContent(), /Candidate validation evidence verified/);

  await page.locator('#recorded-example-choice').selectOption('tess-invalid-declaration');
  assert.equal(await page.locator('#recorded-example-content').isVisible(), false);
  await page.locator('#recorded-example-open').click();
  await page.locator('#recorded-example-status').filter({hasText: 'failed verification'}).waitFor();
  assert.doesNotMatch(await page.locator('#recorded-example-status').textContent(), /Candidate validation evidence verified/);
  assert.deepEqual(faults, []);
  assert.ok(calls.length >= 3);
  assert.ok(calls.every(call => call.method === 'GET'), 'recorded example uses GET only');
  // '/api/operations' is Monitor's read-only list (bare route); no single-operation route is read.
  assert.ok(calls.every(call => ['/api/choices', '/api/native-chain/choices', '/api/operations', '/api/recorded-examples', `/api/recorded-examples/${metadata.example_id}`, '/api/recorded-examples/tess-recorded-b', '/api/recorded-examples/tess-invalid-declaration'].includes(call.path)), 'no operation, preparation, launch, review, token, or log route is called');
  assert.ok(responses.filter(response => response.path === '/api/recorded-examples/tess-invalid-declaration').every(response => response.status === 409));
  assert.ok(responses.filter(response => response.path !== '/api/recorded-examples/tess-invalid-declaration').every(response => response.status === 200));
  await page.screenshot({path: resolve(evidence, 'recorded-example.png'), fullPage: true});
  await writeFile(resolve(evidence, 'browser-receipt.json'), JSON.stringify({head: execFileSync('git', ['rev-parse', 'HEAD'], {cwd: root, encoding: 'utf8'}).trim(), workspace: metadata.workspace, before: metadata.before, calls, responses, faults, content}, null, 2));
} catch (error) {
  if (page) await page.screenshot({path: resolve(evidence, 'failure.png'), fullPage: true});
  await writeFile(resolve(evidence, 'failure.json'), JSON.stringify({error: error.message, calls, responses, faults, stderr}, null, 2));
  throw error;
} finally {
  clearTimeout(timer);
  if (browser) await browser.close();
  if (server.exitCode === null) {const done = new Promise(resolve => server.once('exit', resolve)); server.kill('SIGINT'); await done;}
  if (metadata) {
    const after = JSON.parse(await readFile(resolve(fixtureDir, 'after.json'), 'utf8'));
    assert.deepEqual(after.workspace, metadata.before, 'viewing must leave original candidate files byte-identical');
    assert.deepEqual(after.invalid_workspace, metadata.invalid_before, 'viewing must leave the corrupted integrity fixture byte-identical');
  }
}
