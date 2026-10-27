/** Real Chromium -> HTTP -> detached native shell, two pseudo iterations.
 * Separate synthetic projections below establish display/race behavior only.
 */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir, readFile, writeFile, unlink, readdir} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_EVIDENCE_DIR']) assert.ok(process.env[key], `Set ${key}`);
const evidence = resolve(process.env.CONSOLE_EVIDENCE_DIR);
await mkdir(evidence, {recursive: true});
const fixture = resolve(evidence, 'fixture'); await mkdir(fixture);
const started = Date.now(), head = execFileSync('git', ['rev-parse', 'HEAD'], {cwd: root, encoding: 'utf8'}).trim();
assert.equal(execFileSync('git', ['status', '--porcelain'], {cwd: root, encoding: 'utf8'}), '', 'Capture requires clean committed checkout');
const deadline = setTimeout(() => {console.error('600s browser witness limit'); process.exit(2);}, 600000);
let server, browser, stderr = '';
async function startServer(monitor = false) {
  server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.native_chain_fixture', fixture, ...(monitor ? ['--monitor'] : [])], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  server.stderr.on('data', chunk => {stderr += chunk;});
  const lines = createInterface({input: server.stdout});
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture startup timed out: ' + stderr)), 150000);
    lines.once('line', line => {clearTimeout(timer); accept(JSON.parse(line));});
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Fixture exit ${code}: ${stderr}`));});
  });
  await until(async () => {
    try {return (await fetch(metadata.origin)).ok;} catch {return false;}
  });
  return metadata;
}
async function stopServer() {
  if (!server || server.exitCode !== null) return;
  const done = new Promise(resolve => server.once('exit', resolve)); server.kill('SIGTERM'); await done;
}
async function until(predicate, timeout = 15000) {
  const end = Date.now() + timeout;
  while (!(await predicate())) {assert.ok(Date.now() < end, 'Timed out waiting for browser evidence'); await new Promise(r => setTimeout(r, 100));}
}
async function connect(page, token) {
  if (await page.locator('#access-change').isVisible()) await page.locator('#access-change').click(); 
  await page.locator('#token').fill(token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
}
try {
  const metadata = await startServer();
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const context = await browser.newContext(); const page = await context.newPage(), faults = [], calls = [];
  page.on('pageerror', e => faults.push(e.message));
  page.on('request', r => {if (new URL(r.url()).pathname.startsWith('/api/')) calls.push({method: r.method(), path: new URL(r.url()).pathname});});
  await page.goto(metadata.origin); await connect(page, metadata.token);
  await page.locator('nav a[href="#workflow"]').click();
  await page.locator('#editor-source').waitFor({state: 'attached'});
  await until(() => page.locator('#editor-source').isEnabled());
  await page.locator('#editor-advanced').evaluate(el => {el.open = true;});
  const draft = '# unsaved unrelated editor draft\n' + await page.locator('#editor-source').inputValue();
  await page.locator('#editor-source').fill(draft);
  await page.locator('nav a[href="#home"]').click();
  await page.locator('#native-chain-choice').selectOption('native');
  await page.locator('#native-chain-review').click();
  await until(() => page.locator('#native-chain-launch').isEnabled(), 90000);
  assert.match(await page.locator('#native-chain-details').textContent(), /browser_pseudo/);
  let intent, lost = false, hideStatus = true, posts = 0;
  await page.route('**/api/native-chain/launch', async route => {
    posts++; intent = route.request().postDataJSON();
    const response = await route.fetch(); assert.equal(response.status(), 202);
    if (!lost) {lost = true; await route.abort('failed');} else await route.fulfill({response});
  });
  await page.route('**/api/operations/*', async route => {
    if (hideStatus && intent && new URL(route.request().url()).pathname === '/api/operations/' + intent.operation_id) {
      return route.fulfill({status: 404, json: {error: {message: 'Synthetic lost-response observation outage'}}});
    }
    await route.continue();
  });
  await page.locator('#native-chain-launch').click();
  await until(() => lost, 90000);
  await until(async () => (await page.locator('#native-chain-status').textContent()).includes('unconfirmed'));
  await writeFile(resolve(evidence, 'intent.json'), JSON.stringify(intent, null, 2));
  assert.equal(await page.locator('#native-chain-new').isEnabled(), false, 'Uncertain intent cannot be cleared');
  await page.locator('#native-chain-choice').selectOption('');
  assert.equal(await page.locator('#native-chain-launch').isEnabled(), false, 'Changing selection cannot clear pending intent');
  await page.locator('nav a[href="#workflow"]').click();
  assert.equal(await page.locator('#editor-source').inputValue(), draft);
  await page.locator('nav a[href="#home"]').click();
  await connect(page, metadata.token); // explicit reconnect checks UUID, never POST
  assert.equal(posts, 1);
  hideStatus = false;
  await page.locator('#native-chain-retry').click();
  await page.locator('#native-chain-status').filter({hasText: 'existing'}).waitFor({timeout: 90000});
  assert.equal(posts, 2);
  await page.locator('#native-chain-monitor').click();
  await page.locator('#native-chain-observation').waitFor();
  // Native chains report whole-run cumulative tokens (ab2f40dd), not an unsupported notice.
  await page.locator('#tokens-status').filter({hasText: 'Whole-run cumulative usage.'}).waitFor();
  let final;
  await until(async () => {
    final = await page.evaluate(id => window.consoleSession.request('operations/' + id), intent.operation_id);
    return final.state === 'completed' && final.process.status === 'exited';
  }, 280000);
  const native = final.native_chain;
  assert.equal(native.terminal.supervision.execution.status, 'completed');
  assert.equal(native.terminal.supervision.cleanup.final.status, 'absent');
  assert.equal(native.terminal.supervision.direct_child_reaped, true);
  assert.equal(native.evidence.availability, 'available');
  assert.deepEqual(native.evidence.anomalies, []);
  assert.deepEqual(native.evidence.checkpoints.map(c => c.native_status), ['completed', 'completed']);
  assert.ok(native.evidence.checkpoints.every(c => c.manifest_verified && c.artifact_verified));
  assert.notEqual(native.evidence.token_run_id, intent.operation_id);
  const restored = JSON.parse(execFileSync(process.env.EDITOR_PYTHON, ['-c', 'import json,sys;from pathlib import Path;p=list((Path(sys.argv[1])/"iter_002").rglob("interpretation_iter_002.json"));assert len(p)==1;print(p[0].read_text())', native.admission.workspace], {cwd: root, encoding: 'utf8'}));
  assert.equal(restored.cold_start, false);
  await writeFile(resolve(evidence, 'status.json'), JSON.stringify(final, null, 2));
  await writeFile(resolve(evidence, 'restored-iteration2.json'), JSON.stringify(restored, null, 2));
  const log = await page.evaluate(id => window.consoleSession.request(`operations/${id}/log?kind=operation&max_bytes=65536`), intent.operation_id);
  assert.ok(log.text); await writeFile(resolve(evidence, 'operation-log.json'), JSON.stringify(log, null, 2));
  await page.locator('#native-chain-observation details[data-evidence-key="current:1"] summary').click();
  await new Promise(r => setTimeout(r, 2300));
  assert.equal(await page.locator('#native-chain-observation details[data-evidence-key="current:1"]').getAttribute('open'), '');
  await page.screenshot({path: resolve(evidence, 'native-monitor.png'), fullPage: true});
  await page.locator('nav a[href="#workflow"]').click(); assert.equal(await page.locator('#editor-source').inputValue(), draft);
  await page.locator('nav a[href="#home"]').click();
  await page.locator('#native-chain-new').click();
  assert.equal(await page.locator('#native-chain-intent').isHidden(), true);
  await page.locator('#native-chain-monitor').evaluate(a => {location.hash = a.hash;});
  const beforeReload = calls.length;
  page.on('dialog', dialog => dialog.accept()); await page.reload(); await connect(page, metadata.token);
  await page.locator('#native-chain-observation').waitFor();
  assert.ok(calls.slice(beforeReload).every(c => !c.path.startsWith('/api/editor') && c.path !== '/api/choices' && c.path !== '/api/native-chain/choices'));
  assert.equal(posts, 2);
  await stopServer();
  await unlink(resolve(fixture, 'inputs/declaration.json')); await unlink(resolve(fixture, 'review/capture.json'));
  const recovered = JSON.parse(execFileSync(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.native_chain_fixture', fixture, '--recover', resolve(evidence, 'intent.json')], {cwd: root, encoding: 'utf8'}));
  assert.equal(recovered.observation, 'existing');
  await startServer(true); await page.reload(); await connect(page, metadata.token);
  await page.locator('#native-chain-observation').waitFor();
  const retry = await page.evaluate(payload => window.consoleSession.request('native-chain/launch', payload), intent);
  assert.equal(retry.observation, 'existing');
  const recoveredStatus = await page.evaluate(id => window.consoleSession.request('operations/' + id), intent.operation_id);
  assert.deepEqual(recoveredStatus.native_chain.admission, native.admission);
  assert.equal(recoveredStatus.state, 'completed');
  const operations = await readdir(resolve(fixture, 'state/operations'));
  assert.deepEqual(operations, [intent.operation_id], 'Recovery never creates another operation');
  const operationPath = resolve(fixture, 'state/operations', intent.operation_id);
  const processRecord = await readFile(resolve(operationPath, 'process.json'), 'utf8');
  await page.evaluate(payload => window.consoleSession.request('native-chain/launch', payload), intent);
  assert.equal(await readFile(resolve(operationPath, 'process.json'), 'utf8'), processRecord, 'No redispatch/replaced process identity');
  await page.locator('nav a[href="#home"]').click();
  await page.locator('#native-chain-status').filter({hasText: 'No native captures configured'}).waitFor();
  assert.equal(await page.locator('#prepare-button').isEnabled(), false);
  await projections(context, metadata, final);
  assert.deepEqual(faults, []);
  await writeFile(resolve(evidence, 'result.json'), JSON.stringify({head, root, duration_seconds: (Date.now()-started)/1000, api_cost: 0, scientific_gpu: 0, actual_native_iterations: 2, real_http_posts: posts, operation_id: intent.operation_id, recovered: recovered.observation, rendering_fixtures: 'separate synthetic projections/races passed', faults}, null, 2));
  console.log('PASS native chain browser witness: ' + evidence);
} finally {
  clearTimeout(deadline); if (browser) await browser.close(); await stopServer();
  await writeFile(resolve(evidence, 'server-stderr.log'), stderr);
}

async function projections(context, metadata, realStatus) {
  // Deliberately synthetic records: these prove rendering and async fences only.
  const page = await context.newPage(); const candidate = '11111111-1111-4111-8111-111111111111';
  let status = structuredClone(realStatus), reviewReply, releaseReview, tokenReply, releaseTokens;
  let reviewRequestCount = 0, holdStatus = false, statusWaiting = false, releaseStatus;
  const delayedStatus = new Promise(r => {releaseStatus = r;});
  const holdReview = new Promise(r => {releaseReview = r;}), holdTokens = new Promise(r => {releaseTokens = r;});
  const fakeReview = {choice_id: 'one', label: 'One', request_digest: 'a'.repeat(64), admission: realStatus.native_chain.admission,
    capture_path: '/fixture/capture', envelope: '/fixture/envelope', read_only: [], network: false, devices: [], environment_names: [], timeout_seconds: 1, input_max_bytes: 1, max_iterations_observed: 2, max_observation_bytes: 1,
    credential_readiness: {ready: true, required_names: [], omitted_names: [], present_names: [], missing_names: [], file_status: 'not_needed', instructions: []}};
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const reply = json => route.fulfill({json});
    if (path === '/api/choices') return reply([]);
    if (path === '/api/native-chain/choices') return reply([{choice_id: 'one', label: 'One'}, {choice_id: 'two', label: 'Two'}]);
    if (path === '/api/native-chain/review') {reviewRequestCount++; reviewReply = true; await holdReview; return reply(fakeReview);}
    if (path.endsWith('/tokens')) {tokenReply = true; await holdTokens; return reply({groups: [{provider: 'STALE-CANDIDATE', requested_model: 'old', served_model: null, reported_total_tokens: 999}], quality: {partial: false}, reason: 'reported_responses', observed_at: 'old'});}
    if (path.endsWith('/log')) return reply({next_offset: 0, observed_size: 0, text: '', missing: true});
    if (path === '/api/operations/' + candidate) {
      if (holdStatus) {statusWaiting = true; await delayedStatus;}
      return reply({...realStatus, operation_id: candidate, kind: 'candidate', state: 'STALE_STATUS', native_chain: undefined});
    }
    if (path.startsWith('/api/operations/')) return reply(status);
    throw new Error('Unexpected fixture request ' + path);
  });
  await page.goto(metadata.origin + '/#home'); await connect(page, metadata.token);
  await page.locator('#native-chain-choice').selectOption('one'); await page.locator('#native-chain-review').click();
  await until(() => reviewReply); await page.locator('#native-chain-choice').selectOption('two');
  await connect(page, metadata.token); releaseReview(); await new Promise(r => setTimeout(r, 150));
  assert.equal(reviewRequestCount, 1); assert.equal(await page.locator('#native-chain-launch').isEnabled(), false);
  assert.equal(await page.locator('#native-chain-details').textContent(), '');
  await page.goto(metadata.origin + '/#slow-control/' + candidate); await connect(page, metadata.token);
  await until(() => tokenReply);
  await page.evaluate(id => {location.hash = 'slow-control/' + id;}, realStatus.operation_id);
  releaseTokens(); await page.locator('#native-chain-observation').waitFor();
  assert.equal(await page.locator('#token-rows').textContent(), '');
  assert.equal(await page.locator('#tokens-times').textContent(), '');
  assert.match(await page.locator('#tokens-status').textContent(), /not supported/);
  holdStatus = true;
  await page.evaluate(id => {location.hash = 'slow-control/' + id;}, candidate);
  await until(() => statusWaiting);
  await page.evaluate(id => {location.hash = 'slow-control/' + id;}, realStatus.operation_id);
  releaseStatus();
  await page.locator('#native-chain-observation').waitFor();
  assert.doesNotMatch(await page.locator('#monitor-status').textContent(), /STALE_STATUS/);
  for (const [name, setup, expected] of [
    ['mixed', s => {s.native_chain.evidence.checkpoints[1].native_status = 'no_records';}, /no_records/],
    ['all-no-records', s => {for (const c of s.native_chain.evidence.checkpoints) c.native_status = 'no_records';}, /no_records/],
    ['timeout', s => {s.native_chain.terminal.supervision.execution.status = 'timed_out'; s.native_chain.terminal.supervision.execution.returncode = 124;}, /timed_out/],
    ['unknown-cleanup', s => {s.state = 'unknown'; s.native_chain.terminal.supervision.cleanup.final.status = 'unknown';}, /unknown/],
    ['integrity', s => {s.native_chain.evidence.availability = 'integrity_failure'; s.native_chain.evidence.checkpoints[0].integrity = 'invalid';}, /integrity_failure/],
    ['missing', s => {s.native_chain.terminal = null; s.native_chain.evidence = {availability: 'unavailable', checkpoints: [], anomalies: []};}, /Checkpoint evidence unavailable/],
  ]) {
    status = structuredClone(realStatus); setup(status);
    await page.evaluate(s => window.renderNativeChain(s), status);
    assert.match(await page.locator('#native-chain-observation').textContent(), expected, name);
  }
  await page.close();
}
