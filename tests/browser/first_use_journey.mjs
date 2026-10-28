/** First-use journey witness: the operator's real first use in the default (beginner) view,
 * real Chromium + real authoring API + temporary projects (workflow_editor_server), 1440x1100.
 * Home -> connect in the header banner -> Home "Start from a template" -> gallery, Blank
 * workflow first -> module search focused -> `+` beside the unconnected output adds Implement
 * already wired -> drag + Tidy up (undoable, no overlap) -> Storage folder via "Create
 * external input" -> Save opens the confirmation step (Cancel, then Save version).
 * Then the runnable reusable project: Templates -> Use template -> advice focused -> type
 * advice -> no dead `+` on the fixed template shape -> Tidy up -> Save version -> Next: Run.
 * Also: advanced sections hidden, connection collapses to a header chip, canvas fully
 * visible without page scroll, no POST other than checks before Save.
 * Explicit env: EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir, readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-first-use-journey');
await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => { errors += chunk; });
const lines = createInterface({input: server.stdout});
const waitUntil = async (predicate, what = 'Browser condition') => {
  const deadline = Date.now() + 20000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error(`${what} timed out`); await new Promise(r => setTimeout(r, 50)); }
};
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Server startup timeout: ${errors}`)), 30000);
    lines.on('line', line => {
      try { const value = JSON.parse(line); if (!value.origin || !value.token) return; clearTimeout(timer); lines.close(); accept(value); }
      catch { /* Native plugin registration may write one informational line first. */ }
    });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Server ${code}: ${errors}`)); });
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}}), faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push(new URL(request.url()).pathname); });
  // The fixture's reusable project is the runnable one (as in page_guidance.mjs).
  await page.route('**/api/editor/projects', async route => {
    const response = await route.fetch(), json = await response.json();
    await route.fulfill({response, json: json.map(item => ({...item, candidate_run_enabled: item.project_id === 'reusable'}))});
  });
  const status = () => page.locator('#editor-status').textContent();
  const pending = () => page.locator('#editor-pending').textContent();
  const hidden = selectors => page.evaluate(list => list.map(selector => {
    const element = document.querySelector(selector); return !element || getComputedStyle(element.closest('[data-ui-flag]') || element).display === 'none';
  }), selectors);
  const overlaps = () => page.evaluate(() => {
    const boxes = [...document.querySelectorAll('#editor-graph .circuit-card')].map(card => ({id: card.dataset.node, r: card.getBoundingClientRect()}));
    const found = [];
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i].r, b = boxes[j].r;
      if (a.left < b.right - .5 && b.left < a.right - .5 && a.top < b.bottom - .5 && b.top < a.bottom - .5) found.push(`${boxes[i].id} x ${boxes[j].id}`);
    }
    return found;
  });

  // 1. Home in the beginner view: advanced sections are not shown.
  await page.goto(metadata.origin + '/#home');
  const advanced = ['#editor-advanced', '#editor-history', '#editor-review-disclosure', '#editor-refresh', '#native-chain-heading', '#monitor-form', '#workflow-details'];
  assert.deepEqual(await hidden(advanced), advanced.map(() => true), 'Beginner view hides advanced and developer sections');
  assert.equal(await page.locator('header #access-section #token').isVisible(), true, 'Connect lives in the header banner');

  // 2. Connect: the banner collapses to a header chip.
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  assert.equal(await page.locator('#token').isHidden(), true);
  assert.ok((await page.locator('#access-section').boundingBox()).height <= 40, 'Connected state is one chip');

  const ids = async () => page.locator('#editor-graph .circuit-card').evaluateAll(cards => cards.map(card => card.dataset.node));
  const handleOf = id => page.locator(`.circuit-card[data-node="${id}"] > .circuit-add-next`);
  const saveVersion = async name => {
    await page.locator('#editor-review').click();
    await page.locator('#editor-save-confirm').waitFor();
    await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()), 'checked');
    await page.locator('#editor-version-name').fill(name);
    await page.screenshot({path: join(evidence, `save-step-${name}.png`)});
    await page.locator('#editor-save').click();
    await waitUntil(async () => (await status()).includes(`Saved reviewed bytes as version "${name}"`), `saved ${name}`);
    assert.equal(await page.locator('#editor-save-confirm').isHidden(), true, 'The step closes after Save');
  };

  // 3. Path A, build it yourself (first project, a one-module workflow): Home "Start from a
  //    template" -> Blank workflow (first card) -> module search focused.
  await page.locator('#home-start-template').click();
  const gallery = page.locator('#editor-template-gallery');
  await waitUntil(async () => new URL(page.url()).hash === '#workflow' && await gallery.evaluate(dialog => dialog.open), 'gallery');
  await waitUntil(async () => (await status()).includes('Opened supported'), 'first project');
  await gallery.locator('.template-card[data-template="single-loop-with-advice"]').waitFor();
  assert.equal(await gallery.locator('.template-card').first().getAttribute('data-template'), 'blank', 'Blank workflow is the first card');
  await gallery.locator('.template-card[data-template="blank"]').click();
  await gallery.locator('#editor-template-blank').click();
  await waitUntil(async () => !(await gallery.evaluate(dialog => dialog.open)), 'gallery closed');
  assert.equal(await page.evaluate(() => document.activeElement?.classList.contains('palette-search')), true, 'Blank workflow focuses the module search');
  await page.waitForTimeout(100);
  // The canvas viewport is bounded by the frame: it scrolls inside, the panel never does.
  const bounded = async label => {
    const frame = await page.evaluate(() => {
      const rect = selector => document.querySelector(selector).getBoundingClientRect();
      const viewport = rect('.circuit-viewport'), workspace = rect('.editor-workspace'), panel = rect('.workflow-canvas-panel');
      return {scrollY, top: viewport.top, bottom: viewport.bottom, height: viewport.height, panelBottom: panel.bottom, panelTop: panel.top,
        panelScrollTop: document.querySelector('.workflow-canvas-panel').scrollTop, workspaceHeight: workspace.height, workspaceBottom: workspace.bottom, innerHeight};
    });
    assert.ok(frame.top >= frame.panelTop - .5 && frame.bottom <= frame.panelBottom + .5 && frame.height <= frame.workspaceHeight && frame.panelScrollTop === 0,
      `${label}: viewport inside the canvas panel ${JSON.stringify(frame)}`);
    return frame;
  };
  const frame = await bounded('open');
  assert.equal(frame.scrollY, 0);
  assert.ok(frame.top >= 0 && frame.bottom <= frame.innerHeight && frame.workspaceBottom <= frame.innerHeight + 1 && frame.height >= 400,
    `Canvas visible without page scroll and tall: ${JSON.stringify(frame)}`);
  await page.locator('.circuit-contract-legend > summary').click();
  await bounded('legend open');
  await page.locator('.circuit-contract-legend > summary').click();
  await page.screenshot({path: join(evidence, 'workflow-open-1440.png')});

  // 4. `+` beside the unconnected output adds the next module already wired (one undo step).
  const before = await ids();
  assert.deepEqual(before, ['p'], 'The first project holds one proposal module');
  await page.locator('.circuit-card[data-node="p"]').hover();
  await handleOf('p').click();
  await page.locator('.canvas-add-popover').waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.classList.contains('canvas-add-search')), true, 'Search has focus');
  const options = page.locator('.canvas-add-popover .canvas-add-option');
  assert.ok((await options.evaluateAll(items => items.map(item => item.dataset.protocol))).includes('proposal-to-implementation'), 'Implement accepts a model plan');
  await page.locator('.canvas-add-search').fill('implement');
  await page.locator('.canvas-add-popover .canvas-add-option[data-protocol="proposal-to-implementation"]').click();
  await waitUntil(async () => (await ids()).length === 2, 'module added');
  const added = (await ids()).find(id => !before.includes(id));
  await waitUntil(async () => (await page.locator(`.circuit-wire-target[data-from="p"][data-to="${added}"]`).count()) === 1, 'added module wired to its source');
  assert.match(await page.locator('#editor-undo').getAttribute('title'), /Add capability/, 'Add + wire is one undo step');
  await page.locator('.circuit-card[data-node="p"]').hover();
  assert.equal(await handleOf('p').count(), 0, 'A connected output no longer offers +');

  // 5. Move cards: drag the new card, then Tidy up (one undoable edit); cards never overlap.
  const heading = page.locator(`#circuit-node-${added}`), box = await heading.boundingBox();
  await page.mouse.move(box.x + 30, box.y + 10); await page.mouse.down();
  await page.mouse.move(box.x + 30, box.y + 74, {steps: 4}); await page.mouse.up();
  await waitUntil(async () => /Move capability/.test(await page.locator('#editor-undo').getAttribute('title')), 'drag recorded');
  await page.locator('#circuit-tidy').click();
  await waitUntil(async () => /Tidy up layout/.test(await page.locator('#editor-undo').getAttribute('title')), 'tidy recorded');
  assert.deepEqual(await overlaps(), [], 'Tidy up leaves no overlapping cards');

  // 6. Storage folder through "Create external input" (no location is guessed).
  await heading.click();
  for (let round = 0; round < 6; round++) {
    const form = page.locator('#editor-inspector .external-input-create').first();
    if (!(await form.count())) break;
    const socket = await form.getAttribute('data-socket');
    await form.locator('summary').click();
    const mode = form.locator('select[name="external-mode"]');
    if (await mode.count()) await mode.selectOption('file');
    assert.equal(await form.locator('input[name="external-location"]').inputValue(), '');
    await form.locator('input[name="external-location"]').fill(`inputs/${socket.replace('.', '_')}.json`);
    const id = await form.locator('input[name="external-id"]').inputValue();
    await form.locator('button').click();
    await waitUntil(async () => (await pending()).includes(id), `input ${id} created`);
    await page.waitForTimeout(100);
  }
  await waitUntil(async () => (await pending()).includes('· complete'), 'new module complete');
  assert.deepEqual(posts.filter(path => !/\/(draft|nodes-draft|review|template)$/.test(path)), [], 'Nothing is saved before Save');

  // 7. Save: the check opens the confirmation step; Save version writes the checked bytes.
  await page.locator('#editor-review').click();
  await page.locator('#editor-save-confirm').waitFor();
  await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()), 'checked');
  assert.match(await page.locator('#editor-diff').textContent(), new RegExp(`id='${added}'`), 'The checked bytes add the new module');
  await page.locator('#editor-save-cancel').click();
  assert.equal(await page.locator('#editor-save-confirm').isHidden(), true, 'Cancel closes the step without saving');
  await saveVersion('built-myself');
  assert.match(await readFile(metadata.source, 'utf8'), new RegExp(`id='${added}'`), 'Saved file holds the new module');

  // 8. Path B, start from a template (runnable reusable project): Templates -> Use template ->
  //    advice field focused -> type advice. A template is a complete fixed shape: no output
  //    offers a dead `+` (the server's profile admits no extra module there).
  await page.locator('#editor-project').selectOption('reusable');
  await waitUntil(async () => (await page.locator('#editor-path').textContent()) === metadata.reusable_source, 'reusable project');
  assert.match(await page.locator('#editor-task-chip').textContent(), /^Task: /, 'Task state is one chip');
  await page.locator('#editor-template-open').click();
  await gallery.locator('.template-card[data-template="single-loop-with-advice"]').click();
  assert.equal(await gallery.locator('#editor-template-import').textContent(), 'Use template');
  const sourceBefore = await readFile(metadata.reusable_source);
  await gallery.locator('#editor-template-import').click();
  await waitUntil(async () => !(await gallery.evaluate(dialog => dialog.open)), 'gallery closed');
  await waitUntil(async () => (await status()).includes('Declaration validated'), 'template checked');
  assert.equal(await page.locator('#editor-save-confirm').isHidden(), true, 'A template import does not open the save step');
  assert.ok((await readFile(metadata.reusable_source)).equals(sourceBefore), 'Using a template writes nothing');
  await waitUntil(() => page.evaluate(() => document.activeElement?.classList.contains('advice-input')), 'advice focused');
  const advice = 'Start with small models; earlier runs overfit after a few epochs.';
  await page.keyboard.type(advice);
  assert.equal(await page.locator('#editor-inspector .advice-input').inputValue(), advice);
  for (const id of await ids()) {
    await page.locator(`.circuit-card[data-node="${id}"]`).hover();
    assert.equal(await handleOf(id).count(), 0, `${id}: no + where no module can follow`);
  }
  await page.locator('#circuit-tidy').click();
  await waitUntil(async () => /Tidy up layout/.test(await page.locator('#editor-undo').getAttribute('title')), 'template tidy recorded');
  assert.deepEqual(await overlaps(), [], 'Tidy up leaves the template cards disjoint');
  await page.locator('#circuit-fit').click();
  await bounded('template after fit');
  assert.equal(await page.locator('.circuit-viewport').getAttribute('data-outside-cards'), '0', 'Fit shows every module inside the visible viewport');
  await saveVersion('first-loop');
  assert.ok((await readFile(metadata.reusable_source, 'utf8')).includes(advice), 'Saved file holds the advice');

  // 9. Next: Run.
  const next = page.locator('#workflow-next-run');
  await waitUntil(async () => !(await next.isDisabled()), 'run gate open');
  await next.click(); await page.locator('#view-run').waitFor();
  assert.equal(new URL(page.url()).hash, '#run');
  assert.deepEqual(faults, []);
  console.log(`PASS first-use journey: Blank -> + add wired -> drag/tidy -> storage input -> save step; template -> advice -> tidy -> save -> Run; screenshots in ${evidence}`);
} finally {
  await browser?.close();
  server.kill();
}
