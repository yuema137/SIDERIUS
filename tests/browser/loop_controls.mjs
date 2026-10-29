/** Authored-loop Stop/Pause/Resume controls and honest loop state over a stubbed API. No provider/GPU/native effects. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {tmpdir} from 'node:os';
import {showAllConsoleSections} from './console_view_flags.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = ''; server.stderr.on('data', chunk => {errors += chunk;});
const lines = createInterface({input: server.stdout});
const running = '33333333-3333-4333-8333-333333333333';
const fixed = '44444444-4444-4444-8444-444444444444';
const finished = '55555555-5555-4555-8555-555555555555';
const pausing = '66666666-6666-4666-8666-666666666666';
const digest = 'c'.repeat(64);
const thresholdStop = '77777777-7777-4777-8777-777777777777';
const patienceStop = '88888888-8888-4888-8888-888888888888';
const resumedStop = '99999999-9999-4999-8999-999999999999';
const judgeStop = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
let browser;
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Server startup timeout: ${errors}`)), 15000);
    lines.on('line', line => {
      try {
        const value = JSON.parse(line);
        if (!value.origin || !value.token) return;
        clearTimeout(timer); lines.close(); accept(value);
      } catch { /* Native plugin registration may write one informational line first. */ }
    });
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Server ${code}: ${errors}`));});
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage(), posts = [], faults = [];
  page.on('pageerror', error => faults.push(error.message));
  let stopRecorded = false, runningTerminal = false, pausingTerminal = false, resumedTerminal = false, resumed = null;
  const pausePosts = [], resumePosts = [];
  const status = (operation, fields) => ({operation_id: operation, kind: 'candidate', request_digest: 'a'.repeat(64), observed_at: 'fixture',
    state: 'active', process: {status: 'alive', reason: 'observed'}, finishing: false, receipt_available: false, native_status: null,
    native_id: null, validation_passed: null, reason: 'fixture', ...fields});
  const terminal = (operation, nativeStatus, attempted) => status(operation, {state: 'completed', process: {status: 'exited', reason: 'observed'},
    receipt_available: true, native_status: nativeStatus, native_id: 'fixture-run', loop: {final_iteration: 3, attempted_iterations: attempted}});
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    assert.equal(request.headers().authorization, 'Bearer ' + metadata.token);
    const reply = json => route.fulfill({status: 200, json});
    if (request.method() === 'POST') {
      assert.equal(request.headers()['content-type'], 'application/json');
      await new Promise(done => setTimeout(done, 400)); // Keep the request pending across a second click.
      if (url.pathname === '/api/loop-resumes') {
        const body = JSON.parse(request.postData());
        resumePosts.push(body); resumed = body.request_id;
        return route.fulfill({status: 202, json: {operation_id: resumed, kind: 'candidate_loop_resume', request_digest: 'b'.repeat(64), observed_at: 'fixture', observation: 'starting'}});
      }
      assert.equal(request.postData(), '{}');
      if (url.pathname === `/api/operations/${pausing}/loop-pause`) { pausePosts.push(url.pathname); return reply({operation_id: pausing, outcome: 'requested'}); }
      assert.equal(url.pathname, `/api/operations/${running}/loop-stop`, 'Stop is posted only for the running loop');
      posts.push(url.pathname);
      return reply({operation_id: running, outcome: 'requested'});
    }
    assert.equal(request.method(), 'GET');
    if (url.pathname === '/api/choices') return reply({operations_store_id: '0123456789abcdef0123456789abcdef', tasks: []});
    if (url.pathname === '/api/native-chain/choices' || url.pathname === '/api/recorded-examples') return reply([]);
    // Monitor lists this console's operations once per connection, also on UUID routes.
    if (url.pathname === '/api/operations') return reply({operations: [], unreadable: 0, examined: 0, incomplete: false});
    if (url.pathname.endsWith('/tokens')) return reply({reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []});
    if (url.pathname.endsWith('/log')) return reply({text: '', next_offset: 0, observed_size: 0, truncated: false, missing: false});
    if (url.pathname.endsWith('/graph-results')) {
      const id = url.pathname.split('/')[3], count = id === pausing ? 1 : id === resumed ? 3 : 0;
      return reply({operation_id: id, available: count > 0, bodies: Array.from({length: count}, (_, index) => ({iteration: index + 1, tuning_state: 'failed', result: null}))});
    }
    if (url.pathname === `/api/operations/${pausing}/loop-resume-review`) return reply({predecessor_operation_id: pausing, expected_receipt_digest: digest, completed_iterations: 1, final_iteration: 3,
      credential_readiness: {required_names: ['OPENAI_API_KEY'], omitted_names: [], unresolved_routes: [], present_names: ['OPENAI_API_KEY'], missing_names: [], file_status: 'readable', ready: true, instructions: []}});
    if (url.pathname === `/api/operations/${pausing}`) return reply(!pausingTerminal ? status(pausing, {loop: {final_iteration: 3, attempted_iterations: null}})
      : {...terminal(pausing, 'paused', 1), ...(resumed ? {successor_operation_id: resumed} : {})});
    if (resumed && url.pathname === `/api/operations/${resumed}`) return reply({...(resumedTerminal ? terminal(resumed, 'completed', 3) : status(resumed, {loop: {final_iteration: 3, attempted_iterations: null}})), kind: 'candidate_loop_resume'});
    if (url.pathname === `/api/operations/${running}`) return reply(runningTerminal ? terminal(running, 'stopped', 1) : status(running, {loop: {final_iteration: 3, attempted_iterations: null, stop_requested: stopRecorded, pause_requested: false}}));
    if (url.pathname === `/api/operations/${fixed}`) return reply(status(fixed, {}));
    if (url.pathname === `/api/operations/${finished}`) return reply(terminal(finished, 'completed', 3));
    if (url.pathname === `/api/operations/${thresholdStop}`) {
      const value = terminal(thresholdStop, 'completed', 3);
      value.loop = {final_iteration: 5, attempted_iterations: 3, stop_reason: {kind: 'metric_threshold', condition_index: 0, iteration: 3,
        metric_id: 'accuracy', direction: 'higher', threshold: 0.85, incumbent: 0.9, incumbent_iteration: 3}};
      return reply(value);
    }
    if (url.pathname === `/api/operations/${patienceStop}`) {
      const value = terminal(patienceStop, 'completed', 4);
      value.loop = {final_iteration: 6, attempted_iterations: 4, stop_reason: {kind: 'no_improvement', condition_index: 1, iteration: 4,
        k: 2, non_improving_bodies: 2, last_improvement_iteration: 2, incumbent: -1.25}};
      return reply(value);
    }
    if (url.pathname === `/api/operations/${resumedStop}`) {
      // Resumed at body 3 after a pause at body 2: every iteration in the receipt counts the whole run.
      const value = {...terminal(resumedStop, 'completed', 3), kind: 'candidate_loop_resume'};
      value.loop = {final_iteration: 5, attempted_iterations: 3, stop_reason: {kind: 'no_improvement', condition_index: 0, iteration: 3,
        k: 2, non_improving_bodies: 2, last_improvement_iteration: 1, incumbent: 0.75}};
      return reply(value);
    }
    if (url.pathname === `/api/operations/${judgeStop}`) {
      // B2-5: the receipt's judge verdicts, rationale copied from their evidence by the server.
      const value = terminal(judgeStop, 'completed', 3), evidence = {evidence_path: 'judge/2.json', evidence_sha256: 'e'.repeat(64), request_sha256: 'f'.repeat(64)};
      value.loop = {final_iteration: 5, attempted_iterations: 3, stop_reason: {kind: 'judge', condition_index: 0, iteration: 3, ...evidence},
        judge_verdicts: [{iteration: 1, decision: null, rationale: null, confidence: null},
          {iteration: 2, decision: 'continue', rationale: 'Still improving.', confidence: 'medium'},
          {iteration: 3, decision: 'stop', rationale: 'Two bodies add no new insight.', confidence: 'high'}]};
      return reply(value);
    }
    throw new Error('unexpected path ' + url.pathname);
  });
  await page.goto(`${metadata.origin}/#monitor/${running}`);
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  const state = page.locator('#loop-state'), stop = page.locator('#loop-stop');
  await state.filter({hasText: 'Research loop: up to 3 bodies.'}).waitFor();
  await stop.waitFor({state: 'visible'});
  assert.ok(!(await state.textContent()).includes('Stop requested'));

  await stop.dblclick();
  await state.filter({hasText: 'Stop requested'}).waitFor();
  assert.equal(posts.length, 1, 'a double click issues exactly one Stop request');
  assert.ok(await stop.isHidden(), 'no second Stop control after acknowledgement');
  await page.waitForTimeout(2500); // At least one further poll still reads an active operation.
  const requested = await state.textContent();
  assert.match(requested, /Not yet stopped\./);
  assert.ok(!/stopped at/i.test(requested), 'acknowledgement alone never reads as stopped');
  await page.screenshot({path: resolve(tmpdir(), 'siderius-loop-stop-requested.png'), fullPage: true});
  // M-1: the recorded Stop comes from server status, so a reload still shows it and
  // offers neither Stop nor Pause again (no second control POST).
  stopRecorded = true;
  await page.reload();
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await state.filter({hasText: 'Stop requested'}).waitFor();
  assert.ok(await stop.isHidden(), 'reload keeps Stop hidden once recorded');
  assert.ok(await page.locator('#loop-pause-group').isHidden(), 'Pause is hidden once a Stop is recorded');
  assert.equal(posts.length + pausePosts.length, 1, 'no further control request after reload');

  runningTerminal = true;
  await state.filter({hasText: 'Research loop stopped at a completed body boundary after 1 of 3 bodies.'}).waitFor();
  assert.ok(await stop.isHidden());
  assert.equal(posts.length, 1);

  await page.evaluate(id => { location.hash = 'monitor/' + id; }, fixed);
  await page.locator('#monitor-status').filter({hasText: 'Run in progress.'}).waitFor();
  await page.locator(`#operation-observed[title*="${fixed}"]`).waitFor({state: 'attached'});
  assert.ok(await page.locator('#loop-control').isHidden(), 'a candidate without a declared loop has no loop control');

  await page.evaluate(id => { location.hash = 'monitor/' + id; }, finished);
  await state.filter({hasText: 'Research loop finished after 3 of 3 bodies.'}).waitFor();
  assert.ok(await stop.isHidden(), 'a finished loop has no Stop');
  assert.ok(!(await state.textContent()).includes('Stop'), 'Stop state does not leak across operations');
  assert.equal(posts.length, 1);
  await page.screenshot({path: resolve(tmpdir(), 'siderius-loop-finished.png'), fullPage: true});
  assert.ok(await page.locator('#loop-resume-group').isHidden(), 'a finished loop has no Resume');

  // Pause -> "Pause requested" -> paused receipt -> reviewed Resume -> resumed segment.
  const pause = page.locator('#loop-pause'), resumeGroup = page.locator('#loop-resume-group');
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, pausing);
  await state.filter({hasText: 'Research loop: up to 3 bodies.'}).waitFor();
  await pause.waitFor({state: 'visible'});
  await pause.dblclick();
  await state.filter({hasText: 'Pause requested'}).waitFor();
  assert.equal(pausePosts.length, 1, 'a double click issues exactly one Pause request');
  assert.ok(await pause.isHidden(), 'no second Pause control after acknowledgement');
  await page.waitForTimeout(2500);
  const pauseRequested = await state.textContent();
  assert.match(pauseRequested, /Not yet paused\./);
  assert.ok(!/paused at/i.test(pauseRequested), 'acknowledgement alone never reads as paused');
  assert.ok(await resumeGroup.isHidden(), 'no Resume before a paused receipt');

  pausingTerminal = true;
  await state.filter({hasText: 'Research loop paused at a completed body boundary after 1 of 3 bodies.'}).waitFor();
  assert.ok(!(await state.textContent()).includes('ended'), 'paused is resumable, never "ended"');
  assert.ok(await pause.isHidden() && await stop.isHidden());
  await page.locator('#graph-results-observation').filter({hasText: 'Workflow training results'}).waitFor();
  await resumeGroup.waitFor({state: 'visible'});
  assert.ok(await page.locator('#loop-resume').isHidden(), 'Resume requires a review first');
  await page.locator('#loop-resume-review').click();
  await page.locator('#loop-resume-summary').filter({hasText: 'body 2 of 3'}).waitFor();
  await page.screenshot({path: resolve(tmpdir(), 'siderius-loop-paused-review.png'), fullPage: true});
  await page.locator('#loop-resume').dblclick();
  await page.waitForFunction(id => location.hash.startsWith('#monitor/') && location.hash !== '#monitor/' + id, pausing);
  assert.equal(resumePosts.length, 1, 'a double click issues exactly one Resume');
  assert.deepEqual(Object.keys(resumePosts[0]).sort(), ['expected_receipt_digest', 'predecessor_operation_id', 'request_id']);
  assert.equal(resumePosts[0].predecessor_operation_id, pausing);
  assert.equal(resumePosts[0].expected_receipt_digest, digest);
  const retainedId = await page.evaluate(id => JSON.parse(localStorage.getItem(`siderius.loop-resume.v2/${window.consoleSession.operationsStoreId}/${id}`)).request_id, pausing);
  assert.equal(retainedId, resumePosts[0].request_id, 'the request UUID is retained before submission');
  assert.equal(await page.evaluate(() => location.hash), '#monitor/' + resumed);

  await state.filter({hasText: 'Resumed segment. Research loop: up to 3 bodies.'}).waitFor();
  await stop.waitFor({state: 'visible'});
  assert.ok(await pause.isVisible(), 'a running resumed segment can be paused again');
  resumedTerminal = true;
  await state.filter({hasText: 'Research loop finished after 3 of 3 bodies.'}).waitFor();
  await page.locator('#graph-results-observation h3').filter({hasText: 'Iteration 3'}).waitFor();
  assert.equal(await page.locator('#graph-results-observation .graph-result-body').count(), 3);
  assert.ok(await stop.isHidden() && await resumeGroup.isHidden());
  await page.screenshot({path: resolve(tmpdir(), 'siderius-loop-resumed.png'), fullPage: true});

  await page.evaluate(id => { location.hash = 'monitor/' + id; }, pausing);
  await page.locator('#loop-continued').filter({hasText: 'Continued by ' + resumed}).waitFor();
  assert.equal(await page.locator('#loop-successor').getAttribute('href'), '#monitor/' + resumed);
  assert.ok(await resumeGroup.isHidden(), 'a continued segment offers no second Resume');
  assert.equal(await page.evaluate(id => localStorage.getItem(`siderius.loop-resume.v2/${window.consoleSession.operationsStoreId}/${id}`), pausing), null, 'retained intent released once the successor is observed');

  // A declared stop condition completed the loop early: the receipt's reason reads in plain words.
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, thresholdStop);
  await state.filter({hasText: 'Research loop stopped early after body 3 of up to 5: accuracy reached 0.9 (threshold 0.85, higher is better; best at body 3).'}).waitFor();
  assert.ok(await stop.isHidden());
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, patienceStop);
  await state.filter({hasText: 'Research loop stopped early after body 4 of up to 6: no improvement for 2 bodies (condition: 2 bodies; best -1.25 at body 2).'}).waitFor();
  assert.ok(!(await state.textContent()).includes('finished after'), 'an early stop never reads as reaching the limit');
  assert.ok(!(await state.textContent()).includes('whole run'), 'a root segment needs no whole-run note');
  await page.screenshot({path: resolve(tmpdir(), 'siderius-loop-stop-reason.png'), fullPage: true});
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, resumedStop);
  await state.filter({hasText: 'Resumed segment. Research loop stopped early after body 3 of up to 5: no improvement for 2 bodies (condition: 2 bodies; best 0.75 at body 1). Body numbers count the whole run, including earlier segments.'}).waitFor();
  assert.equal(await page.locator('#loop-judge').isHidden(), true, 'no judge list without judge verdicts');
  // B2-5: a judge-stopped loop names the judge and lists each recorded verdict with its reason.
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, judgeStop);
  await state.filter({hasText: 'Research loop stopped early after body 3 of up to 5: the judge decided to stop.'}).waitFor();
  assert.deepEqual(await page.locator('#loop-judge li').allTextContents(), [
    'Judge after body 1: abstained (the judge call failed)',
    'Judge after body 2: continue · Still improving. (confidence medium)',
    'Judge after body 3: stop · Two bodies add no new insight. (confidence high)',
  ]);
  assert.equal(resumePosts.length, 1);
  assert.equal(posts.length, 1);
  assert.deepEqual(faults, []);
  console.log('PASS: Stop and Pause post once and read "requested" until the receipt; a paused loop is resumable after review, Resume posts once with the retained UUID, and the resumed segment shows Stop and its bodies; a receipt stop_reason reads in plain words, with whole-run body numbers on a resumed segment.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM'); lines.close();
}
