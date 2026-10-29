/* Socket tooltip (ui-design-spec.md §6.2/§6.3 "Socket tooltip"): presentation only.
 * One shared, non-interactive tooltip for every canvas socket ([data-tip="port"]) and
 * icon-only canvas control ([data-tip-label], one line):
 *   [swatch] connector name / data description / "Connects with: …" / "Required." (unbound)
 * Name and description come from the server connector catalog (editor-contract-presentation
 * describe), "Connects with" from the server-offered choices (editor-circuit sets it).
 * Schema and protocol ids are never shown here (Mapping details, advanced, hold them).
 * Timing: 300ms after pointer enter, immediately on keyboard focus; hides 150ms after the
 * pointer leaves, on blur, Esc, scroll or a canvas re-render. It never takes pointer events. */
(() => {
  'use strict';
  const graph = document.getElementById('editor-graph');
  const contracts = () => window.editorContractPresentation;
  const tip = document.createElement('div');
  tip.id = 'circuit-tooltip'; tip.className = 'circuit-tooltip'; tip.setAttribute('role', 'tooltip'); tip.hidden = true;
  document.body.append(tip);
  let trigger = null, showTimer = 0, hideTimer = 0;
  const line = (text, className) => { const value = document.createElement('p'); value.textContent = text; if (className) value.className = className; tip.append(value); };
  function fill(port) {
    tip.replaceChildren();
    // Icon-only canvas controls: a one-line name (spec §6.1 tooltip).
    if (port.dataset.tipLabel) { line(port.dataset.tipLabel, 'circuit-tooltip-name'); return; }
    const token = contracts().describe(port.dataset.contract);
    const head = document.createElement('p'); head.className = 'circuit-tooltip-name';
    const swatch = document.createElement('span'); swatch.className = 'circuit-contract-swatch'; swatch.setAttribute('aria-hidden', 'true');
    contracts().decorate(swatch, port.dataset.contract, port.dataset.required !== 'false');
    head.append(swatch, document.createTextNode(token.name)); tip.append(head);
    if (token.description) line(token.description, 'circuit-tooltip-help');
    if (port.dataset.tipConnects) line(`Connects with: ${port.dataset.tipConnects}`, 'circuit-tooltip-help');
    if (port.dataset.required === 'true' && port.classList.contains('is-unbound')) line('Required.', 'circuit-tooltip-required');
  }
  function place() {
    if (!trigger?.isConnected) { hide(true); return; }
    const box = trigger.getBoundingClientRect(), width = tip.offsetWidth, height = tip.offsetHeight, gap = 4;
    // Above the socket when there is room, otherwise below; never over the trigger.
    const top = box.top - gap - height >= 8 ? box.top - gap - height : box.bottom + gap;
    tip.style.left = Math.round(Math.max(8, Math.min(box.left, innerWidth - width - 8))) + 'px';
    tip.style.top = Math.round(Math.min(top, innerHeight - height - 8)) + 'px';
  }
  function show(port) {
    clearTimeout(hideTimer); trigger = port; fill(port); tip.hidden = false; place();
    port.setAttribute('aria-describedby', tip.id);
  }
  function hide(now = false) {
    clearTimeout(showTimer);
    const run = () => { tip.hidden = true; trigger?.removeAttribute('aria-describedby'); trigger = null; };
    if (now) run(); else { clearTimeout(hideTimer); hideTimer = setTimeout(run, 150); }
  }
  const portOf = event => event.target instanceof Element ? event.target.closest('[data-tip="port"][data-contract], [data-tip-label]') : null;
  graph.addEventListener('pointerover', event => {
    const port = portOf(event); if (!port || port === trigger) return;
    clearTimeout(showTimer); showTimer = setTimeout(() => show(port), trigger ? 0 : 300);
  });
  graph.addEventListener('pointerout', event => { const port = portOf(event); if (port && !port.contains(event.relatedTarget)) hide(); });
  graph.addEventListener('focusin', event => { const port = portOf(event); if (port && port.matches(':focus-visible')) show(port); });
  graph.addEventListener('focusout', event => { if (portOf(event)) hide(true); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !tip.hidden) hide(true); });
  addEventListener('scroll', () => { if (!tip.hidden) hide(true); }, {passive: true, capture: true});
  new MutationObserver(() => { if (trigger && !trigger.isConnected) hide(true); }).observe(graph, {childList: true, subtree: true});
})();
