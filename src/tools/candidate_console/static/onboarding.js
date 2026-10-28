/* Opt-in onboarding tour of the Workflow page (ui-design-spec.md §7.3, 4 steps, within the
 * 3-4 step limit). Presentation only: it owns no request, draft or run state and never starts
 * itself. The empty canvas "Take the 4-step tour" and the header Help button open it. Each
 * step highlights a real visible element; there is no backdrop, so the page stays usable.
 * Skip (or Esc) stores `dismissed`, OK stores `done` under siderius.console.tour.v1. */
(() => {
  'use strict';
  const KEY = 'siderius.console.tour.v1';
  // Heading <= 4 words, body <= 120 characters (spec §7.3).
  const STEPS = [
    {title: 'Choose a task', anchors: ['#editor-project', '.workflow-project'],
      text: 'Pick a workflow project. Its task package and version appear beside it.'},
    {title: 'Pick a module', anchors: ['#editor-palette'],
      text: 'Each module in the list is one research step. Click it or drag it onto the canvas.'},
    {title: 'Match connector names', anchors: ['.circuit-viewport', '.workflow-canvas-panel'],
      text: 'Connect an output to an input with the same connector name and colour.'},
    {title: 'Save a version', anchors: ['#editor-save', '.workflow-actions'],
      text: 'Review the exact changes, then save. Run unlocks for saved versions.'},
  ];
  let outcome = null, step = -1, card = null, target = null, opener = null, frame = 0;
  try { outcome = localStorage.getItem(KEY); } catch { /* Storage denial keeps this page's outcome in memory. */ }

  const visible = element => !!element && element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden';
  const anchorFor = index => STEPS[index].anchors.map(selector => document.querySelector(selector)).find(visible) || null;
  const announce = () => window.dispatchEvent(new CustomEvent('console-onboarding', {detail: {outcome, step}}));

  function remember(value) {
    outcome = value;
    try { localStorage.setItem(KEY, value); } catch { /* Keep working without persistent storage. */ }
  }
  function build() {
    card = document.createElement('section');
    card.id = 'onboarding-tour'; card.className = 'onboarding-tour'; card.hidden = true;
    card.setAttribute('role', 'dialog'); card.setAttribute('aria-modal', 'false'); card.setAttribute('aria-labelledby', 'onboarding-title');
    card.innerHTML = '<p class="onboarding-count" id="onboarding-count"></p><h2 id="onboarding-title"></h2><p id="onboarding-text"></p>' +
      '<div class="onboarding-actions"><button type="button" class="secondary" id="onboarding-close">Skip</button>' +
      '<button type="button" class="secondary" id="onboarding-back">Back</button><button type="button" id="onboarding-next">Next</button></div>';
    document.body.append(card);
    card.querySelector('#onboarding-back').addEventListener('click', () => show(step - 1));
    card.querySelector('#onboarding-next').addEventListener('click', () => { if (step < STEPS.length - 1) show(step + 1); else close('done'); });
    card.querySelector('#onboarding-close').addEventListener('click', () => close('dismissed'));
    card.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); close('dismissed'); } });
  }
  function place() {
    frame = 0;
    if (step < 0 || !card) return;
    const next = anchorFor(step);
    if (next !== target) { target?.classList.remove('onboarding-target'); target = next; target?.classList.add('onboarding-target'); }
    const gap = 4, margin = 8, box = card.getBoundingClientRect(), width = box.width, height = box.height;
    let left = margin, top = innerHeight - height - margin;
    if (target) {
      const r = target.getBoundingClientRect();
      // Prefer the side with room: right, below, left, above; then clamp into the window.
      if (r.right + gap + width <= innerWidth - margin) { left = r.right + gap; top = r.top; }
      else if (r.bottom + gap + height <= innerHeight - margin) { left = r.left; top = r.bottom + gap; }
      else if (r.left - gap - width >= margin) { left = r.left - gap - width; top = r.top; }
      else { left = r.left; top = r.top - gap - height; }
    }
    card.style.left = Math.round(Math.min(Math.max(left, margin), innerWidth - width - margin)) + 'px';
    card.style.top = Math.round(Math.min(Math.max(top, margin), innerHeight - height - margin)) + 'px';
  }
  const schedule = () => { if (!frame) frame = requestAnimationFrame(place); };
  function show(index) {
    if (!card) build();
    step = Math.max(0, Math.min(index, STEPS.length - 1));
    const item = STEPS[step];
    card.querySelector('#onboarding-count').textContent = `${step + 1}/${STEPS.length}`;
    card.querySelector('#onboarding-title').textContent = item.title;
    card.querySelector('#onboarding-text').textContent = item.text;
    card.querySelector('#onboarding-back').disabled = step === 0;
    card.querySelector('#onboarding-next').textContent = step === STEPS.length - 1 ? 'OK' : 'Next';
    card.dataset.step = String(step + 1);
    card.hidden = false;
    anchorFor(step)?.scrollIntoView({block: 'nearest', inline: 'nearest'});
    place();
    card.querySelector('#onboarding-next').focus({preventScroll: true});
    announce();
  }
  function open(index = 0) {
    opener = document.activeElement;
    if (window.consoleNavigation?.view !== 'workflow') {
      // The tour explains the Workflow page; show it once that view is visible.
      window.addEventListener('console-view', () => requestAnimationFrame(() => show(index)), {once: true});
      location.hash = 'workflow';
      return;
    }
    show(index);
  }
  function close(result) {
    if (step < 0) return;
    step = -1; card.hidden = true;
    target?.classList.remove('onboarding-target'); target = null;
    if (result) remember(result);
    announce();
    if (opener?.isConnected) opener.focus({preventScroll: true});
    opener = null;
  }
  addEventListener('scroll', schedule, {passive: true, capture: true});
  addEventListener('resize', schedule);
  addEventListener('console-view', event => { if (event.detail.view !== 'workflow') close(null); });
  document.getElementById('onboarding-help').addEventListener('click', () => open(0));
  window.consoleOnboarding = Object.freeze({get outcome() { return outcome; }, get step() { return step; }, steps: STEPS.length, open, close: () => close(null)});
})();
