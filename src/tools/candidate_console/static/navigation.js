/* Fragment routes select persistent panels; controllers retain all working state. */
(() => {
  'use strict';
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  let view = 'home', operation = null;
  function route(focus = false) {
    // The former `#slow-control[/<UUID>]` route stays a bookmark-compatible alias of Monitor.
    if (location.hash === '#slow-control' || location.hash.startsWith('#slow-control/')) {
      history.replaceState(history.state, '', '#monitor' + location.hash.slice('#slow-control'.length));
    }
    const fragment = location.hash.slice(1) || 'home';
    const parts = fragment.split('/');
    const valid = ['home', 'workflow', 'run', 'monitor', 'settings'].includes(parts[0]) &&
      (parts.length === 1 || (parts.length === 2 && parts[0] === 'monitor' && uuid.test(parts[1])));
    // A malformed Monitor operation link stays on Monitor and says why; any other unknown
    // route (a typo, an old bookmark) returns to Home (E-8).
    if (!valid && parts[0] !== 'monitor') { history.replaceState(history.state, '', '#home'); route(focus); return; }
    document.getElementById('route-status').textContent = valid ? '' : 'Invalid operation UUID. Enter a complete operation UUID in Monitor.';
    view = valid ? parts[0] : 'monitor'; operation = valid && parts.length === 2 ? parts[1] : null;
    const skip = document.getElementById('skip-to-canvas'); if (skip) skip.hidden = view !== 'workflow';
    document.title = {workflow: 'SIDERIUS · Workflow', run: 'SIDERIUS · Run', settings: 'SIDERIUS · Settings'}[view] || 'SIDERIUS · Candidate console';
    for (const panel of document.querySelectorAll('[data-view]')) panel.hidden = panel.dataset.view !== view;
    for (const link of document.querySelectorAll('nav a')) {
      if (link.hash === '#' + view) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    }
    window.dispatchEvent(new CustomEvent('console-view', {detail: {view, operation, valid}}));
    if (focus) document.querySelector(`[data-view="${view}"] h1`).focus();
  }
  window.consoleNavigation = Object.freeze({isOperationId: value => uuid.test(value), get view() {return view;}, get operation() {return operation;}});
  window.addEventListener('hashchange', () => route(true));
  document.getElementById('skip-to-canvas')?.addEventListener('click', event => { event.preventDefault(); window.editorCircuit?.focusCanvas(); });
  route();
})();
