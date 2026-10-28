/** Workflow canvas fit, folded optional inputs, interpretation layout and task-panel state
 * at 1440x900 (UX walkthrough 2026-10-27: 2 of 5 cards off-screen, PROPOSE cut off,
 * overlapping interpretation cards, an empty "Task package and version" box).
 * Fails if: any of the five cards lies outside the canvas or the window after open;
 * Fit, zoom or Arrange view sends a POST, dirties the editor or changes saved bytes;
 * an optional unbound input is drawn as its own card row instead of inside the
 * "N optional inputs" summary, the summary cannot expand, or its state is lost when a
 * selection re-renders the canvas; the interpretation fixture renders overlapping cards
 * or an unrouted wire; an overlapping saved layout offers no display-only way out; a
 * zoomed pointer drag records screen pixels instead of document pixels; or the task
 * panel shows no state text (before connect, light and dark).
 * Env: EDITOR_PYTHON (this checkout .venv/bin/python), CONSOLE_PLAYWRIGHT_MODULE,
 * CONSOLE_BROWSER_EXECUTABLE; optional CONSOLE_EVIDENCE_DIR for screenshots.
 */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-editor-canvas-fit');
await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = ''; server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
const metadata = await new Promise((accept, reject) => {
  lines.once('line', line => accept(JSON.parse(line)));
  server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`)));
  setTimeout(() => reject(new Error(`server startup timeout: ${serverErrors}`)), 15000);
});
// An overlapping saved layout (hypothesis drawn over interpret), rendered by the fixture's own source writer.
const overlapping = execFileSync(process.env.EDITOR_PYTHON, ['-c',
  'from tests.browser.workflow_editor_server import five_node_source; print(five_node_source((("interpret", 0.0, 0.0), ("hypothesis", 100.0, 40.0), ("build", 640.0, 0.0), ("check", 960.0, 0.0), ("fit", 1280.0, 0.0))), end="")'],
{cwd: root, encoding: 'utf8'});
const parsed = path => JSON.parse(execFileSync(process.env.EDITOR_PYTHON,
  ['-c', 'import sys; from pathlib import Path; from workflows.definition import parse_workflow_source; print(parse_workflow_source(Path(sys.argv[1]).read_text()).model_dump_json())', path],
  {cwd: root, encoding: 'utf8'}));
const byNode = positions => Object.fromEntries(positions.map(({node, x, y}) => [node, {x, y}]));
let browser;
async function waitUntil(predicate, label = 'Browser condition') {
  const deadline = Date.now() + 15000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error(`${label} timed out`); await new Promise(next => setTimeout(next, 50)); }
}
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1440, height: 900}});
  const faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push(new URL(request.url()).pathname); });
  await page.goto(metadata.origin + '/editor.html');

  // Task panel before connecting: an explicit state, never an empty box.
  await page.locator('#editor-task-state').waitFor();
  assert.match(await page.locator('#editor-task-state').textContent(), /Connect/);

  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  const status = () => page.locator('#editor-status').textContent();
  await waitUntil(async () => (await status()).includes('Opened supported'), 'first project');
  const open = async project => {
    await page.locator('#editor-project').selectOption(project);
    await waitUntil(async () => (await page.locator('.circuit-card').count()) === 5 && (await status()).includes('Opened supported'), `open ${project}`);
  };
  const dirty = () => page.evaluate(() => window.workflowEditor.state.dirty);
  const scale = () => page.evaluate(() => {
    const match = /scale\(([\d.]+)\)/.exec(document.querySelector('.circuit-world').style.transform);
    return match ? Number(match[1]) : 1;
  });
  // Every card fully inside the canvas client area, and the canvas inside the window.
  const assertAllInView = async label => {
    await page.locator('.circuit-viewport').evaluate(element => element.scrollIntoView({block: 'start'}));
    const result = await page.evaluate(() => {
      const viewport = document.querySelector('.circuit-viewport'), frame = viewport.getBoundingClientRect();
      const inner = {left: frame.left + viewport.clientLeft, top: frame.top + viewport.clientTop};
      inner.right = inner.left + viewport.clientWidth; inner.bottom = inner.top + viewport.clientHeight;
      return {inner, window: {width: innerWidth, height: innerHeight}, outside: viewport.dataset.outsideCards,
        cards: [...document.querySelectorAll('.circuit-card')].map(card => {
          const box = card.getBoundingClientRect();
          return {node: card.dataset.node, left: box.left, right: box.right, top: box.top, bottom: box.bottom};
        })};
    });
    assert.equal(result.cards.length, 5, label);
    for (const card of result.cards) {
      assert.ok(card.left >= result.inner.left - 1 && card.right <= result.inner.right + 1 && card.top >= result.inner.top - 1 && card.bottom <= result.inner.bottom + 1,
        `${label}: ${card.node} ${JSON.stringify(card)} is outside the canvas ${JSON.stringify(result.inner)}`);
      assert.ok(card.left >= 0 && card.right <= result.window.width && card.top >= 0 && card.bottom <= result.window.height,
        `${label}: ${card.node} is outside the ${result.window.width}x${result.window.height} window`);
    }
    assert.equal(result.outside, '0', `${label}: the canvas reports cards outside the view`);
    assert.match(await page.locator('.circuit-view-note').textContent(), /All 5 capabilities are in view/);
  };
  const assertDisjoint = async label => {
    const values = await page.evaluate(() => [...document.querySelectorAll('.circuit-card')].map(card => {
      const box = card.getBoundingClientRect();
      return {node: card.dataset.node, left: box.left, right: box.right, top: box.top, bottom: box.bottom};
    }));
    for (let i = 0; i < values.length; i++) for (let j = i + 1; j < values.length; j++) {
      const a = values[i], b = values[j];
      assert.ok(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top, `${label}: ${a.node} overlaps ${b.node}`);
    }
  };
  // Every result-sourced binding in the connection list has a drawn wire.
  const assertWired = async label => {
    const resultEdges = (await page.locator('#editor-edges li').allTextContents()).filter(text => /^\w+\.result → /.test(text));
    assert.ok(resultEdges.length > 0, label);
    assert.equal(await page.locator('path.circuit-wire').count(), resultEdges.length, `${label}: every result binding is routed`);
    assert.doesNotMatch(await page.locator('.circuit-message').textContent(), /could not be routed|overlap/, label);
  };

  // 1. Five-node: fit on open shows every card at 1440x900 and changes nothing saved.
  const fiveBytes = await readFile(metadata.five_node_source, 'utf8');
  await open('five_node');
  posts.length = 0;
  await waitUntil(async () => (await page.locator('.circuit-viewport').getAttribute('data-outside-cards')) === '0', 'fit on open');
  assert.ok(await scale() < 1, 'The five-node row is wider than the canvas, so it opens zoomed out');
  await assertAllInView('five_node after fit on open');
  await page.screenshot({path: join(evidence, 'five-node-fit-1440x900.png')});
  await page.locator('#circuit-zoom-reset').click();
  assert.equal(await page.locator('.circuit-zoom').textContent(), '100 %');
  assert.match(await page.locator('.circuit-view-note').textContent(), /outside the view/, 'At 100 % the visible cue names the hidden cards');
  await page.locator('#circuit-zoom-out').click();
  await page.locator('#circuit-fit').click();
  await assertAllInView('five_node after Fit to view');
  assert.deepEqual(posts, [], 'Viewing sends no request');
  assert.equal(await dirty(), false, 'Viewing is not an edit');
  assert.equal(await readFile(metadata.five_node_source, 'utf8'), fiveBytes, 'Viewing never changes saved bytes');

  // 2. Optional unbound inputs fold into one expandable summary row per card.
  const card = page.locator('.circuit-card[data-node="hypothesis"]');
  const summary = card.locator('.circuit-optional > summary');
  assert.equal(await summary.count(), 1);
  const count = Number(/^(\d+) optional inputs?$/.exec(await summary.textContent())?.[1]);
  assert.ok(count >= 1, 'The summary states how many optional inputs are folded');
  const folded = card.locator('.circuit-optional [data-input]');
  assert.equal(await folded.count(), count);
  for (const port of await folded.all()) {
    assert.equal(await port.getAttribute('data-required'), 'false');
    assert.ok(await port.evaluate(element => element.classList.contains('is-unbound')));
    assert.equal(await port.isVisible(), false, 'Folded inputs take no row until expanded');
  }
  assert.equal(await card.locator(':scope > [data-input].is-unbound[data-required="false"]').count(), 0, 'No optional unbound input is drawn as its own row');
  assert.ok(await card.locator(':scope > [data-input]').count() >= 1, 'Required and bound inputs stay visible');
  const collapsedHeight = await card.evaluate(element => element.offsetHeight);
  await summary.click();
  assert.equal(await folded.first().isVisible(), true, 'The summary expands');
  assert.ok(await card.evaluate(element => element.offsetHeight) > collapsedHeight);
  await page.locator('#circuit-node-interpret').click();
  assert.equal(await page.locator('.circuit-card[data-node="hypothesis"] .circuit-optional').evaluate(element => element.open), true,
    'A selection re-render keeps the expanded state');
  await page.locator('.circuit-card[data-node="hypothesis"] .circuit-optional > summary').click();
  assert.equal(await dirty(), false);
  assert.deepEqual(posts, []);

  // 3. Task panel: explicit state text and either version controls or an explanation, light and dark.
  const theme = page.getByRole('combobox', {name: 'Color theme', exact: true});
  for (const mode of ['light', 'dark']) {
    await theme.selectOption(mode);
    const panel = page.locator('#editor-task-controls');
    assert.match(await page.locator('#editor-task-state').textContent(), /This workflow (uses task package|is not bound)/, `${mode}: saved task state`);
    assert.equal(await page.locator('#editor-task-state').isVisible(), true);
    if (await page.locator('#editor-task-choice').count()) {
      assert.equal(await page.locator('#editor-task-choice').isVisible(), true);
      assert.equal(await page.locator('#editor-task-update').isVisible(), true);
    } else {
      const why = page.locator('#editor-task-unavailable');
      assert.equal(await why.isVisible(), true, `${mode}: explains why no version can be chosen`);
      assert.match(await why.textContent(), /No task versions are configured/);
      assert.match(await why.locator('a').getAttribute('href'), /bind-a-task-version/);
    }
    assert.equal(await page.locator('#editor-task-refresh').isVisible(), true);
    assert.ok((await panel.boundingBox()).height > 60, `${mode}: panel is not an empty box`);
    await page.locator('.workflow-task-details').screenshot({path: join(evidence, `task-panel-${mode}.png`)});
  }
  await theme.selectOption('light');

  // 4. Interpretation fixture: complete disjoint saved layout, every wire routed, all in view.
  const interpretationBytes = await readFile(metadata.interpretation_source, 'utf8');
  await open('interpretation');
  await waitUntil(async () => (await page.locator('.circuit-viewport').getAttribute('data-outside-cards')) === '0', 'interpretation fit');
  await assertDisjoint('interpretation saved layout');
  await assertWired('interpretation saved layout');
  await assertAllInView('interpretation after fit on open');
  await page.screenshot({path: join(evidence, 'interpretation-fit-1440x900.png')});
  assert.equal(await readFile(metadata.interpretation_source, 'utf8'), interpretationBytes);

  // 5. An overlapping saved layout: the canvas says so and Arrange view is a display-only way out.
  await writeFile(metadata.five_node_partial_source, overlapping);
  const overlapBytes = await readFile(metadata.five_node_partial_source, 'utf8');
  const saved = byNode(parsed(metadata.five_node_partial_source).positions);
  await open('five_node_partial');
  assert.match(await page.locator('.circuit-message').textContent(), /overlap.*Arrange view/);
  posts.length = 0;
  const arrange = page.locator('#circuit-arrange');
  await arrange.click();
  assert.equal(await arrange.getAttribute('aria-pressed'), 'true');
  await assertDisjoint('arranged view');
  await assertWired('arranged view');
  assert.match(await page.locator('.circuit-view-note').textContent(), /display only/);
  await page.locator('#circuit-arrange').click();
  assert.equal(await page.locator('#circuit-arrange').getAttribute('aria-pressed'), 'false');
  const shown = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('.circuit-card')].map(element => [element.dataset.node, {...element._position}])));
  assert.deepEqual(shown, saved, 'Leaving Arrange view shows the saved positions again');
  assert.deepEqual(posts, []);
  assert.equal(await dirty(), false);
  assert.equal(await readFile(metadata.five_node_partial_source, 'utf8'), overlapBytes, 'Arrange view never changes saved bytes');

  // 6. A zoomed pointer drag records document pixels (screen delta / zoom).
  await page.locator('#circuit-fit').click();
  const zoom = await scale();
  assert.ok(zoom < 1, 'Fit zooms out for the drag check');
  const heading = page.locator('#circuit-node-build');
  const before = await page.locator('.circuit-card[data-node="build"]').evaluate(element => ({...element._position}));
  const box = await heading.boundingBox();
  await page.mouse.move(box.x + 20, box.y + 10); await page.mouse.down();
  await page.mouse.move(box.x + 80, box.y + 50, {steps: 4}); await page.mouse.up();
  const after = await page.locator('.circuit-card[data-node="build"]').evaluate(element => ({...element._position}));
  assert.deepEqual(after, {x: Math.round(before.x + 60 / zoom), y: Math.round(before.y + 40 / zoom)});
  assert.equal(await dirty(), true, 'A drag is an ordinary local edit');
  assert.equal(await readFile(metadata.five_node_partial_source, 'utf8'), overlapBytes, 'A local move is not saved without Review/Save');
  assert.deepEqual(faults, []);
  console.log(JSON.stringify({result: 'PASS', evidence}));
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  await new Promise(resolveExit => server.once('exit', resolveExit));
}
