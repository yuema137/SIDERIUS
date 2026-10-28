/** Scenario (b), operator first-use flow: import "Single loop with your own advice" ->
 * write "Your advice to the agents" (first inspector input) -> Review -> Save; contrast with the
 * plain loop, whose proposal agent does not read advice.
 *
 * Deviations from the requested flow, by the current catalog (not by this witness):
 * - "remove the Literature review node" is not scripted: no template has Literature inside a
 *   loop, because no catalogued protocol joins literature.output into an interpretation-fed
 *   proposal (B6-9 `interpretation-to-literature` / a literature advisory adaptor are missing).
 *   The advice template is therefore the loop without Literature from the start.
 * - "findings" binds the proposal's expert_context socket to a managed external, but the
 *   reusable preparation owner fills it with None (candidate_prepare/reusable_interpretation.py);
 *   authored findings text has no field yet, so findings travel inside the advice text.
 *
 * Scenario (c), documented only, BLOCKED on B6
 * (.structured-coding/plans/advanced/b6-adaptors-and-aggregators.md):
 * "expand to 3 literature reviews on different aspects and aggregate into one proposal" needs
 *  1. three literature nodes in one declaration admitted by an execution profile (the literature
 *     profile admits exactly one review: fanout.py literature_candidate, len(reviews) == 1);
 *  2. a `literature.collection` contract + `literature-collection-to-proposal` protocol over the
 *     existing owner `local_typed_evidence_many` (B6 §5 P1, PR B6-4), fed by a `collect` adaptor
 *     node (B6-1 declaration format, B6-3 adaptor readiness/execution);
 *  3. for the loop variant, `interpretation-to-literature` (B6-9) so reviews can follow feedback.
 * Missing capability in one line: N literature.output -> 1 proposal.input aggregation (B6-1/B6-3/B6-4).
 */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdir, readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {join, resolve, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
for (const name of ['EDITOR_PYTHON', 'CONSOLE_PLAYWRIGHT_MODULE', 'CONSOLE_BROWSER_EXECUTABLE']) {
  assert.ok(process.env[name], `Set ${name}`);
}
const evidence = process.env.CONSOLE_EVIDENCE_DIR || join(tmpdir(), 'siderius-scenario_template_advice');
await mkdir(evidence, {recursive: true});
const server = spawn(process.env.EDITOR_PYTHON, ['-m', 'tests.browser.workflow_editor_server'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
let serverErrors = '';
server.stderr.on('data', chunk => { serverErrors += chunk; });
const lines = createInterface({input: server.stdout});
const metadata = await new Promise((resolveMetadata, reject) => {
  lines.once('line', line => resolveMetadata(JSON.parse(line)));
  server.once('exit', code => reject(new Error(`server exit ${code}: ${serverErrors}`)));
  setTimeout(() => reject(new Error(`server startup timeout: ${serverErrors}`)), 15000);
});
// The fixture's "reusable" project: an unbound reusable source with its own task references.
const parsed = () => JSON.parse(execFileSync(process.env.EDITOR_PYTHON, ['-c',
  'import sys; from pathlib import Path; from workflows.definition import parse_workflow_source; print(parse_workflow_source(Path(sys.argv[1]).read_text()).model_dump_json())',
  metadata.reusable_source], {cwd: root, encoding: 'utf8'}));
const original = parsed();
async function waitUntil(predicate) {
  const deadline = Date.now() + 15000;
  while (!(await predicate())) {
    if (Date.now() > deadline) throw new Error('Browser condition timed out');
    await new Promise(resolveWait => setTimeout(resolveWait, 50));
  }
}
let browser;
try {
  const {chromium} = createRequire(import.meta.url)(process.env.CONSOLE_PLAYWRIGHT_MODULE);
  browser = await chromium.launch({headless: true, executablePath: process.env.CONSOLE_BROWSER_EXECUTABLE});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const faults = [];
  page.on('pageerror', error => faults.push(error.message));
  await page.goto(metadata.origin + '/#workflow');
  await page.locator('#token').fill(metadata.token);
  await page.locator('#access-form button').click();
  const status = page.locator('#editor-status');
  await waitUntil(async () => (await status.textContent()).includes('Opened '));
  await page.locator('#editor-project').selectOption('reusable');
  await waitUntil(async () => (await page.locator('#editor-path').textContent()) === metadata.reusable_source);

  // Beginner entry: compact cards (icon, title, one sentence); the graph preview opens on demand.
  const importTemplate = async (id, title) => {
    // Compare exact bytes on disk before/after import (a prior Save may have changed them).
    const before = await readFile(metadata.reusable_source);
    await page.locator('#editor-template-open').click();
    const gallery = page.locator('#editor-template-gallery');
    await gallery.locator(`.template-card[data-template="${id}"]`).click();
    await page.screenshot({path: join(evidence, `gallery-${id}.png`)});
    assert.equal(await gallery.locator('.template-card .template-thumbnail').count(), 0, 'Cards stay compact');
    assert.equal(await gallery.locator('#editor-template-detail h3').textContent(), title);
    assert.equal(await gallery.locator('#editor-template-detail svg.template-thumbnail').count(), 1, 'Preview shown before import');
    await gallery.locator('#editor-template-import').click();
    await waitUntil(async () => !(await gallery.evaluate(dialog => dialog.open)));
    await waitUntil(async () => (await status.textContent()).includes('Checked.'));
    assert.ok((await readFile(metadata.reusable_source)).equals(before), 'Import never writes before Save');
  };
  // Human advice is the first input of the inspector, labelled and multi-line.
  const adviceFirst = async () => {
    const first = page.locator('#editor-inspector').locator('textarea, input, select').first();
    assert.equal(await first.getAttribute('class'), 'advice-input');
    assert.equal(await page.locator('#editor-inspector .advice-label').first().textContent(), 'Your advice to the agents');
    assert.ok((await first.getAttribute('placeholder')).startsWith('e.g. '));
  };
  const reviewAndSave = async () => {
    await page.locator('#editor-review').click();
    await waitUntil(async () => !(await page.locator('#editor-save').isDisabled()));
    await page.locator('#editor-save').click();
    await waitUntil(async () => (await status.textContent()).includes('Saved as "'));
  };
  // Scenario (b): import the loop with your own advice, write advice first, review, save.
  await importTemplate('single-loop-with-advice', 'Single loop with your own advice');
  await page.locator('#circuit-node-propose').click();
  await adviceFirst();
  assert.equal(await page.locator('#editor-inspector .advice-warning').count(), 0, 'The advice socket is connected');
  const advice = 'Earlier attempts overfit after a few epochs; prefer smaller models first.';
  await page.locator('#editor-inspector .advice-input').fill(advice);
  await reviewAndSave();
  await page.screenshot({path: join(evidence, 'saved.png'), fullPage: true});
  const saved = parsed();
  assert.equal(saved.preparation_options.proposal_advice, advice);
  const propose = saved.definition.nodes.find(node => node.id === 'propose');
  const sources = Object.fromEntries(propose.request.arguments.map(item => [item.name, item.source]));
  assert.deepEqual(sources.human_advice, {kind: 'external', binding: 'advice'});
  assert.deepEqual(sources.expert_context, {kind: 'external', binding: 'findings'});
  assert.ok(!saved.definition.nodes.some(node => node.capability === 'literature'));
  // Contrast: the plain loop's proposal agent cannot read advice, and the field says so.
  await importTemplate('single-research-loop', 'Single research loop');
  await page.locator('#circuit-node-propose').click();
  await adviceFirst();
  assert.equal(await page.locator('#editor-inspector .advice-warning').count(), 1);
  assert.deepEqual(faults, []);
} finally {
  await browser?.close();
  server.kill();
}
