/** Real Chromium + real authoring API + temporary ordinary Python project.
 * Explicit env: EDITOR_PYTHON (this checkout .venv/bin/python),
 * CONSOLE_PLAYWRIGHT_MODULE and CONSOLE_BROWSER_EXECUTABLE (existing installs).
 * No provider calls, native launch, datasets or downloads. Server is cleaned up.
 */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {readFile, writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = ''; server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
const metadata = await Promise.race([new Promise((accept, reject) => { lines.once('line', line => accept(JSON.parse(line))); server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`))); }), new Promise((_, reject) => setTimeout(() => reject(new Error('server startup timeout')), 15000))]);
let browser;
async function waitUntil(predicate) { const deadline = Date.now() + 15000; while (!(await predicate())) { if (Date.now() > deadline) throw new Error("Browser condition timed out"); await new Promise(resolve => setTimeout(resolve, 50)); } }
try {
  const require = createRequire(import.meta.url);
  const {chromium} = require(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
  const faults = []; page.on('pageerror', error => faults.push(error.message));
  for (let tries = 0; ; tries++) {
    try { await page.goto(metadata.origin + '/editor.html'); break; }
    catch (error) { if (tries >= 20) throw error; await new Promise(resolve => setTimeout(resolve, 100)); }
  }
  await page.locator('#editor-token').fill(metadata.token);
  await page.locator('#editor-connect button').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported')); 
  const source = page.locator('#editor-source');
  const original = await source.inputValue();
  await page.locator('#editor-inspector select').selectOption({label: 'other'});
  // A source edit cannot silently replace an unrendered inspector proposal.
  assert.equal(await source.isDisabled(), true);
  await assert.rejects(source.fill(original + '# attempted source switch\n', {timeout: 100}));
  assert.equal(await source.inputValue(), original);
  assert.match(await page.locator('#editor-pending').textContent(), /Review changes to update Python source/);
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  assert.match(await page.locator('#editor-edges').textContent(), /external:other → p.request/);
  assert.match(await page.locator('#editor-diff').textContent(), /binding='other'/);
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Saved reviewed'));
  const inspect = () => JSON.parse(execFileSync(process.env.EDITOR_PYTHON, ['-c', 'import sys; from pathlib import Path; from workflows.definition import parse_workflow_source; print(parse_workflow_source(Path(sys.argv[1]).read_text()).model_dump_json())', metadata.source], {cwd: root, encoding: 'utf8'}));
  assert.equal(inspect().definition.nodes[0].request.binding, 'other');
  assert.equal(inspect().definition.task.manifest, 'missing.json');
  // Ordinary coding-agent edit to canonical file, then source refresh projects new nodes.
  const disk = await readFile(metadata.source, 'utf8');
  const agent = original.replace('nodes=(NodeInstance', 'nodes=(NodeInstance(id="second", capability="proposal", request=ExternalRequest(binding="other")),NodeInstance');
  await writeFile(metadata.source, agent);
  await page.locator('#editor-refresh').click();
  await waitUntil(async () => (await page.locator('#editor-graph button').count()) === 2);
  // Review a GUI proposal, then external write: save must conflict and retain it.
  await source.fill((await source.inputValue()).replace('old.json', 'gui.json'));
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  const pending = await source.inputValue();
  await writeFile(metadata.source, agent.replace('old.json', 'agent.json'));
  await page.locator('#editor-save').click();
  await page.locator('#editor-conflict').waitFor({state: 'visible'});
  assert.equal(await source.inputValue(), pending);
  assert.match(await readFile(metadata.source, 'utf8'), /agent.json/);
  await page.locator('#editor-rebase').click();
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  // A second changed base after explicit reconciliation also refuses.
  await writeFile(metadata.source, agent.replace('old.json', 'second-race.json'));
  await page.locator('#editor-save').click();
  await page.locator('#editor-conflict').waitFor({state: 'visible'});
  assert.equal(await source.inputValue(), pending);
  assert.match(await readFile(metadata.source, 'utf8'), /second-race.json/);
  await page.locator('#editor-rebase').click();
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Saved reviewed'));
  assert.equal(inspect().definition.externals[0].location, 'gui.json');
  assert.equal(inspect().definition.nodes.length, 2);
  // Delayed old Review must not override newer source edits or enable Save.
  let release; const blocked = new Promise(resolve => { release = resolve; });
  await page.route('**/api/editor/example/review', async route => { const response = await route.fetch(); await blocked; await route.fulfill({response}); });
  await source.fill((await source.inputValue()) + '# first proposal\n');
  await page.locator('#editor-review').click();
  await source.fill((await source.inputValue()) + '# newer proposal\n');
  release(); await page.waitForTimeout(250);
  assert.match(await source.inputValue(), /newer proposal/);
  assert.equal(await page.locator('#editor-save').isDisabled(), true);
  await page.unroute('**/api/editor/example/review');
  // Hostile text stays text, not HTML, through source and references.
  const hostile = '<img src=x onerror="window.editorHostile=true">';
  await source.fill((await source.inputValue()).replace('missing.json', hostile.replaceAll('"', "'")));
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  assert.equal(await page.evaluate(() => window.editorHostile), undefined);
  assert.equal(await page.locator('#editor-references img').count(), 0);
  // A failed project load cannot leave the previous conflict actionable.
  await writeFile(metadata.source, agent.replace('old.json', 'last-agent.json'));
  await page.locator('#editor-save').click();
  await page.locator('#editor-conflict').waitFor({state: 'visible'});
  await page.route('**/api/editor/other', route => route.fulfill({status: 409, contentType: 'application/json', body: JSON.stringify({error: {code: 'filesystem', message: 'Injected unavailable project'}})}));
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#editor-project').selectOption('other');
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Injected unavailable project'));
  assert.equal(await page.locator('#editor-conflict').isHidden(), true);
  assert.equal(await page.locator('#editor-rebase').isDisabled(), true);
  assert.equal(await source.isDisabled(), true);
  assert.equal(await source.inputValue(), '');
  assert.equal(await page.locator('#editor-path').textContent(), '');
  assert.equal(await page.locator('#editor-revision').textContent(), '');
  assert.equal(await page.locator('#editor-review').isDisabled(), true);
  assert.equal(await page.locator('#editor-save').isDisabled(), true);
  // Reusable declarations use the real canonical authoring path; managed roles
  // have no editable location, while all unsupported preparation choices survive.
  await page.locator('#editor-project').selectOption('reusable');
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'));
  assert.equal(await page.getByLabel('external:initial', {exact: true}).count(), 0);
  assert.equal(await page.getByLabel('external:build_store', {exact: true}).count(), 0);
  assert.equal(await page.getByLabel('external:check_store', {exact: true}).count(), 0);
  assert.match(await page.locator('#editor-references').textContent(), /external:initial.*managed/);
  await page.getByLabel('task.manifest', {exact: true}).fill('edited-task.yaml');
  await page.locator('#editor-review').click();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
  await page.locator('#editor-save').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Saved reviewed'));
  await page.locator('#editor-refresh').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'));
  const reusable = JSON.parse(execFileSync(process.env.EDITOR_PYTHON, ['-c', 'import sys; from pathlib import Path; from workflows.definition import parse_workflow_source; print(parse_workflow_source(Path(sys.argv[1]).read_text()).model_dump_json())', metadata.reusable_source], {cwd: root, encoding: 'utf8'}));
  assert.equal(reusable.definition.schema_version, 2);
  assert.equal(reusable.definition.task.manifest, 'edited-task.yaml');
  assert.equal('workspace' in reusable.definition.task, false);
  assert.deepEqual(reusable.definition.externals.slice(0, 3), [
    {id: 'initial', contract: 'proposal.input', kind: 'managed_candidate'},
    {id: 'build_store', contract: 'storage', kind: 'managed_candidate'},
    {id: 'check_store', contract: 'storage', kind: 'managed_candidate'},
  ]);
  assert.equal(reusable.definition.externals[3].location, 'context.json');
  assert.deepEqual(reusable.preparation_options, {
    proposal_advice: 'Prefer a small interpretable baseline',
    implementation_advice: 'Keep diagnostics explicit', validation_advice: 'Inspect held-out residuals',
    allowed_output_types: ['regressor'],
  });
  assert.deepEqual(reusable.positions, [{node: 'build', x: 120, y: -30}]);
  assert.deepEqual(faults, []);
  console.log('PASS: real API inspector → graph → Python diff → exact disk save/reload; agent refresh; two retained conflicts/reconciliation; stale review fence; inert hostile text; reusable managed roles and preparation options survive real edit/review/save/reload.');
} finally { if (browser) await browser.close(); server.kill('SIGTERM'); lines.close(); }
