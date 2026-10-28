/** Port legibility witness (U4, U5, C1): per-contract colour/shape/name tokens, legend,
 * hover and drag connection preview with a refusal naming both contracts, and the
 * per-node protocol-mapping chip. Real offline families fixture; no providers/data/training.
 * Uses EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE and a fresh
 * CONSOLE_EVIDENCE_DIR for screenshots.
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {showAllConsoleSections} from './console_view_flags.mjs';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const key of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE', 'CONSOLE_EVIDENCE_DIR']) assert.ok(process.env[key], `Set ${key}`);
await mkdir(process.env.CONSOLE_EVIDENCE_DIR, {recursive: false});
// The eight-node families graph (two proposals, implementation and validation branches)
// carries proposal, implementation, validation, storage and optional contracts.
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.changed_task_fixture'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: {...process.env, CONSOLE_TASK_PROFILE: 'families'}});
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
  showAllConsoleSections(browser);
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}}), faults = [];
  page.on('pageerror', error => faults.push(error.message));
  page.setDefaultTimeout(30000);
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token); await page.locator('#access-form button').click();
  await page.locator('#access-status').filter({hasText: 'Connected.'}).waitFor();
  await waitUntil(async () => page.evaluate(() => document.querySelector('#editor-source').value.length > 0 && document.querySelector('#editor-task-choice').options.length === 3));
  await page.locator('#editor-task-choice').selectOption('old');
  assert.equal(await page.locator('.editor-node').count(), 8);
  const original = await readFile(metadata.source, 'utf8');
  const output = name => page.locator(`#circuit-output-${name}`);
  const input = (name, argument) => page.locator(`#circuit-input-${name}-${argument}`);
  const dirty = () => page.evaluate(() => window.workflowEditor.state.dirty);
  const message = () => page.locator('.circuit-message').textContent();
  // Optional inputs are folded; expand every card so all socket kinds render.
  for (const summary of await page.locator('.circuit-optional > summary').all()) await summary.click();

  // U4: one stable token per contract, distinct across contracts, rendered by CSS.
  const ports = await page.evaluate(() => [...document.querySelectorAll('.circuit-port[data-contract]')].map(port => {
    const socket = getComputedStyle(port.querySelector('.circuit-socket'));
    return {id: port.id, contract: port.dataset.contract, shape: port.dataset.contractShape, fill: port.dataset.contractFill,
      required: port.dataset.required, colour: socket.borderTopColor, background: socket.backgroundColor,
      radius: socket.borderTopLeftRadius, transform: socket.transform, name: port.querySelector('.circuit-port-contract').textContent};
  }));
  const byContract = new Map();
  for (const port of ports) {
    const token = JSON.stringify([port.shape, port.colour, port.name]);
    if (byContract.has(port.contract)) assert.equal(byContract.get(port.contract), token, `${port.contract} renders one token everywhere`);
    else byContract.set(port.contract, token);
    assert.notEqual(port.name, port.contract, `${port.id} shows a readable name, not only the id`);
    if (port.shape === 'diamond') assert.notEqual(port.transform, 'none', `${port.id} diamond is rotated`);
    if (port.shape === 'circle') assert.equal(port.radius, '50%', `${port.id} circle is round`);
  }
  assert.ok(byContract.size >= 6, `families graph shows several contracts: ${[...byContract.keys()]}`);
  const tokens = [...byContract.values()].map(value => JSON.parse(value)).map(([shape, colour]) => `${shape}|${colour}`);
  assert.equal(new Set(tokens).size, tokens.length, 'distinct contracts render distinct colour+shape pairs');
  assert.equal(await input('build_left', 'output').locator('.circuit-port-contract').textContent(), 'Model plan');
  // Names come from the server and name the schema only: the producing output and the
  // consuming input show the same name; direction is an arrow on the socket.
  assert.equal(await output('hypothesis').locator('.circuit-port-contract').textContent(), 'Model plan');
  for (const port of ports) assert.doesNotMatch(port.name, /\b(input|output|request|result|in|out)\b/i, `${port.id} name has no direction word`);
  const arrows = await page.evaluate(() => [...document.querySelectorAll('.circuit-port[data-contract]')].map(port => ({
    output: port.hasAttribute('data-output'), direction: port.dataset.contractDirection, label: port.getAttribute('aria-label'),
    first: port.firstElementChild?.classList.contains('circuit-port-direction'),
    last: [...port.querySelectorAll(':scope > .circuit-port-direction')].length === 1})));
  for (const arrow of arrows) {
    assert.equal(arrow.direction, arrow.output ? 'sends' : 'receives');
    assert.match(arrow.label, arrow.output ? /^Sends / : /^Receives /);
    assert.ok(arrow.last, 'one direction arrow per socket');
    if (!arrow.output) assert.ok(arrow.first, 'incoming arrow precedes the input label');
  }
  assert.match(await output('hypothesis').getAttribute('aria-label'), /^Sends Model plan\./);
  // Arrows sit in the port padding: they add no height, so measured layout keeps cards apart.
  const arrowFlow = await page.evaluate(() => [...document.querySelectorAll('.circuit-port > .circuit-port-direction')]
    .every(mark => getComputedStyle(mark).position === 'absolute'));
  assert.ok(arrowFlow, 'direction arrows take no layout space');
  const cardRects = await page.evaluate(() => [...document.querySelectorAll('.circuit-card')].map(card => ({
    node: card.dataset.node, left: card.offsetLeft, top: card.offsetTop, right: card.offsetLeft + card.offsetWidth, bottom: card.offsetTop + card.offsetHeight})));
  for (const [i, a] of cardRects.entries()) for (const b of cardRects.slice(i + 1)) {
    assert.ok(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top, `${a.node} and ${b.node} do not overlap`);
  }
  // Required inputs/outputs are filled; optional inputs are hollow.
  for (const port of ports.filter(value => value.required !== undefined)) {
    assert.equal(port.fill, port.required === 'true' ? 'filled' : 'hollow', port.id);
    if (port.required === 'true') assert.equal(port.background, port.colour, `${port.id} filled socket`);
    else assert.notEqual(port.background, port.colour, `${port.id} hollow socket`);
  }
  assert.ok(ports.some(port => port.required === 'false'), 'an optional input is present');
  // Wires carry the colour of the result they transport.
  const wire = page.locator('path.circuit-wire[data-from="hypothesis"][data-to="build_left"]');
  assert.equal(await wire.evaluate(path => getComputedStyle(path).stroke),
    ports.find(port => port.id === 'circuit-output-hypothesis').colour);

  // Legend lists every contract present in the graph with its swatch and readable name.
  const legend = page.locator('.circuit-contract-legend');
  assert.match(await legend.locator('summary').textContent(), /^Port types \(\d+\)$/);
  await legend.locator('summary').click();
  const legendIds = await legend.locator('li').evaluateAll(items => items.map(item => item.dataset.contract));
  for (const contract of byContract.keys()) assert.ok(legendIds.includes(contract), `legend lists ${contract}`);
  assert.match(await legend.locator('li[data-contract="proposal.output"]').textContent(), /Model plan/);
  assert.equal(await legend.locator('.circuit-contract-legend-direction .circuit-port-direction').count(), 2, 'legend explains both arrows');
  assert.match(await legend.locator('li[data-contract="proposal.output"]').getAttribute('title'), /model specification/, 'server description is the row tooltip');
  assert.ok(await legend.locator('li[data-contract="proposal.output"] .circuit-contract-swatch[data-contract-shape="square"]').count());

  // C1 hover preview: compatible inputs highlight, incompatible ones dim, nothing is selected.
  await page.locator('#circuit-fit').click();
  await output('alternate').hover();
  assert.ok(await input('build_left', 'output').evaluate(element => element.classList.contains('compatible')));
  assert.ok(await input('check_left', 'proposal').evaluate(element => element.classList.contains('compatible')));
  const dimmed = input('check_left', 'implementation');
  assert.ok(await dimmed.evaluate(element => element.classList.contains('incompatible')));
  const dim = await dimmed.evaluate(element => ({
    port: getComputedStyle(element).opacity,
    socket: getComputedStyle(element.querySelector('.circuit-socket')).opacity,
    pill: getComputedStyle(element.querySelector('.circuit-port-contract')).borderTopStyle}));
  assert.ok(Number(dim.socket) < 0.5, 'incompatible input dims its socket');
  assert.equal(dim.pill, 'dashed', 'incompatible input dashes its contract pill');
  assert.equal(dim.port, '1', 'incompatible label text is not faded below 4.5:1 (port stays clickable)');
  assert.match(await dimmed.getAttribute('title'), /expects implementation\.output .*provides proposal\.output/);
  assert.equal(await output('alternate').getAttribute('aria-pressed'), 'false', 'hover does not select');
  await page.mouse.move(2, 2);
  assert.equal(await page.locator('.circuit-port.compatible, .circuit-port.incompatible').count(), 0, 'leaving the output clears the preview');
  assert.equal(await dirty(), false);

  // Refused connection names both contracts.
  await output('check_left').click(); await input('build_left', 'output').click();
  assert.match(await message(), /refused: build_left\.output expects proposal\.output \(Model plan\), but check_left\.result provides validation\.output \(Code verdict\)/);
  assert.equal(await dirty(), false); await page.keyboard.press('Escape');

  // U5: the protocol mapping chip expands to source -> argument field mappings.
  assert.equal(await page.locator('#circuit-adapter-hypothesis').count(), 0, 'external-request nodes have no mapping chip');
  const chip = page.locator('#circuit-adapter-build_left'), fields = page.locator('#circuit-adapter-fields-build_left');
  assert.match(await chip.textContent(), /Mapping: proposal-to-implementation/);
  assert.equal(await chip.getAttribute('aria-expanded'), 'false'); assert.ok(await fields.isHidden());
  await chip.click();
  assert.equal(await chip.getAttribute('aria-expanded'), 'true'); assert.ok(await fields.isVisible());
  const inputs = await page.locator('.circuit-card[data-node="build_left"] [data-input]').count();
  assert.equal(await fields.locator('li').count(), inputs, 'one field row per protocol argument');
  assert.match(await fields.locator('li[data-argument="output"]').textContent(), /hypothesis\.result → output.*proposal\.output/);
  assert.match(await fields.locator('li[data-argument="storage"]').textContent(), /external:\S+ → storage/);
  assert.match(await fields.locator('.circuit-adapter-owner').textContent(), /into implementation\.input.*no extra node/);

  // C1 drag: press an output, drag over a compatible input (highlighted), release to bind.
  await page.locator('#circuit-fit').click();
  // As a user would: bring the canvas (and the drop target) into the window before dragging.
  await page.locator('.circuit-viewport').scrollIntoViewIfNeeded();
  await input('build_left', 'output').scrollIntoViewIfNeeded();
  const from = await output('alternate').boundingBox(), to = await input('build_left', 'output').boundingBox();
  // A drop outside the window hits nothing (elementFromPoint is null): fail clearly instead of timing out.
  const windowSize = await page.evaluate(() => ({width: innerWidth, height: innerHeight}));
  for (const box of [from, to]) assert.ok(box.y + box.height / 2 < windowSize.height && box.x + box.width / 2 < windowSize.width, `drag endpoint on screen: ${JSON.stringify(box)} in ${JSON.stringify(windowSize)}`);
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2); await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, {steps: 6});
  assert.ok(await input('build_left', 'output').evaluate(element => element.classList.contains('compatible')), 'drag highlights the target');
  await page.mouse.up();
  await waitUntil(dirty);
  await waitUntil(async () => /alternate\.result → output/.test(await page.locator('#circuit-adapter-fields-build_left li[data-argument="output"]').textContent()));
  assert.equal(await page.locator('#circuit-adapter-build_left').getAttribute('aria-expanded'), 'true', 'chip stays open across the re-render');
  assert.equal(await readFile(metadata.source, 'utf8'), original, 'previewing and wiring never write the source');

  for (const theme of ['dark', 'light']) {
    await page.locator('#theme-preference').selectOption(theme);
    await page.screenshot({path: resolve(process.env.CONSOLE_EVIDENCE_DIR, `port-legibility-${theme}.png`), fullPage: true});
  }
  assert.deepEqual(faults, []);
  console.log('PASS server-owned schema names, direction arrows, distinct contract tokens, filled/hollow sockets, wire colour, legend, hover preview, named refusal, mapping chip and drag-to-connect; no API/GPU');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  if (errors) process.stderr.write(errors);
}
