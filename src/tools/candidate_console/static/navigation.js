/* Fragment routes select persistent panels; controllers retain all working state.
 * Without a selected task (task-selection.js `gated`) Workflow and Run links are
 * aria-disabled and their routes show the `task-required` panel instead; the hidden
 * controllers keep running underneath, so this is presentation only. */
(() => {
  'use strict';
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  let view = 'home', operation = null;
  const GATED = ['workflow', 'run'], REASON = 'Choose a task first';
  // Panel visibility and link state; repainted when the task selection changes.
  function paint() {
    const blocked = GATED.includes(view) && !!window.consoleTask?.gated;
    const shown = blocked ? 'task-required' : view;
    for (const panel of document.querySelectorAll('[data-view]')) panel.hidden = panel.dataset.view !== shown;
    const heading = document.getElementById('task-required-heading');
    if (heading) heading.textContent = {workflow: 'Workflow', run: 'Run'}[view] || '';
    for (const link of document.querySelectorAll('nav a, #step-indicator a')) {
      const target = link.hash.slice(1);
      if (GATED.includes(target) && window.consoleTask?.gated) { link.setAttribute('aria-disabled', 'true'); link.title = REASON; }
      else if (link.getAttribute('aria-disabled') === 'true') { link.removeAttribute('aria-disabled'); link.removeAttribute('title'); }
    }
    return shown;
  }
  function route(focus = false) {
    // The former `#slow-control[/<UUID>]` route stays a bookmark-compatible alias of Monitor.
    if (location.hash === '#slow-control' || location.hash.startsWith('#slow-control/')) {
      history.replaceState(history.state, '', '#monitor' + location.hash.slice('#slow-control'.length));
    }
    const fragment = location.hash.slice(1) || 'home';
    const parts = fragment.split('/');
    const valid = ['home', 'task', 'workflow', 'run', 'monitor', 'settings'].includes(parts[0]) &&
      (parts.length === 1 || (parts.length === 2 && parts[0] === 'monitor' && uuid.test(parts[1])));
    // A malformed Monitor operation link stays on Monitor and says why; any other unknown
    // route (a typo, an old bookmark) returns to Home (E-8).
    if (!valid && parts[0] !== 'monitor') { history.replaceState(history.state, '', '#home'); route(focus); return; }
    document.getElementById('route-status').textContent = valid ? '' : 'Invalid operation UUID. Enter a complete operation UUID in Monitor.';
    view = valid ? parts[0] : 'monitor'; operation = valid && parts.length === 2 ? parts[1] : null;
    const skip = document.getElementById('skip-to-canvas'); if (skip) skip.hidden = view !== 'workflow';
    document.title = {task: 'SIDERIUS · Task', workflow: 'SIDERIUS · Workflow', run: 'SIDERIUS · Run', settings: 'SIDERIUS · Settings'}[view] || 'SIDERIUS · Candidate console';
    const shown = paint();
    for (const link of document.querySelectorAll('nav a')) {
      if (link.hash === '#' + view) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    }
    window.dispatchEvent(new CustomEvent('console-view', {detail: {view, operation, valid}}));
    if (focus) document.querySelector(`[data-view="${shown}"] h1`).focus();
  }
  window.consoleNavigation = Object.freeze({isOperationId: value => uuid.test(value), get view() {return view;}, get operation() {return operation;}});
  window.addEventListener('hashchange', () => route(true));
  window.addEventListener('console-task', paint);
  // A disabled link does nothing; a typed or bookmarked route still shows why.
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[aria-disabled="true"]');
    if (link) event.preventDefault();
  });
  document.getElementById('skip-to-canvas')?.addEventListener('click', event => { event.preventDefault(); window.editorCircuit?.focusCanvas(); });
  route();
})();
