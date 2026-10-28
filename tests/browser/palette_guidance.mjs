/** Browser witness: palette guidance. The rail is a compact stage-ordered stack of
 * capability rows (icon, name, step, Start here / Optional context badge) whose
 * accordion details show the description, output type, connects-from/to and the
 * addable routes with typed socket chips; hover and keyboard focus show the same
 * popover (inputs with origin, output, connects-from/to) and highlight compatible
 * canvas ports; Escape dismisses it; text keeps >= 4.5:1 contrast in light and dark;
 * the narrow drawer still opens. Nothing is posted and the source is never written. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[key], `Set ${key}`);
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.node_palette_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = '', browser;
server.stderr.on('data', chunk => { errors += chunk; });
const lines = createInterface({input: server.stdout});
const waitUntil = async (predicate, what = 'Browser condition') => {
  const deadline = Date.now() + 20000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error(`${what} timed out`); await new Promise(resolve => setTimeout(resolve, 50)); }
};
// Contrast of an element's text against its first opaque ancestor background.
const contrastOf = locator => locator.evaluate(element => {
  const rgba = color => color.match(/[\d.]+/g).map(Number);
  const luminance = color => rgba(color).slice(0, 3).map(value => value / 255)
    .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
  let node = element;
  while (node && (rgba(getComputedStyle(node).backgroundColor)[3] ?? 1) < 1) node = node.parentElement;
  const background = node ? getComputedStyle(node).backgroundColor : 'rgb(255, 255, 255)';
  const a = luminance(getComputedStyle(element).color), b = luminance(background);
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
});
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Fixture startup timeout: ${errors}`)), 30000);
    lines.once('line', line => { clearTimeout(timer); accept(JSON.parse(line)); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${errors}`)); });
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}}), faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push(request.url()); });
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'), 'open');
  const original = await readFile(metadata.source, 'utf8');
  const palette = page.locator('#editor-palette'), popover = page.locator('#palette-popover');
  await waitUntil(async () => (await palette.locator('.palette-row').count()) === 6, 'catalog rows');

  // Compact stack in server stage order, all collapsed, rows touching with no gaps.
  const rows = await palette.locator('.palette-category').evaluateAll(groups => groups.map(group => {
    const box = group.getBoundingClientRect();
    return {capability: group.dataset.capability, open: group.open, top: box.top, bottom: box.bottom, left: box.left, width: box.width,
      icon: !!group.querySelector('summary svg'), badge: group.querySelector('.palette-badge')?.textContent || ''};
  }));
  assert.deepEqual(rows.map(row => row.capability), ['interpretation', 'literature', 'proposal', 'implementation', 'validation', 'tuning']);
  assert.ok(rows.every(row => !row.open && row.icon), 'collapsed rows with icons');
  for (let i = 1; i < rows.length; i++) {
    assert.ok(Math.abs(rows[i].top - rows[i - 1].bottom) <= 1.5, `row ${rows[i].capability} touches the previous row`);
    assert.ok(Math.abs(rows[i].left - rows[0].left) < .5 && Math.abs(rows[i].width - rows[0].width) < .5, 'aligned rows');
  }
  assert.ok(rows.every(row => row.bottom - row.top < 48), `compact rows ${JSON.stringify(rows.map(row => row.bottom - row.top))}`);
  assert.equal(rows.find(row => row.capability === 'proposal').badge, 'Start here');
  assert.equal(rows.find(row => row.capability === 'interpretation').badge, 'Optional context');
  assert.equal(rows.find(row => row.capability === 'literature').badge, 'Optional context');
  const guide = await palette.locator('.palette-guide').textContent();
  assert.match(guide, /Start with PROPOSE, then add IMPLEMENT → VALIDATE → TRAIN & TUNE\./);
  assert.match(guide, /INTERPRET, LITERATURE add optional context/);

  // Accordion details: description, output type, connections and typed routes.
  const validation = palette.locator('.palette-category[data-capability="validation"]');
  await validation.locator('summary').click();
  await waitUntil(async () => validation.evaluate(group => group.open), 'expand validation');
  assert.match(await validation.locator('.palette-details-description').textContent(), /\S/);
  const sends = validation.locator('.palette-details-output .palette-chip');
  assert.equal(await sends.getAttribute('data-contract'), 'validation.output');
  assert.equal(await sends.getAttribute('data-direction'), 'sends');
  assert.match(await sends.textContent(), /→$/, 'sent type reads "<name> →"');
  assert.equal(await validation.locator('.palette-details-from').textContent(), 'Connects from: PROPOSE, IMPLEMENT');
  assert.equal(await validation.locator('.palette-details-to').textContent(), 'Connects to: TRAIN & TUNE');
  const route = validation.locator('.palette-entry[data-protocol="implementation-to-validation"]');
  assert.deepEqual(await route.locator('.palette-chip[data-contract]').evaluateAll(chips => chips.map(chip => chip.dataset.contract)),
    ['implementation.output', 'storage', 'validation.output']);
  // Direction is an arrow plus receives/sends accessible text, never encoded in the name.
  const directions = await route.locator('.palette-chip[data-contract]').evaluateAll(chips => chips.map(chip => [chip.dataset.direction, chip.textContent.trim(), chip.getAttribute('aria-label')]));
  assert.deepEqual(directions.map(([direction]) => direction), ['receives', 'receives', 'sends']);
  assert.ok(directions.slice(0, 2).every(([, text, label]) => text.startsWith('→') && label.startsWith('receives ')), JSON.stringify(directions));
  assert.ok(directions[2][1].endsWith('→') && directions[2][2].startsWith('sends '), JSON.stringify(directions));
  assert.match(await route.locator('.palette-chip-more').textContent(), /\+3 optional/);
  for (const chip of await route.locator('.palette-chip[data-contract] .circuit-contract-swatch').all()) {
    assert.ok(await chip.getAttribute('data-contract-shape'), 'chip carries the contract shape token');
  }

  // Hover: popover content plus compatible canvas ports, presentation only.
  await route.hover();
  await popover.waitFor({state: 'visible'});
  const text = await popover.textContent();
  assert.match(text, /Receives/); assert.match(text, /Sends/);
  assert.match(await popover.locator('li[data-argument="output"]').textContent(), /required · from IMPLEMENT/);
  assert.match(await popover.locator('li[data-argument="storage"]').textContent(), /required · external input/);
  assert.match(await popover.locator('li[data-argument="llm_provider"]').textContent(), /optional/);
  assert.equal(await popover.locator('.palette-popover-from').textContent(), 'Connects from: PROPOSE, IMPLEMENT');
  assert.equal(await popover.locator('.palette-popover-to').textContent(), 'Connects to: TRAIN & TUNE');
  assert.equal(await route.getAttribute('aria-describedby'), 'palette-popover');
  const lit = () => page.locator('.circuit-port.palette-compatible').evaluateAll(ports => ports.map(port => port.id).sort());
  assert.deepEqual(await lit(), ['circuit-output-implement']);
  const routeBox = await route.boundingBox(), popBox = await popover.boundingBox();
  assert.ok(popBox.x >= routeBox.x + routeBox.width || popBox.y >= routeBox.y + routeBox.height, 'popover does not cover its entry');
  await page.mouse.move(1400, 1050);
  await popover.waitFor({state: 'hidden'});
  assert.deepEqual(await lit(), []);

  // Keyboard: open the tuning row with Enter, Tab to a route, same popover; Escape hides.
  const tuning = palette.locator('.palette-category[data-capability="tuning"]');
  await tuning.locator('summary').focus();
  await page.keyboard.press('Enter');
  await waitUntil(async () => tuning.evaluate(group => group.open), 'expand tuning by keyboard');
  const tuningRoute = tuning.locator('.palette-entry[data-protocol="validated-candidate-to-tuning"]');
  await page.keyboard.press('Tab');
  await waitUntil(async () => tuningRoute.evaluate(element => element === document.activeElement), 'tab to tuning route');
  await popover.waitFor({state: 'visible'});
  assert.match(await popover.locator('li[data-argument="validation"]').textContent(), /from VALIDATE/);
  assert.match(await popover.locator('li[data-argument="proposal"]').textContent(), /from PROPOSE/);
  assert.equal(await popover.locator('.palette-popover-to').textContent(), 'Connects to: no other capability (final step)');
  assert.deepEqual(await lit(), ['circuit-output-propose', 'circuit-output-validate']);
  assert.equal(await tuningRoute.evaluate(element => element.matches(':focus-visible')), true);
  await page.keyboard.press('Escape');
  await popover.waitFor({state: 'hidden'});
  assert.deepEqual(await lit(), []);

  // Contrast of every guidance text role in both themes.
  const theme = page.getByRole('combobox', {name: 'Color theme', exact: true});
  for (const mode of ['light', 'dark']) {
    await theme.selectOption(mode);
    await waitUntil(async () => (await page.locator('html').getAttribute('data-theme')) === mode, `theme ${mode}`);
    const targets = [
      palette.locator('.palette-guide'), validation.locator('summary .capability-name'), validation.locator('.palette-step'),
      palette.locator('.palette-category[data-capability="proposal"] .palette-badge'), validation.locator('.palette-details-description'),
      validation.locator('.palette-details-from'), route.locator('.palette-entry-route'), route.locator('.palette-chip').first(),
    ];
    for (const target of targets) {
      const ratio = await contrastOf(target);
      assert.ok(ratio >= 4.5, `${mode}: ${await target.evaluate(element => element.className)} contrast ${ratio}`);
    }
    await route.hover(); await popover.waitFor({state: 'visible'});
    for (const target of [popover.locator('.palette-popover-description'), popover.locator('li[data-argument="storage"]'), popover.locator('.palette-popover-hint')]) {
      const ratio = await contrastOf(target);
      assert.ok(ratio >= 4.5, `${mode}: popover ${await target.evaluate(element => element.className || element.tagName)} contrast ${ratio}`);
    }
    await page.mouse.move(1400, 1050); await popover.waitFor({state: 'hidden'});
  }

  // Narrow width: the drawer toggle still opens the same stack.
  await page.setViewportSize({width: 760, height: 1000});
  const toggle = palette.locator('.palette-toggle');
  await toggle.click();
  assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
  await palette.locator('.palette-category[data-capability="proposal"] summary').waitFor({state: 'visible'});

  assert.deepEqual(posts, [], 'guidance sends no POST');
  assert.equal(await readFile(metadata.source, 'utf8'), original);
  assert.deepEqual(faults, []);
  console.log('PASS palette stage-ordered compact stack, start guide, accordion details with typed routes, hover and keyboard popover, compatible-port highlight, Escape, light/dark contrast, narrow drawer, no writes.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors) process.stderr.write(errors);
}
