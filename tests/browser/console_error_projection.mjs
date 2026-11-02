/** Real HTTP/browser error projections; synthetic causes, no sandbox/GPU/provider calls. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {waitForMetadata} from './fixture_metadata.mjs';
import {showAllConsoleSections} from './console_view_flags.mjs';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_EVIDENCE_DIR']) assert.ok(process.env[key], key);
const evidence = process.env.CONSOLE_EVIDENCE_DIR;
await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.setups_fixture', '--error-projections'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let diagnostics = '', browser;
server.stderr.on('data', chunk => { diagnostics += chunk; });
const secret = 'private-browser-secret-sentinel';
try {
  const metadata = await waitForMetadata(server);
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});
  const faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/#task');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#task-summary-state[data-state="failed"]').waitFor();
  assert.match(await page.locator('#task-summary-state').textContent(), /Invalid value while reading task summary facts/);
  assert.ok(!(await page.locator('body').textContent()).includes(secret));
  const summary = await page.request.get(metadata.origin + '/api/tasks/synthetic/summary', {headers: {Authorization: 'Bearer ' + metadata.token}});
  assert.ok(!(await summary.text()).includes(secret));
  await page.screenshot({path: join(evidence, 'task-safe-error.png'), fullPage: true});
  await page.locator('nav a[href="#workflow"]').click();
  await page.locator('#setup-new').click();
  await page.locator('#setup-new-label').fill('Failed setup');
  const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/setups'));
  await page.locator('#setup-new-create').click();
  const refused = await response;
  assert.equal(refused.status(), 409);
  assert.ok(!(await refused.text()).includes(secret));
  await page.locator('#setup-new-status').filter({hasText: 'Invalid value'}).waitFor();
  assert.match(await page.locator('#setup-new-status').textContent(), /projects\/failed-setup\/ was left in place/);
  assert.ok(!(await page.locator('body').textContent()).includes(secret));
  assert.ok(diagnostics.includes(secret), 'Server retains the private cause');
  assert.deepEqual(faults, []);
  await page.screenshot({path: join(evidence, 'setup-safe-error.png'), fullPage: true});
  // A real editor review carries native target/current failure observations.
  await page.locator('#setup-new-label').fill('Editor setup');
  await page.locator('#setup-new-create').click();
  await page.locator('#setup-new-dialog').waitFor({state: 'hidden'});
  const headers = {Authorization: 'Bearer ' + metadata.token, Origin: metadata.origin};
  const opened = await page.request.get(metadata.origin + '/api/editor/editor-setup', {headers});
  const current = await opened.json();
  const checked = await page.request.post(metadata.origin + '/api/editor/editor-setup/review', {
    headers, data: {expected_sha256: current.sha256, proposal: {kind: 'source', source: current.source}}
  });
  assert.equal(checked.status(), 200);
  assert.ok(!(await checked.text()).includes(secret));
  const review = (await checked.json()).task_reference_update;
  assert.match(review.observation.result.failure.message, /Invalid value/);
  assert.match(review.current_observation.result.failure.message, /Unexpected error/);
  // Exercise the production JSON details renderer with the safe HTTP observations.
  // Only its visibility gates are synthetic; this does not assert save admission.
  await page.evaluate(review => {
    const parent = document.createElement('div'); parent.id = 'error-witness-review';
    document.body.append(parent);
    review.save_supported = true;
    review.current_observation.result.candidate_check = {};
    window.editorTaskControls.renderReview(parent, {review, connected: true, saving: false}, {});
  }, review);
  await page.locator('#error-witness-review summary').filter({hasText: 'Task declaration details'}).click();
  const details = await page.locator('#error-witness-review pre').textContent();
  assert.ok(!details.includes(secret));
  assert.match(details, /Invalid value/); assert.match(details, /Unexpected error/);
  assert.ok(diagnostics.includes(secret));
  assert.deepEqual(faults, []);
  await page.screenshot({path: join(evidence, 'editor-safe-observations.png'), fullPage: true});
  console.log('PASS: Task/setup/editor HTTP and browser projections exclude private causes; server logs retain them');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
}
