/** Loop Resume with segment host resources under a shared host ledger (#1385), over a stubbed API.
 *
 * A loop whose first run declared no `resources` could not be resumed from a console that
 * shares a host ledger: admission refused `resources_required` and the panel had no input.
 * Here the review refusal reveals the Resume panel's resources fieldset (run-scheduling.js
 * `readResources('loop-resume-resources')`); the next review POSTs the declared values, the
 * summary shows the echoed reservation, the fieldset is fixed while the review is in flight, an
 * edit after review discards it, and Resume carries exactly the reviewed `resources` with its
 * `review_digest`.
 * A retained request from before the reservation existed (no `resources`, never admitted) is
 * dropped after a typed `unknown_operation` probe instead of overriding the newer review, and a
 * Resume refused before any claim (`resource_refused`) is not retained.
 * A loop whose first run declared resources is reviewed with GET and sends none.
 * Fails if: the fieldset never appears (no `resources_required` handling), the review is a GET
 * without the values, an edited review still enables Resume, or the Resume body
 * lacks or alters the reviewed pair. No provider/GPU/native effects.
 * Required: EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {waitForMetadata} from './fixture_metadata.mjs';
import {showAllConsoleSections} from './console_view_flags.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = ''; server.stderr.on('data', chunk => {errors += chunk;});
const undeclared = '33333333-3333-4333-8333-333333333333';
const declared = '44444444-4444-4444-8444-444444444444';
const stale = '55555555-5555-4555-8555-555555555555'; // a retained, never-admitted request UUID
const store = '0123456789abcdef0123456789abcdef';
const digest = 'c'.repeat(64), bound = (cpus) => String(cpus).repeat(64).slice(0, 64);
const ready = {required_names: ['OPENAI_API_KEY'], omitted_names: [], unresolved_routes: [], present_names: ['OPENAI_API_KEY'], missing_names: [], file_status: 'readable', ready: true, instructions: []};
const delay = ms => new Promise(done => setTimeout(done, ms));
let browser;
try {
  const metadata = await waitForMetadata(server, {timeoutMs: 15000});
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage(), faults = [], reviews = [], resumes = [], probes = [];
  let refuseNextResume = false;
  page.on('pageerror', error => faults.push(error.message));
  let hold = null; // When set, the next resources review waits for this promise.
  const paused = operation => ({operation_id: operation, kind: 'candidate', request_digest: 'a'.repeat(64), observed_at: 'fixture',
    state: 'completed', process: {status: 'exited', reason: 'observed'}, finishing: false, receipt_available: true, native_status: 'paused',
    native_id: 'fixture-run', validation_passed: null, reason: 'fixture', outcome: {failed_phases: [], completed_iterations: 1},
    loop: {final_iteration: 3, attempted_iterations: 1, stop_requested: false, pause_requested: false}});
  const review = (operation, extra = {}) => ({predecessor_operation_id: operation, expected_receipt_digest: digest, completed_iterations: 1, final_iteration: 3, credential_readiness: ready, ...extra});
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    assert.equal(request.headers().authorization, 'Bearer ' + metadata.token);
    const reply = json => route.fulfill({status: 200, json});
    if (url.pathname.endsWith('/loop-resume-review')) {
      const operation = url.pathname.split('/')[3];
      const body = request.method() === 'POST' ? JSON.parse(request.postData()) : null;
      reviews.push({operation, method: request.method(), body});
      if (operation === declared) { assert.equal(request.method(), 'GET'); return reply(review(declared)); }
      if (!body?.resources) return route.fulfill({status: 409, json: {error: {code: 'resources_required', message: "this console shares a host ledger and the loop's first run declared no host resources: declare them for the resumed segment, then review again"}}});
      if (hold) { const gate = hold; hold = null; await gate; }
      return reply(review(undeclared, {resources: body.resources, review_digest: bound(body.resources.cpu_slots)}));
    }
    if (url.pathname === '/api/loop-resumes') {
      const body = JSON.parse(request.postData());
      resumes.push(body);
      if (refuseNextResume) { refuseNextResume = false; return route.fulfill({status: 409, json: {error: {code: 'resource_refused', message: "the run's host resources exceed the host budget even when it is idle; lower them, then review again"}}}); }
      return route.fulfill({status: 202, json: {operation_id: body.request_id, kind: 'candidate_loop_resume', request_digest: 'b'.repeat(64), observed_at: 'fixture', observation: 'starting'}});
    }
    assert.equal(request.method(), 'GET', 'unexpected POST ' + url.pathname);
    if (url.pathname === `/api/operations/${stale}`) { probes.push(stale); return route.fulfill({status: 404, json: {error: {code: 'unknown_operation', message: 'this operation store has no operation with this ID'}}}); }
    if (url.pathname === '/api/choices') return reply({operations_store_id: store, tasks: [], host_ledger: true});
    if (url.pathname.endsWith('/setups') && url.pathname.startsWith('/api/tasks/')) return reply({setups: []});
    if (url.pathname === '/api/tasks') return reply({tasks: [{task_id: 'synthetic', label: 'Synthetic task', revision: null}]});
    if (url.pathname === '/api/native-chain/choices' || url.pathname === '/api/recorded-examples') return reply([]);
    if (url.pathname === '/api/operations') return reply({operations: [], unreadable: 0, examined: 0, incomplete: false});
    if (url.pathname.endsWith('/tokens')) return reply({reason: 'usage_unavailable', quality: {partial: false}, observed_at: 'fixture', groups: []});
    if (url.pathname.endsWith('/log')) return reply({text: '', next_offset: 0, observed_size: 0, truncated: false, missing: false});
    if (url.pathname.endsWith('/graph-results')) return reply({operation_id: url.pathname.split('/')[3], available: false, bodies: []});
    for (const operation of [undeclared, declared]) if (url.pathname === `/api/operations/${operation}`) return reply(paused(operation));
    // The resumed segments: any other operation reads as a starting resume.
    const id = url.pathname.split('/')[3];
    return reply({...paused(id), kind: 'candidate_loop_resume', state: 'active', process: {status: 'alive', reason: 'observed'}, receipt_available: false, native_status: null, loop: {final_iteration: 3, attempted_iterations: null}});
  });
  await page.goto(`${metadata.origin}/#monitor/${undeclared}`);
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  const fieldset = page.locator('#loop-resume-resources'), status = page.locator('#loop-resume-status');
  const summary = page.locator('#loop-resume-summary'), resume = page.locator('#loop-resume');
  const field = name => page.locator('#loop-resume-resources-' + name);
  await page.locator('#loop-resume-group').waitFor({state: 'visible'});
  assert.ok(await fieldset.isHidden(), 'nothing is asked before the review says it is needed');
  // A Resume retained by an earlier attempt without host resources (e.g. before this console
  // shared a ledger), refused before any claim and never admitted.
  const retainedKey = `siderius.loop-resume.v2/${store}/${undeclared}`;
  await page.evaluate(([key, value]) => localStorage.setItem(key, JSON.stringify(value)), [retainedKey,
    {origin: metadata.origin, expected_receipt_digest: digest, request_id: stale}]);

  // 1. The plain review is refused; the refusal reveals the fieldset.
  await page.locator('#loop-resume-review').click();
  await status.filter({hasText: 'first run declared no host resources'}).waitFor();
  await fieldset.waitFor({state: 'visible'});
  assert.ok(await resume.isHidden(), 'no Resume without a review');
  assert.deepEqual(reviews.map(item => item.method), ['GET']);

  // 2. An invalid declaration is not sent.
  await field('declare').check(); await field('gpu').selectOption('0'); await field('cpus').fill('1');
  await page.locator('#loop-resume-review').click();
  await status.filter({hasText: 'Resume review not sent'}).waitFor();
  assert.equal(reviews.length, 1, 'an invalid declaration sends no review');

  // 3. The fieldset is fixed while the review is in flight: the values sent are the values shown.
  await field('memory').fill('2'); await field('cpus').fill('2');
  let release; hold = new Promise(done => { release = done; });
  await page.locator('#loop-resume-review').click();
  await page.waitForFunction(() => document.getElementById('loop-resume-resources').disabled);
  assert.deepEqual(reviews.at(-1), {operation: undeclared, method: 'POST', body: {resources: {gpu_count: 0, host_memory_gib: 2, cpu_slots: 2, time_budgeted: false}}});
  release();
  await page.waitForFunction(() => !document.getElementById('loop-resume-resources').disabled);
  // The stale record differs from the reviewed reservation: probed, proven absent, dropped.
  assert.deepEqual(probes, [stale]);
  assert.equal(await page.evaluate(key => localStorage.getItem(key), retainedKey), null, 'the never-admitted record is dropped');

  // 4. The review binds those values; a later edit discards it.
  await summary.filter({hasText: 'Host resources: Reserves no GPU, 2 GiB host memory and 2 CPU slots.'}).waitFor();
  assert.equal(reviews.at(-1).body.resources.cpu_slots, 2);
  await resume.waitFor({state: 'visible'});
  await field('memory').fill('3');
  await status.filter({hasText: 'Host resources changed'}).waitFor();
  assert.ok(await resume.isHidden(), 'an edit after review needs a new review');
  await page.locator('#loop-resume-review').click();
  await summary.filter({hasText: '3 GiB host memory and 2 CPU slots'}).waitFor();

  // 5. A Resume refused before any claim is not retained; the fields unlock for a new review.
  refuseNextResume = true;
  await resume.click();
  await status.filter({hasText: 'Resume was not submitted'}).waitFor();
  assert.equal(await page.evaluate(key => localStorage.getItem(key), retainedKey), null, 'a pre-claim refusal is not retained');
  assert.equal(await fieldset.evaluate(el => el.disabled), false, 'the reservation can be edited again');
  assert.notEqual(resumes[0].request_id, stale);
  assert.deepEqual(resumes[0].resources, {gpu_count: 0, host_memory_gib: 3, cpu_slots: 2, time_budgeted: false});
  await page.locator('#loop-resume-review').click();
  await summary.filter({hasText: '3 GiB host memory and 2 CPU slots'}).waitFor();

  // 6. Resume sends exactly the reviewed pair and retains it with a new request UUID.
  await resume.click();
  await page.waitForFunction(id => location.hash.startsWith('#monitor/') && location.hash !== '#monitor/' + id, undeclared);
  assert.equal(resumes.length, 2);
  assert.deepEqual(resumes[1].resources, {gpu_count: 0, host_memory_gib: 3, cpu_slots: 2, time_budgeted: false});
  assert.equal(resumes[1].expected_review_digest, bound(2));
  assert.equal(resumes[1].expected_receipt_digest, digest);
  assert.ok(![stale, resumes[0].request_id].includes(resumes[1].request_id), 'a dropped request UUID is never reused');
  const kept = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), retainedKey);
  assert.deepEqual([kept.request_id, kept.resources, kept.expected_review_digest], [resumes[1].request_id, resumes[1].resources, bound(2)]);

  // 7. A loop whose first run declared resources: GET review, no fieldset, no resources sent.
  await page.evaluate(id => { location.hash = 'monitor/' + id; }, declared);
  await page.locator('#loop-state').filter({hasText: 'paused at a completed iteration boundary'}).waitFor();
  await page.locator('#loop-resume-review').click();
  await summary.filter({hasText: 'iteration 2 of 3'}).waitFor();
  assert.ok(await fieldset.isHidden(), 'a declared root asks for nothing');
  assert.ok(!(await summary.textContent()).includes('Host resources'));
  await resume.click();
  await page.waitForFunction(id => location.hash.startsWith('#monitor/') && location.hash !== '#monitor/' + id, declared);
  assert.deepEqual(Object.keys(resumes[2]).sort(), ['expected_receipt_digest', 'predecessor_operation_id', 'request_id']);
  await delay(100);
  assert.deepEqual(faults, []);
  console.log('PASS: a stale never-admitted retained Resume is dropped, a pre-claim refusal is not retained, an undeclared loop root reveals the Resume resources fieldset on refusal, reviews them by POST, discards stale reviews, and Resume carries exactly the reviewed reservation; a declared root sends none.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors && process.exitCode) process.stderr.write(errors);
}
