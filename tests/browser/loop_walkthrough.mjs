/** "Check the workflow" walk-through (operator UX decision 2026-10-28) on the five-node loop.
 * Fails if the token never travels the wires, if a complete loop is not reported complete
 * after following its feedback wire, if a break stops anywhere but the first unconnected
 * required socket, if that socket gets no soft red halo (or a halo larger than its card),
 * or if prefers-reduced-motion still animates (token or pulse) instead of showing the halo. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {tmpdir} from 'node:os';
import {mkdir} from 'node:fs/promises';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[key], `Set ${key}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-loop-walkthrough');
await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => { errors += chunk; });
const waitUntil = async (predicate, what) => {
  const deadline = Date.now() + 20000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error(`${what} timed out`); await new Promise(next => setTimeout(next, 30)); }
};
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Fixture startup timeout: ${errors}`)), 30000);
    createInterface({input: server.stdout}).once('line', line => { clearTimeout(timer); accept(JSON.parse(line)); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${errors}`)); });
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('#editor-project option[value="interpretation"]').waitFor({state: 'attached'});
  await page.locator('#editor-project').selectOption('interpretation');
  await page.locator('#circuit-node-fit').waitFor();
  const state = () => page.locator('.circuit-viewport').getAttribute('data-walk-state');
  // Count tokens as they appear (the walk removes its token when it ends).
  const watchTokens = () => page.evaluate(() => {
    window.__tokens = 0; window.__positions = new Set(); window.__watch?.disconnect();
    (window.__watch = new MutationObserver(records => { for (const record of records) for (const node of record.addedNodes) if (node.classList?.contains('circuit-walk-token')) {
      window.__tokens++;
      const sample = () => { if (node.isConnected) { window.__positions.add(node.style.left + ',' + node.style.top); requestAnimationFrame(sample); } };
      sample();
    } })).observe(document.getElementById('editor-graph'), {childList: true, subtree: true});
  });
  assert.equal(await page.locator('.circuit-feedback[data-from="fit"][data-to="interpret"]').count(), 1, 'the loop feedback wire is drawn');

  // Complete loop: the token travels every wire, then the feedback wire.
  await watchTokens();
  await page.locator('#circuit-check').click();
  await waitUntil(async () => (await state()) === 'complete', 'complete walk');
  assert.equal(await page.evaluate(() => window.__tokens), 1, 'one token travelled');
  assert.ok(await page.evaluate(() => window.__positions.size) > 10, 'the token moved along the wires');
  assert.match(await page.locator('.circuit-message').textContent(), /loop is complete/i);
  assert.equal(await page.locator('.walk-break').count(), 0);

  // Break: disconnect Implement's required Model plan; the walk stops at that socket.
  await page.locator('#circuit-node-build').click();
  await page.locator('#editor-inspector button[aria-label="Disconnect build.output"]').click();
  await waitUntil(async () => (await page.locator('#editor-pending').textContent()).includes('incomplete'), 'draft inspected');
  await watchTokens();
  await page.locator('#circuit-check').click();
  await waitUntil(async () => (await state()) === 'break', 'break');
  assert.equal(await page.evaluate(() => window.__tokens), 1, 'the token travelled up to the break');
  const broken = page.locator('.walk-break');
  assert.deepEqual(await broken.evaluateAll(items => items.map(item => item.id)), ['circuit-input-build-output'], 'halo on the first break only');
  assert.match(await page.locator('#circuit-walk-note').textContent(), /^Implement can't start: .+ is not connected\.$/);
  const halo = await page.evaluate(() => {
    const socket = document.querySelector('.walk-break .circuit-socket'), card = socket.closest('.circuit-card');
    const style = getComputedStyle(socket), box = socket.getBoundingClientRect(), outline = card.getBoundingClientRect();
    // Largest outer reach of the halo: max spread + blur over all shadow layers.
    const reach = Math.max(...style.boxShadow.split(/,(?![^(]*\))/).map(layer => {
      const lengths = (layer.replace(/(rgba?|color-mix|oklab|color)\([^)]*\)+/g, '').match(/-?[\d.]+px/g) || []).map(parseFloat);
      return (lengths[2] || 0) + (lengths[3] || 0);
    }));
    return {shadow: style.boxShadow, animation: style.animationName, size: box.width + 2 * reach, card: Math.min(outline.width, outline.height)};
  });
  assert.notEqual(halo.shadow, 'none', 'the socket has a halo');
  assert.equal(halo.animation, 'walk-halo', 'it pulses gently');
  assert.ok(halo.size < halo.card, `the halo (${halo.size}px) stays smaller than the card (${halo.card}px)`);
  await page.screenshot({path: join(evidence, 'loop-walkthrough-break.png')});

  // Reduced motion: no token, no pulse, the same halo at once.
  await page.emulateMedia({reducedMotion: 'reduce'});
  await watchTokens();
  await page.locator('#circuit-check').click();
  assert.equal(await state(), 'break', 'the result shows without waiting for an animation');
  assert.equal(await page.evaluate(() => window.__tokens), 0, 'no token moves');
  assert.equal(await page.locator('.walk-break').evaluate(item => getComputedStyle(item.querySelector('.circuit-socket')).animationName), 'none');
  assert.notEqual(await page.locator('.walk-break .circuit-socket').evaluate(item => getComputedStyle(item).boxShadow), 'none', 'halo still shown');
  assert.deepEqual(faults, []);
  console.log('PASS check-the-loop: token travels every wire and the feedback wire; a break stops at build.output with a card-sized-or-smaller soft red halo and anchored sentence; reduced motion shows the halo with no token or pulse.');
} finally {
  await browser?.close();
  server.kill();
}
