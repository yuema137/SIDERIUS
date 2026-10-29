/** Run lane with a host ledger, real Chromium against a real console (B3-4c UI):
 * the review POST carries the declared resources and parallel nodes, the review
 * summary shows what was reviewed, and an edit made while /review is in flight
 * discards that stale review so Launch stays disabled until a new review.
 *
 * Why this fails without the generation bump (reusable-run.js, runScheduling.changed):
 * the review handler accepts a response only while `generation` still equals the
 * value it captured when the request was sent. The in-flight edit below happens
 * while `review` is still null, so the listener's only effect is that bump. Remove
 * it and the held response for "1 CPU slot" is accepted after the edit to 2: the
 * summary then shows the old reservation and Launch is enabled, failing both the
 * `#capture-scheduling-review` absence and the Launch-disabled assertions.
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
const evidence = process.env.CONSOLE_EVIDENCE_DIR || await mkdtemp(join(tmpdir(), 'siderius-host-scheduling-'));
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
  const metadata = JSON.parse((await completed(start('setup', root, '--origin', origin, '--endpoint', endpoint, '--captures-count', '1', '--host-ledger'))).trim().split('\n').at(-1));
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

  // The console shares a host ledger: the panel is offered, the "needs a ledger" note is not.
  await page.locator('#scheduling').waitFor({state: 'visible'});
  assert.equal(await page.locator('#scheduling-unavailable').isHidden(), true);
  await page.evaluate(() => { document.getElementById('scheduling').open = true; });
  await page.locator('#scheduling-declare').check(); await page.locator('#scheduling-gpu').selectOption('0');
  await page.locator('#scheduling-memory').fill('2'); await page.locator('#scheduling-cpus').fill('1');
  await page.locator('#scheduling-validation-on').check();
  await page.locator('#scheduling-validation-memory').fill('1'); await page.locator('#scheduling-validation-cpus').fill('1');

  // 1. Hold the first review in flight and edit the panel before it lands.
  let held = null, release, heldBody = null;
  const gate = new Promise(done => {release = done;});
  await page.route('**/reusable-captures/review', async route => {
    if (held === null) { held = route; heldBody = route.request().postDataJSON(); await gate; }
    await route.continue();
  });
  await page.locator('#capture-review').click();
  await until(() => heldBody !== null);
  assert.deepEqual(heldBody.resources, {gpu_count: 0, host_memory_gib: 2, cpu_slots: 1, time_budgeted: false});
  assert.deepEqual(heldBody.parallel, {capabilities: {validation: {gpu: false, host_memory_gib: 1, cpu_slots: 1}}});
  await page.locator('#scheduling-cpus').fill('2');   // the edit made while /review is in flight
  release();
  await delay(1500);                                   // let the stale response arrive and be handled
  assert.equal(await page.locator('#capture-scheduling-review').count(), 0, 'Stale review discarded');
  assert.equal(await page.locator('#capture-launch').isDisabled(), true, 'Launch stays disabled after an in-flight edit');

  // 2. A fresh review binds the edited values; the summary shows exactly those.
  let reviewedBody = null;
  await page.unroute('**/reusable-captures/review');
  await page.route('**/reusable-captures/review', async route => { reviewedBody = route.request().postDataJSON(); await route.continue(); });
  await page.locator('#capture-review').click();
  await page.locator('#capture-status').filter({hasText: 'Reviewed.'}).waitFor();
  assert.equal(reviewedBody.resources.cpu_slots, 2);
  assert.match(await page.locator('#capture-scheduling-review').textContent(),
    /Reserves no GPU, 2 GiB host memory and 2 CPU slots\. Runs these node kinds in parallel: validation\./);
  assert.equal(await page.locator('#capture-launch').isEnabled(), true);

  // 3. Any edit after the review discards it and disables Launch.
  await page.locator('#scheduling-memory').fill('3');
  await page.locator('#capture-status').filter({hasText: 'review again'}).waitFor();
  assert.equal(await page.locator('#capture-scheduling-review').count(), 0);
  assert.equal(await page.locator('#capture-launch').isDisabled(), true);
  assert.deepEqual(faults, []);
  console.log('PASS: ledger run lane review carries resources and parallel nodes, in-flight and later edits discard the review');
} finally {
  if (browser) await browser.close();
  await stop(server); await stop(provider);
  await writeFile(join(evidence, 'processes.json'), JSON.stringify(children.map(child => ({mode: child.mode, exitCode: child.exitCode, signal: child.signalCode, errors: child.errors})), null, 2));
}
