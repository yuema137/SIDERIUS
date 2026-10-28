/* Home "Quick start": choose a task (an editor project with its own task and data
 * references), then open the default research-loop template in it as an unsaved draft.
 * Reuses the template gallery's import path; rounds, stop conditions and training
 * settings are then edited in the ordinary panel and recorded in the workflow source. */
(() => {
  'use strict';
  // No task declares its own template yet; this catalog entry is the default for all.
  const DEFAULT_TEMPLATE = 'single-research-loop';
  const $ = id => document.getElementById(id);
  const editorState = () => window.workflowEditor.state;
  function element(tag, text, parent, className) {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    if (className) el.className = className;
    parent?.append(el);
    return el;
  }
  const dialog = element('dialog', '', document.body, 'quick-start'); dialog.id = 'quick-start-dialog';
  dialog.setAttribute('aria-labelledby', 'quick-start-title');
  element('h2', 'Quick start', dialog).id = 'quick-start-title';
  element('p', 'Choose a task. Its ready-made research loop opens as an unsaved draft: set the rounds, stop conditions and training settings, add your advice, then save and run.', dialog, 'muted');
  const label = element('label', 'Task', dialog); label.htmlFor = 'quick-start-project';
  const select = element('select', '', dialog); select.id = 'quick-start-project';
  const state = element('p', '', dialog); state.id = 'quick-start-status'; state.setAttribute('role', 'status');
  const actions = element('div', '', dialog, 'actions');
  const start = element('button', 'Open research loop', actions); start.type = 'button'; start.id = 'quick-start-open';
  const close = element('button', 'Cancel', actions, 'secondary'); close.type = 'button';
  close.addEventListener('click', () => dialog.close());
  // Options mirror the editor's own project list (one owner); refreshed whenever it changes.
  function options() {
    const source = [...$('editor-project').options];
    const previous = select.value;
    select.replaceChildren(...source.map(item => {
      const option = element('option', item.textContent + (item.dataset.runnable === 'true' ? '' : ' (edit only, not runnable)'));
      option.value = item.value; return option;
    }));
    select.value = source.some(item => item.value === previous) ? previous : $('editor-project').value;
    start.disabled = !source.length || !window.consoleSession.connected;
    state.textContent = source.length ? '' : 'Loading tasks…';
  }
  new MutationObserver(options).observe($('editor-project'), {childList: true});
  const loaded = project => new Promise(resolve => {
    const check = () => {
      const value = editorState();
      if (value.projectId === project && value.savedSha256 && !value.saving) { window.removeEventListener('workflow-editor-state', check); resolve(); return true; }
      return false;
    };
    if (!check()) window.addEventListener('workflow-editor-state', check);
  });
  start.addEventListener('click', async () => {
    const project = select.value;
    if (!project || start.disabled) return;
    start.disabled = true; state.textContent = 'Opening…';
    try {
      if ($('editor-project').value !== project) {
        $('editor-project').value = project;
        $('editor-project').dispatchEvent(new Event('change'));
        if ($('editor-project').value !== project) { state.textContent = 'Kept the current workflow.'; return; }
      }
      await loaded(project);
      const imported = await window.editorTemplates.importById(DEFAULT_TEMPLATE);
      if (imported) { dialog.close(); return; }
      state.textContent = $('editor-template-status')?.textContent || 'The research loop could not be opened.';
    } finally { start.disabled = false; }
  });
  function open() {
    location.hash = 'workflow';
    options();
    if (!dialog.open) dialog.showModal();
    select.focus();
  }
  $('home-quick-start').addEventListener('click', event => { event.preventDefault(); open(); });
  window.consoleSession.subscribe(options);
  window.quickStart = Object.freeze({open});
})();
