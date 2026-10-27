/** Real native offline observation + authenticated HTTP authoring, no providers/data/training.
 * Metadata drift and delayed responses are isolated transport-fence witnesses.
 * Uses existing EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE,
 * and a fresh CONSOLE_EVIDENCE_DIR for screenshots.
 */
import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_EVIDENCE_DIR']) assert.ok(process.env[key], `Set ${key}`);
await mkdir(process.env.CONSOLE_EVIDENCE_DIR, {recursive: false});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.changed_task_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => {errors += chunk;});
const lines = createInterface({input: server.stdout});
const waitUntil = async predicate => {
  const deadline = Date.now() + 30000;
  while (!(await predicate())) {if (Date.now() > deadline) throw new Error('Condition timed out'); await new Promise(resolve => setTimeout(resolve, 50));}
};
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture startup timeout: ' + errors)), 45000);
    lines.once('line', line => {clearTimeout(timer); accept(JSON.parse(line));});
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Fixture exit ${code}: ${errors}`));});
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}}), faults = [], requests = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => {if (request.method() === 'POST') requests.push({path: new URL(request.url()).pathname, body: request.postDataJSON()});});
  await page.goto(metadata.origin + '/#workflow');
  const connect = async token => {await page.locator('#token').fill(token); await page.locator('#access-form button').click();};
  await connect(metadata.token);
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  await waitUntil(async () => page.evaluate(() => document.querySelector('#editor-source').value.length > 0 && document.querySelector('#editor-task-choice').options.length === 3));
  page.setDefaultTimeout(30000);
  await page.locator('#editor-task-choice').selectOption('old');
  const original = await readFile(metadata.source, 'utf8');
  const output = name => page.locator(`#circuit-output-${name}`);
  const input = (name, argument) => page.locator(`#circuit-input-${name}-${argument}`);
  const dirty = () => page.evaluate(() => window.workflowEditor.state.dirty);
  assert.equal(await page.locator('.editor-node').count(), 8);
  const layoutSnapshot = () => page.evaluate(() => ({
    positions: [...document.querySelectorAll('.circuit-card')].map(card => [card.dataset.node, card.style.left, card.style.top]),
    wires: [...document.querySelectorAll('path.circuit-wire')].map(path => path.getAttribute('d'))
  }));
  const dragHeader = page.locator('#circuit-node-hypothesis');
  await dragHeader.scrollIntoViewIfNeeded();
  const initialLayout = await layoutSnapshot();
  let dragRect = await dragHeader.boundingBox();
  await page.mouse.move(dragRect.x + 30, dragRect.y + 15); await page.mouse.down();
  await page.mouse.move(dragRect.x + 32, dragRect.y + 15); await page.mouse.up();
  assert.deepEqual(await layoutSnapshot(), initialLayout, 'A sub-threshold drag restores card and committed wire geometry');
  dragRect = await dragHeader.boundingBox();
  await page.mouse.move(dragRect.x + 30, dragRect.y + 15); await page.mouse.down();
  await page.mouse.move(dragRect.x + 70, dragRect.y + 45); await page.keyboard.press('Escape'); await page.mouse.up();
  assert.deepEqual(await layoutSnapshot(), initialLayout, 'Escape restores an in-progress drag and its wires');
  dragRect = await dragHeader.boundingBox();
  await dragHeader.evaluate(element => element.addEventListener('pointerdown', event => { element.dataset.testPointer = event.pointerId; }, {once: true}));
  await page.mouse.move(dragRect.x + 30, dragRect.y + 15); await page.mouse.down();
  await page.mouse.move(dragRect.x + 70, dragRect.y + 45);
  await dragHeader.dispatchEvent('pointercancel', {pointerId: Number(await dragHeader.getAttribute('data-test-pointer'))}); await page.mouse.up();
  assert.deepEqual(await layoutSnapshot(), initialLayout, 'Pointer cancellation restores card and wires');
  assert.equal(await dirty(), false);
  await output('hypothesis').focus(); await page.keyboard.press('Space');
  assert.ok(await input('build_left', 'output').evaluate(element => element.classList.contains('compatible')));
  await page.keyboard.press('Escape');
  assert.equal(await dirty(), false);
  await output('hypothesis').click(); await output('hypothesis').click({button: 'right'});
  assert.equal(await dirty(), false);
  await output('check_left').click(); await input('build_left', 'output').click();
  assert.match(await page.locator('.circuit-message').textContent(), /refused/);
  assert.equal(await dirty(), false); await page.keyboard.press('Escape');
  await output('alternate').focus(); await page.keyboard.press('Space');
  await input('build_left', 'output').focus(); await page.keyboard.press('Space');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'circuit-input-build_left-output');
  await output('alternate').click(); await input('check_left', 'proposal').click();
  assert.ok(await dirty());
  assert.ok(await page.locator('#editor-task-update').isDisabled());
  await page.locator('#circuit-node-build_left').click();
  assert.equal(await page.locator('#editor-inspector select[data-argument="output"] option:checked').textContent(), 'alternate.result');
  const beforePosition = await page.locator('.circuit-card[data-node="build_left"]').evaluate(element => element._position);
  const beforeLayout = await page.evaluate(() => [...document.querySelectorAll('.circuit-card')].map(card => ({node: card.dataset.node, ...card._position})));
  await page.locator('#circuit-node-build_left').focus(); await page.keyboard.press('Alt+ArrowDown');
  // Pointer deltas below are screen pixels; compare them at 100 % (fit-on-open may have zoomed out).
  await page.locator('#circuit-zoom-reset').click();
  const header = page.locator('#circuit-node-build_left'); await header.scrollIntoViewIfNeeded();
  const rect = await header.boundingBox();
  await header.evaluate(element => element.addEventListener('pointerdown', event => { element.dataset.testPointer = event.pointerId; }, {once: true}));
  await page.mouse.move(rect.x + 30, rect.y + 15); await page.mouse.down();
  const otherPointer = Number(await header.getAttribute('data-test-pointer')) + 1;
  const ownedLayout = await layoutSnapshot(), ownedDirty = await dirty();
  for (const type of ['pointerdown', 'pointermove', 'pointerup', 'pointercancel']) {
    await header.dispatchEvent(type, {pointerId: otherPointer, button: 0, clientX: rect.x + 160, clientY: rect.y + 130});
    assert.deepEqual(await layoutSnapshot(), ownedLayout, `${type} from another pointer cannot move or finish the owner gesture`);
    assert.equal(await dirty(), ownedDirty);
  }
  await page.mouse.move(rect.x + 70, rect.y + 45, {steps: 4}); await page.mouse.up();
  const position = await page.locator('.circuit-card[data-node="build_left"]').evaluate(element => element._position);
  assert.deepEqual(position, {x: beforePosition.x + 40, y: beforePosition.y + 50});
  assert.equal(requests.length, 0, 'Selecting, cancelling, wiring and dragging do not send POSTs');
  assert.equal(await readFile(metadata.source, 'utf8'), original);
  await page.locator('#editor-review').click();
  await page.locator('#editor-task-acknowledge').waitFor();
  await page.locator('#editor-task-acknowledge').check(); await page.locator('#editor-save').click();
  await waitUntil(async () => !(await dirty()) && (await readFile(metadata.source, 'utf8')) !== original);
  const saved = await readFile(metadata.source, 'utf8');
  assert.deepEqual(requests.map(item => item.path.split('/').at(-1)), ['review', 'save']);
  const reviewed = requests[0].body.proposal.document;
  // A move persists every displayed card position, not only the moved card.
  assert.deepEqual(reviewed.positions, beforeLayout.map(item => item.node === 'build_left' ? {node: 'build_left', ...position} : item));
  assert.equal(reviewed.execution_profile, 'native-proposal-families/v1');
  assert.ok(await page.locator('path.circuit-wire[data-from="alternate"][data-to="build_left"]').count());
  const call = promisify(execFile);
  const requestPath = resolve(metadata.source, '../circuit-prepare.json');
  await writeFile(requestPath, JSON.stringify({...metadata.prepare_request, expected_source_sha256: createHash('sha256').update(saved).digest('hex')}));
  const {stdout} = await call(process.env.EDITOR_PYTHON, ['-m', 'tools.candidate_prepare', '--reusable-request', requestPath], {cwd: root, timeout: 90000});
  const prepared = JSON.parse(stdout); assert.equal(prepared.status, 'prepared', prepared.error);
  const snapshot = resolve(prepared.envelope, 'workflow.py.snapshot');
  assert.equal(await readFile(snapshot, 'utf8'), saved);
  for (const owner of ['hypothesis', 'alternate']) {
    const seed = JSON.parse(await readFile(resolve(prepared.envelope, `inputs/proposal.${owner}.json`), 'utf8'));
    assert.equal(seed.task_composition_ref.semantic_fingerprint, metadata.saved_binding.semantic_fingerprint);
  }
  const candidate = JSON.parse(await readFile(prepared.candidate_request_path, 'utf8'));
  const nodes = candidate.preview.document.definition.nodes;
  for (const [node, argument] of [['build_left', 'output'], ['check_left', 'proposal']]) {
    assert.equal(nodes.find(value => value.id === node).request.arguments.find(value => value.name === argument).source.node, 'alternate');
  }
  for (const theme of ['dark', 'light']) {
    await page.locator('#theme-preference').selectOption(theme);
    await page.screenshot({path: resolve(process.env.CONSOLE_EVIDENCE_DIR, `circuit-${theme}.png`), fullPage: true});
  }
  await page.setViewportSize({width: 390, height: 900});
  await page.screenshot({path: resolve(process.env.CONSOLE_EVIDENCE_DIR, 'circuit-narrow.png'), fullPage: true});
  const staleInspector = await page.locator('#editor-inspector select[data-argument="output"]').elementHandle();
  await call(process.env.EDITOR_PYTHON, ['-c', `
from pathlib import Path
import json
from workflows.definition import parse_workflow_source, render_workflow_source, ReusableWorkflowDocument
p = Path(__import__('sys').argv[1])
raw = parse_workflow_source(p.read_text()).model_dump(mode='json')
for node, argument in [('build_left', 'output'), ('check_left', 'proposal')]:
    value = next(item for item in raw['definition']['nodes'] if item['id'] == node)
    next(item for item in value['request']['arguments'] if item['name'] == argument)['source']['node'] = 'hypothesis'
p.write_text(render_workflow_source(ReusableWorkflowDocument.model_validate_json(json.dumps(raw))))
`, metadata.source], {cwd: root});
  await page.locator('#editor-refresh').click();
  await waitUntil(async () => (await page.locator('#editor-source').inputValue()) !== saved);
  assert.ok(await page.locator('path.circuit-wire[data-from="hypothesis"][data-to="build_left"]').count());
  assert.deepEqual(await page.locator('.circuit-card[data-node="build_left"]').evaluate(element => element._position), position);
  const refreshedSource = await page.locator('#editor-source').inputValue(), refreshedLayout = await layoutSnapshot();
  assert.equal(await dirty(), false);
  await staleInspector.evaluate(element => {
    element.value = [...element.options].find(option => option.textContent === 'alternate.result').value;
    element.dispatchEvent(new Event('change', {bubbles: true}));
  });
  assert.equal(await dirty(), false, 'A retained inspector handle cannot edit a replacement graph');
  assert.equal(await page.locator('#editor-source').inputValue(), refreshedSource);
  assert.deepEqual(await layoutSnapshot(), refreshedLayout);
  assert.deepEqual(requests.map(item => item.path.split('/').at(-1)), ['review', 'save']);
  assert.equal(await readFile(snapshot, 'utf8'), saved, 'Code edits never rewrite the previous capture');
  assert.deepEqual(faults, []);
  console.log('PASS real socket branch move, keyboard/cancel/type refusal, pointer and keyboard layout, reviewed save, native family preparation, code roundtrip, themes and narrow view; no API/GPU');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors) process.stderr.write(errors);
}
