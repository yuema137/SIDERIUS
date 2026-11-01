/** Real HTTP/browser error projections; synthetic causes, no sandbox/GPU/provider calls. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_EVIDENCE_DIR']) assert.ok(process.env[key], key);
const evidence = process.env.CONSOLE_EVIDENCE_DIR;
await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.setups_fixture', '--error-projections'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let diagnostics = '', browser;
server.stderr.on('data', chunk => { diagnostics += chunk; });
const lines = createInterface({input: server.stdout});
const secret = 'private-browser-secret-sentinel';
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error('Server startup timeout')), 30000);
    lines.once('line', line => { clearTimeout(timer); accept(JSON.parse(line)); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Server exited ${code}`)); });
  });
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
  console.log('PASS: Task/setup HTTP and browser projections exclude private causes; server logs retain them');
} finally {
  if (browser) await browser.close();
  lines.close();
  server.kill('SIGTERM');
}
