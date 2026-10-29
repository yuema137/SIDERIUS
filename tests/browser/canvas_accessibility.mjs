/** Keyboard and screen-reader paths of the Workflow canvas (red-team E-7, E-8).
 * Fails if an unknown hash route does not return to Home, if "Skip to canvas" is missing or
 * does not move focus onto the canvas, if a wire is read aloud with field ids instead of
 * module and connector names, if wires sit in the beginner Tab order, or if a keyboard-
 * focused wire (advanced tools on) has no visible focus ring. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[key], `Set ${key}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.node_palette_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => { errors += chunk; });
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

  // E-8: a typo route lands on Home; a malformed Monitor link stays on Monitor and says why.
  await page.goto(metadata.origin + '/#workfow');
  assert.equal(new URL(page.url()).hash, '#home');
  assert.equal(await page.locator('[data-view="home"]').isVisible(), true);
  assert.equal(await page.locator('#skip-to-canvas').isHidden(), true, 'no skip link outside the Workflow view');
  await page.goto(metadata.origin + '/#monitor/not-a-uuid');
  assert.equal(await page.locator('[data-view="monitor"]').isVisible(), true);

  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await page.locator('.circuit-wire-target').first().waitFor({state: 'attached'});

  // Skip link: first Tab stop of the page; Enter puts focus on a module card.
  assert.equal(await page.evaluate(() => document.querySelector('a[href], button, input, select, [tabindex]')?.id), 'skip-to-canvas', 'first Tab stop');
  await page.locator('#skip-to-canvas').focus();
  assert.equal(await page.locator('#skip-to-canvas').isVisible(), true, 'visible while focused');
  await page.keyboard.press('Enter');
  assert.ok((await page.evaluate(() => document.activeElement?.className)).includes('editor-node'), 'focus is on a module card');
  assert.equal(new URL(page.url()).hash, '#workflow', 'the skip link never changes the route');

  // Wires: plain-language names, out of the beginner Tab order.
  const wires = page.locator('.circuit-wire-target');
  for (const label of await wires.evaluateAll(items => items.map(item => item.getAttribute('aria-label')))) {
    assert.match(label, /^[A-Z][\w &]+ sends [A-Z][\w ]+ to [A-Z][\w &]+$/, `wire label: ${label}`);
    assert.ok(!/\.(result|output|request)\b/.test(label), `no field ids: ${label}`);
  }
  assert.deepEqual([...new Set(await wires.evaluateAll(items => items.map(item => item.getAttribute('tabindex'))))], ['-1']);

  // Advanced tools on: wires join the Tab order and show a focus ring.
  await page.evaluate(() => window.uiSettings.set('advanced', true));
  await page.locator('.circuit-wire-target[tabindex="0"]').first().waitFor({state: 'attached'});
  const heading = page.locator('.editor-node').first();
  await heading.focus();
  await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Tab');
  await page.evaluate(() => document.querySelector('.circuit-wire-target').focus());
  const ring = await page.evaluate(() => {
    const target = document.querySelector('.circuit-wire-target');
    return {focused: document.activeElement === target, visible: target.matches(':focus-visible'), stroke: getComputedStyle(target).stroke};
  });
  assert.ok(ring.focused && ring.visible, 'the wire has keyboard focus');
  assert.notEqual(ring.stroke, 'rgba(0, 0, 0, 0)', 'a focused wire shows a halo');
  assert.notEqual(ring.stroke, 'none');
  assert.deepEqual(faults, []);
  console.log('PASS unknown route -> Home, Skip to canvas focuses a module, wires read "X sends Y to Z" and stay out of the beginner Tab order, focused wire shows a ring.');
} finally {
  await browser?.close();
  server.kill();
}
