/* Run page stepper and the single "what to do next" line (R-6). Presentation only: it
 * reads the step owners' run-step-state events and never decides eligibility. */
(() => {
  'use strict';
  const facts = {prepare: {}, launch: {}};
  const steps = [...document.querySelectorAll('#run-stepper [data-run-step]')];
  // #1145: a step that ended without success says what happened and where to look; it
  // never reads "finished" or "Preparing…". Keys are `operationOutcome.ending` values.
  const PREPARE_ENDED = {
    failed: 'The preparation failed. The cause and its log are named below; start over to try again.',
    timed_out: 'The preparation reached its time limit and was stopped. Its log is named below; start over to try again.',
    interrupted: 'The preparation was interrupted before finishing. Its log is named below; start over to try again.',
    operation_failed: 'The preparation failed before reporting a result. Details are below and in Monitor; start over to try again.',
    not_started: 'The preparation did not start: its worker could not be launched. Start over to try again.',
    cancelled_before_start: 'The preparation was cancelled before it started; nothing was prepared. Start over to try again.',
  };
  const LAUNCH_ENDED = {
    failed: 'The run failed. The cause is shown below; open it in Monitor for the full log.',
    timed_out: 'The run reached its time limit and was stopped. Open it in Monitor for its logs.',
    interrupted: 'The run was interrupted before finishing. Open it in Monitor for its logs.',
    cancelled: 'The run was stopped on request before finishing; no candidate result was produced. Open it in Monitor for its logs.',
    operation_failed: 'The run failed before reporting a result. Open it in Monitor for details.',
    not_started: 'The run did not start: its worker could not be launched. Open it in Monitor for details.',
    cancelled_before_start: 'The run was cancelled before it started: it never ran, and nothing was produced.',
  };
  function render() {
    const prepare = facts.prepare, launch = facts.launch;
    let step = 'prepare', next;
    if (!window.consoleSession.connected) next = 'Connect to start.';
    else if (launch.intent) {
      step = 'follow';
      next = launch.problem ? 'This run needs attention below.'
        : LAUNCH_ENDED[launch.ending] || (launch.finished ? 'The run has finished. Open it in Monitor for results and logs.'
          : 'The run is in progress. Follow it in Monitor.');
    } else if (launch.selected) {
      step = 'launch';
      next = launch.outdated ? 'The prepared run below holds an older version: prepare the current version, or launch the older one.'
        : launch.reviewed ? 'Next: launch the run.' : 'Next: review the prepared run.';
    } else if (prepare.intent) {
      next = prepare.prepared ? 'Next: open the prepared run.' : prepare.problem ? 'The preparation needs attention below.'
        : PREPARE_ENDED[prepare.ending] || 'Preparing… this page updates by itself.';
    } else if (!window.newRunGate?.ready) next = 'Save the workflow first, then come back here.';
    else next = prepare.reviewed ? 'Next: prepare.' : (window.experimentSetups?.current?.group === 'task' ? 'Next: check the inputs.' : 'Next: choose the task, then check the inputs.');
    const order = steps.map(item => item.dataset.runStep), at = order.indexOf(step);
    for (const [index, item] of steps.entries()) {
      if (index === at) item.setAttribute('aria-current', 'step'); else item.removeAttribute('aria-current');
      item.toggleAttribute('data-done', index < at);
    }
    document.getElementById('run-entry').toggleAttribute('data-current', step === 'prepare');
    document.getElementById('capture-heading').closest('section').toggleAttribute('data-current', step === 'launch');
    document.getElementById('run-next').textContent = next;
  }
  window.addEventListener('run-step-state', event => { facts[event.detail.source] = event.detail; render(); });
  window.consoleSession.subscribe(render);
  render();
})();
