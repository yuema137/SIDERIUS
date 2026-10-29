/* Home "Quick start": choose a task, then create a setup from the research-loop template or
 * open one of the task's existing setups; Workflow opens it with the advice field focused.
 * Every list has a loading, empty and failed state (#1131): never a permanent "Loading".
 * Tasks are task-selection.js's; setups and creation go through experiment-setups.js. */
(() => {
  'use strict';
  const TEMPLATE = 'single-loop-with-advice', CREATE = '';
  const SETUP_GUIDE = 'https://github.com/yuema137/SIDERIUS/blob/master/src/tools/candidate_console/README.md#set-up-and-open-the-console';
  const $ = id => document.getElementById(id);
  const session = window.consoleSession, tasks = window.consoleTask;
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
  element('p', 'Choose a task. A ready-made research loop is created for it as an experiment setup and opens in Workflow: set the rounds, stop conditions and training settings, add your advice, then save and run.', dialog, 'muted');
  const taskLabel = element('label', 'Choose a task', dialog); taskLabel.htmlFor = 'quick-start-task';
  const taskSelect = element('select', '', dialog); taskSelect.id = 'quick-start-task';
  const taskState = element('p', '', dialog); taskState.id = 'quick-start-task-state'; taskState.setAttribute('role', 'status');
  const taskRetry = element('button', 'Retry', dialog, 'secondary'); taskRetry.type = 'button'; taskRetry.id = 'quick-start-task-retry';
  const setupLabel = element('label', 'Experiment setup', dialog); setupLabel.htmlFor = 'quick-start-setup';
  const setupSelect = element('select', '', dialog); setupSelect.id = 'quick-start-setup';
  const setupState = element('p', '', dialog); setupState.id = 'quick-start-setup-state'; setupState.setAttribute('role', 'status');
  const nameLabel = element('label', 'Label of the new setup', dialog); nameLabel.htmlFor = 'quick-start-label';
  const name = element('input', '', dialog); name.id = 'quick-start-label'; name.maxLength = 160; name.autocomplete = 'off';
  const state = element('p', '', dialog); state.id = 'quick-start-status'; state.setAttribute('role', 'status');
  const actions = element('div', '', dialog, 'actions');
  const start = element('button', 'Open research loop', actions); start.type = 'button'; start.id = 'quick-start-open';
  const close = element('button', 'Cancel', actions, 'secondary'); close.type = 'button';
  close.addEventListener('click', () => dialog.close());
  let setups = null, setupsFor = null, setupsError = '';

  function renderTasks() {
    const loaded = tasks.state === 'ready', list = loaded ? tasks.tasks : [];
    const previous = taskSelect.value || tasks.selectedId || '';
    taskSelect.replaceChildren(...list.map(task => { const option = element('option', task.label); option.value = task.task_id; return option; }));
    if (list.some(task => task.task_id === previous)) taskSelect.value = previous;
    taskSelect.hidden = taskLabel.hidden = !list.length;
    taskRetry.hidden = tasks.state !== 'error';
    taskState.replaceChildren();
    if (!session.connected) taskState.textContent = 'Connect with your console token first.';
    else if (tasks.state === 'error') taskState.textContent = `Tasks could not be loaded: ${tasks.error}`;
    else if (!loaded) taskState.textContent = 'Loading tasks…';
    else if (!list.length) {
      taskState.textContent = 'No task is configured. Add your task to siderius_workspace/settings/console.json, then restart the console. ';
      const link = element('a', 'How to add a task (step 2)', taskState); link.href = SETUP_GUIDE; link.target = '_blank'; link.rel = 'noopener noreferrer';
    }
  }
  async function loadSetups() {
    const id = taskSelect.value, revision = session.revision;
    if (!id || !session.connected || (setupsFor === id && setups)) { renderSetups(); return; }
    setupsFor = id; setups = null; setupsError = ''; renderSetups();
    try {
      const value = await session.request(`tasks/${encodeURIComponent(id)}/setups`);
      if (id !== taskSelect.value || revision !== session.revision) return;
      setups = value.setups;
    } catch (error) {
      if (error.stale || id !== taskSelect.value) return;
      setupsError = error.message; setupsFor = null;
    }
    renderSetups();
  }
  function renderSetups() {
    const task = tasks.tasks.find(item => item.task_id === taskSelect.value);
    const shown = !!task;
    setupLabel.hidden = setupSelect.hidden = !shown || !setups;
    if (shown && setups) {
      const previous = setupSelect.value;
      const create = element('option', 'Create a setup from the research-loop template'); create.value = CREATE;
      setupSelect.replaceChildren(create, ...setups.map(setup => {
        const option = element('option', setup.label + (setup.runnable ? '' : ' (Runs are not enabled for this setup)')); option.value = setup.setup_id; return option;
      }));
      if ([...setupSelect.options].some(option => option.value === previous)) setupSelect.value = previous;
      if (!name.value || name.dataset.suggested === name.value) { name.value = `${task.label} research loop`; name.dataset.suggested = name.value; }
    }
    const creating = shown && !!setups && setupSelect.value === CREATE;
    nameLabel.hidden = name.hidden = !creating;
    start.textContent = creating ? 'Create and open' : 'Open research loop';
    start.disabled = !session.connected || !shown || !setups;
    setupState.textContent = !shown ? '' : setupsError ? `Setups could not be loaded: ${setupsError} Choose the task again to retry.` : !setups ? 'Loading the setups of this task…' : '';
  }
  function render() { renderTasks(); void loadSetups(); }

  // Resolves true once the editor holds the setup's saved source, false after a bounded
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
  async function focusAdvice() {
    // Advice is the first thing to write (L-6). The inspector may re-render once more after
    // the setup opens; re-focus until the advice field holds focus (bounded). The author's
    // own first click or key ends this at once.
    let acted = false;
    const act = () => { acted = true; };
    document.addEventListener('pointerdown', act, {capture: true, once: true});
    document.addEventListener('keydown', act, {capture: true, once: true});
    try {
      for (const wait of [0, 150, 400, 800]) {
        await new Promise(done => setTimeout(done, wait));
        if (acted || document.activeElement?.classList.contains('advice-input')) break;
        await window.editorAdvice?.focusFirst();
      }
    } finally {
      document.removeEventListener('pointerdown', act, {capture: true});
      document.removeEventListener('keydown', act, {capture: true});
    }
  }
  start.addEventListener('click', async () => {
    const taskId = taskSelect.value, chosen = setupSelect.value, label = name.value.trim();
    if (!taskId || start.disabled) return;
    if (chosen === CREATE && !label) { state.textContent = 'Enter a label for the new setup.'; name.focus(); return; }
    start.disabled = true; state.textContent = chosen === CREATE ? 'Creating the setup…' : 'Opening…';
    try {
      tasks.select(taskId);
      let setupId = chosen;
      if (chosen === CREATE) {
        try { setupId = (await window.experimentSetups.create(TEMPLATE, label))?.setup_id; }
        catch (error) { state.textContent = error.message; return; }
        if (!setupId) return;
        setupsFor = null;
      } else await window.experimentSetups.load(setupId, true);
      location.hash = 'workflow';
      if (editorState().projectId !== setupId) { state.textContent = 'Kept the current workflow.'; return; }
      if (!(await loaded(setupId))) {
        state.textContent = `Couldn't open ${setupId}: ${$('editor-status')?.textContent || 'the workflow did not load.'} Reload the page to try again.`;
        return;
      }
      dialog.close(); state.textContent = '';
      await focusAdvice();
    } finally { start.disabled = false; renderSetups(); }
  });
  taskSelect.addEventListener('change', () => { name.value = ''; void loadSetups(); });
  setupSelect.addEventListener('change', renderSetups);
  taskRetry.addEventListener('click', () => tasks.reload());
  function open() {
    state.textContent = ''; setupsFor = null;
    render();
    if (!dialog.open) dialog.showModal();
    (taskSelect.hidden ? (taskRetry.hidden ? close : taskRetry) : taskSelect).focus();
  }
  $('home-quick-start').addEventListener('click', event => { event.preventDefault(); open(); });
  window.addEventListener('console-task', () => { if (dialog.open) render(); });
  session.subscribe(() => { if (dialog.open) render(); });
  window.quickStart = Object.freeze({open});
})();
