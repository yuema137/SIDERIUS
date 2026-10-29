/** Layout, Settings and first-run onboarding witness (ui-design-spec.md §1, §2, §7, §10):
 * real Chromium + real authoring API + temporary project.
 * 1. Defaults: Home is a hero (theme-matched logo + one sentence) and three entry cards;
 *    Settings-gated Advanced/developer sections are hidden; the empty canvas states one
 *    sentence and one action; the tour never opens itself.
 * 2. Settings: the header gear panel toggles "Show advanced tools" / "Show developer details",
 *    revealing gated sections at once; the choice survives reload and can be turned off.
 * 3. Tour: four steps, each anchored to a visible real element that the card does not cover;
 *    the page stays usable while it is open; Back/Next/OK; Skip and Esc close it; outcome is
 *    stored; Help reopens it (also from another page); Home "Start from a template" opens it.
 * 4. Layout at 1440x1100 and 1024x768, light and dark, every page: no overlapping cards, every
 *    top-level block on the page grid, no horizontal overflow, header logo visible without
 *    overlapping header controls, and the docked editor frame (rail | canvas | Selection with
 *    equal tops, bottoms and 48px headers; inspector 352px wide, 320px at 1024).
 * 5. Rendered text >= 4.5:1 contrast and >= 12px outside the circuit canvas and rail.
 * No review, save, preparation or launch request is made. Screenshots go to CONSOLE_EVIDENCE_DIR.
 * Explicit env: EDITOR_PYTHON, CONSOLE_PLAYWRIGHT_MODULE, CONSOLE_BROWSER_EXECUTABLE. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createRequire} from 'node:module';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) assert.ok(process.env[name], `Set ${name}`);
const evidence = process.env.CONSOLE_EVIDENCE_DIR || await mkdtemp(join(tmpdir(), 'siderius-layout-onboarding-'));
await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let errors = ''; server.stderr.on('data', chunk => {errors += chunk;});
const lines = createInterface({input: server.stdout});
const KEY = 'siderius.console.tour.v1';
let browser;
async function waitUntil(predicate, label = 'Browser condition') {
  const deadline = Date.now() + 15000;
  while (!(await predicate())) { if (Date.now() > deadline) throw new Error(`${label} timed out`); await new Promise(r => setTimeout(r, 50)); }
}
try {
  const metadata = await new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error(`Server startup timeout: ${errors}`)), 15000);
    lines.on('line', line => {
      try { const value = JSON.parse(line); if (!value.origin || !value.token) return; clearTimeout(timer); lines.close(); accept(value); }
      catch { /* Native plugin registration may write one informational line first. */ }
    });
    server.once('exit', code => {clearTimeout(timer); reject(new Error(`Server ${code}: ${errors}`));});
  });
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const context = await browser.newContext({viewport: {width: 1440, height: 1100}, colorScheme: 'light'});
  const page = await context.newPage(), faults = [], posts = [];
  page.on('pageerror', error => faults.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') posts.push(new URL(request.url()).pathname); });
  const tour = page.locator('#onboarding-tour');
  const tourOpen = async () => (await tour.count()) > 0 && await tour.isVisible();
  const connect = async () => {
    await page.locator('#token').fill(metadata.token); await page.locator('#access-form button[type="submit"]').click();
    await waitUntil(async () => (await page.locator('#editor-status').textContent()).includes('Opened supported'), 'workflow open');
    await page.locator('.circuit-card').first().waitFor();
  };

  // 1. Defaults: hero + three entry cards, gated sections hidden, one-action empty canvas.
  await page.goto(metadata.origin + '/#home');
  assert.equal(await page.locator('.home-intro img.logo-light').isVisible(), true, 'Light theme shows the navy wordmark');
  assert.equal(await page.locator('.home-intro img.logo-dark').isVisible(), false);
  assert.equal(await page.locator('.home-intro p').count(), 1, 'One plain sentence under the logo');
  assert.equal(await page.locator('#view-home .entry-card').count(), 3);
  const gated = {advanced: ['#native-chain-heading', '#editor-advanced', '#editor-refresh', '#monitor-form', '#recorded-example-heading'],
    developer: ['#workflow-details', '#operation-facts', '#tokens-provenance']};
  const gatedShown = async flag => page.evaluate(selectors => selectors.map(selector => {
    const element = document.querySelector(selector); return getComputedStyle(element.closest('[data-ui-flag]') || element).display !== 'none';
  }), gated[flag]);
  for (const flag of Object.keys(gated)) assert.deepEqual(await gatedShown(flag), gated[flag].map(() => false), `${flag} sections hidden by default`);
  await page.locator('nav a[href="#workflow"]').click(); await page.locator('#view-workflow').waitFor();
  assert.equal(await page.locator('#workflow-start-guide').isVisible(), true, 'Empty canvas start state');
  assert.match(await page.locator('#workflow-start-state').textContent(), /Connect/);
  assert.deepEqual(await page.locator('#workflow-start-guide button:visible:not(.link-button)').evaluateAll(items => items.map(item => item.id)), ['workflow-start-template'], 'One primary action: Start from a template');
  assert.equal(await page.locator('#onboarding-start').isVisible(), true, 'The tour stays a secondary link');
  assert.equal(await tourOpen(), false, 'The tour never opens itself over the page');
  assert.equal(await page.locator('.inspector-empty').isVisible(), true, 'Selection explains what to do before anything is selected');
  await page.screenshot({path: join(evidence, 'first-run-1440-light.png')});

  // 2. Settings: toggles reveal gated sections immediately and persist across reload.
  await page.locator('#settings-toggle').click();
  assert.equal(await page.locator('#settings-panel').isVisible(), true);
  await page.locator('#settings-panel input[data-ui-setting="advanced"]').check();
  assert.deepEqual(await gatedShown('advanced'), gated.advanced.map(() => true), 'Show advanced tools reveals advanced sections');
  assert.deepEqual(await gatedShown('developer'), gated.developer.map(() => false), 'Developer details stay hidden');
  await page.locator('#settings-panel input[data-ui-setting="developer"]').check();
  assert.deepEqual(await gatedShown('developer'), gated.developer.map(() => true));
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#settings-panel').isHidden(), true, 'Esc closes Settings');
  await page.reload();
  assert.deepEqual(await gatedShown('advanced'), gated.advanced.map(() => true), 'Advanced choice survives reload');
  assert.deepEqual(await gatedShown('developer'), gated.developer.map(() => true), 'Developer choice survives reload');
  await page.locator('#settings-toggle').click();
  assert.equal(await page.locator('#settings-panel input[data-ui-setting="advanced"]').isChecked(), true);
  await page.locator('#settings-panel input[data-ui-setting="advanced"]').uncheck();
  await page.locator('#settings-panel input[data-ui-setting="developer"]').uncheck();
  await page.locator('#settings-toggle').click();
  assert.deepEqual(await gatedShown('advanced'), gated.advanced.map(() => false), 'Turning the setting off hides them again');
  assert.equal(await page.evaluate(() => localStorage.getItem('siderius.console.ui.advanced')), null);

  await connect();
  assert.equal(await page.locator('#workflow-start-guide').isVisible(), false, 'The empty canvas yields to capability cards');

  // 2. Tour: anchored steps, non-blocking, Back/Next/Done.
  const steps = [
    ['Choose a task', '#editor-project'], ['Pick a module', '#editor-palette'],
    ['Match connector names', '.circuit-viewport'], ['Save a version', '#editor-review'],
  ];
  const checkStep = async (index, theme) => {
    const [title, selector] = steps[index];
    await waitUntil(async () => (await tour.getAttribute('data-step')) === String(index + 1), `tour step ${index + 1}`);
    assert.equal(await page.locator('#onboarding-title').textContent(), title);
    assert.equal(await page.locator('#onboarding-count').textContent(), `${index + 1}/4`);
    assert.ok(title.split(' ').length <= 4 && (await page.locator('#onboarding-text').textContent()).length <= 120, `step ${index + 1}: spec text limits`);
    const target = page.locator('.onboarding-target');
    assert.equal(await target.count(), 1, `step ${index + 1}: exactly one highlighted element`);
    assert.equal(await target.evaluate((element, wanted) => element.matches(wanted), selector), true, `step ${index + 1} anchors ${selector}`);
    assert.equal(await target.isVisible(), true, `step ${index + 1}: anchor is visible`);
    await page.waitForTimeout(50); // one animation frame for placement after scrolling
    const geometry = await page.evaluate(() => {
      const card = document.getElementById('onboarding-tour').getBoundingClientRect(), anchor = document.querySelector('.onboarding-target').getBoundingClientRect();
      return {card: {left: card.left, right: card.right, top: card.top, bottom: card.bottom}, anchor: {x: (anchor.left + anchor.right) / 2, y: (anchor.top + anchor.bottom) / 2, top: anchor.top, bottom: anchor.bottom}, width: innerWidth, height: innerHeight};
    });
    const {card, anchor} = geometry;
    assert.ok(card.left >= 0 && card.top >= 0 && card.right <= geometry.width && card.bottom <= geometry.height, `step ${index + 1}: tour card inside the window ${JSON.stringify(card)}`);
    assert.ok(anchor.bottom > 0 && anchor.top < geometry.height, `step ${index + 1}: anchor is scrolled into view`);
    assert.ok(!(anchor.x >= card.left && anchor.x <= card.right && anchor.y >= card.top && anchor.y <= card.bottom), `step ${index + 1}: the card does not cover its anchor`);
    await page.screenshot({path: join(evidence, `tour-step-${index + 1}-1440-${theme}.png`)});
  };
  // With a workflow open the empty-canvas guide is gone; a user opens the tour from header Help.
  assert.equal(await page.locator('#onboarding-start').isVisible(), false, 'The empty-canvas tour entry yields to the workflow');
  await page.locator('#onboarding-help').click();
  await checkStep(0, 'light');
  assert.equal(await page.locator('#onboarding-back').isDisabled(), true);
  await page.locator('#onboarding-next').click(); await checkStep(1, 'light');
  await page.locator('#onboarding-next').click(); await checkStep(2, 'light');
  // Non-blocking: the page stays usable with the tour open.
  await page.locator('.circuit-card .editor-node').first().click();
  await page.locator('#editor-inspector .inspector-capability-heading').waitFor();
  assert.equal(await page.locator('.inspector-empty').isVisible(), false, 'Selection empty state yields to the selected capability');
  assert.equal(await tourOpen(), true, 'Using the page does not close the tour');
  await page.locator('#onboarding-back').click(); await checkStep(1, 'light');
  await page.locator('#onboarding-next').click(); await checkStep(2, 'light');
  await page.locator('#onboarding-next').click(); await checkStep(3, 'light');
  assert.equal(await page.locator('#onboarding-next').textContent(), 'OK');
  await page.locator('#onboarding-next').click();
  assert.equal(await tourOpen(), false);
  assert.equal(await page.locator('.onboarding-target').count(), 0, 'Closing removes the highlight');
  assert.equal(await page.evaluate(key => localStorage.getItem(key), KEY), 'done', 'Finishing is remembered');

  // Reopen from "?" in dark mode; Escape closes and returns focus. From another page it switches to Workflow.
  await page.locator('#theme-preference').selectOption('dark');
  await page.locator('#onboarding-help').click();
  await checkStep(0, 'dark');
  await page.keyboard.press('Escape');
  assert.equal(await tourOpen(), false);
  assert.equal(await page.evaluate(key => localStorage.getItem(key), KEY), 'dismissed', 'Esc is Skip');
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'onboarding-help', 'Focus returns to the help button');
  await page.locator('nav a[href="#monitor"]').click(); await page.locator('#view-monitor').waitFor();
  await page.locator('#onboarding-help').click();
  await waitUntil(async () => new URL(page.url()).hash === '#workflow' && await tourOpen(), 'tour from Monitor');
  await checkStep(0, 'dark');
  assert.equal(await page.locator('.home-intro img.logo-dark').count(), 1);
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('header img.logo-dark')).display !== 'none'), true, 'Dark theme shows the white wordmark');
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('header img.logo-light')).display), 'none');
  await page.locator('#onboarding-close').click();
  assert.equal(await tourOpen(), false);
  await page.locator('#theme-preference').selectOption('light');
  // Home "Start from a template" opens the template gallery on Workflow (not the tour).
  await page.locator('nav a[href="#home"]').click();
  await page.locator('#home-start-template').click();
  await waitUntil(async () => new URL(page.url()).hash === '#workflow' && await page.locator('#editor-template-gallery').evaluate(dialog => dialog.open), 'gallery from Home template');
  assert.equal(await tourOpen(), false);
  await page.locator('#editor-template-close').click();
  await page.reload();
  assert.equal(await tourOpen(), false, 'The tour does not reopen itself after reload');
  await connect();

  // 3 + 4. Layout and contrast on every page, two viewports, both themes.
  const measure = () => page.evaluate(() => {
    const view = document.querySelector('[data-view]:not([hidden])');
    const shown = element => element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden';
    const box = element => { const r = element.getBoundingClientRect(); return {left: r.left, right: r.right, top: r.top + scrollY, bottom: r.bottom + scrollY, height: r.height}; };
    const cards = [...document.querySelectorAll('#access-section, #step-indicator, [data-view]:not([hidden]) .card')]
      .filter(element => shown(element) && !element.closest('.circuit-world'));
    const overlaps = [];
    for (let i = 0; i < cards.length; i++) for (let j = i + 1; j < cards.length; j++) {
      const a = cards[i], b = cards[j];
      if (a.contains(b) || b.contains(a)) continue;
      const p = box(a), q = box(b);
      if (p.right > q.left + .5 && q.right > p.left + .5 && p.bottom > q.top + .5 && q.bottom > p.top + .5) overlaps.push(`${a.id || a.className} x ${b.id || b.className}`);
    }
    const blocks = [...view.children].filter(element => shown(element) && element.tagName !== 'H1').map(element => ({name: element.id || element.className || element.tagName, ...box(element)}));
    const workspace = view.querySelector('.editor-workspace');
    const column = selector => { const element = view.querySelector(selector); return element && shown(element) ? box(element) : null; };
    const header = selector => { const element = view.querySelector(selector); return element && shown(element) ? element.getBoundingClientRect().height : null; };
    const logo = [...document.querySelectorAll('header .brand img.logo')].find(shown);
    const logoBox = logo && logo.getBoundingClientRect();
    const headerItems = ['.brand > span', '.console-intro', '.theme-control', '#onboarding-help', '#settings-toggle']
      .map(selector => document.querySelector('header ' + selector)).filter(element => element && shown(element));
    const logoOverlaps = logoBox ? headerItems.filter(element => { const r = element.getBoundingClientRect();
      return r.right > logoBox.left + .5 && logoBox.right > r.left + .5 && r.bottom > logoBox.top + .5 && logoBox.bottom > r.top + .5; }).map(element => element.id || element.className) : ['no logo'];
    return {view: view.dataset.view, overlaps, blocks, logo: logoBox && {height: logoBox.height, theme: logo.classList.contains('logo-dark') ? 'dark' : 'light', loaded: logo.complete && logo.naturalWidth > 0}, logoOverlaps, viewBox: box(view), access: box(document.getElementById('access-section')), accessCollapsed: document.getElementById('access-section').classList.contains('access-collapsed'),
      overflow: document.documentElement.scrollWidth - innerWidth,
      columns: workspace ? {workspace: box(workspace), palette: column('.editor-workspace > .editor-palette'), canvas: column('.workflow-canvas-panel'), inspector: column('.workflow-inspector-panel'),
        headers: [header('.editor-workspace > .editor-palette > h3'), header('.workflow-canvas-panel > h2'), header('.workflow-inspector-panel > h2')],
        viewport: column('.circuit-viewport'), panelScrollTop: view.querySelector('.workflow-canvas-panel')?.scrollTop ?? 0} : null};
  });
  const contrast = () => page.evaluate(() => {
    const parse = value => { const match = /rgba?\(([^)]+)\)/.exec(value); if (!match) return null; const parts = match[1].split(/[ ,/]+/).filter(Boolean).map(Number); return {rgb: parts.slice(0, 3), alpha: parts.length > 3 ? parts[3] : 1}; };
    const luminance = rgb => rgb.map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
    const background = element => {
      for (let node = element; node; node = node.parentElement) { const color = parse(getComputedStyle(node).backgroundColor); if (color && color.alpha === 1) return color.rgb; }
      return parse(getComputedStyle(document.documentElement).backgroundColor)?.rgb || [255, 255, 255];
    };
    const faded = element => { for (let node = element; node; node = node.parentElement) if (Number(getComputedStyle(node).opacity) < 1) return true; return false; };
    const failures = [];
    const scope = [document.querySelector('header'), document.querySelector('nav.actions'), document.querySelector('main')];
    for (const container of scope) for (const element of [container, ...container.querySelectorAll('*')]) {
      if (!element.getClientRects().length || getComputedStyle(element).visibility === 'hidden') continue;
      if (element.closest('[hidden], #editor-graph, #editor-palette, option') || element.matches(':disabled') || faded(element)) continue;
      if (![...element.childNodes].some(node => node.nodeType === 3 && node.textContent.trim())) continue;
      const fg = parse(getComputedStyle(element).color); if (!fg) continue;
      const bg = background(element);
      const mixed = fg.rgb.map((v, i) => v * fg.alpha + bg[i] * (1 - fg.alpha));
      const a = luminance(mixed), b = luminance(bg), ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      // Inspector field internals (s8/s2) join the 12px floor in the spec conformance pass.
      if (parseFloat(getComputedStyle(element).fontSize) < 12 && !element.closest('#editor-inspector')) failures.push(`${element.tagName.toLowerCase()}#${element.id}.${element.className} font-size ${getComputedStyle(element).fontSize}`);
      if (ratio < 4.5) failures.push(`${element.tagName.toLowerCase()}#${element.id}.${element.className} "${element.textContent.trim().slice(0, 40)}" ${ratio.toFixed(2)}`);
    }
    return failures;
  });
  for (const [width, height] of [[1440, 1100], [1024, 768]]) {
    await page.setViewportSize({width, height});
    for (const theme of ['light', 'dark']) {
      await page.locator('#theme-preference').selectOption(theme);
      for (const view of ['home', 'workflow', 'run', 'monitor']) {
        await page.locator(`nav a[href="#${view}"]`).click(); await page.locator(`#view-${view}`).waitFor();
        await page.waitForTimeout(100);
        const label = `${view}-${width}-${theme}`, result = await measure();
        assert.deepEqual(result.overlaps, [], `${label}: overlapping cards`);
        assert.ok(result.overflow <= 0, `${label}: horizontal overflow ${result.overflow}px`);
        for (const block of result.blocks) {
          assert.ok(Math.abs(block.left - result.viewBox.left) <= 1 && Math.abs(block.right - result.viewBox.right) <= 1, `${label}: ${block.name} is off the page grid ${JSON.stringify(block)} vs ${JSON.stringify(result.viewBox)}`);
        }
        // Connected: the connection is a header chip (spec L6); only the disconnected banner spans the grid.
        if (!result.accessCollapsed) assert.ok(Math.abs(result.access.left - result.viewBox.left) <= 1 && Math.abs(result.access.right - result.viewBox.right) <= 1, `${label}: connection banner is off the page grid`);
        assert.ok(result.logo && result.logo.loaded && result.logo.theme === theme && result.logo.height >= 28 && result.logo.height <= 32,
          `${label}: header logo ${JSON.stringify(result.logo)}`);
        assert.deepEqual(result.logoOverlaps, [], `${label}: header logo overlaps header controls`);
        if (result.columns) {
          // Docked frame: rail | canvas | Selection, one top/bottom, 48px headers, spec widths.
          const {workspace, palette, canvas, inspector, headers} = result.columns;
          assert.ok(palette && canvas && inspector, `${label}: rail, canvas and Selection are shown`);
          assert.ok(Math.abs(palette.left - workspace.left) <= 1 && Math.abs(inspector.right - workspace.right) <= 1, `${label}: rail and Selection close the frame`);
          assert.ok(palette.right <= canvas.left + .5 && canvas.right <= inspector.left + .5, `${label}: columns in order without overlap`);
          for (const panel of [palette, canvas, inspector]) {
            assert.ok(Math.abs(panel.top - palette.top) <= 1 && Math.abs(panel.bottom - palette.bottom) <= 1, `${label}: panels share top and bottom edges ${JSON.stringify(result.columns)}`);
          }
          assert.ok(Math.abs(inspector.right - inspector.left - (width >= 1280 ? 352 : 320)) <= 1, `${label}: Selection width ${inspector.right - inspector.left}`);
          assert.ok(headers.every(value => value !== null && Math.abs(value - 48) <= 1), `${label}: 48px panel headers ${headers}`);
          // The canvas viewport is bounded by its panel (it scrolls inside; the panel never scrolls).
          const {viewport} = result.columns;
          if (viewport) assert.ok(viewport.top >= canvas.top - .5 && viewport.bottom <= canvas.bottom + .5 && viewport.height <= workspace.height && result.columns.panelScrollTop === 0,
            `${label}: canvas viewport inside its panel ${JSON.stringify({viewport, canvas, workspace})}`);
        }
        assert.deepEqual(await contrast(), [], `${label}: text below 4.5:1 or 12px`);
        await page.screenshot({path: join(evidence, `${label}.png`), fullPage: true});
      }
    }
  }
  assert.deepEqual(posts.filter(path => !path.endsWith('/draft')), [], 'Onboarding and layout checks never review, save, prepare or launch');
  assert.deepEqual(faults, []);
  console.log(`PASS: first-run guide, anchored non-blocking 4-step tour (dismiss/reopen/remember), disjoint aligned cards, three-column editor, text contrast; screenshots in ${evidence}`);
} finally {
  await browser?.close();
  server.kill();
}
