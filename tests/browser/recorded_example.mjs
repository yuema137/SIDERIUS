/** Chromium -> authenticated GET-only historical view; no native execution. */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

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
  page = await browser.newPage();
  page.on('response', response => {if (new URL(response.url()).pathname.startsWith('/api/')) responses.push({path: new URL(response.url()).pathname, status: response.status()});});
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => {if (new URL(request.url()).pathname.startsWith('/api/')) calls.push({method: request.method(), path: new URL(request.url()).pathname});});
  await page.goto(metadata.origin);
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  await page.goto(`${metadata.origin}/#slow-control`);
  await page.locator('#recorded-example-choice option[value="tess-recorded"]').waitFor({state: 'attached'});
  await page.locator('#recorded-example-open').click();
  await page.locator('#recorded-example-status').filter({hasText: 'Candidate validation evidence verified'}).waitFor();
  assert.equal(await page.locator('#recorded-example-content').isVisible(), true);
  const content = await page.locator('#recorded-example-content').textContent();
  assert.match(await page.locator('#recorded-example-heading').locator('..').textContent(), /Candidate validation evidence only/);
  assert.match(content, /accepted/);
  assert.match(content, /Validation passed/);
  assert.match(content, /PROPOSAL: tiny_pooled_conv_regressor/);
  assert.match(content, /IMPLEMENTATION: tiny_pooled_conv_regressor/);
  assert.match(content, /VALIDATION: tiny_pooled_conv_regressor · passed: true/);
  assert.match(content, /Editable source snapshot.*Unavailable in the captured request/);
  assert.match(content, /Observed provider reports; missing or unrecorded usage may exist/);
  assert.match(await page.locator('#recorded-token-rows').textContent(), /26942/);
  assert.match(await page.locator('#recorded-token-rows').textContent(), /7346/);
  assert.equal(await page.locator('#recorded-token-rows tr').count(), 1);
  await page.locator('#recorded-token-table').locator('xpath=..').locator('summary').click();
  assert.deepEqual(faults, []);
  assert.ok(calls.length >= 3);
  assert.ok(calls.every(call => call.method === 'GET'), 'recorded example uses GET only');
  assert.ok(calls.every(call => ['/api/choices', '/api/native-chain/choices', '/api/recorded-examples', `/api/recorded-examples/${metadata.example_id}`].includes(call.path)), 'no operation, preparation, launch, review, token, or log route is called');
  assert.ok(responses.every(response => response.status === 200));
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
    assert.deepEqual(after, metadata.before, 'viewing must leave all candidate files byte-identical');
  }
}
