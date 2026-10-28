/* Workflow page bar (ui-design-spec.md §1.2 L5/L6, canvas-study M1): presentation only.
 * - Save confirmation step: the primary Save (#editor-review) runs the ordinary check
 *   (editor.js Review); when that check succeeds, this step opens with the version name and
 *   #editor-save, which writes exactly the checked bytes (editor.js owns both requests).
 *   A template import's own check does not open it (quietly()).
 * - Task chip: the saved task package/version in one line; it opens the task details.
 * - Undo/Redo/Revert as icon buttons (editor-draft.js creates them) and a `⋯` overflow menu.
 * - Workspace height: the docked rail | canvas | Selection frame fills the window below the
 *   page bar (--workspace-height); the rail and Selection scroll inside it.
 * It reads window.workflowEditor.state and never mutates a draft, request or run. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const strip = $('editor-save-confirm');
  let quiet = 0, wasReviewed = false, open = false;
  const state = () => window.workflowEditor.state;
  const element = (tag, text, parent, className) => {
    const value = document.createElement(tag); value.textContent = text;
    if (className) value.className = className;
    if (parent) parent.append(value); return value;
  };

  // --- Save confirmation step -------------------------------------------------------
  function showStrip(value) {
    open = value; strip.hidden = !value; fitWorkspace();
    if (value) { $('editor-save').focus({preventScroll: true}); strip.scrollIntoView({block: 'nearest'}); }
  }
  function summary(current) {
    const text = $('editor-save-summary'); text.replaceChildren();
    if (current.taskReview) {
      text.append('This save also updates task references. Confirm the findings under Task package and version, then save. ');
      const show = element('button', 'Show task findings', text, 'link-button'); show.type = 'button';
      show.addEventListener('click', () => openTaskPanel(true));
    } else text.textContent = current.reviewedTypedSource
      ? 'The workflow is checked. Save writes the Python text you typed in Advanced source as a new version.'
      : 'The workflow is checked. Save writes exactly the checked file as a new version.';
  }
  function syncStrip() {
    const current = state();
    // Opens on each new successful check; closes when an edit invalidates it or after Save.
    if (current.reviewed && !wasReviewed && !quiet) showStrip(true);
    if (!current.reviewed && open) showStrip(false);
    wasReviewed = current.reviewed;
    if (open) summary(current);
  }
  $('editor-save-cancel').addEventListener('click', () => { showStrip(false); $('editor-review').focus(); });
  strip.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); showStrip(false); $('editor-review').focus(); } });
  // Pressing Save again re-opens the step even when the check result is unchanged.
  $('editor-review').addEventListener('click', () => { wasReviewed = false; });

  // --- Task chip -----------------------------------------------------------------------
  function openTaskPanel(focus) {
    const panel = $('editor-task-panel'); panel.open = true;
    panel.scrollIntoView({block: 'start'});
    if (focus) (panel.querySelector('#editor-task-acknowledge, #editor-task-choice, button:not(:disabled)') || panel.querySelector('summary')).focus();
  }
  function syncChip() {
    const current = state(), chip = $('editor-task-chip'), label = chip.querySelector('.chip-label');
    const opened = window.consoleSession.connected && current.sourceAvailable;
    const binding = current.taskBinding;
    const needs = opened && !!binding && !current.taskSelected;
    label.textContent = !opened ? 'Task: not open' : binding ? `Task: ${binding.package_id} · ${binding.revision}` : 'Task: not bound';
    chip.classList.toggle('needs-attention', needs || current.taskReview);
    chip.title = needs ? 'Choose the configured task version before saving.' : 'Show the task package and version this workflow uses.';
  }
  $('editor-task-chip').addEventListener('click', () => openTaskPanel(true));
  // Advanced users see the task details open by default; beginners open them from the chip.
  if (window.uiSettings?.isEnabled('advanced')) $('editor-task-panel').open = true;

  // --- Icon buttons and overflow menu -------------------------------------------------
  for (const [id, icon] of [['editor-undo', 'undo-2'], ['editor-redo', 'redo-2'], ['editor-discard-draft', 'rotate-ccw']]) {
    const button = $(id); if (!button) continue;
    const text = button.textContent; button.textContent = '';
    button.classList.add('icon-button'); button.dataset.icon = icon; button.setAttribute('aria-label', text);
    element('span', text, button, 'sr-only');
    if (!button.title) button.title = text;
  }
  function menu() {
    const box = element('details', '', document.querySelector('#view-workflow .workflow-next'), 'overflow-menu');
    const summaryButton = element('summary', '', box, 'icon-button'); summaryButton.dataset.icon = 'ellipsis';
    summaryButton.setAttribute('aria-label', 'More actions'); summaryButton.title = 'More actions';
    const list = element('div', '', box, 'overflow-list'); list.setAttribute('role', 'menu');
    const item = (text, icon, run, flag = null) => {
      const button = element('button', text, list, 'secondary'); button.type = 'button'; button.setAttribute('role', 'menuitem');
      if (icon) button.dataset.icon = icon;
      if (flag) button.dataset.uiFlag = flag;
      button.addEventListener('click', () => { box.open = false; run(); });
    };
    const reveal = id => { const target = $(id); target.open = true; target.scrollIntoView({block: 'start'}); target.querySelector('summary')?.focus(); };
    item('New from template…', 'layout-template', () => window.editorTemplates?.open());
    item('Take the tour', 'circle-question-mark', () => window.consoleOnboarding?.open(0));
    item('Task package and version', 'flask-conical', () => openTaskPanel(true));
    item('Version history', 'file-clock', () => reveal('editor-history'), 'advanced');
    item('Advanced source', 'code-xml', () => reveal('editor-advanced'), 'advanced');
    item('Settings…', 'settings', () => $('settings-toggle').click());
    box.addEventListener('keydown', event => { if (event.key === 'Escape' && box.open) { box.open = false; summaryButton.focus(); } });
    document.addEventListener('pointerdown', event => { if (box.open && !box.contains(event.target)) box.open = false; });
  }
  menu();

  // --- Workspace height --------------------------------------------------------------
  let frame = 0;
  function fitWorkspace() {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const workspace = document.querySelector('#view-workflow .editor-workspace');
      if (!workspace || !workspace.getClientRects().length) return;
      // Measured as if scrolled to the top; the open save step adds to the page, not the frame.
      const top = workspace.getBoundingClientRect().top + scrollY - (open ? strip.offsetHeight + 16 : 0);
      document.documentElement.style.setProperty('--workspace-height', Math.max(480, Math.floor(innerHeight - top - 16)) + 'px');
    });
  }
  addEventListener('resize', fitWorkspace);
  window.addEventListener('console-view', fitWorkspace);
  window.addEventListener('ui-settings-change', fitWorkspace);
  new ResizeObserver(fitWorkspace).observe(document.querySelector('#view-workflow .page-bar'));

  // Why Save / Next: Run are disabled, inline beside them (spec §9).
  function syncReasons() {
    const current = state(), connected = window.consoleSession.connected, opened = connected && current.sourceAvailable;
    const problems = document.querySelectorAll('#editor-problems .editor-problem').length;
    const checking = /checking/.test($('editor-pending').textContent);
    $('editor-save-reason').textContent = !opened || !$('editor-review').disabled ? ''
      : problems ? `Fix ${problems} problem${problems === 1 ? '' : 's'} to save` : current.saving ? 'Saving…' : checking ? 'Checking…' : '';
    $('workflow-next-reason').textContent = !opened || !$('workflow-next-run').disabled ? ''
      : !current.candidateEnabled ? 'Not set up for runs' : 'Save a version to run';
  }
  // controls() announces its state before it sets the buttons' disabled flags: read them after.
  function sync() { syncStrip(); syncChip(); queueMicrotask(syncReasons); fitWorkspace(); }
  new MutationObserver(syncReasons).observe($('editor-problems'), {childList: true, subtree: true, attributes: true});
  window.addEventListener('new-run-gate', syncReasons);
  window.addEventListener('workflow-editor-state', sync);
  window.consoleSession.subscribe(sync);
  sync();
  /** Run `action` (sync or async) without opening the save step for the check it causes. */
  async function quietly(action) {
    quiet++;
    try { return await action(); } finally { quiet--; wasReviewed = state().reviewed; }
  }
  window.editorPageBar = Object.freeze({quietly, openTaskPanel});
})();
