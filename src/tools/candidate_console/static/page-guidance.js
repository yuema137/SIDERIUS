/* Page guidance: step indicator, empty-canvas start state, page-bar problems chip and the
 * Workflow -> Run handoff.
 * Presentation only. Run eligibility is read from window.newRunGate (new-run.js),
 * the single Run gate; the reasons below only explain a closed gate. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const session = window.consoleSession, onboarding = window.consoleOnboarding;
  function blocked(state) {
    if (!session.connected) return 'Connect to see which saved workflow version a run uses.';
    if (!state.projectId) return 'Open a workflow project on the Workflow page first.';
    if (!state.sourceAvailable) return 'The selected workflow source is not open.';
    if (!state.candidateEnabled) return 'This project is editable but not enabled for runs.';
    if (!state.reusableSource) return 'This workflow source is not a supported reusable declaration, so it cannot be prepared as a run.';
    if (state.conflict) return 'Resolve the source conflict on the Workflow page first.';
    if (state.saving) return 'Saving the workflow.';
    if (state.dirty || state.sourceDirty) return 'Save first: the workflow has unsaved edits. Review and save them on the Workflow page.';
    return 'Save the reviewed workflow first.';
  }
  function render() {
    const state = window.workflowEditor.state, ready = window.newRunGate.ready;
    const opened = session.connected && !!state.projectId && state.sourceAvailable;
    // Only bytes a console Save recorded are a "saved version" (red-team A-6/A-7).
    const name = ready ? window.editorVersions?.nameFor(state.savedSha256) : null;
    const message = !ready ? blocked(state)
      : name ? `Saved version "${name}" of project ${state.projectId} is ready to run.`
      : `The current file of project ${state.projectId} (version ${state.savedSha256.slice(0, 12)}) is ready to run.`;
    $('workflow-next-run').disabled = !ready;
    $('workflow-next-run').title = ready ? message : `${message} Run is enabled only for a saved version.`;
    $('workflow-next-state').textContent = ready ? message : `${message} Run is enabled only for a saved version.`;
    // B8-3: while step 2 holds a prepared run of another version, the Run page names what
    // Launch would actually use instead of claiming the newest save is ready.
    const captured = window.reusableCandidate?.capturedVersion;
    const label = version => version.name ? `version "${version.name}"` : `version ${version.sha256.slice(0, 12)}`;
    $('run-source-state').textContent = captured && ready && captured.sha256 !== state.savedSha256
      ? `The prepared run in step 2 uses ${label(captured)}. Your saved ${name ? `version "${name}"` : 'version'} is newer and not in it; prepare it to run it.`
      : captured && captured.sha256 === state.savedSha256 ? `The prepared run in step 2 uses ${label(captured)}, your current saved version.`
      : message;
    // Empty canvas (CSS hides it once a capability card is drawn): one sentence, one action.
    $('workflow-start-state').textContent = !session.connected ? 'Connect with your console token at the top, then start from a template.'
      : !state.projectId ? 'Choose a workflow project in the bar above, or ask the console operator to configure one.'
      : !opened ? 'This workflow source is not open.'
      : 'Add a module from the list on the left.';
    // Problems chip in the page bar mirrors the count editor-problems.js renders.
    const problems = $('editor-problems'), count = problems.hidden ? 0 : problems.querySelectorAll('.editor-problem').length;
    $('problems-chip').hidden = !count;
    $('problems-chip').replaceChildren(window.consoleIcons?.make('circle-alert', 16) || '', `${count} problem${count === 1 ? '' : 's'}`);
    if (!count) setProblemsOpen(false);
    const view = window.consoleNavigation.view;
    const current = {workflow: opened ? 'workflow' : 'task', run: 'run', monitor: 'results'}[view] || null;
    const done = {task: opened, workflow: ready};
    $('step-indicator').hidden = !current;
    for (const item of $('step-indicator').querySelectorAll('[data-step]')) {
      const step = item.dataset.step, link = item.querySelector('a');
      if (step === current) link.setAttribute('aria-current', 'step'); else link.removeAttribute('aria-current');
      item.classList.toggle('done', step !== current && !!done[step]);
    }
  }
  $('workflow-next-run').addEventListener('click', () => { if (window.newRunGate.ready) location.hash = 'run'; });
  $('onboarding-start').addEventListener('click', () => onboarding.open(0));
  // Home "Quick start" (quick-start.js) replaces the former Home template entry; the
  // gallery stays on the Workflow page.
  // Problems popover (spec §9): opens under the chip, never reflows the canvas.
  function setProblemsOpen(open) {
    const chip = $('problems-chip'), box = $('editor-problems');
    box.classList.toggle('open', open); chip.setAttribute('aria-expanded', String(open));
    if (open) box.style.left = Math.max(0, chip.offsetLeft) + 'px';
  }
  $('problems-chip').addEventListener('click', () => {
    const open = !$('editor-problems').classList.contains('open'); setProblemsOpen(open);
    if (open) $('editor-problems').querySelector('.editor-problem')?.focus();
  });
  $('editor-problems').addEventListener('keydown', event => { if (event.key === 'Escape') { setProblemsOpen(false); $('problems-chip').focus(); } });
  document.addEventListener('pointerdown', event => {
    if ($('editor-problems').classList.contains('open') && !$('editor-problems').contains(event.target) && !$('problems-chip').contains(event.target)) setProblemsOpen(false);
  });
  new MutationObserver(render).observe($('editor-problems'), {attributes: true, attributeFilter: ['hidden'], childList: true, subtree: true});
  for (const name of ['workflow-editor-state', 'new-run-gate', 'console-view', 'console-onboarding', 'editor-versions', 'run-step-state']) window.addEventListener(name, render);
  session.subscribe(render);
  render();
})();
