/** L-1 witness (red-team report 7): Home → Quick start → the default research-loop
 * template, then Run. With the launch policy unset in the Train & tune inspector, the
 * field is marked required and the Run page's Check inputs refuses with the launch
 * policy owner's message before anything is prepared; with the template's declared
 * pair (Record only / Diagnostic) Check inputs passes and the launched run gets past
 * training admission. Offline fixture provider and training runner; no paid API. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, mkdir, unlink, rename} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';

const checkout = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR || await mkdtemp(join(tmpdir(), 'siderius-reusable-browser-'));
await mkdir(evidence, {recursive: true});
const root = await mkdtemp(join(evidence, 'project-')), children = [], faults = [];
function start(...args) {
  const child = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.reusable_candidate_fixture', ...args], {cwd: checkout, stdio: ['ignore', 'pipe', 'pipe']});
  child.output = ''; child.errors = ''; child.mode = args[0];
  child.stdout.on('data', chunk => {child.output += chunk;}); child.stderr.on('data', chunk => {child.errors += chunk;});
  children.push(child); return child;
}
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, timeout = 20000) { const end = Date.now() + timeout; while (!(await predicate())) {if (Date.now() > end) throw new Error('Condition timed out'); await delay(50);} }
async function completed(child, timeout = 100000) { await until(() => child.exitCode !== null, timeout); assert.equal(child.exitCode, 0, child.errors); return child.output; }
async function stop(child) { if (!child || child.exitCode !== null || child.signalCode !== null) return; child.kill('SIGTERM'); await until(() => child.exitCode !== null || child.signalCode !== null); }
const probe = createServer(); await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${probe.address().port}`; await new Promise(resolve => probe.close(resolve));
let browser, server, provider, metadata;
try {
  provider = start('provider', root);
  const lines = createInterface({input: provider.stdout});
  const endpoint = await new Promise(resolve => lines.once('line', line => resolve(JSON.parse(line).endpoint))); lines.close();
  metadata = JSON.parse((await completed(start('setup', root, '--origin', origin, '--endpoint', endpoint, '--captures-count', '0', '--training'))).trim().split('\n').at(-1));
  server = start('serve', root);
  async function ready() { await until(async () => { try {return (await fetch(origin + '/')).ok;} catch {return false;} }); }
  await ready();
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}}), page = await context.newPage();
  page.on('pageerror', error => faults.push(error.message));
  const status = () => page.locator('#editor-status').textContent();
  const view = async name => { await page.locator(`nav a[href="#${name}"]`).click(); await page.locator(`#view-${name}`).waitFor(); };
  await page.goto(origin + '/#home');
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();

  // Quick start: a project (L-7 wording), runnable ones first, then the template draft.
  await page.locator('#home-quick-start').click();
  const dialog = page.locator('#quick-start-dialog');
  await until(() => dialog.evaluate(el => el.open));
  assert.equal(await dialog.locator('label[for="quick-start-project"]').textContent(), 'Project (its task and data)');
  await page.locator('#quick-start-project option[value="capture"]').waitFor({state: 'attached'});
  assert.equal(await page.locator('#quick-start-project option').first().getAttribute('value'), 'capture', 'Runnable projects first');
  await page.locator('#quick-start-project').selectOption('disabled');
  assert.match(await page.locator('#quick-start-warning').textContent(), /edit this project but not run it/);
  await page.locator('#quick-start-project').selectOption('capture');
  await page.locator('#quick-start-open').click();
  await until(async () => !(await dialog.evaluate(el => el.open)), 30000);
  await page.locator('#circuit-node-train').waitFor();
  // L-6: the advice field has focus after Quick start, as after a gallery import.
  await until(() => page.evaluate(() => document.activeElement?.classList.contains('advice-input')));

  // L-1b: the Train & tune inspector shows the template's declared pair as plain choices.
  await page.locator('#circuit-node-train').click();
  const policy = page.locator('#editor-training-policy');
  await policy.waitFor();
  assert.equal(await policy.locator('[data-training-choice="healthgate_mode"]').inputValue(), 'observe_only');
  assert.equal(await policy.locator('[data-training-choice="result_authority"]').inputValue(), 'diagnostic');
  assert.equal(await policy.locator('[data-training-choice="healthgate_mode"] option:checked').textContent(), 'Record only');
  // Unset reads as a problem on the field.
  await policy.locator('[data-training-choice="healthgate_mode"]').selectOption('');
  assert.match(await policy.locator('[data-training-choice-field="healthgate_mode"] .field-error').textContent(), /Required: choose one/);
  const save = async () => {
    await page.locator('#editor-review').click();
    await page.locator('#editor-save-confirm').waitFor();
    await until(async () => !(await page.locator('#editor-save').isDisabled()));
    await page.locator('#editor-save').click();
    await until(async () => (await status()).includes('Saved reviewed bytes'));
  };
  await save();
  const checkInputs = async () => {
    await view('run');
    if (!(await page.locator('#new-run-task').inputValue())) await page.locator('#new-run-task').selectOption('synthetic');
    await page.locator('#new-run-review').click();
    await until(async () => /Inputs (checked|not accepted)/.test(await page.locator('#new-run-status').textContent()));
    return page.locator('#new-run-status').textContent();
  };
  // L-1a: Check inputs refuses with the launch-policy owner's message; nothing is prepared.
  const refused = await checkInputs();
  assert.match(refused, /Inputs not accepted: a formal launch must declare --healthgate_mode/);
  assert.equal(await page.locator('#new-run-prepare').isDisabled(), true);
  await page.screenshot({path: join(evidence, 'run-policy-refused.png'), fullPage: true});
  const {readdir} = await import('node:fs/promises');
  const operations = async () => { try { return (await readdir(join(metadata.state, 'operations'))).length; } catch { return 0; } };
  assert.equal(await operations(), 0, 'A refused review prepares nothing');

  // Choose Record only again (the template's pair), save, and run.
  await view('workflow');
  await page.locator('#circuit-node-train').click();
  await page.locator('#editor-training-policy [data-training-choice="healthgate_mode"]').selectOption('observe_only');
  assert.equal(await page.locator('[data-training-choice-field="healthgate_mode"] .field-error').textContent(), '');
  await save();
  assert.match(await checkInputs(), /Inputs checked/);
  await page.locator('#new-run-prepare').click();
  await page.locator('#new-run-operation-status').filter({hasText: 'Prepared.'}).waitFor({timeout: 120000});
  // Auto-opened in step 2 (this page prepared it).
  await page.locator('#capture-status').filter({hasText: 'Prepared run opened'}).waitFor();
  await page.locator('#capture-review').click();
  await page.locator('#capture-status').filter({hasText: 'Reviewed.'}).waitFor();
  await until(() => page.locator('#capture-launch').isEnabled());
  await page.locator('#capture-launch').click();
  await page.locator('#capture-operation-status').filter({hasText: /Finished|Failed/}).waitFor({timeout: 240000});
  const outcome = await page.locator('#capture-operation-status').textContent();
  await page.screenshot({path: join(evidence, 'run-after-policy.png'), fullPage: true});
  // The run gets past training admission: no launch-policy failure anywhere.
  assert.doesNotMatch(outcome, /FormalLaunchPolicyError|must declare/);
  // A clean finish additionally needs a host where the formal runtime probe can measure
  // (a CUDA device); elsewhere the run must fail later, for that named reason (L-2), and
  // never for the launch policy. CONSOLE_REQUIRE_FINISH=1 demands the clean finish.
  if (process.env.CONSOLE_REQUIRE_FINISH === '1') assert.match(outcome, /^Finished/, 'The template run finishes: ' + outcome);
  else assert.match(outcome, /^Finished|^Failed: .*Cause \(from the log\): (?!.*FormalLaunchPolicyError)/, outcome);
  assert.deepEqual(faults, []);
  await writeFile(join(evidence, 'result.json'), JSON.stringify({result: 'PASS', root, outcome}, null, 2));
  console.log(JSON.stringify({result: 'PASS', evidence, outcome}));
} finally {
  if (browser) await browser.close();
  await stop(server); await stop(provider);
}
