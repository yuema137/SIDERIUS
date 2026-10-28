/** Theme acceptance against real static/API serving and a temporary editor project.
 * Required: EDITOR_PYTHON (this checkout's frozen .venv/bin/python),
 * CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE (existing installations).
 * Optional CONSOLE_SCREENSHOT_DIR. Only synthetic editor files and intercepted
 * console observations are used; no preparation, launch, provider or GPU work.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createRequire} from 'node:module';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const screenshots = process.env.CONSOLE_SCREENSHOT_DIR || await mkdtemp(join(tmpdir(), 'siderius-theme-browser-'));
await mkdir(screenshots, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = ''; server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
let browser;
const key = 'siderius.console.theme';
async function waitUntil(predicate) {
  const deadline = Date.now() + 15000;
  while (!(await predicate())) {
    if (Date.now() > deadline) throw new Error('Browser condition timed out');
    await new Promise(resolve => setTimeout(resolve, 50));
  }
}
try {
  const metadata = await new Promise((accept, reject) => {
    const timeout = setTimeout(() => reject(new Error('Server startup timeout')), 15000);
    lines.once('line', line => { clearTimeout(timeout); accept(JSON.parse(line)); });
    server.once('exit', code => { clearTimeout(timeout); reject(new Error(`Server exit ${code}: ${serverErrors}`)); });
  });
  const require = createRequire(import.meta.url);
  const {chromium} = require(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const context = await browser.newContext({colorScheme: 'dark', viewport: {width: 1440, height: 1000}});
  // Count actual timer creation, not timer firings: toggling must not add polling.
  await context.addInitScript(() => {
    window.themeTimerCount = 0;
    const interval = window.setInterval.bind(window);
    window.setInterval = (...args) => { window.themeTimerCount++; return interval(...args); };
  });
  const page = await context.newPage();
  const faults = []; page.on('pageerror', error => faults.push(error.message));
  const apiRequests = [];
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push([request.method(), new URL(request.url()).pathname]); });
  let navigationCount = 0; page.on('framenavigated', frame => { if (frame === page.mainFrame()) navigationCount++; });
  const theme = page.getByRole('combobox', {name: 'Color theme', exact: true});
  const applied = () => page.locator('html').getAttribute('data-theme');
  // Tokens alone cannot detect filters or selectors that alter rendered controls.
  async function renderedButtonContrast(mode) {
    const buttons = page.locator('button:enabled');
    for (const button of await buttons.all()) {
      if (!(await button.isVisible())) continue;
      const name = await button.textContent();
      for (const state of ['normal', 'hover', 'focus']) {
        await page.mouse.move(0, 0);
        await theme.focus();
        if (state === 'hover') await button.hover();
        if (state === 'focus') {
          await page.keyboard.press('Tab'); // Establish keyboard focus visibility.
          await button.focus();
        }
        const appearance = await button.evaluate(element => {
          const style = getComputedStyle(element);
          const luminance = color => {
            const channels = color.match(/[\d.]+/g).slice(0, 3).map(Number)
              .map(value => value / 255)
              .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
            return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
          };
          const ratio = (fg, bg) => {
            const a = luminance(fg), b = luminance(bg);
            return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
          };
          let parent = element.parentElement;
          while (parent && getComputedStyle(parent).backgroundColor === 'rgba(0, 0, 0, 0)') parent = parent.parentElement;
          return {
            text: ratio(style.color, style.backgroundColor), filter: style.filter,
            focusVisible: element.matches(':focus-visible'), outlineStyle: style.outlineStyle,
            outline: ratio(style.outlineColor, getComputedStyle(parent).backgroundColor),
          };
        });
        assert.equal(appearance.filter, 'none', `${mode}/${name}/${state}: color filters require rendered contrast accounting`);
        assert.ok(appearance.text >= 4.5, `${mode}/${name}/${state}: text contrast ${appearance.text}`);
        if (state === 'focus') {
          assert.equal(appearance.focusVisible, true);
          assert.notEqual(appearance.outlineStyle, 'none');
          assert.ok(appearance.outline >= 3, `${mode}/${name}: focus contrast ${appearance.outline}`);
        }
      }
    }
    await page.mouse.move(0, 0);
    await theme.focus();
  }
  async function capture(label) {
    for (const width of [1440, 720, 390]) {
      await page.setViewportSize({width, height: 1000});
      for (const mode of ['light', 'dark']) {
        await theme.selectOption(mode);
        await renderedButtonContrast(mode);
        // Actual shared foreground/background roles must retain readable contrast.
        const contrast = await page.evaluate(() => {
          const styles = getComputedStyle(document.documentElement);
          const luminance = name => {
            const hex = styles.getPropertyValue(name).trim().slice(1);
            const channels = [0, 2, 4].map(index => parseInt(hex.slice(index, index + 2), 16) / 255)
              .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
            return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
          };
          return [
            ['--text', '--panel', 4.5], ['--text', '--bg', 4.5],
            ['--muted', '--panel', 4.5], ['--muted', '--bg', 4.5],
            ['--on-primary', '--primary', 4.5], ['--primary', '--panel', 4.5],
            ['--secondary', '--panel', 4.5], ['--error', '--panel', 4.5],
            ['--muted', '--disabled', 4.5], ['--text', '--control', 4.5],
            ['--warning', '--warning-bg', 4.5], ['--edge', '--panel', 3],
            ['--control-border', '--control', 3], ['--focus', '--bg', 3],
          ].map(([fg, bg, minimum]) => {
            const a = luminance(fg), b = luminance(bg);
            return {fg, bg, minimum, ratio: (Math.max(a, b) + .05) / (Math.min(a, b) + .05)};
          });
        });
        for (const pair of contrast) assert.ok(pair.ratio >= pair.minimum, `${mode}: ${JSON.stringify(pair)}`);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${label}/${width}/${mode}: overflow`);
        await page.screenshot({path: join(screenshots, `${label}-${width}-${mode}.png`), fullPage: true});
      }
    }
    await page.setViewportSize({width: 1440, height: 1000});
  }
  await page.goto(metadata.origin);
  assert.equal(await theme.inputValue(), 'system'); assert.equal(await applied(), 'dark');
  await page.emulateMedia({colorScheme: 'light'});
  await waitUntil(async () => (await applied()) === 'light');
  // Native keyboard selection exposes the selected option and preserves focus.
  await theme.focus(); await page.keyboard.press('Home'); await page.keyboard.press('ArrowDown');
  assert.equal(await theme.inputValue(), 'light');
  assert.equal(await theme.evaluate(element => element === document.activeElement), true);
  await page.emulateMedia({colorScheme: 'dark'});
  assert.equal(await applied(), 'light');
  assert.equal(await page.evaluate(key => localStorage.getItem(key), key), 'light');
  await page.reload(); assert.equal(await theme.inputValue(), 'light'); assert.equal(await applied(), 'light');
  await page.getByRole('link', {name: 'Workflow Editor', exact: true}).click();
  assert.equal(await theme.inputValue(), 'light'); assert.equal(await applied(), 'light');
  await theme.selectOption('system');
  assert.equal(await applied(), 'dark');
  await page.emulateMedia({colorScheme: 'light'});
  await waitUntil(async () => (await applied()) === 'light');
  await page.evaluate(key => localStorage.setItem(key, 'invalid-value'), key);
  await page.reload(); assert.equal(await theme.inputValue(), 'system'); assert.equal(await applied(), 'light');

  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.getByText('Opened supported declaration.', {exact: false}).waitFor();
  await page.locator('#editor-inspector select').selectOption({label: 'other'});
  // Selecting a binding starts an asynchronous draft check (POST editor/<project>/draft);
  // snapshot only the settled state, never the transient 'checking' label.
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()) === 'Pending binding draft · complete');
  const snapshot = () => page.evaluate(() => ({
    source: document.querySelector('#editor-source').value,
    pending: document.querySelector('#editor-pending').textContent,
    project: document.querySelector('#editor-project').value,
    revision: document.querySelector('#editor-revision').textContent,
    selected: document.querySelector('.editor-node[aria-pressed="true"]').dataset.node,
    binding: document.querySelector('#editor-inspector select')?.value,
    saveDisabled: document.querySelector('#editor-save').disabled,
    diff: document.querySelector('#editor-diff').textContent,
  }));
  async function retainEditor(label) {
    const before = await snapshot(), calls = apiRequests.length, navigations = navigationCount;
    await capture(label);
    assert.deepEqual(await snapshot(), before, `${label}: theme altered editor state`);
    assert.equal(apiRequests.length, calls, `${label}: theme called API`);
    assert.equal(navigationCount, navigations, `${label}: theme reloaded/navigated`);
  }
  await retainEditor('inspector-unsaved');
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  await retainEditor('reviewed-source');
  const source = page.locator('#editor-source');
  await page.locator('#editor-advanced > summary').click();
  await source.fill((await source.inputValue()) + '# unsaved theme fixture\n');
  await retainEditor('source-unsaved');
  await source.fill('invalid Python !!!');
  await page.locator('#editor-review').click();
  await waitUntil(async () => (await page.locator('#editor-diagnostics').textContent()).length > 0);
  await retainEditor('review-error');

  page.once('dialog', dialog => dialog.accept());
  await page.goto(metadata.origin);
  await capture('console-empty');
  await page.locator('#configured-task > summary').click();
  const operation = '22222222-2222-4222-8222-222222222222';
  let tokenError = false;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    assert.equal(route.request().method(), 'GET', 'Theme test forbids all effectful console requests');
    let body;
    if (['/api/native-chain/choices', '/api/recorded-examples'].includes(path)) body = [];
    else if (path === '/api/operations') body = {operations: [], unreadable: 0, examined: 0, incomplete: false};
    else if (path === '/api/choices') body = [{task_id: 'synthetic', label: 'Synthetic theme fixture', preparation_timeout_seconds: 120, candidate_timeout_seconds: 300}];
    else if (path.endsWith('/tokens')) {
      if (tokenError) return route.fulfill({status: 409, json: {error: {code: 'integrity', message: 'Synthetic token read error'}}});
      body = {run_id: operation, availability: 'available', reason: 'reported_responses', quality: {partial: true}, observed_at: 'fixture', groups: [{provider: 'fixture', requested_model: 'offline', served_model: null, response_rows: 1, reported_input_tokens: 12, reported_output_tokens: null, reported_total_tokens: null, missing_input_rows: 0, missing_output_rows: 1, missing_total_rows: 1}]};
    } else if (path.endsWith('/log')) body = {operation_id: operation, kind: 'native', offset: 0, next_offset: 0, missing: false, truncated: false, text: 'Synthetic monitoring fixture. No execution.'};
    else body = {operation_id: operation, kind: 'candidate', state: 'running', process: {status: 'alive', reason: 'fixture'}, finishing: false, receipt_available: false, native_status: null};
    await route.fulfill({json: body});
  });
  await page.locator('#token').fill('theme-fixture'); await page.locator('#access-form button').click();
  await page.getByText('Connected. Observations', {exact: false}).waitFor();
  await page.locator('#run-name').fill('unsaved-run-fixture');
  await page.locator('nav a[href="#monitor"]').click();
  await page.locator('details', {has: page.locator('#tokens-table')}).getByText('Reported token table', {exact: true}).click(); // Recorded example has its own table.
  await page.locator('#operation-id').fill(operation); await page.locator('#monitor-button').click();
  await page.locator('#tokens-status').filter({hasText: 'Partial evidence'}).waitFor();
  const monitor = () => page.evaluate(() => ({run: document.querySelector('#run-name').value, task: document.querySelector('#task').value, operation: document.querySelector('#operation-id').value, rows: document.querySelector('#token-rows').textContent, timers: window.themeTimerCount, launch: document.querySelector('#launch-button').disabled}));
  const before = await monitor(), navigations = navigationCount;
  await capture('console-partial-monitor');
  assert.deepEqual(await monitor(), before);
  assert.equal(navigationCount, navigations);
  tokenError = true;
  await page.locator('#tokens-status').filter({hasText: 'Reported tokens stale'}).waitFor();
  await capture('console-error-monitor');
  assert.deepEqual(await monitor(), before);
  // Non-GET editor calls are read-only inspections: two explicit Reviews plus the binding
  // draft check (POST editor/<project>/draft, 6026b798). Save/prepare/launch must never occur.
  const nonGet = apiRequests.filter(([method]) => method !== 'GET').map(([, path]) => path);
  assert.equal(nonGet.filter(path => path.endsWith('/review')).length, 2, 'Exactly the two explicit editor reviews');
  assert.ok(nonGet.every(path => /^\/api\/editor\/[^/]+\/(review|draft)$/.test(path)), 'Only review/draft inspections before console monitoring: ' + nonGet.join(', '));
  assert.deepEqual(faults, []);
  await context.close();

  // Both read and write denial must work, including fallback on a fresh load.
  const denied = await browser.newContext({colorScheme: 'dark'});
  await denied.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', {get() { throw new DOMException('Denied', 'SecurityError'); }});
  });
  const deniedPage = await denied.newPage();
  deniedPage.on('pageerror', error => faults.push(error.message));
  await deniedPage.goto(metadata.origin);
  const deniedTheme = deniedPage.getByRole('combobox', {name: 'Color theme', exact: true});
  await deniedTheme.selectOption('light');
  assert.equal(await deniedPage.locator('html').getAttribute('data-theme'), 'light');
  await deniedPage.reload();
  assert.equal(await deniedTheme.inputValue(), 'system');
  assert.equal(await deniedPage.locator('html').getAttribute('data-theme'), 'dark');
  assert.deepEqual(faults, []);
  await denied.close();

  // A denied write cannot replace an older readable persisted preference.
  const writeDenied = await browser.newContext({colorScheme: 'dark'});
  const writeDeniedPage = await writeDenied.newPage();
  writeDeniedPage.on('pageerror', error => faults.push(error.message));
  await writeDeniedPage.goto(metadata.origin);
  await writeDeniedPage.getByRole('combobox', {name: 'Color theme', exact: true}).selectOption('light');
  await writeDenied.addInitScript(() => {
    Storage.prototype.setItem = () => { throw new DOMException('Quota exceeded', 'QuotaExceededError'); };
  });
  await writeDeniedPage.reload();
  const writeDeniedTheme = writeDeniedPage.getByRole('combobox', {name: 'Color theme', exact: true});
  await writeDeniedTheme.selectOption('dark');
  assert.equal(await writeDeniedPage.locator('html').getAttribute('data-theme'), 'dark');
  assert.equal(await writeDeniedPage.evaluate(key => localStorage.getItem(key), key), 'light');
  await writeDeniedPage.reload();
  assert.equal(await writeDeniedTheme.inputValue(), 'light');
  assert.equal(await writeDeniedPage.locator('html').getAttribute('data-theme'), 'light');
  assert.deepEqual(faults, []);
  await writeDenied.close();
  console.log(`PASS: rendered normal/hover/focus button contrast, theme preferences, keyboard/focus, read/write-denied storage and preserved old preference, retained inspector/source/review/monitor identities; no theme API calls/reloads/new timers; fixture screenshots ${screenshots}`);
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM'); lines.close();
}
