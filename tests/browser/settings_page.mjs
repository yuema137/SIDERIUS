/** Settings page witnesses: allowlisted choices, folder refs, CAS save, stale and read-only.
 * Real static assets and boundary from workflow_editor_server; /api/settings is mocked.
 * Requires EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE;
 * optional CONSOLE_SCREENSHOT_DIR.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = ''; server.stderr.on('data', chunk => {errors += chunk;});
const lines = createInterface({input: server.stdout});
let browser;
const SCHEMA = 'siderius.console-global-settings/v1';
const DEFAULT = {source: 'library', name: 'default-9f0124a7c346.json', sha256: '9f0124a7c346' + 'f'.repeat(52)};
const pending = {schema_version: SCHEMA, llm_profile: DEFAULT, advice: null, data_folders: {}};
function settingsView({writable = true, settings = pending, sha = 'a'.repeat(64), active = pending, activeSha = 'a'.repeat(64)} = {}) {
  return {
    enabled: true, writable, settings_sha256: sha, pending: settings, active, active_sha256: activeSha,
    restart_required: sha !== activeSha,
    rows: [
      {name: 'advice', task_id: null, origin: 'server_config', label: 'None', effective: null},
      {name: 'llm_profile', task_id: 'synthetic', origin: 'global_settings', label: DEFAULT.name, effective: '/srv/ws/library/llm/' + DEFAULT.name},
      {name: 'data_root', task_id: 'synthetic', origin: 'workspace_layout', label: 'Workspace layout', effective: '/srv/ws/data/synthetic'},
    ],
    llm_profiles: [{label: DEFAULT.name, ref: DEFAULT}, {label: 'Lab profile', ref: {source: 'allowlist', id: 'lab'}}],
    advice_files: [{label: 'Shared advice', ref: {source: 'allowlist', id: 'notes'}}],
    data_roots: [{id: 'lab', label: 'Lab disk'}, {id: 'workspace', label: 'Workspace data'}],
    tasks: [{task_id: 'synthetic', label: 'Synthetic task', data_root_origin: 'workspace_layout'}],
    workspace_root: '/srv/ws',
    workspace: {workspace_status: 'present', ready: false, init_command: null, entries: [{name: 'data/synthetic', status: 'missing', created_by: 'operator'}]},
    host: 'fixture-host',
  };
}
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error('Server startup timeout')), 15000);
    lines.once('line', line => {clearTimeout(timer); accept(JSON.parse(line));});
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Server ${code}: ${errors}`));});
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}}), faults = [], puts = [];
  page.on('pageerror', error => faults.push(error.message));
  let view = settingsView(), putReply = null;
  await page.route('**/api/settings**', async route => {
    const request = route.request(), url = new URL(request.url());
    assert.equal(request.headers().authorization, 'Bearer ' + metadata.token);
    if (url.pathname === '/api/settings/folders') {
      assert.equal(request.method(), 'GET');
      assert.equal(url.searchParams.get('root_id'), 'lab');
      const subpath = url.searchParams.get('subpath');
      const entries = subpath === '' ? [{name: 'runs', kind: 'directory'}, {name: 'elsewhere', kind: 'link'}] : [{name: 'a', kind: 'directory'}];
      return route.fulfill({json: {entries, incomplete: false}});
    }
    if (request.method() === 'PUT') {
      assert.equal(request.headers()['content-type'], 'application/json');
      puts.push(JSON.parse(request.postData()));
      return route.fulfill(putReply());
    }
    return route.fulfill({json: view});
  });
  await page.goto(metadata.origin + '/#settings');
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#settings-status').filter({hasText: 'Choose values'}).waitFor();
  assert.match(await page.locator('#settings-host').textContent(), /fixture-host/);
  assert.equal(await page.locator('#settings-save').isDisabled(), true, 'Nothing to save before a change');
  assert.match(await page.locator('#settings-workspace-problems').textContent(), /data\/synthetic: missing \(put the task data here\)/);
  assert.match(await page.locator('#settings-rows').textContent(), /Workspace folder/);

  // Choose an allowlisted model and a folder under an allowlisted root; links are not selectable.
  await page.getByLabel('Lab profile').check();
  await page.locator('#settings-root-synthetic').selectOption('lab');
  await page.getByRole('button', {name: 'runs/'}).waitFor();
  assert.equal(await page.getByRole('button', {name: 'elsewhere/'}).count(), 0);
  assert.match(await page.locator('#settings-data').textContent(), /elsewhere \(link; not selectable\)/);
  await page.getByRole('button', {name: 'runs/'}).click();
  await page.getByRole('button', {name: 'Use runs'}).click();
  assert.match(await page.locator('#settings-pending').textContent(), /Unsaved changes/);
  const saved = {schema_version: SCHEMA, llm_profile: {source: 'allowlist', id: 'lab'}, advice: null, data_folders: {synthetic: {root_id: 'lab', subpath: 'runs'}}};
  putReply = () => ({json: settingsView({settings: saved, sha: 'b'.repeat(64)})});
  await page.locator('#settings-save').click();
  await page.locator('#settings-status').filter({hasText: 'Saved; active after server restart.'}).waitFor();
  assert.deepEqual(puts.at(-1), {expected_sha256: 'a'.repeat(64), settings: saved}, 'CAS on the loaded revision; refs only');
  assert.match(await page.locator('#settings-pending').textContent(), /Saved but not yet active: model profile, data folders/);
  if (process.env.CONSOLE_SCREENSHOT_DIR) await page.screenshot({path: join(process.env.CONSOLE_SCREENSHOT_DIR, 'settings-desktop.png'), fullPage: true});

  // A stale save is refused and explained; the page keeps the user's choice.
  await page.getByLabel('Shared advice').check();
  putReply = () => ({status: 409, json: {error: {code: 'stale', message: 'settings changed since they were loaded; reload'}}});
  await page.locator('#settings-save').click();
  await page.locator('#settings-status').filter({hasText: 'changed elsewhere'}).waitFor();
  assert.equal(puts.at(-1).expected_sha256, 'b'.repeat(64));

  // Read-only consoles disable every control.
  view = settingsView({writable: false});
  await page.locator('#settings-reload').click();
  await page.locator('#settings-status').filter({hasText: 'Read-only'}).waitFor();
  assert.equal(await page.locator('#settings-save').isDisabled(), true);
  assert.equal(await page.getByLabel('Lab profile').isDisabled(), true);
  // An unusable settings file is named with its recovery, and Save stays off without a digest.
  view = {...settingsView(), pending: null, settings_sha256: null, restart_required: false,
    problem: 'settings/global_settings.json cannot be read: it must be a regular file owned by you with mode 600. Run chmod 600 on it (or restore it), then Reload.'};
  await page.locator('#settings-reload').click();
  await page.locator('#settings-status').filter({hasText: 'chmod 600'}).waitFor();
  assert.equal(await page.locator('#settings-save').isDisabled(), true);
  await page.setViewportSize({width: 390, height: 844});
  if (process.env.CONSOLE_SCREENSHOT_DIR) await page.screenshot({path: join(process.env.CONSOLE_SCREENSHOT_DIR, 'settings-mobile.png'), fullPage: true});
  assert.deepEqual(faults, []);
  console.log('PASS: settings view, allowlist choice, no-follow folder picking, CAS PUT with refs only, restart notice, stale refusal and read-only mode.');
} finally { if (browser) await browser.close(); server.kill('SIGTERM'); lines.close(); }
