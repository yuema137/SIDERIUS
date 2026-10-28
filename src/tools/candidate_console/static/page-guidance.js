/* Page guidance: step indicator, first-run guide and the Workflow -> Run handoff.
 * Presentation only. Run eligibility is read from window.newRunGate (new-run.js),
 * the single Run gate; the reasons below only explain a closed gate. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const session = window.consoleSession;
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
    const message = ready
      ? `Saved version ${state.savedSha256.slice(0, 12)} of ${state.projectId} is ready to run.`
      : blocked(state);
    $('workflow-next-run').disabled = !ready;
    $('workflow-next-state').textContent = ready ? message : `${message} Run is enabled only for a saved version.`;
    $('run-source-state').textContent = message;
    $('workflow-start-guide').hidden = opened;
    $('workflow-start-state').textContent = !session.connected ? 'Connect above to load the configured projects.'
      : !state.projectId ? 'No workflow project is open. Choose one in Project, or ask the console operator to configure one.' : '';
    const view = window.consoleNavigation.view;
    const current = {workflow: opened ? 'workflow' : 'task', run: 'run', 'slow-control': 'results'}[view] || null;
    const done = {task: opened, workflow: ready};
    $('step-indicator').hidden = !current;
    for (const item of $('step-indicator').querySelectorAll('[data-step]')) {
      const step = item.dataset.step, link = item.querySelector('a');
      if (step === current) link.setAttribute('aria-current', 'step'); else link.removeAttribute('aria-current');
      item.classList.toggle('done', step !== current && !!done[step]);
    }
  }
  $('workflow-next-run').addEventListener('click', () => { if (window.newRunGate.ready) location.hash = 'run'; });
  for (const name of ['workflow-editor-state', 'new-run-gate', 'console-view']) window.addEventListener(name, render);
  session.subscribe(render);
  render();
})();
