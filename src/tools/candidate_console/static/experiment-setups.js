/* Experiment setups of the selected task (Workflow page bar) and the "New setup…" dialog.
 * Presentation only. Lists come from GET /api/tasks/{task_id}/setups (setups.py owns
 * which setups belong to a task) and GET /api/editor/projects (legacy projects that match
 * no configured task are listed after them); POST /api/tasks/{task_id}/setups creates one.
 * editor.js owns the open project: this module only hands it the list (useSetups). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const session = window.consoleSession, tasks = window.consoleTask;
  const BLANK = '';
  const REFUSED_403 = 'Creating setups in the browser is turned off for this console. The console operator turns it on with "experiment_setups": {"browser_creatable": true} in siderius_workspace/settings/console.json, then restarts the console (init writes this for new workspaces).';
  let list = [], loadedKey = null, loading = null, catalog = null, error = '';
  const el = (tag, text, parent, className) => {
    const node = document.createElement(tag); if (text) node.textContent = text;
    if (className) node.className = className; if (parent) parent.append(node); return node;
  };
  const say = text => { $('setup-state').textContent = text; $('setup-state').hidden = !text; };
  const openId = () => window.workflowEditor.state.projectId;
  const current = () => list.find(item => item.id === openId()) || null;

  // --- List -------------------------------------------------------------------------
  async function load(preferred = null, force = false) {
    const taskId = tasks.selectedId, revision = session.revision, key = `${revision}/${taskId}`;
    if (!session.connected || !taskId || (!force && (loadedKey === key || loading === key))) return;
    loading = key; say('Loading the experiment setups of this task…');
    try {
      const [projects, ...perTask] = await Promise.all([session.request('editor/projects'),
        ...tasks.tasks.map(task => session.request(`tasks/${encodeURIComponent(task.task_id)}/setups`))]);
      if (revision !== session.revision || taskId !== tasks.selectedId) return;
      const byTask = Object.fromEntries(tasks.tasks.map((task, index) => [task.task_id, perTask[index].setups]));
      const matched = new Set(Object.values(byTask).flat().map(setup => setup.setup_id));
      list = [
        ...byTask[taskId].map(setup => ({id: setup.setup_id, label: setup.label, runnable: setup.runnable, refsMatchTask: setup.refs_match_task, group: 'task', taskId})),
        ...projects.filter(item => !matched.has(item.project_id))
          .map(item => ({id: item.project_id, label: item.project_id, runnable: item.candidate_run_enabled, refsMatchTask: null, group: 'other', taskId: null}))
      ];
      loadedKey = key; error = ''; say('');
      window.workflowEditor.useSetups(list, preferred);
    } catch (failure) {
      if (failure.stale || revision !== session.revision) return;
      error = failure.message; say(`Experiment setups could not be loaded: ${failure.message}`);
    } finally { if (loading === key) loading = null; }
    render();
  }
  function render() {
    const item = current(), task = tasks.selected;
    $('setup-drift').hidden = !(item && item.refsMatchTask === false);
    $('setup-new').disabled = !session.connected || !task;
    $('setup-retry').hidden = !error;
    // Run page header: which setup and task a new run uses.
    $('run-setup-header').hidden = !item;
    $('run-setup-header').textContent = item ? `Setup: ${item.label} · Task: ${item.group === 'task' && task ? task.label : 'not bound to a configured task'}` : '';
    window.dispatchEvent(new CustomEvent('experiment-setup', {detail: {setup: item, task}}));
  }

  // --- New setup dialog ---------------------------------------------------------------
  const dialog = el('dialog', '', document.body, 'setup-new'); dialog.id = 'setup-new-dialog';
  dialog.setAttribute('aria-labelledby', 'setup-new-title');
  el('h2', 'New experiment setup', dialog).id = 'setup-new-title';
  const intro = el('p', '', dialog, 'muted'); intro.id = 'setup-new-intro';
  const shapes = el('fieldset', '', dialog, 'setup-new-shapes'); el('legend', 'Start from', shapes);
  const nameLabel = el('label', 'Label', dialog); nameLabel.htmlFor = 'setup-new-label';
  const name = el('input', '', dialog); name.id = 'setup-new-label'; name.maxLength = 160; name.autocomplete = 'off';
  const status = el('p', '', dialog); status.id = 'setup-new-status'; status.setAttribute('role', 'status');
  const actions = el('div', '', dialog, 'actions');
  const create = el('button', 'Create setup', actions); create.type = 'button'; create.id = 'setup-new-create';
  const cancel = el('button', 'Cancel', actions, 'secondary'); cancel.type = 'button';
  cancel.addEventListener('click', () => dialog.close());
  function shape(value, title, description, checked) {
    const option = el('label', '', shapes, 'setup-new-shape'), input = el('input', '', option);
    input.type = 'radio'; input.name = 'setup-new-shape'; input.value = value; input.checked = checked;
    const text = el('span', '', option); el('strong', title, text); el('span', description, text);
  }
  async function showShapes(preferred) {
    shapes.querySelectorAll('.setup-new-shape').forEach(node => node.remove());
    try { catalog ||= (await session.request('editor/templates')).templates; }
    catch (failure) { if (!failure.stale) status.textContent = `Templates unavailable: ${failure.message}. You can still start blank.`; }
    for (const template of catalog || []) shape(template.id, template.title, template.description, template.id === preferred);
    shape(BLANK, 'Blank', 'One Propose step; add modules on the canvas.', !(catalog || []).some(template => template.id === preferred));
  }
  async function submit(templateId, label) {
    const task = tasks.selected;
    if (!task || !session.connected) return null;
    try {
      const view = await session.request(`tasks/${encodeURIComponent(task.task_id)}/setups`, {label, template_id: templateId || null});
      await load(view.setup_id, true);
      return view;
    } catch (failure) {
      if (failure.stale) return null;
      const finding = failure.value?.finding?.message;
      throw new Error(failure.status === 403 ? REFUSED_403 : failure.message + (finding ? ` ${finding}` : ''));
    }
  }
  create.addEventListener('click', async () => {
    const label = name.value.trim(), chosen = shapes.querySelector('input:checked')?.value ?? BLANK;
    if (!label) { status.textContent = 'Enter a label for the setup.'; name.focus(); return; }
    create.disabled = true; status.textContent = 'Creating…';
    try {
      const view = await submit(chosen, label);
      if (view) { dialog.close(); location.hash = 'workflow'; }
    } catch (failure) { status.textContent = failure.message; }
    finally { create.disabled = false; }
  });
  async function open(preferred = 'single-loop-with-advice') {
    const task = tasks.selected; if (!task) return;
    intro.textContent = `A setup is one workflow for the task "${task.label}". Choose how it starts and give it a label; you can change the workflow afterwards.`;
    status.textContent = ''; name.value = '';
    if (!dialog.open) dialog.showModal();
    await showShapes(preferred); name.focus();
  }
  $('setup-new').addEventListener('click', () => void open());
  $('setup-retry').addEventListener('click', () => void load(null, true));
  $('setup-drift-update').addEventListener('click', () => window.editorPageBar?.openTaskPanel(true));

  for (const name of ['console-task', 'workflow-editor-state']) window.addEventListener(name, render);
  window.addEventListener('console-task', () => {
    if (['workflow', 'run'].includes(window.consoleNavigation?.view)) void load();
  });
  session.subscribe(render);
  render();
  window.experimentSetups = Object.freeze({load: (preferred, force) => load(preferred, force), open, create: submit,
    get list() { return list; }, get current() { return current(); }});
})();
