/** Real Chromium interaction against fixed static assets and intercepted API fixtures.
 * Required external inputs (no downloads or dependency installation):
 * CONSOLE_PLAYWRIGHT_MODULE: absolute installed playwright or playwright-core module.
 * CONSOLE_BROWSER_EXECUTABLE: absolute compatible Chromium executable.
 * CONSOLE_TEST_ORIGIN: http://127.0.0.1:<unused port>; this test starts a static server.
 * Optional CONSOLE_SCREENSHOT_DIR: artifact directory (default: fresh OS temp directory).
 * Run from any directory: node /path/to/checkout/tests/browser/candidate_console.mjs
 * Requires a host that permits Chromium/local socket creation. No native execution.
 */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir, mkdtemp, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import {showAllConsoleSections} from './console_view_flags.mjs';

const require = createRequire(import.meta.url);
for (const name of ['CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_TEST_ORIGIN']) {
  assert.ok(process.env[name], `Set ${name} explicitly; see this file's runner contract.`);
}
for (const name of ['CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) {
  assert.ok(isAbsolute(process.env[name]), `${name} must be absolute.`);
  await access(process.env[name]);
}
const origin = new URL(process.env.CONSOLE_TEST_ORIGIN);
assert.equal(origin.protocol, 'http:'); assert.equal(origin.hostname, '127.0.0.1');
assert.ok(origin.port && Number(origin.port) >= 1024); assert.equal(origin.pathname, '/');
assert.equal(origin.username + origin.password + origin.search + origin.hash, '');
const assets = join(dirname(fileURLToPath(import.meta.url)), '../../src/tools/candidate_console/static');
const screenshots = process.env.CONSOLE_SCREENSHOT_DIR || await mkdtemp(join(tmpdir(), 'siderius-console-browser-'));
await mkdir(screenshots, { recursive: true });
const server = createServer(async (req, res) => {
  const files = { '/': ['index.html', 'text/html'], '/app.js': ['app.js', 'text/javascript'], '/theme.js': ['theme.js', 'text/javascript'], '/theme.css': ['theme.css', 'text/css'], '/styles.css': ['styles.css', 'text/css'], '/icons.svg': ['icons.svg', 'image/svg+xml'] };
  // Serve every static script/style index.html loads, as production does; a missing module
  // (for example editor-task-controls.js) breaks session listeners before Connect completes.
  const asset = /^\/([a-z0-9-]+)\.(js|css)$/.exec(req.url);
  if (asset) files[req.url] = [asset[1] + '.' + asset[2], asset[2] === 'js' ? 'text/javascript' : 'text/css'];
  if (/^\/siderius-logo-(light|dark)\.svg$/.test(req.url)) files[req.url] = [req.url.slice(1), 'image/svg+xml'];
  const file = files[req.url];
  if (!file) { res.writeHead(404); res.end(); return; }
  try {
    res.writeHead(200, { 'Content-Type': file[1], 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'" });
    res.end(await readFile(join(assets, file[0])));
  } catch { res.writeHead(500); res.end(); }
});
await new Promise((resolve, reject) => { server.once('error', reject); server.listen(Number(origin.port), '127.0.0.1', resolve); });
const { chromium } = require(process.env.CONSOLE_PLAYWRIGHT_MODULE);
let browser;
try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE });
  showAllConsoleSections(browser);
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const faults = [];
  page.on('pageerror', error => faults.push(error.message));
  const requests = [];
  let preparation, candidate, dropPreparation = true, dropCandidate = true, staleLaunch = false, busyCandidate = true;
  let readinessBlocked = false;
  let nativeState = 'completed', finishing = false, disconnected = false;
  const hostile = '<img src=x onerror="window.hostile=true">';
  const known = '22222222-2222-4222-8222-222222222222';
  const logOffsets = [];
  let tokenFailure = false, delayedTokenId = null, releaseTokens, tokenSeen;
  let delayTokens, tokenDelaySeen;
  const otherKnown = '33333333-3333-4333-8333-333333333333';
  const tokenSnapshot = id => ({ run_id: id, run_name: 'fixture', observed_at: '2026-10-22T12:00:00Z', last_valid_usage_at: '2026-10-22T11:59:00Z',
    availability: id === preparation?.operation_id ? 'not_applicable' : 'available', reason: id === preparation?.operation_id ? 'preparation_not_applicable' : 'reported_responses',
    quality: { partial: true }, groups: id === preparation?.operation_id ? [] : [
      { provider: id === known ? 'OLD-RUN-IDENTITY' : 'fake', requested_model: hostile, served_model: 'served-model', response_rows: 2, reported_input_tokens: 100, reported_output_tokens: 25, reported_total_tokens: 130, missing_input_rows: 1, missing_output_rows: 0, missing_total_rows: 1 },
      { provider: 'fake', requested_model: 'missing-usage', served_model: null, response_rows: 1, reported_input_tokens: null, reported_output_tokens: null, reported_total_tokens: null, missing_input_rows: 1, missing_output_rows: 1, missing_total_rows: 1 }] });
  const status = id => ({ operation_id: id, kind: id === preparation?.operation_id ? 'prepare' : 'candidate', request_digest: 'a'.repeat(64), observed_at: '2026-10-22T12:00:00Z', state: nativeState,
    process: { status: finishing ? 'alive' : 'exited', reason: hostile }, finishing, receipt_available: nativeState === 'completed', native_status: nativeState === 'completed' ? (id === preparation?.operation_id ? 'prepared' : 'rejected') : null,
    native_id: 'native-fixture', validation_passed: false, reason: hostile });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin.origin) { await route.abort(); return; }
    if (!url.pathname.startsWith('/api/')) { await route.continue(); return; }
    const request = route.request();
    assert.equal(request.headers().authorization, 'Bearer browser-fixture-token');
    requests.push({ method: request.method(), path: url.pathname, body: request.postDataJSON() });
    const reply = (body, code = 200) => route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(body) });
    if (disconnected) { await route.abort(); return; }
    // Read-only lists owned by other panels; empty fixtures keep this witness on its own flow.
    if (['/api/native-chain/choices', '/api/recorded-examples'].includes(url.pathname)) return reply([]);
    if (url.pathname === '/api/operations') return reply({ operations: [], unreadable: 0, examined: 0, incomplete: false });
    if (url.pathname.endsWith('/graph-results')) return reply({ error: { code: 'not_found', message: 'Fixture has no workflow results' } }, 404);
    if (url.pathname === '/api/choices') return reply([{ task_id: 'synthetic', label: 'Synthetic ' + hostile, task_manifest: '/fixture/task.json', data_root: '/fixture/data', llm_config_file: '/fixture/llm.json', preparation_root: '/fixture/preparations', candidate_root: '/fixture/candidates', preparation_timeout_seconds: 120, candidate_timeout_seconds: 300 }]);
    if (url.pathname === '/api/preparations') {
      preparation = request.postDataJSON();
      if (dropPreparation) { dropPreparation = false; await route.abort(); return; }
      return reply({ operation_id: preparation.operation_id, kind: 'prepare', request_digest: 'a'.repeat(64), observed_at: 'now', observation: 'existing' }, 202);
    }
    if (url.pathname.endsWith('/review')) return reply({ prepare_operation_id: preparation.operation_id, prepared_digest: 'b'.repeat(64), task_id: 'synthetic', task_label: 'Synthetic ' + hostile, run_name: preparation.run_name,
      credential_readiness: { required_names: ['GEMINI_API_KEY'], omitted_names: [], unresolved_routes: [], present_names: readinessBlocked ? [] : ['GEMINI_API_KEY'], missing_names: readinessBlocked ? ['GEMINI_API_KEY'] : [], file_status: 'readable', ready: !readinessBlocked, instructions: readinessBlocked ? ['Set nonempty values in credential_file.'] : [] }, composition_fingerprint: 'c'.repeat(64), stages: ['propose', 'implement', 'validate'], routes: [{ node_id: 'propose', provider: 'fake', model: 'offline' }],
      proposal_advice: preparation.proposal_advice, implementation_advice: null, validation_advice: null, task_manifest: '/external/' + 'long-path/'.repeat(20) + 'task.json', data_root: '/external/data', candidate_workspace: '/external/candidate',
      preparation_timeout_seconds: 120, candidate_timeout_seconds: 300, network: 'none', devices: [], environment_names: [], read_only: ['/external/dependency'] });
    if (url.pathname === '/api/candidates') {
      candidate = request.postDataJSON();
      if (staleLaunch) return reply({ error: { code: 'stale_review', message: 'Review changed ' + hostile } }, 409);
      if (dropCandidate) { dropCandidate = false; await route.abort(); return; }
      if (busyCandidate) { busyCandidate = false; return reply({ error: { code: 'busy', message: 'Store is busy while the preparation wrapper finishes.' } }, 409); }
      return reply({ operation_id: candidate.candidate_operation_id, kind: 'candidate', request_digest: 'a'.repeat(64), observed_at: 'now', observation: 'existing' }, 202);
    }
    if (url.pathname.endsWith('/tokens')) {
      const id = url.pathname.split('/')[3], snapshot = tokenSnapshot(id);
      if (id === delayedTokenId) { tokenSeen(); await delayTokens; }
      if (tokenFailure) return reply({ error: { code: 'integrity', message: 'Token-only fixture read failed' } }, 409);
      return reply(snapshot);
    }
    if (url.pathname.endsWith('/log')) {
      const offset = Number(url.searchParams.get('offset')); logOffsets.push(offset);
      return reply({ operation_id: url.pathname.split('/')[3], kind: url.searchParams.get('kind'), offset, next_offset: 73, observed_size: 73, missing: false, truncated: false, text: offset === 0 ? 'Native rejected · 🧪 ' + hostile : '' });
    }
    return reply(status(url.pathname.split('/')[3]));
  });
  await page.goto(origin.origin);
  await page.locator('#configured-task > summary').click();
  // Keyboard connect proves associated labels, native submit and focus navigation.
  await page.getByLabel('Console token', { exact: true }).focus();
  await page.keyboard.type('browser-fixture-token'); await page.keyboard.press('Tab'); await page.keyboard.press('Enter');
  await page.locator('#access-status').filter({ hasText: 'Connected.' }).waitFor({state: 'attached'});
  await page.locator('#prepare-form').getByLabel('Run name', { exact: true }).fill('browser-offline');
  await page.getByText('Optional stage advice', { exact: true }).click();
  await page.getByLabel('Proposal advice', { exact: true }).fill(hostile);
  await page.getByRole('button', { name: 'Prepare request', exact: true }).dblclick();
  await page.getByText('Submission outcome is unconfirmed or refused:', { exact: false }).waitFor({state: 'attached'});
  assert.equal(requests.filter(item => item.method === 'POST').length, 1);
  assert.equal(await page.locator('#prepare-form').getByLabel('Run name', { exact: true }).isDisabled(), true);
  const uncertainId = await page.locator('#prepare-id').textContent();
  await page.locator('nav a[href="#monitor"]').click();
  await page.locator('nav a[href="#home"]').click();
  await page.locator('#access-change').click(); // Connected pages collapse the token form.
  await page.locator('#token').fill('browser-fixture-token');
  await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  assert.equal(await page.locator('#prepare-id').textContent(), uncertainId);
  assert.equal(requests.filter(item => item.method === 'POST').length, 1, 'Reconnect/navigation retain uncertain submission without retrying');
  await page.getByRole('button', { name: 'Retry same preparation', exact: true }).click();
  await page.getByText('Prepared request loaded.', { exact: false }).waitFor({state: 'attached'});
  await page.locator('#tokens-status').filter({ hasText: 'Not applicable to preparation' }).waitFor({state: 'attached'});
  const preps = requests.filter(item => item.path === '/api/preparations');
  assert.equal(preps.length, 2); assert.deepEqual(preps[0].body, preps[1].body);
  assert.equal(requests.filter(item => item.path === '/api/candidates').length, 0);
  assert.equal(await page.locator('#review img').count(), 0);
  assert.ok((await page.locator('#review').textContent()).includes(hostile));
  for (const [name, width, height, zoom] of [['desktop',1440,900,1], ['compact',1024,768,1], ['mobile',390,844,1], ['desktop-200-percent',1440,900,2]]) {
    // 200% desktop zoom is qualified at its equivalent CSS viewport.
    await page.setViewportSize({ width: width / zoom, height: height / zoom });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${name}: page overflows horizontally`);
    await page.screenshot({ path: join(screenshots, name + '.png'), fullPage: true });
  }
  await page.setViewportSize({ width:1440, height:900 });
  await page.getByRole('button', { name: 'Launch candidate', exact: true }).dblclick();
  await page.getByText('No automatic retry will occur.', { exact: false }).waitFor({state: 'attached'});
  await page.getByRole('button', { name: 'Retry same candidate launch', exact: true }).click();
  await page.getByText('Store is busy while the preparation wrapper finishes.', { exact: false }).waitFor({state: 'attached'});
  assert.equal(await page.getByRole('button', { name: 'Retry same candidate launch', exact: true }).isEnabled(), true);
  assert.ok((await page.locator('#review-status').textContent()).includes('Prepared request loaded.'));
  await page.getByRole('button', { name: 'Retry same candidate launch', exact: true }).click();
  await page.getByText('Candidate submission observed:', { exact: false }).waitFor({state: 'attached'});
  const launches = requests.filter(item => item.path === '/api/candidates');
  assert.equal(launches.length, 3);
  assert.deepEqual(launches[0].body, launches[1].body); assert.deepEqual(launches[1].body, launches[2].body);
  await page.locator('nav a[href="#monitor"]').click();
  await page.locator('details', {has: page.locator('#tokens-table')}).getByText('Reported token table', {exact: true}).click(); // Recorded example has its own table.
  await page.getByText('Activity and logs', {exact: true}).click();
  await page.locator('#monitor-status').filter({ hasText: 'Native: rejected' }).waitFor({state: 'attached'});
  assert.equal(await page.locator('#log img').count(), 0);
  assert.ok((await page.locator('#log').textContent()).includes(hostile));
  await page.waitForTimeout(2200); assert.ok(logOffsets.includes(73), 'Log cursor must use returned byte offset.');
  await page.locator('#tokens-status').filter({ hasText: 'Partial evidence' }).waitFor({state: 'attached'});
  assert.equal(await page.locator('#token-rows tr').count(), 2);
  assert.ok((await page.locator('#token-rows').textContent()).includes('100 · 1 missing'));
  assert.ok((await page.locator('#token-rows').textContent()).includes('Unavailable · 1 missing'));
  assert.equal(await page.locator('#token-rows img').count(), 0);
  const tokenText = await page.locator('#token-rows').textContent();
  await page.waitForTimeout(2200);
  assert.equal(await page.locator('#token-rows').textContent(), tokenText, 'Polling replaces token sums.');
  tokenFailure = true; nativeState = 'unknown';
  await page.locator('#tokens-status').filter({ hasText: 'Reported tokens stale' }).waitFor({state: 'attached'});
  await page.locator('#monitor-status').filter({ hasText: 'State: unknown' }).waitFor({state: 'attached'});
  assert.equal(await page.locator('#token-rows').textContent(), tokenText, 'Token-only failure retains same-run table.');
  assert.ok(logOffsets.filter(offset => offset === 73).length >= 2, 'Logs continue during token-only failure.');
  tokenFailure = false;
  await page.locator('#tokens-status').filter({ hasText: 'Partial evidence' }).waitFor({state: 'attached'});
  for (const [name, width, height, zoom] of [['tokens-desktop',1440,900,1], ['tokens-mobile',390,844,1], ['tokens-200-percent',1440,900,2]]) {
    await page.setViewportSize({ width: width / zoom, height: height / zoom });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${name}: page overflow`);
    await page.screenshot({ path: join(screenshots, name + '.png'), fullPage: true });
  }
  await page.setViewportSize({ width:1440, height:900 });
  // A delayed old run response cannot paint the newly selected run, even transiently.
  delayedTokenId = known;
  delayTokens = new Promise(resolve => { releaseTokens = resolve; });
  tokenDelaySeen = new Promise(resolve => { tokenSeen = resolve; });
  await page.getByLabel('Operation UUID', { exact: true }).fill(known);
  await page.getByRole('button', { name: 'Read operation', exact: true }).click();
  await tokenDelaySeen;
  await page.getByLabel('Operation UUID', { exact: true }).fill(otherKnown);
  await page.getByRole('button', { name: 'Read operation', exact: true }).click();
  assert.equal(await page.locator('#token-rows tr').count(), 0, 'Selection clears old table immediately.');
  await page.evaluate(() => { window.oldTokenPaint = false; new MutationObserver(() => { if (document.querySelector('#token-rows').textContent.includes('OLD-RUN-IDENTITY')) window.oldTokenPaint = true; }).observe(document.querySelector('#token-rows'), { childList: true, subtree: true }); });
  delayedTokenId = null; releaseTokens();
  await page.locator('#token-rows tr').first().waitFor({state: 'attached'});
  assert.equal(await page.evaluate(() => window.oldTokenPaint), false, 'Epoch fence rejects old token response.');
  assert.ok(!(await page.locator('#token-rows').textContent()).includes('OLD-RUN-IDENTITY'));
  const mutations = requests.filter(item => item.method === 'POST').length;
  nativeState = 'unknown';
  await page.getByLabel('Operation UUID', { exact: true }).fill(known);
  await page.getByRole('button', { name: 'Read operation', exact: true }).click();
  await page.locator('#monitor-status').filter({ hasText: 'State: unknown' }).waitFor({state: 'attached'});
  nativeState = 'completed'; finishing = true;
  await page.getByRole('button', { name: 'Read operation', exact: true }).click();
  await page.locator('#monitor-status').filter({ hasText: 'Finishing:' }).waitFor({state: 'attached'});
  assert.ok((await page.locator('#monitor-status').textContent()).includes('Native result is available; the wrapper is still finishing.'));
  assert.ok((await page.locator('#operation-facts').textContent()).includes('alive:'));
  assert.ok((await page.locator('#operation-facts').textContent()).includes('Native receipt availabletrue'));
  disconnected = true;
  await page.getByRole('button', { name: 'Read operation', exact: true }).click();
  await page.locator('#monitor-status').filter({ hasText: 'Observation stale' }).waitFor({state: 'attached'});
  disconnected = false;
  finishing = false; nativeState = 'unknown';
  await page.reload();
  assert.equal(await page.getByLabel('Console token', { exact: true }).inputValue(), '');
  assert.equal(await page.getByLabel('Operation UUID', { exact: true }).inputValue(), known);
  assert.equal(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }).includes('browser-fixture-token')), false);
  assert.equal(new URL(page.url()).search, '');
  await page.getByLabel('Console token', { exact: true }).fill('browser-fixture-token');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await page.locator('#access-status').filter({ hasText: 'Connected.' }).waitFor({state: 'attached'});
  await page.getByRole('button', { name: 'Read operation', exact: true }).click();
  await page.locator('#monitor-status').filter({ hasText: 'State: unknown' }).waitFor({state: 'attached'});
  assert.equal(requests.filter(item => item.method === 'POST').length, mutations, 'Reconnect must be GET-only.');
  await page.locator('nav a[href="#home"]').click();
  await page.locator('#configured-task > summary').click();
  // Fresh preparation and stale review refuse a second launch until reviewed again.
  finishing = false; nativeState = 'completed'; staleLaunch = true;
  await page.locator('#prepare-form').getByLabel('Run name', { exact: true }).fill('second-run');
  await page.getByRole('button', { name: 'Prepare request', exact: true }).click();
  await page.getByText('Prepared request loaded.', { exact: false }).waitFor({state: 'attached'});
  await page.getByRole('button', { name: 'Launch candidate', exact: true }).click();
  await page.getByText('Launch refused.', { exact: false }).waitFor({state: 'attached'});
  await page.waitForTimeout(2200);
  assert.equal(await page.getByRole('button', { name: 'Retry same candidate launch', exact: true }).isDisabled(), true);
  assert.ok((await page.locator('#launch-status').textContent()).includes(hostile));
  assert.equal(await page.evaluate(() => window.hostile), undefined);
  // Hostile text must never create an image; the static brand logos are the only <img> elements.
  assert.equal(await page.locator('img:not([data-brand-logo])').count(), 0);
  assert.equal(await page.locator('img[data-brand-logo]').count(), 4, 'Only the four static brand logos');
  readinessBlocked = true;
  const frozenReview = await page.locator('#review').textContent();
  await page.getByRole('button', { name: 'New preparation', exact: true }).click();
  await page.locator('#prepare-form').getByLabel('Run name', { exact: true }).fill('edited-draft');
  assert.ok(frozenReview.includes('second-run')); assert.equal(await page.locator('#review').textContent(), '');
  assert.ok((await page.locator('#configured-paths').textContent()).includes('/fixture/llm.json'));
  await page.getByRole('button', { name: 'Prepare request', exact: true }).click();
  await page.locator('#review-status').filter({ hasText: 'Launch blocked' }).waitFor({state: 'attached'});
  assert.equal(await page.getByRole('button', { name: 'Launch candidate', exact: true }).isDisabled(), true);
  assert.ok((await page.locator('#review').textContent()).includes('GEMINI_API_KEY'));
  const blockedReview = await page.locator('#review').textContent();
  const blockedId = await page.locator('#prepare-id').textContent();
  const blockedMutations = requests.filter(item => item.method === 'POST').length;
  for (const width of [1440, 390]) {
    await page.setViewportSize({width, height: 900});
    for (const mode of ['light', 'dark']) {
      await page.getByRole('combobox', {name: 'Color theme', exact: true}).selectOption(mode);
      assert.equal(await page.locator('#review').textContent(), blockedReview);
      assert.equal(await page.locator('#prepare-id').textContent(), blockedId);
      assert.equal(await page.locator('#launch-button').isDisabled(), true);
      assert.equal(requests.filter(item => item.method === 'POST').length, blockedMutations);
      await page.screenshot({path: join(screenshots, `readiness-blocked-${width}-${mode}.png`), fullPage: true});
    }
  }

  readinessBlocked = false;
  await page.getByRole('button', { name: 'Refresh readiness', exact: true }).click();
  await page.locator('#review-status').filter({ hasText: 'Name presence checked' }).waitFor({state: 'attached'});
  assert.equal(await page.getByRole('button', { name: 'Launch candidate', exact: true }).isEnabled(), true);
  assert.equal(faults.length, 0, faults.join('\n'));
  console.log(`PASS: real ${browser.version()} interactions; UUID retries, explicit launch, stale/unknown/rejected/finishing, escaped text, byte cursor, GET-only reopen, memory-only token, reported-token replacement/null/partial/stale/epoch fencing and readiness blockers/refresh plus eleven screenshots (${screenshots}).`);
  await context.close();
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
