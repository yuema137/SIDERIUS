/** Run lane review states the GPU requirement (issue #1136), real Chromium against a
 * real console. A prepared run whose workflow trains shows "Compute: NVIDIA GPU
 * required"; when the task passes no /dev/nvidia<N> node into the sandbox it also
 * warns that training runs will be refused, and the warning disappears when one is passed.
 *
 * The review also repeats the server's device warnings (ReusableCaptureReview.device_warnings,
 * the wording `check` prints: a device path missing on this host, GPU nodes without /sys;
 * walkthrough N2); without that, Review enabled Launch with no hint of the refusal to come.
 * Why this fails without the change (reusable-run.js computeReview): the review
 * summary then has no #capture-compute-review line, and a task configured with
 * candidate_devices [] (the fixture default) gets no warning before Launch, which
 * is how the walkthrough operator met a LaunchGuardFailure after launching.
 * Required: EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, mkdir, writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';

const checkout = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR || await mkdtemp(join(tmpdir(), 'siderius-gpu-compute-review-'));
await mkdir(evidence, {recursive: true});
const root = await mkdtemp(join(evidence, 'project-')), children = [], faults = [];
function start(...args) {
  const child = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.reusable_candidate_fixture', ...args], {cwd: checkout, stdio: ['ignore', 'pipe', 'pipe']});
  child.output = ''; child.errors = ''; child.mode = args[0];
  child.stdout.on('data', chunk => {child.output += chunk;}); child.stderr.on('data', chunk => {child.errors += chunk;});
  children.push(child); return child;
}
const delay = ms => new Promise(done => setTimeout(done, ms));
async function until(predicate, timeout = 20000) { const end = Date.now() + timeout; while (!(await predicate())) {if (Date.now() > end) throw new Error('Condition timed out'); await delay(50);} }
async function completed(child, timeout = 100000) { await until(() => child.exitCode !== null, timeout); assert.equal(child.exitCode, 0, child.errors); return child.output; }
async function stop(child) { if (!child || child.exitCode !== null || child.signalCode !== null) return; child.kill('SIGTERM'); await until(() => child.exitCode !== null || child.signalCode !== null); }
const probe = createServer(); await new Promise(done => probe.listen(0, '127.0.0.1', done));
const origin = `http://127.0.0.1:${probe.address().port}`; await new Promise(done => probe.close(done));
let browser, server, provider;
try {
  provider = start('provider', root);
  const lines = createInterface({input: provider.stdout});
  const endpoint = await new Promise(done => lines.once('line', line => done(JSON.parse(line).endpoint))); lines.close();
  const metadata = JSON.parse((await completed(start('setup', root, '--origin', origin, '--endpoint', endpoint, '--captures-count', '1', '--training'))).trim().split('\n').at(-1));
  server = start('serve', root);
  await until(async () => { try {return (await fetch(origin + '/')).ok;} catch {return false;} });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage();
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(origin + '/#workflow');
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  await page.locator('#editor-status').filter({hasText: 'Opened '}).waitFor();
  await page.locator('#editor-project').selectOption('capture');
  await page.locator('nav a[href="#run"]').click();
  await page.locator('#capture-earlier').evaluate(el => {el.open = true;});
  await page.locator('#capture-task').selectOption('synthetic');
  const run = metadata.captures[0];
  await page.locator('#capture-run option[value="' + run.run_id + '"]').waitFor({state: 'attached'});
  await page.locator('#capture-run').selectOption(run.run_id); await page.locator('#capture-open').click();
  await page.locator('#capture-status').filter({hasText: 'Prepared run opened'}).waitFor();

  // 1. The real review: this workflow trains, and the fixture task passes no device nodes.
  let reviewed = null;
  await page.route('**/reusable-captures/review', async route => {
    const response = await route.fetch(); reviewed = await response.json(); await route.fulfill({response});
  });
  await page.locator('#capture-review').click();
  await page.locator('#capture-compute-review').waitFor();
  assert.ok(reviewed.nodes.some(([, capability]) => capability === 'tuning'), 'fixture workflow trains');
  assert.deepEqual(reviewed.devices, []);
  assert.equal(await page.locator('#capture-compute-review').textContent(), 'Compute: NVIDIA GPU required');
  assert.equal(await page.locator('#capture-compute-warning').textContent(),
    'This task does not pass a GPU into the run sandbox; runs that train a model will be refused.');
  await page.screenshot({path: join(evidence, 'compute-warning.png'), fullPage: true});

  // 2. Same review with a GPU node in the sandbox devices: the requirement stays, the warning goes.
  await page.unroute('**/reusable-captures/review');
  await page.route('**/reusable-captures/review', async route => {
    const response = await route.fetch(); const body = await response.json();
    await route.fulfill({response, json: {...body, devices: ['/dev/nvidiactl', '/dev/nvidia0']}});
  });
  await page.locator('#capture-review').click();
  await page.locator('#capture-scheduling-review').waitFor();
  await until(async () => (await page.locator('#capture-summary').textContent()).includes('Compute: NVIDIA GPU required'));
  assert.equal(await page.locator('#capture-compute-warning').count(), 0, 'no warning with /dev/nvidia0 passed');

  // 3. /dev/nvidiactl alone is not a GPU device node: the warning returns.
  await page.unroute('**/reusable-captures/review');
  await page.route('**/reusable-captures/review', async route => {
    const response = await route.fetch(); const body = await response.json();
    await route.fulfill({response, json: {...body, devices: ['/dev/nvidiactl']}});
  });
  await page.locator('#capture-review').click();
  await page.locator('#capture-compute-warning').waitFor();
  assert.equal(await page.locator('[id^="capture-device-warning-"]').count(), 0, 'no server warning for this review');

  // 4. N2: the server's device warnings (the wording check prints) are repeated in the review.
  const serverWarnings = ['Device /dev/nvidia1 does not exist on this host; the run sandbox cannot pass it.',
    'GPU devices are passed but /sys is not mounted read-only; CUDA may fail to start inside the run sandbox (see README).'];
  await page.unroute('**/reusable-captures/review');
  await page.route('**/reusable-captures/review', async route => {
    const response = await route.fetch(); const body = await response.json();
    await route.fulfill({response, json: {...body, devices: ['/dev/nvidia0', '/dev/nvidia1'], device_warnings: serverWarnings}});
  });
  await page.locator('#capture-review').click();
  await page.locator('#capture-device-warning-1').waitFor();
  assert.deepEqual(await page.locator('[id^="capture-device-warning-"]').allTextContents(), serverWarnings.map(text => 'Warning: ' + text));
  assert.deepEqual(await page.locator('[id^="capture-device-warning-"]').evaluateAll(lines => lines.map(line => line.className)), ['warning', 'warning']);
  await page.screenshot({path: join(evidence, 'device-warnings.png'), fullPage: true});
  assert.deepEqual(faults, []);
  console.log('PASS: run review states the NVIDIA GPU requirement and warns when the task passes no GPU device node');
} finally {
  if (browser) await browser.close();
  await stop(server); await stop(provider);
  await writeFile(join(evidence, 'processes.json'), JSON.stringify(children.map(child => ({mode: child.mode, exitCode: child.exitCode, signal: child.signalCode, errors: child.errors})), null, 2));
}
