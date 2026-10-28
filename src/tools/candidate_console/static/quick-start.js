/* Home "Quick start": choose a project (it carries its own task and data references),
 * then open the default research-loop template in it as an unsaved draft.
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
  element('p', 'Choose a project. A ready-made research loop opens in it as an unsaved draft: set the rounds, stop conditions and training settings, add your advice, then save and run.', dialog, 'muted');
  const label = element('label', 'Project (its task and data)', dialog); label.htmlFor = 'quick-start-project';
  const select = element('select', '', dialog); select.id = 'quick-start-project';
  const state = element('p', '', dialog); state.id = 'quick-start-status'; state.setAttribute('role', 'status');
  const actions = element('div', '', dialog, 'actions');
  const start = element('button', 'Open research loop', actions); start.type = 'button'; start.id = 'quick-start-open';
  const close = element('button', 'Cancel', actions, 'secondary'); close.type = 'button';
  close.addEventListener('click', () => dialog.close());
  // Options mirror the editor's own project list (one owner); refreshed whenever it changes.
  function options() {
    // Runnable projects first; edit-only ones last and labelled (L-7).
    const source = [...$('editor-project').options].sort((a, b) => Number(b.dataset.runnable === 'true') - Number(a.dataset.runnable === 'true'));
    const previous = select.value;
    select.replaceChildren(...source.map(item => {
      const option = element('option', item.textContent + (item.dataset.runnable === 'true' ? '' : ' (edit only, not runnable)'));
      option.value = item.value; option.dataset.runnable = item.dataset.runnable; return option;
    }));
    select.value = source.some(item => item.value === previous) ? previous : $('editor-project').value;
    start.disabled = !source.length || !window.consoleSession.connected;
    state.textContent = source.length ? '' : 'Loading projects…';
    warn();
  }
  const warning = element('p', '', dialog, 'muted'); warning.id = 'quick-start-warning';
  dialog.insertBefore(warning, state);
  function warn() {
    const runnable = select.selectedOptions[0]?.dataset.runnable === 'true';
    warning.textContent = select.value && !runnable ? 'You can edit this project but not run it from this console.' : '';
  }
  select.addEventListener('change', warn);
  new MutationObserver(options).observe($('editor-project'), {childList: true});
  // Resolves true once the editor holds the project's saved source, false after a bounded
  // wait (L-3): the dialog must never hang on "Opening…".
  const LOAD_MS = 20000;
  const loaded = project => new Promise(resolve => {
    let timer = null;
    const check = () => {
      const value = editorState();
      if (value.projectId === project && value.savedSha256 && !value.saving) { finish(true); return true; }
      return false;
    };
    const finish = ok => { clearTimeout(timer); window.removeEventListener('workflow-editor-state', check); resolve(ok); };
    if (!check()) { window.addEventListener('workflow-editor-state', check); timer = setTimeout(() => finish(false), LOAD_MS); }
  });
  start.addEventListener('click', async () => {
    const project = select.value;
    if (!project || start.disabled) return;
    start.disabled = true; state.textContent = 'Opening…';
    try {
      // Read the project once first, so an unopenable source fails here with its reason
      // and the button stays available for a retry (L-3).
      try { await window.consoleSession.request('editor/' + encodeURIComponent(project)); }
      catch (error) { if (!error.stale) state.textContent = `Couldn't open ${project}: ${String(error.message).replace(/[.\s]*$/, '.')} Fix it, then try again.`; return; }
      if ($('editor-project').value === project && !editorState().savedSha256 && !$('editor-refresh').disabled) $('editor-refresh').click();
      if ($('editor-project').value !== project) {
        $('editor-project').value = project;
        $('editor-project').dispatchEvent(new Event('change'));
        if ($('editor-project').value !== project) { state.textContent = 'Kept the current workflow.'; return; }
      }
      if (!(await loaded(project))) {
        state.textContent = `Couldn't open ${project}: ${$('editor-status')?.textContent || 'the workflow did not load.'} Reload the page to try again.`;
        return;
      }
      const imported = await window.editorTemplates.importById(DEFAULT_TEMPLATE);
      if (imported) {
        dialog.close(); state.textContent = '';
        // Advice is the first thing to write (L-6). The import's own focus ran while this
        // modal still made the page inert, and the inspector may re-render once more after
        // the draft settles; re-focus until the advice field holds focus (bounded).
        for (const wait of [0, 150, 400, 800]) {
          await new Promise(done => setTimeout(done, wait));
          if (document.activeElement?.classList.contains('advice-input')) break;
          await window.editorAdvice?.focusFirst();
        }
        return;
      }
      state.textContent = $('editor-template-status')?.textContent || 'The research loop could not be opened.';
    } finally { start.disabled = false; }
  });
  function open() {
    location.hash = 'workflow';
    state.textContent = '';
    options();
    if (!dialog.open) dialog.showModal();
    select.focus();
  }
  $('home-quick-start').addEventListener('click', event => { event.preventDefault(); open(); });
  window.consoleSession.subscribe(options);
  window.quickStart = Object.freeze({open});
})();
