/** Template gallery preview legibility: "Start from a template" -> every template with a preview.
 * Regression for the operator reports that the large preview was too small to read, cropped
 * (skipping-edge arcs cut at the top, the right-most node and "Use template" cut at the right),
 * that the dashed feedback line ran through its own "feedback · up to N iteration" label, and
 * that a one-row strip looked unbalanced in the dialog. At 1920, 1280 (default) and 900 px
 * viewports, light and dark, for each template:
 * - the dialog and the preview frame never overflow horizontally (no scrolling), and the
 *   preview and "Use template" lie inside the dialog;
 * - the rendered preview has a balanced aspect, 2:1 to 2.6:1 (width:height);
 * - every node rect, edge, the loop path and its label lie inside the svg viewBox;
 * - no edge passes through a card other than its own two, and no sampled point of any edge or
 *   of the dashed loop path falls inside the loop label's box;
 * - node labels and the loop label render at >= 15 CSS px from 1280 px up and >= 13 at 900.
 * Screenshots: $TMPDIR (else the OS temp dir)/template-preview-<template>-<width>-<theme>.png. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {join, resolve, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) {
  assert.ok(process.env[name], `Set ${name}`);
}
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-template-preview-legibility');
await mkdir(evidence, {recursive: true});
const shots = process.env.TMPDIR || tmpdir();
const templates = [
  {id: 'single-research-loop', title: 'Single research loop', nodes: 5, loop: true},
  {id: 'single-loop-with-advice', title: 'Single loop with your own advice', nodes: 5, loop: true},
  {id: 'single-step', title: 'Single step (no loop)', nodes: 4, loop: false},
];
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = '';
server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
const metadata = await new Promise((resolveMetadata, reject) => {
  lines.once('line', line => resolveMetadata(JSON.parse(line)));
  server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`)));
  setTimeout(() => reject(new Error(`server startup timeout: ${serverErrors}`)), 15000);
});
async function waitUntil(predicate, what) {
  const deadline = Date.now() + 15000;
  while (!(await predicate())) {
    if (Date.now() > deadline) throw new Error(`Browser condition timed out: ${what}`);
    await new Promise(resolveWait => setTimeout(resolveWait, 50));
  }
}

/** Geometry of the open preview, measured in the page (svg user units unless noted). */
const measure = () => {
  const dialog = document.getElementById('editor-template-gallery');
  const svg = dialog.querySelector('#editor-template-detail svg.template-thumbnail');
  const frame = svg.parentElement;
  const box = element => { const r = element.getBoundingClientRect(); return {left: r.left, top: r.top, right: r.right, bottom: r.bottom}; };
  const view = svg.viewBox.baseVal;
  const inView = element => {
    const b = element.getBBox(), slack = 3;
    return b.x >= view.x - slack && b.y >= view.y - slack && b.x + b.width <= view.x + view.width + slack && b.y + b.height <= view.y + view.height + slack;
  };
  const scale = svg.getScreenCTM().a;
  const px = text => parseFloat(getComputedStyle(text).fontSize) * scale;
  const sample = path => {
    const length = path.getTotalLength(), points = [];
    for (let i = 0; i <= 200; i++) points.push(path.getPointAtLength(length * i / 200));
    return points;
  };
  const within = (p, b, slack) => p.x >= b.x - slack && p.x <= b.x + b.width + slack && p.y >= b.y - slack && p.y <= b.y + b.height + slack;
  const nodes = [...svg.querySelectorAll('.template-node')].map(group => ({id: group.querySelector('text').textContent, rect: group.querySelector('rect')}));
  const label = svg.querySelector('.template-loop-label'), labelBox = label?.getBBox();
  const edges = [...svg.querySelectorAll('.template-edge')], loop = svg.querySelector('.template-loop');
  // Edge through a foreign card (not one of its endpoints); cards are shrunk 6 units.
  const throughCards = [];
  const previewNodes = [...svg.querySelectorAll('.template-node rect')].map(rect => rect.getBBox());
  for (const edge of edges) {
    const points = sample(edge), ends = [points[0], points.at(-1)];
    for (const card of previewNodes) {
      const own = ends.some(end => within(end, card, 2));
      if (!own && points.some(point => within(point, {x: card.x + 6, y: card.y + 6, width: card.width - 12, height: card.height - 12}, 0))) {
        throughCards.push(`${edge.dataset.source}>${edge.dataset.target}`);
      }
    }
  }
  const labelHits = labelBox ? [...edges, loop].filter(Boolean).filter(path => sample(path).some(point => within(point, labelBox, 2))).length : 0;
  const rendered = svg.getBoundingClientRect();
  return {
    dialog: box(dialog), dialogScroll: dialog.scrollWidth - dialog.clientWidth,
    frame: box(frame), svg: box(svg), button: box(document.getElementById('editor-template-import')),
    frameScroll: frame.scrollWidth - frame.clientWidth, aspect: rendered.width / rendered.height,
    nodeCount: nodes.length, nodesInView: nodes.map(n => inView(n.rect)),
    edgesInView: [...edges, loop].filter(Boolean).map(inView), labelInView: label ? inView(label) : null,
    nodeFont: [...svg.querySelectorAll('.template-node text')].map(px), labelFont: label ? px(label) : null,
    throughCards, labelHits,
  };
};
const inside = (inner, outer, what) => {
  for (const side of ['left', 'top']) assert.ok(inner[side] >= outer[side] - 1, `${what}: ${side} ${inner[side]} < ${outer[side]}`);
  for (const side of ['right', 'bottom']) assert.ok(inner[side] <= outer[side] + 1, `${what}: ${side} ${inner[side]} > ${outer[side]}`);
};

let browser;
const results = [];
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  for (const [width, height] of [[1280, 900], [1920, 1080], [900, 800]]) {
    for (const colorScheme of ['light', 'dark']) {
      const page = await browser.newPage({viewport: {width, height}, colorScheme});
      const faults = [];
      page.on('pageerror', error => faults.push(error.message));
      await page.goto(metadata.origin + '/#workflow');
      await page.locator('#token').fill(metadata.token);
      await page.locator('#access-form button').click();
      await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened '), 'project opened');
      await page.locator('#editor-project').selectOption('reusable');
      await waitUntil(async () => (await page.locator('#editor-path').textContent()) === metadata.reusable_source, 'reusable source');
      await page.locator('#editor-template-open').click();
      const gallery = page.locator('#editor-template-gallery');
      for (const template of templates) {
        const where = `${template.id} ${width}px ${colorScheme}`;
        await gallery.locator(`.template-card[data-template="${template.id}"]`).click();
        assert.equal(await gallery.locator('#editor-template-detail h3').textContent(), template.title);
        const svg = gallery.locator('#editor-template-detail svg.template-thumbnail');
        assert.equal(await svg.getAttribute('role'), 'img');
        if (template.loop) assert.match(await svg.getAttribute('aria-label'), /repeated up to 1 time\(s\) from train back to interpret/);
        await gallery.locator('#editor-template-import').scrollIntoViewIfNeeded();
        const m = await page.evaluate(measure);
        const shot = join(shots, `template-preview-${template.id}-${width}-${colorScheme}.png`);
        await page.screenshot({path: shot});
        await page.screenshot({path: join(evidence, `template-preview-${template.id}-${width}-${colorScheme}.png`)});
        assert.ok(m.dialogScroll <= 1, `${where}: dialog overflows horizontally by ${m.dialogScroll}px`);
        assert.ok(m.frameScroll <= 1, `${where}: preview scrolls horizontally by ${m.frameScroll}px`);
        inside(m.frame, m.dialog, `${where}: preview frame`);
        inside(m.svg, m.frame, `${where}: preview svg`);
        inside(m.button, m.dialog, `${where}: Use template button`);
        assert.ok(m.aspect >= 2 && m.aspect <= 2.6, `${where}: preview aspect ${m.aspect.toFixed(2)} outside 2..2.6`);
        assert.equal(m.nodeCount, template.nodes);
        assert.ok(m.nodesInView.every(Boolean), `${where}: node rect outside viewBox`);
        assert.ok(m.edgesInView.every(Boolean), `${where}: edge outside viewBox ${JSON.stringify(m.edgesInView)}`);
        assert.equal(m.labelInView, template.loop ? true : null, `${where}: loop label outside viewBox`);
        assert.deepEqual(m.throughCards, [], `${where}: edges pass through cards`);
        assert.equal(m.labelHits, 0, `${where}: an edge or the loop path crosses the loop label`);
        const floor = width >= 1280 ? 15 : 13;
        for (const font of m.nodeFont) assert.ok(font >= floor, `${where}: node label renders at ${font.toFixed(1)}px`);
        if (template.loop) assert.ok(m.labelFont >= floor, `${where}: loop label renders at ${m.labelFont.toFixed(1)}px`);
        results.push(`${where}: aspect ${m.aspect.toFixed(2)}, node ${Math.min(...m.nodeFont).toFixed(1)}px${template.loop ? `, loop label ${m.labelFont.toFixed(1)}px` : ''} -> ${shot}`);
      }
      assert.deepEqual(faults, []);
      await page.close();
    }
  }
} finally {
  await browser?.close();
  server.kill();
}
for (const line of results) console.log(line);
console.log('PASS template preview legibility');
