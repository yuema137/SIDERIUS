/** Paper capability names and non-overlapping card layout on the five-node authored loop.
 * Fails if the interpreter renders the generic CAPABILITY card, if any two cards overlap
 * (light or dark), if a pointer or Alt+Arrow move persists only the moved node, or if a
 * save without a move rewrites stored positions.
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
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-capability-layout');
await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = ''; server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
const metadata = await new Promise((accept, reject) => {
  lines.once('line', line => accept(JSON.parse(line)));
  server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`)));
  setTimeout(() => reject(new Error(`server startup timeout: ${serverErrors}`)), 15000);
});
const parsed = path => JSON.parse(execFileSync(process.env.EDITOR_PYTHON,
  ['-c', 'import sys; from pathlib import Path; from workflows.definition import parse_workflow_source; print(parse_workflow_source(Path(sys.argv[1]).read_text()).model_dump_json())', path],
  {cwd: root, encoding: 'utf8'}));
const byNode = positions => Object.fromEntries(positions.map(({node, x, y}) => [node, {x, y}]));
let browser;
async function waitUntil(predicate) {
  const deadline = Date.now() + 15000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error('Browser condition timed out'); await new Promise(next => setTimeout(next, 50)); }
}
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push({path: new URL(request.url()).pathname, body: request.postDataJSON()}); });
  await page.goto(metadata.origin + '/editor.html');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  const status = () => page.locator('#editor-status').textContent();
  await waitUntil(async () => (await status()).includes('Opened supported'));
  const open = async project => {
    await page.locator('#editor-project').selectOption(project);
    await waitUntil(async () => (await page.locator('.circuit-card').count()) === 5 && (await status()).includes('Opened supported'));
  };
  const boxes = () => page.evaluate(() => [...document.querySelectorAll('.circuit-card')].map(card => {
    const box = card.getBoundingClientRect();
    return {node: card.dataset.node, left: box.left, right: box.right, top: box.top, bottom: box.bottom};
  }));
  const assertDisjoint = async label => {
    const values = await boxes();
    assert.equal(values.length, 5, label);
    for (let i = 0; i < values.length; i++) for (let j = i + 1; j < values.length; j++) {
      const a = values[i], b = values[j];
      assert.ok(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top,
        `${label}: ${a.node} ${JSON.stringify(a)} overlaps ${b.node} ${JSON.stringify(b)}`);
    }
  };
  const displayed = () => page.evaluate(() => Object.fromEntries([...document.querySelectorAll('.circuit-card')].map(card => [card.dataset.node, {...card._position}])));
  const reviewAndSave = async () => {
    posts.length = 0;
    await page.locator('#editor-review').click();
    await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
    await page.locator('#editor-save').click();
    await waitUntil(async () => (await status()).includes('Saved reviewed'));
    assert.deepEqual(posts.map(item => item.path.split('/').at(-1)), ['review', 'save']);
    return posts[0].body.proposal.document;
  };

  // Labels and complete saved layout, light and dark.
  await open('five_node');
  const theme = page.getByRole('combobox', {name: 'Color theme', exact: true});
  for (const mode of ['light', 'dark']) {
    await theme.selectOption(mode);
    assert.equal(await page.locator('html').getAttribute('data-theme'), mode);
    assert.equal(await page.locator('#circuit-node-interpret .capability-name').textContent(), 'INTERPRET');
    assert.deepEqual(await page.locator('.circuit-card .capability-name').allTextContents(),
      ['INTERPRET', 'PROPOSE', 'IMPLEMENT', 'VALIDATE', 'TRAIN & TUNE']);
    assert.equal(await page.locator('.capability-generic').count(), 0, `${mode}: generic CAPABILITY card rendered`);
    const accent = await page.locator('.circuit-card[data-node="interpret"]').evaluate(card => {
      const style = getComputedStyle(card);
      return [style.getPropertyValue('--capability-accent').trim(), style.getPropertyValue('--capability-generic').trim()];
    });
    assert.ok(accent[0] && accent[0] !== accent[1], `${mode}: interpretation uses its own theme accent`);
    await assertDisjoint(`${mode} saved five-node layout`);
    await page.screenshot({path: join(evidence, `five-node-${mode}.png`), fullPage: true});
  }

  // A non-position edit saves without rewriting stored positions.
  const before = parsed(metadata.five_node_source);
  await page.locator('#editor-advanced > summary').click();
  await page.getByText('References', {exact: true}).click();
  await page.getByLabel('task.manifest', {exact: true}).fill('edited-task.yaml');
  await reviewAndSave();
  const edited = parsed(metadata.five_node_source);
  assert.equal(edited.definition.task.manifest, 'edited-task.yaml');
  assert.deepEqual(edited.positions, before.positions, 'A save without a move keeps stored positions exact');

  // Partial stored positions: fallback cards never cover stored ones, and each move
  // gesture persists every displayed position.
  const partial = await readFile(metadata.five_node_partial_source, 'utf8');
  for (const gesture of ['keyboard', 'pointer']) {
    await writeFile(metadata.five_node_partial_source, partial);
    await open('five_node');
    await open('five_node_partial');
    assert.deepEqual(Object.keys(byNode(parsed(metadata.five_node_partial_source).positions)).sort(), ['build', 'fit']);
    await assertDisjoint(`${gesture}: partial stored layout`);
    const shown = await displayed();
    let moved;
    if (gesture === 'keyboard') {
      await page.locator('#circuit-node-hypothesis').focus();
      await page.keyboard.press('Alt+ArrowDown');
      moved = {...shown, hypothesis: {x: shown.hypothesis.x, y: shown.hypothesis.y + 20}};
    } else {
      // Screen-pixel drag deltas equal document deltas at 100 % (fit-on-open may have zoomed out).
      await page.locator('#circuit-zoom-reset').click();
      const heading = page.locator('#circuit-node-interpret');
      await heading.scrollIntoViewIfNeeded();
      const box = await heading.boundingBox();
      await page.mouse.move(box.x + 30, box.y + 15); await page.mouse.down();
      await page.mouse.move(box.x + 70, box.y + 75, {steps: 4}); await page.mouse.up();
      moved = {...shown, interpret: {x: shown.interpret.x + 40, y: shown.interpret.y + 60}};
    }
    const reviewed = await reviewAndSave();
    assert.deepEqual(byNode(reviewed.positions), moved, `${gesture}: every displayed position is persisted`);
    assert.deepEqual(byNode(parsed(metadata.five_node_partial_source).positions), moved);
    await page.locator('#editor-refresh').click();
    await waitUntil(async () => (await status()).includes('Opened supported'));
    assert.deepEqual(await displayed(), moved, `${gesture}: reopened layout is the saved layout`);
    await assertDisjoint(`${gesture}: reopened layout`);
    await page.screenshot({path: join(evidence, `partial-${gesture}.png`), fullPage: true});
  }
  assert.deepEqual(faults, []);
  console.log(JSON.stringify({result: 'PASS', evidence}));
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  await new Promise(resolveExit => server.once('exit', resolveExit));
}
