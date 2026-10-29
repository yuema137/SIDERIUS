/* Workflow page bar (ui-design-spec.md §1.2 L5/L6, canvas-study M1): presentation only.
 * - Save confirmation step: the primary Save (#editor-review) runs the ordinary check
 *   (editor.js Review); when that check succeeds, this step opens with the version name and
 *   #editor-save, which writes exactly the checked bytes (editor.js owns both requests).
 *   A template import's own check does not open it (quietly()).
 * - Task chip: the open setup's own task label (setups.py binds each setup to one task)
 *   and, when the workflow pins one, its task package version; read-only, it opens the
 *   Task tab, where the Task version card (the version switch) lives. A separate
 *   "Task version: not pinned" note appears only when that task declares versions and
 *   the workflow pins none. Task reference review findings and acknowledgements render
 *   in this save step (#editor-task-review).
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
    if (current.taskReview) text.textContent = 'This save also updates task references. Confirm the task findings below, then save.';
    else text.textContent = current.reviewedTypedSource
      ? 'The workflow is checked. Save writes the Python text you typed in Advanced source as a new version.'
      : 'The workflow is checked. Save writes exactly the checked file as a new version.';
    // Red-team S-1: the server lists the comments these exact bytes drop; say so in plain words.
    const lost = current.removedComments, warning = $('editor-save-comments');
    warning.hidden = !lost.length;
    if (lost.length) {
      const shown = lost.slice(0, 3).map(comment => comment.length > 60 ? comment.slice(0, 59) + '…' : comment).join(', ');
      warning.textContent = `Saving rewrites the file: ${lost.length} comment${lost.length === 1 ? '' : 's'} will be removed (${shown}${lost.length > 3 ? ', …' : ''}).`;
    }
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

  // --- Workflow identity: version tag and dirty dot (tour #18) ----------------------------
  const tag = element('span', '', null, 'version-tag'); tag.id = 'editor-version-tag'; tag.hidden = true;
  const dot = element('span', '', tag, 'dirty-dot'); dot.setAttribute('aria-hidden', 'true');
  const tagName = element('span', '', tag, 'version-tag-name');
  const tagDirty = element('span', ' · unsaved changes', tag, 'sr-only');
  $('editor-project').after(tag);
  function syncTag() {
    const current = state(), versions = window.editorVersions;
    const opened = window.consoleSession.connected && current.sourceAvailable && !!current.savedSha256;
    tag.hidden = !opened || !versions?.loaded;
    if (tag.hidden) return;
    // A file the console never saved is not a saved version (red-team A-6/A-7).
    const name = versions.nameFor(current.savedSha256), recorded = versions.recorded(current.savedSha256);
    tagName.textContent = name || 'Not saved here yet';
    tag.classList.toggle('unrecorded', !recorded);
    dot.hidden = !current.dirty; tagDirty.hidden = !current.dirty;
    tag.title = (recorded && name ? `Saved version "${name}"` : 'This file has no version saved in the console yet') +
      (current.dirty ? '. You have unsaved changes.' : '.');
  }
  window.addEventListener('editor-versions', syncTag);

  // --- Task chip -----------------------------------------------------------------------
  function openTaskPanel(focus) {
    const panel = $('editor-task-panel');
    const reveal = () => {
      panel.open = true; panel.scrollIntoView({block: 'start'});
      if (focus) (panel.querySelector('#editor-task-choice, button:not(:disabled)') || panel.querySelector('summary')).focus();
    };
    if (window.consoleNavigation.view === 'task') { reveal(); return; }
    // After the route focuses the Task heading, move focus on to the version card.
    window.addEventListener('console-view', () => setTimeout(reveal), {once: true});
    location.hash = 'task';
  }
  // Walkthrough N1: "Task: not bound" meant "no task version pinned" and read as a setup
  // detached from its task. The chip names the setup's own task; the pin is separate.
  const pin = element('span', 'Task version: not pinned', null, 'version-tag unrecorded');
  pin.id = 'editor-task-version'; pin.hidden = true;
  pin.title = 'Task versions are optional. This workflow does not pin a recorded version of its task package, so it uses the package as it is now. To pin one, open the Task version card from the task chip.';
  $('editor-task-chip').after(pin);
  function ownTask() {
    const setup = window.experimentSetups?.current;
    return setup?.taskId ? window.consoleTask.tasks.find(task => task.task_id === setup.taskId) || null : null;
  }
  function syncChip() {
    const current = state(), chip = $('editor-task-chip'), label = chip.querySelector('.chip-label');
    const opened = window.consoleSession.connected && current.sourceAvailable;
    const binding = current.taskBinding, task = ownTask();
    const needs = opened && !!binding && !current.taskSelected;
    const name = task ? task.label : binding ? binding.package_id : 'not a setup of a configured task';
    label.textContent = !opened ? 'Task: not open' : `Task: ${name}${binding ? ` · version ${binding.revision}` : ''}`;
    pin.hidden = !opened || !!binding || !task?.revision;
    chip.classList.toggle('needs-attention', needs);
    chip.title = needs ? 'Choose the configured task version on the Task tab before saving.' : 'Show the task and the version this workflow uses on the Task tab.';
  }
  $('editor-task-chip').addEventListener('click', () => openTaskPanel(true));
  // Advanced users see the task details open by default; beginners open them from the chip.
  if (window.uiSettings?.isEnabled('advanced')) $('editor-task-panel').open = true;

  // --- Icon buttons and overflow menu -------------------------------------------------
  for (const [id, icon] of [['editor-undo', 'undo-2'], ['editor-redo', 'redo-2']]) {
    const button = $(id); if (!button) continue;
    const text = button.textContent; button.textContent = '';
    button.classList.add('icon-button'); button.dataset.icon = icon; button.setAttribute('aria-label', text);
    element('span', text, button, 'sr-only');
    if (!button.title) button.title = text;
  }
  // Revert keeps a visible label beside its icon, so it never reads as a second Undo (red-team A-5).
  const revert = $('editor-discard-draft');
  if (revert) { revert.dataset.icon = 'rotate-ccw'; revert.classList.add('revert-button'); revert.title = 'Revert to saved: drop unsaved changes (Undo brings them back)'; }
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
    item('Task version', 'flask-conical', () => openTaskPanel(true));
    // Beginner entry (red-team A-3): history lists saved versions and restores one as a draft.
    item('Version history', 'file-clock', () => reveal('editor-history'));
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
      : problems ? `Fix ${problems} problem${problems === 1 ? '' : 's'} to save` : current.saving ? 'Saving…'
      : current.inspectionFailed ? 'Check failed: press Check again' : checking ? 'Checking…' : '';
    $('workflow-next-reason').textContent = !opened || !$('workflow-next-run').disabled ? ''
      : !current.candidateEnabled ? 'Not set up for runs' : 'Save a version to run';
  }
  // controls() announces its state before it sets the buttons' disabled flags: read them after.
  function sync() { syncStrip(); syncChip(); syncTag(); queueMicrotask(syncReasons); fitWorkspace(); }
  new MutationObserver(syncReasons).observe($('editor-problems'), {childList: true, subtree: true, attributes: true});
  window.addEventListener('new-run-gate', syncReasons);
  window.addEventListener('workflow-editor-state', sync);
  for (const name of ['experiment-setup', 'console-task']) window.addEventListener(name, syncChip);
  window.consoleSession.subscribe(sync);
  sync();
  /** Run `action` (sync or async) without opening the save step for the check it causes. */
  async function quietly(action) {
    quiet++;
    try { return await action(); } finally { quiet--; wasReviewed = state().reviewed; }
  }
  window.editorPageBar = Object.freeze({quietly, openTaskPanel});
})();
