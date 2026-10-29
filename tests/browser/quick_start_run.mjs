/** L-1 witness (red-team report 7): the default research-loop template (gallery import on a
 * runnable legacy project; Quick start itself is quick_start.mjs), then Run. With the launch policy unset in the Train & tune inspector, the
 * field is marked required and the Run page's Check inputs refuses with the launch
 * policy owner's message before anything is prepared; with the template's declared
 * pair (Block on failure / Scientific, trial/formal mode) Check inputs passes and the launched run gets past
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
import {chooseFirstConfiguredTask} from './console_task_choice.mjs';

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
  chooseFirstConfiguredTask(browser);
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}}), page = await context.newPage();
  page.on('pageerror', error => faults.push(error.message));
  const status = () => page.locator('#editor-status').textContent();
  const view = async name => { await page.locator(`nav a[href="#${name}"]`).click(); await page.locator(`#view-${name}`).waitFor(); };
  await page.goto(origin + '/#home');
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();

  // The research-loop template on the runnable legacy project. Quick start itself creates
  // an experiment setup (quick_start.mjs); this fixture has no workspace to create one in,
  // so the same template is imported through the gallery, Quick start's former path.
  await view('workflow');
  await page.locator('#editor-project option[value="capture"]').waitFor({state: 'attached'});
  if ((await page.locator('#editor-project').inputValue()) !== 'capture') await page.locator('#editor-project').selectOption('capture');
  await until(async () => (await status()).includes('Opened capture'));
  await page.locator('#editor-template-open').click();
  await page.locator('.template-card[data-template="single-loop-with-advice"]').click();
  await page.locator('#editor-template-import').click();
  await page.locator('#circuit-node-train').waitFor();
  // L-6: the advice field has focus after the gallery import, as after Quick start.
  await until(() => page.evaluate(() => document.activeElement?.classList.contains('advice-input')));
  // The focused field is Propose model's, and its advice input is connected (no warning):
  // what the user types reaches the proposal agent.
  assert.equal(await page.locator('#editor-inspector .advice-warning').count(), 0, 'Propose model advice input is connected');
  const ADVICE = 'Prefer a small interpretable baseline (quick-start advice marker).';
  await page.keyboard.type(ADVICE);

  // L-1b: the Train & tune inspector shows the template's declared pair as plain choices.
  await page.locator('#circuit-node-train').click();
  const policy = page.locator('#editor-training-policy');
  await policy.waitFor();
  assert.equal(await policy.locator('[data-training-choice="healthgate_mode"]').inputValue(), 'blocking');
  assert.equal(await policy.locator('[data-training-choice="result_authority"]').inputValue(), 'scientific');
  assert.equal(await policy.locator('[data-training-choice="healthgate_mode"] option:checked').textContent(), 'Block on failure');
  // Unset reads as a problem on the field.
  await policy.locator('[data-training-choice="healthgate_mode"]').selectOption('');
  assert.match(await policy.locator('[data-training-choice-field="healthgate_mode"] .field-error').textContent(), /Required: choose one/);
  const save = async () => {
    await page.locator('#editor-review').click();
    await page.locator('#editor-save-confirm').waitFor();
    await until(async () => !(await page.locator('#editor-save').isDisabled()));
    await page.locator('#editor-save').click();
    await until(async () => (await status()).includes('Saved as "'));
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

  // Choose Block on failure again (the template's pair), save, and run.
  await view('workflow');
  await page.locator('#circuit-node-train').click();
  await page.locator('#editor-training-policy [data-training-choice="healthgate_mode"]').selectOption('blocking');
  assert.equal(await page.locator('[data-training-choice-field="healthgate_mode"] .field-error').textContent(), '');
  await save();
  // B8-2: record every preparation status line; none may claim a finished failure.
  await page.evaluate(() => {
    window.prepTexts = [];
    new MutationObserver(() => window.prepTexts.push(document.getElementById('new-run-operation-status').textContent))
      .observe(document.getElementById('new-run-operation-status'), {childList: true, characterData: true, subtree: true});
  });
  const prepareAndReview = async () => {
    assert.match(await checkInputs(), /Inputs checked/);
    await page.locator('#new-run-prepare').click();
    await page.locator('#new-run-operation-status').filter({hasText: 'Prepared.'}).waitFor({timeout: 120000});
    // Auto-opened in step 2 (this page prepared it).
    await page.locator('#capture-status').filter({hasText: 'Prepared run opened'}).waitFor();
    await page.locator('#capture-review').click();
    await page.locator('#capture-status').filter({hasText: 'Reviewed.'}).waitFor();
  };
  await prepareAndReview();
  // The typed advice is in the prepared request's Propose model advice input.
  const {readFile: read} = await import('node:fs/promises');
  const runId = await page.evaluate(() => JSON.parse(localStorage.getItem(window.reusableIntents.key('preparation'))).payload.selection.run_id);
  const inputs = join(root, 'runs', runId, 'inputs');
  const adviceFiles = (await readdir(inputs, {recursive: true})).filter(name => /advice/.test(name));
  assert.ok(adviceFiles.length, 'An advice input file is prepared: ' + (await readdir(inputs, {recursive: true})).join(', '));
  assert.ok((await Promise.all(adviceFiles.map(name => read(join(inputs, name), 'utf8')))).some(text => text.includes(ADVICE)),
    'The typed advice reaches the prepared advice input');
  const prepTexts = await page.evaluate(() => window.prepTexts);
  assert.ok(prepTexts.every(text => !/finished without a prepared run|start over/i.test(text)), 'No false failure while preparing: ' + JSON.stringify(prepTexts));
  // B8-3: the run names the captured version; a newer save is named as not in it.
  assert.match(await page.locator('#capture-source').textContent(), /^This run uses version "/);
  await view('workflow');
  await page.locator('#editor-loop-final-iteration').fill('2');
  await save();
  await view('run');
  assert.match(await page.locator('#run-source-state').textContent(), /The prepared run in step 2 uses version ".+"\. Your saved version ".+" is newer and not in it/);
  assert.match(await page.locator('#capture-source').textContent(), /You have since saved version ".+"; it is not in this run/);
  assert.match(await page.locator('#run-next').textContent(), /older version/);
  assert.equal(await page.locator('#capture-prepare-current').isVisible(), true);
  await page.screenshot({path: join(evidence, 'run-older-capture.png'), fullPage: true});
  // B8-4 (shared by Start over): preparing the current version clears step 2.
  await page.locator('#capture-prepare-current').click();
  assert.equal(await page.locator('#capture-launch').isDisabled(), true, 'No older capture left ready to launch');
  assert.equal(await page.locator('#capture-summary').textContent(), '');
  assert.equal(await page.locator('#capture-source').textContent(), '');
  assert.equal(await page.locator('#new-run-intent').isHidden(), true, 'Step 1 started over');
  assert.match(await page.locator('#run-source-state').textContent(), /is ready to run/);
  await prepareAndReview();
  assert.doesNotMatch(await page.locator('#capture-source').textContent(), /not in this run/);
  // B8-4, the red team's exact path: step 1 "Start over" with a reviewed capture in step 2.
  await page.locator('#new-run-dismiss').click();
  assert.equal(await page.locator('#capture-launch').isDisabled(), true, 'Start over leaves nothing to launch');
  assert.doesNotMatch(await page.locator('#run-next').textContent(), /launch the run/);
  await prepareAndReview();
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
