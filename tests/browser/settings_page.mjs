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
    llm_profiles: [{label: DEFAULT.name, ref: DEFAULT, required_names: ['OPENAI_API_KEY'], routes: [{name: 'propose', applicability: 'conditional', transport: {provider: 'openai', model_id: 'gpt-x'}}]}, {label: 'Lab profile', ref: {source: 'allowlist', id: 'lab'}, required_names: [], routes: []}],
    advice_files: [{label: 'Shared advice', ref: {source: 'allowlist', id: 'notes'}, present_keys: ['propose', 'mindset'], unsupported_keys: ['mindset']}],
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
  let view = settingsView(), putReply = null; const uploads = [];
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
    if (url.pathname === '/api/settings/exports') {
      exports.push(JSON.parse(request.postData()));
      return route.fulfill({json: {name: 'my-export', files: ['workflow.py', 'llm.json']}});
    }
    if (url.pathname.startsWith('/api/settings/exports/')) {
      downloads.push(url.pathname);
      return route.fulfill({body: 'exported bytes', contentType: 'application/octet-stream'});
    }
    if (url.pathname === '/api/settings/library') {
      assert.equal(request.method(), 'POST');
      uploads.push(JSON.parse(request.postData()));
      return route.fulfill({json: {source: 'library', name: 'notes-0123456789ab.json', sha256: '0123456789ab' + '0'.repeat(52)}});
    }
    if (request.method() === 'PUT') {
      assert.equal(request.headers()['content-type'], 'application/json');
      puts.push(JSON.parse(request.postData()));
      return route.fulfill(putReply());
    }
    return route.fulfill({json: view});
  });
  const exports = [], downloads = [];
  await page.route(/\/api\/editor\/(projects|demo)$/, route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({json: path.endsWith('/projects') ? [{project_id: 'demo', candidate_run_enabled: true}] : {sha256: 'c'.repeat(64)}});
  });
  await page.goto(metadata.origin + '/#settings');
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#settings-status').filter({hasText: 'Choose values'}).waitFor();
  assert.match(await page.locator('#settings-host').textContent(), /fixture-host/);
  assert.equal(await page.locator('#settings-save').isDisabled(), true, 'Nothing to save before a change');
  // Readiness problems read as one plain sentence with the fix that applies (task data: the operator creates it).
  assert.equal(await page.locator('#settings-workspace-problems').textContent(), "data/synthetic is missing. Create this folder on the server and put the task's data in it.");
  assert.equal(await page.locator('#settings-init').isHidden(), true, 'init cannot create task data');
  assert.match(await page.locator('#settings-rows').textContent(), /Workspace folder/);

  // Run-page origin lines: only this task's rows whose server path equals the reviewed value.
  const originLinesResult = await page.evaluate(name => window.consoleSettings.originLines('synthetic', {llm_profile: '/srv/ws/library/llm/' + name, data_root: '/elsewhere'}), DEFAULT.name);
  assert.deepEqual(originLinesResult, [`Model profile source: Settings page (${DEFAULT.name})`]);
  assert.deepEqual(await page.evaluate(() => window.consoleSettings.originLines('other-task', {llm_profile: 'x'})), []);

  // Cards show owner-derived key names and routes; unusable advice keys are marked.
  assert.match(await page.locator('#settings-models').textContent(), /Needs keys: OPENAI_API_KEY/);
  assert.match(await page.locator('#settings-advice').textContent(), /Workflows cannot use mindset yet/);
  // Import sends the file's text to the server library; no path leaves the browser.
  await page.locator('#settings-import-advice').setInputFiles({name: 'notes.json', mimeType: 'application/json', buffer: Buffer.from('{"propose": "x"}')});
  await page.locator('#settings-status').filter({hasText: 'Imported as notes-0123456789ab.json'}).waitFor();
  assert.deepEqual(uploads, [{kind: 'advice', label: 'notes', content: '{"propose": "x"}'}]);

  // Export pins the saved source digest; downloads go through the bearer session as a Blob.
  await page.locator('#settings-export-project option[value="demo"]').waitFor({state: 'attached'});
  await page.locator('#settings-export').click();
  await page.locator('#settings-export-status').filter({hasText: 'no advice.json was written'}).waitFor();
  assert.deepEqual(exports, [{project_id: 'demo', task_id: 'synthetic', name: 'my-export', expected_source_sha256: 'c'.repeat(64)}]);
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', {name: 'Download llm.json'}).click()]);
  assert.equal(download.suggestedFilename(), 'llm.json');
  assert.deepEqual(downloads, ['/api/settings/exports/my-export/llm.json']);

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

  // A save whose folder sync the server could not confirm says so instead of a plain success.
  const notice = 'Saved, but the server could not confirm the save is on disk; save again or check the disk before restarting.';
  const withAdvice = {...saved, advice: {source: 'allowlist', id: 'notes'}};
  putReply = () => ({json: {...settingsView({settings: withAdvice, sha: 'd'.repeat(64)}), notice}});
  await page.locator('#settings-save').click();
  await page.locator('#settings-status').filter({hasText: 'could not confirm'}).waitFor();
  assert.equal(await page.locator('#settings-status').textContent(), notice);
  assert.deepEqual(puts.at(-1), {expected_sha256: 'b'.repeat(64), settings: withAdvice});

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
  console.log('PASS: settings view, profile/advice cards, advice import, export and bearer download, allowlist choice, no-follow folder picking, CAS PUT with refs only, restart notice, stale refusal, unconfirmed-durability notice and read-only mode.');
} finally { if (browser) await browser.close(); server.kill('SIGTERM'); lines.close(); }
