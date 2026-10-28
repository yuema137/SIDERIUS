/* Run page stepper and the single "what to do next" line (R-6). Presentation only: it
 * reads the step owners' run-step-state events and never decides eligibility. */
(() => {
  'use strict';
  const facts = {prepare: {}, launch: {}};
  const steps = [...document.querySelectorAll('#run-stepper [data-run-step]')];
  function render() {
    const prepare = facts.prepare, launch = facts.launch;
    let step = 'prepare', next;
    if (!window.consoleSession.connected) next = 'Connect to start.';
    else if (launch.intent) {
      step = 'follow';
      next = launch.problem ? 'This run needs attention below.'
        : launch.finished ? 'The run has finished. Open it in Monitor for results and logs.'
          : 'The run is in progress. Follow it in Monitor.';
    } else if (launch.selected) {
      step = 'launch';
      next = launch.outdated ? 'The prepared run below holds an older version: prepare the current version, or launch the older one.'
        : launch.reviewed ? 'Next: launch the run.' : 'Next: review the prepared run.';
    } else if (prepare.intent) {
      next = prepare.prepared ? 'Next: open the prepared run.' : prepare.problem ? 'The preparation needs attention below.' : 'Preparing… this page updates by itself.';
    } else if (!window.newRunGate?.ready) next = 'Save the workflow first, then come back here.';
    else next = prepare.reviewed ? 'Next: prepare.' : 'Next: choose the task, then check the inputs.';
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
