/** Template gallery preview legibility: "Start from a template" -> "Single research loop".
 * Regression for the operator report that the large preview was too small to read, cropped
 * (skipping-edge arcs cut at the top, the right-most node and "Use template" cut at the right)
 * and that the dashed feedback line ran through its own "feedback · up to N iteration" label.
 * At 1920, 1280 (default) and 900 (layout breakpoint) px viewports, light and dark:
 * - the dialog never overflows horizontally and the preview, every node and "Use template" lie
 *   inside the dialog's visible box (the preview may scroll inside its own frame, never clip);
 * - every node rect, edge, the loop path and its label lie inside the svg viewBox;
 * - no sampled point of the dashed loop path falls inside the loop label's box;
 * - node labels and the loop label render at >= 13 CSS px.
 * Screenshots: $TMPDIR/template-preview-<width>-<theme>.png (and the evidence directory). */
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

/** Geometry of the open preview, measured in the page. */
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
  const loop = svg.querySelector('.template-loop'), label = svg.querySelector('.template-loop-label');
  let crossings = 0;
  if (loop && label) {
    const b = label.getBBox(), length = loop.getTotalLength();
    for (let i = 0; i <= 400; i++) {
      const p = loop.getPointAtLength(length * i / 400);
      if (p.x >= b.x - 2 && p.x <= b.x + b.width + 2 && p.y >= b.y - 2 && p.y <= b.y + b.height + 2) crossings++;
    }
  }
  return {
    dialog: box(dialog), dialogScroll: dialog.scrollWidth - dialog.clientWidth,
    frame: box(frame), svg: box(svg), button: box(document.getElementById('editor-template-import')),
    nodesInView: [...svg.querySelectorAll('.template-node rect')].map(inView),
    edgesInView: [...svg.querySelectorAll('.template-edge, .template-loop')].map(inView),
    labelInView: label ? inView(label) : null,
    nodeFont: [...svg.querySelectorAll('.template-node text')].map(px), labelFont: label ? px(label) : null,
    crossings, frameScrolls: frame.scrollWidth > frame.clientWidth + 1,
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
      await gallery.locator('.template-card[data-template="single-research-loop"]').click();
      assert.equal(await gallery.locator('#editor-template-detail h3').textContent(), 'Single research loop');
      const svg = gallery.locator('#editor-template-detail svg.template-thumbnail');
      assert.equal(await svg.getAttribute('role'), 'img');
      assert.match(await svg.getAttribute('aria-label'), /repeated up to 1 time\(s\) from train back to interpret/);
      await gallery.locator('#editor-template-import').scrollIntoViewIfNeeded();
      const m = await page.evaluate(measure);
      const where = `${width}px ${colorScheme}`;
      const shot = join(shots, `template-preview-${width}-${colorScheme}.png`);
      await page.screenshot({path: shot});
      await page.screenshot({path: join(evidence, `template-preview-${width}-${colorScheme}.png`)});
      assert.ok(m.dialogScroll <= 1, `${where}: dialog overflows horizontally by ${m.dialogScroll}px`);
      inside(m.frame, m.dialog, `${where}: preview frame`);
      inside(m.button, m.dialog, `${where}: Use template button`);
      // From the default 1280 px up the whole graph fits; narrower frames scroll to the last node.
      if (width >= 1280) assert.equal(m.frameScrolls, false, `${where}: preview needs scrolling`);
      if (!m.frameScrolls) inside(m.svg, m.frame, `${where}: preview svg`);
      else {
        const last = await page.evaluate(() => {
          const frame = document.querySelector('#editor-template-detail .template-preview');
          frame.scrollLeft = frame.scrollWidth;
          const r = [...frame.querySelectorAll('.template-node rect')].at(-1).getBoundingClientRect(), f = frame.getBoundingClientRect();
          return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, frame: {left: f.left, right: f.right, top: f.top, bottom: f.bottom}};
        });
        inside(last, last.frame, `${where}: last node after scrolling the preview`);
        await page.screenshot({path: join(shots, `template-preview-${width}-${colorScheme}-scrolled.png`)});
      }
      assert.deepEqual(m.nodesInView, [true, true, true, true, true], `${where}: node rect outside viewBox`);
      assert.ok(m.edgesInView.every(Boolean), `${where}: edge outside viewBox ${JSON.stringify(m.edgesInView)}`);
      assert.equal(m.labelInView, true, `${where}: loop label outside viewBox`);
      assert.equal(m.crossings, 0, `${where}: the dashed loop path crosses its label`);
      for (const font of m.nodeFont) assert.ok(font >= 13, `${where}: node label renders at ${font.toFixed(1)}px`);
      assert.ok(m.labelFont >= 13, `${where}: loop label renders at ${m.labelFont.toFixed(1)}px`);
      assert.deepEqual(faults, []);
      results.push(`${where}: node ${Math.min(...m.nodeFont).toFixed(1)}px, loop label ${m.labelFont.toFixed(1)}px, frame scrolls=${m.frameScrolls} -> ${shot}`);
      await page.close();
    }
  }
} finally {
  await browser?.close();
  server.kill();
}
for (const line of results) console.log(line);
console.log('PASS template preview legibility');
