/** #1187: oversized graphs retain the 75% floor, explain overflow, and Fit returns
 * to the selected (or first) module. Real editor/source path; no viewing writes.
 * Reverting frameModule fails the selected-module framing assertion. */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {readFile, writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {waitForMetadata} from './fixture_metadata.mjs';
import {showAllConsoleSections} from './console_view_flags.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
server.stderr.resume();
const metadata = await waitForMetadata(server, {timeoutMs: 15000}).catch(error => {
  server.kill('SIGTERM'); throw error;
});
const source = (dx, dy) => execFileSync(process.env.EDITOR_PYTHON, ['-c',
  'import sys; from tests.browser.workflow_editor_server import five_node_source; nodes=("interpret", "hypothesis", "build", "check", "fit"); print(five_node_source(tuple((n, 400+i*float(sys.argv[1]), 300+i*float(sys.argv[2])) for i,n in enumerate(nodes))), end="")',
  String(dx), String(dy)], {cwd: root, encoding: 'utf8'});

async function assertFramed(page, node) {
  const result = await page.locator(`.circuit-card[data-node="${node}"]`).evaluate(card => {
    const viewport = card.closest('.circuit-viewport'), box = card.getBoundingClientRect(), frame = viewport.getBoundingClientRect();
    return {left: box.left - frame.left - viewport.clientLeft, top: box.top - frame.top - viewport.clientTop,
      width: box.width, height: box.height, viewWidth: viewport.clientWidth, viewHeight: viewport.clientHeight};
  });
  assert.ok(result.left >= -1 && result.top >= -1, `${node}: heading and leading edge are visible: ${JSON.stringify(result)}`);
  assert.ok(result.left + Math.min(result.width, result.viewWidth) <= result.viewWidth + 1, `${node}: horizontal framing`);
  assert.ok(result.top + Math.min(result.height, result.viewHeight) <= result.viewHeight + 1, `${node}: vertical framing`);
}

async function checkOverflow(page, posts, dx, dy, viewportSize) {
  await page.setViewportSize(viewportSize);
  const bytes = source(dx, dy);
  await writeFile(metadata.five_node_source, bytes);
  await page.reload();
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#editor-project').selectOption('five_node');
  await page.locator('#circuit-node-fit').waitFor({state: 'attached'});
  await page.locator('#circuit-fit').click();
  assert.equal(await page.locator('.circuit-zoom').textContent(), '75 %');
  const note = page.locator('.circuit-view-note');
  assert.equal(await note.isVisible(), true);
  assert.match(await note.textContent(), /Scroll the canvas to reach them.*75%.*selected or first module/);
  await assertFramed(page, 'interpret');
  // Keyboard activation of an off-screen module is an ordinary selection, with no edit.
  await page.locator('#circuit-node-fit').focus();
  await page.keyboard.press('Enter');
  await page.locator('#circuit-node-fit[aria-pressed="true"]').waitFor({state: 'attached'});
  await page.locator('.circuit-viewport').evaluate(viewport => { viewport.scrollLeft = 0; viewport.scrollTop = 0; });
  posts.length = 0;
  await page.locator('#circuit-fit').click();
  await assertFramed(page, 'fit');
  await page.locator('#circuit-fit').click();
  await assertFramed(page, 'fit');
  // Scroll to each module: every saved card remains reachable at the legibility floor.
  for (const node of ['interpret', 'hypothesis', 'build', 'check', 'fit']) {
    await page.locator(`.circuit-card[data-node="${node}"]`).evaluate(card => {
      const viewport = card.closest('.circuit-viewport');
      viewport.scrollLeft = card.offsetLeft * 0.75; viewport.scrollTop = card.offsetTop * 0.75;
    });
    await assertFramed(page, node);
  }
  assert.deepEqual(posts, [], 'Fit and scrolling send no POST');
  assert.equal(await page.evaluate(() => window.workflowEditor.state.dirty), false);
  assert.equal(await readFile(metadata.five_node_source, 'utf8'), bytes);
  // Expanded content can make even one module taller than the viewport.
  await page.locator('.circuit-card[data-node="fit"]').evaluate(card => { card.style.minHeight = '1800px'; });
  await page.locator('#circuit-fit').click();
  await assertFramed(page, 'fit');
}

let browser;
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  showAllConsoleSections(browser);
  const page = await browser.newPage();
  const faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push(request.url()); });
  await page.goto(metadata.origin + '/editor.html');
  await checkOverflow(page, posts, 0, 900, {width: 1440, height: 900});
  await checkOverflow(page, posts, 1200, 0, {width: 1440, height: 900});
  await checkOverflow(page, posts, 1000, 1600, {width: 800, height: 700});
  assert.deepEqual(faults, []);
  console.log('PASS: tall, wide, offset graphs; desktop/mobile; selected/first framing; view-only');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  await new Promise(done => server.once('exit', done));
}
