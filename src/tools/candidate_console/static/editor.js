/* Ordinary-file editor: native schemas/catalog stay server-owned. */
(() => {
  'use strict';
  const $ = id => document.getElementById(`editor-${id}`);
  let candidateEnabled = false, sourceAvailable = false;
  let project = '', generation = 0, base = null, graph = null;
  let training = null;
  let taskChoices = null, taskSelection = null, taskMessage = '', taskLoadingRevision = null;
  let taskAcknowledged = false, taskAdopted = false;
  const trainingDrafts = new Map();
  let options = [], selected = null, pending = false, sourceDirty = false, mode = 'source', reviewed = null, conflict = null, saving = false;
  const clone = value => JSON.parse(JSON.stringify(value));
  const status = message => { $('status').textContent = message; };
  const current = (id, version) => project === id && generation === version;
  const node = (tag, text, parent) => {
    const element = document.createElement(tag); element.textContent = text;
    if (parent) parent.append(element); return element;
  };
  const projection = () => Object.freeze({projectId: project, candidateEnabled,
    savedSha256: base?.sha256 || null, dirty: pending, sourceDirty,
    sourceAvailable, reusableSource: base?.document?.definition?.schema_version === 2, saving, conflict: !!conflict});
  window.workflowEditor = Object.freeze({get state() { return projection(); }});
  const bindingEqual = (a, b) => !!a && !!b && ['schema_version', 'package_id', 'revision', 'semantic_fingerprint', 'task_data_path_id'].every(key => a[key] === b[key]);
  const taskReview = () => reviewed?.taskReview;
  function taskAccepted() {
    const review = taskReview();
    return !review || (review.save_supported && !review.findings.some(item => item.state === 'blocked') && taskAcknowledged &&
      (!review.findings.some(item => item.code === 'current_snapshot_adoption') || taskAdopted));
  }
  const canUpdateTask = () => window.consoleSession.connected && sourceAvailable && !!base?.document && graph?.definition.schema_version === 2 &&
    !!taskSelection && !pending && !conflict && !saving && trainingDrafts.size === 0;
  function renderTaskControls() {
    const savedBinding = base?.document?.task_binding;
    const matching = (taskChoices || []).filter(choice => bindingEqual(choice.binding, savedBinding));
    let message = taskMessage;
    if (taskReview()) message = taskReview().save_supported ? 'Task references reviewed, not saved. Review the findings and confirm before saving.' : 'Task reference review is blocked. Keep your draft and inspect the findings.';
    else if (pending && !message) message = "Save existing edits first, then update workflow references. To review a bound draft, select its matching configured task version.";
    else if (!taskChoices?.length && !message) message = 'No version-aware task choices configured. Ordinary unbound editing remains available.';
    else if (savedBinding && !matching.length && !taskSelection && !message) message = 'No configured choice matches the saved binding. Configure a matching choice before reviewing bound edits.';
    else if (!message) message = 'Choose a version, then explicitly update, review and save. Choosing alone does not change source. Changed native identity remains unsupported.';
    window.editorTaskControls.render($('task-controls'), {choices: taskChoices, selection: taskSelection, matching, savedBinding,
      connected: window.consoleSession.connected, saving, canUpdate: canUpdateTask(), message, review: taskReview(),
      acknowledged: taskAcknowledged, adopted: taskAdopted}, {
      select: selectTask, update: updateTask, refresh: () => loadTaskChoices(),
      acknowledge: value => { taskAcknowledged = value; controls(); },
      adopt: value => { taskAdopted = value; controls(); }
    });
  }
  function selectTask(choiceId) {
    if (!window.consoleSession.connected || saving) return;
    const choice = taskChoices?.find(item => item.choice_id === choiceId);
    taskSelection = choice ? {kind: 'task_references', selected_choice_id: choice.choice_id, expected_task_binding: clone(choice.binding)} : null;
    taskMessage = ''; invalidate();
  }
  async function loadTaskChoices() {
    if (!window.consoleSession.connected || taskLoadingRevision === window.consoleSession.revision) return;
    const revision = window.consoleSession.revision; taskLoadingRevision = revision;
    if (taskReview()) invalidate();
    try {
      const value = await api('task-choices');
      if (!window.consoleSession.connected || revision !== window.consoleSession.revision) return;
      taskChoices = value.choices; taskMessage = '';
      if (taskSelection && !taskChoices.some(choice => choice.choice_id === taskSelection.selected_choice_id && bindingEqual(choice.binding, taskSelection.expected_task_binding))) {
        taskSelection = null; taskMessage = 'Configured choice changed; select and review again.';
        invalidate();
      }
      controls();
    } catch (error) {
      if (!error.stale && revision === window.consoleSession.revision) {
        taskChoices = null; taskSelection = null; taskMessage = 'Task choices unavailable: ' + error.message + ' Refresh task choices to retry.';
        taskAcknowledged = false; taskAdopted = false;
        if (taskReview()) invalidate(); else { generation++; controls(); }
      }
    } finally { if (taskLoadingRevision === revision) taskLoadingRevision = null; }
  }
  async function updateTask() {
    if (!canUpdateTask()) return;
    await reviewProposal(clone(taskSelection));
  }
  function controls() {
    window.dispatchEvent(new CustomEvent('workflow-editor-state', {detail: projection()}));
    const connected = window.consoleSession.connected;
    $('project').disabled = !connected || !$('project').options.length;
    const invalidTraining = trainingDrafts.size > 0;
    $('review').disabled = !connected || saving || !graph || invalidTraining || (!!(base?.document?.task_binding || graph?.task_binding) && !taskSelection);
    $('refresh').disabled = !connected || !project;
    $('save').disabled = !connected || saving || !reviewed || reviewed.source !== $('source').value || invalidTraining || !taskAccepted();
    renderTaskControls();
  }
  function invalidate() {
    generation++; reviewed = null; taskAcknowledged = false; taskAdopted = false; controls(); $('diff').textContent = '';
    $('pending').textContent = pending ? (mode === 'document' ? 'Pending inspector edits · Review changes to update Python source before editing it.' : 'Pending source edits · not saved') : 'No pending edits.';
  }
  function changed() { pending = true; $('source').disabled = mode === 'document'; invalidate(); }
  const api = (path, body) => window.consoleSession.request('editor/' + path, body);
  function diagnostic(items = []) { $('diagnostics').textContent = items.map(item => `${item.code}: ${item.message}${item.line ? ` (line ${item.line})` : ''}`).join('\n'); }
  function showConflict(value) {
    conflict = value; reviewed = null; controls();
    $('conflict').hidden = false; $('rebase').disabled = !value.document;
    $('current').textContent = value.source;
    $('conflict-diff').textContent = 'Current disk file version: ' + value.sha256.slice(0, 12) + '\n--- Current disk source\n+++ Pending proposal\n' + value.source.split('\n').map(line => '- ' + line).join('\n') + '\n' + $('source').value.split('\n').map(line => '+ ' + line).join('\n');
    status('Source changed. Pending proposal preserved; inspect current source before choosing a new base.');
  }
  function adopt(value) {
    trainingDrafts.clear();
    taskSelection = null; taskMessage = '';
    sourceAvailable = true; base = value; graph = value.document ? clone(value.document) : null; options = value.binding_options; training = value.training;
    $('source').value = value.source; $('source').disabled = !graph; mode = 'source'; sourceDirty = false; pending = false; conflict = null;
    $('conflict').hidden = true; selected = graph?.definition.nodes.some(n => n.id === selected) ? selected : graph?.definition.nodes[0]?.id;
    invalidate(); diagnostic(value.diagnostics); render();
    $('path').textContent = value.source_path;
    $('revision').textContent = 'File version: ' + value.sha256.slice(0, 12);
    $('inspect').hidden = !!graph;
    status(graph ? 'Opened supported declaration. References remain literal.' : 'Unsupported source is read-only. Repair externally, then refresh.');
  }
  function renderGraph() {
    $('graph').replaceChildren(); $('edges').replaceChildren();
    if (!graph) return;
    for (const item of graph.definition.nodes) {
      const button = node('button', '', $('graph')); button.type = 'button'; button.className = 'editor-node';
      button.setAttribute('aria-pressed', String(item.id === selected)); button.dataset.node = item.id;
      node('strong', item.id, button); node('span', item.capability, button);
      button.addEventListener('click', () => { selected = item.id; render(); });
      const bindings = item.request.kind === 'external' ? [{ name: 'request', source: {kind: 'external', binding: item.request.binding} }] : item.request.arguments;
      for (const binding of bindings) {
        const src = binding.source;
        node('li', `${src.kind === 'external' ? `external:${src.binding}` : `${src.node}.${src.port}`} → ${item.id}.${binding.name}`, $('edges'));
      }
    }
  }
  function field(parent, label, value, update) {
    const wrapper = node('label', label, parent), input = document.createElement('input');
    input.value = value; wrapper.append(input);
    input.addEventListener('input', () => { update(input.value); mode = 'document'; changed(); });
  }
  function renderTraining() {
    const parent = node('fieldset', '', $('inspector'));
    node('legend', 'Native training settings', parent);
    node('p', 'Epochs are ceilings; native planning resolves epochs. Task-owned rules may further constrain this run.', parent);
    node('p', `Preparation output restriction: ${JSON.stringify(training.allowed_output_types)}`, parent);
    const launch = () => (graph.training_settings.launch ||= {});
    const edit = () => { mode = 'document'; changed(); };
    for (const control of training.controls) {
      const wrapper = node('label', control.label, parent);
      const modeSelect = node('select', '', wrapper);
      modeSelect.dataset.trainingMode = control.name;
      for (const [value, title] of [['unset', 'Use native default'], ['supplied', 'Set value'], ...(control.nullable ? [['null', 'None']] : [])]) {
        const option = node('option', title, modeSelect); option.value = value;
      }
      const supplied = graph.training_settings.launch || {};
      modeSelect.value = !Object.hasOwn(supplied, control.name) ? 'unset' : supplied[control.name] === null ? 'null' : 'supplied';
      const input = node('input', '', wrapper); input.dataset.training = control.name;
      input.type = control.kind === 'boolean' ? 'checkbox' : 'number';
      if (input.type === 'number') input.step = control.kind === 'integer' ? '1' : 'any';
      const value = modeSelect.value === 'supplied' ? supplied[control.name] : control.effective;
      if (input.type === 'checkbox') input.checked = value === true; else input.value = value ?? '';
      if (trainingDrafts.has(control.name)) { modeSelect.value = 'supplied'; input.value = trainingDrafts.get(control.name); input.setCustomValidity('Enter a valid number, or choose default / None.'); }
      input.disabled = modeSelect.value !== 'supplied';
      node('small', `Native preview: ${JSON.stringify(control.effective)} (updated on review)`, wrapper);
      const setValue = () => {
        input.setCustomValidity('');
        if (input.type === 'checkbox') launch()[control.name] = input.checked;
        else if (input.value.trim() !== '' && Number.isFinite(input.valueAsNumber) && input.checkValidity()) launch()[control.name] = input.valueAsNumber;
        else { trainingDrafts.set(control.name, input.value); input.setCustomValidity('Enter a valid number, or choose default / None.'); status('Empty numbers are not saved. Enter a value or select default / None.'); return false; }
        trainingDrafts.delete(control.name); return true;
      };
      modeSelect.addEventListener('change', () => {
        input.disabled = modeSelect.value !== 'supplied'; input.setCustomValidity(''); trainingDrafts.delete(control.name);
        if (modeSelect.value === 'unset') delete launch()[control.name];
        else if (modeSelect.value === 'null') launch()[control.name] = null;
        else setValue();
        edit();
      });
      input.addEventListener('input', () => { setValue(); edit(); });
    }
    node('p', 'Workflow parameter rules (exact / range / allowed / predicate):', parent);
    node('pre', JSON.stringify(graph.training_settings.launch?.workflow_parameter_rules ?? null, null, 2), parent);
    const advanced = node('button', 'Edit advanced settings and rules in source', parent); advanced.type = 'button';
    advanced.addEventListener('click', () => { $('advanced').open = true; $('source').focus(); if (mode === 'document') status('Review inspector edits first to update the source.'); });
  }
  function renderInspector() {
    $('inspector').replaceChildren(); $('references').replaceChildren();
    if (!graph) return;
    const item = graph.definition.nodes.find(n => n.id === selected);
    if (item) {
      node('p', `${item.id} · ${item.capability}`, $('inspector'));
      if (item.capability === 'tuning' && training) renderTraining();
      for (const option of options.filter(entry => entry.node === item.id)) {
        const label = node('label', option.argument || 'Request binding', $('inspector'));
        const select = document.createElement('select'); label.append(select);
        const active = option.argument === null ? {kind: 'external', binding: item.request.binding} : item.request.arguments.find(a => a.name === option.argument).source;
        option.choices.forEach((choice, index) => {
          const el = node('option', choice.label, select); el.value = String(index);
          if (JSON.stringify(choice.source) === JSON.stringify(active)) el.selected = true;
        });
        select.dataset.node = item.id; select.dataset.argument = option.argument || 'request';
        select.addEventListener('change', () => {
          const choice = clone(option.choices[Number(select.value)].source);
          if (option.argument === null) item.request.binding = choice.binding;
          else item.request.arguments.find(a => a.name === option.argument).source = choice;
          mode = 'document'; changed(); status('Binding changed locally. Review validates the graph and updates its connections.');
        });
      }
    }
    for (const key of Object.keys(graph.definition.task)) field($('references'), `task.${key}`, graph.definition.task[key], value => { graph.definition.task[key] = value; });
    for (const external of graph.definition.externals) {
      if (external.kind === 'managed_candidate') {
        node('p', `external:${external.id} · ${external.contract} · managed (read-only)`, $('references'));
      } else {
        field($('references'), `external:${external.id}`, external.location, value => { external.location = value; });
      }
    }
  }
  function render() { renderGraph(); renderInspector(); if (sourceDirty) for (const input of document.querySelectorAll('#editor-inspector select, #editor-inspector input, #editor-inspector button, #editor-references input')) input.disabled = true; controls(); }
  function resetProjectState() {
    taskSelection = null; taskMessage = '';
    sourceAvailable = false; pending = false; sourceDirty = false; mode = 'source';
    trainingDrafts.clear();
    base = null; graph = null; conflict = null; reviewed = null; options = []; training = null; selected = null;
    $('conflict').hidden = true; $('rebase').disabled = true;
    $('source').value = ''; $('source').disabled = true;
    $('current').textContent = ''; $('conflict-diff').textContent = '';
    $('path').textContent = ''; $('revision').textContent = '';
    invalidate(); diagnostic(); render(); status('Opening selected project…');
  }
  async function refresh(ask = true) {
    if (!window.consoleSession.connected) return;
    if (pending && ask && !window.confirm('Discard pending edits and refresh from disk?')) return;
    const id = project; invalidate(); const version = generation;
    try { const value = await api(encodeURIComponent(id)); if (current(id, version)) adopt(value); }
    catch (error) { if (error.stale) return; if (current(id, version)) { sourceAvailable = false; controls(); status(error.message + ' Pending state retained.'); } }
  }
  let projectsLoaded = false, loadingRevision = null;
  async function openProjects() {
    if (!window.consoleSession.connected || projectsLoaded || loadingRevision === window.consoleSession.revision) return;
    const revision = window.consoleSession.revision; loadingRevision = revision;
    void loadTaskChoices();
    try {
      const choices = await api('projects');
      $('project').replaceChildren();
      choices.forEach(choice => { const entry = node('option', choice.project_id, $('project')); entry.value = choice.project_id; entry.dataset.runnable = String(choice.candidate_run_enabled); });
      projectsLoaded = true;
      project = choices[0]?.project_id || ''; candidateEnabled = !!choices[0]?.candidate_run_enabled; resetProjectState();
      if (project) await refresh(false); else status('No editor projects configured. Monitoring remains available.');
    } catch (error) { if (!error.stale) status(error.message); }
    finally { if (loadingRevision === revision) loadingRevision = null; }
  }
  function connection() {
    if (!window.consoleSession.connected) { if (taskReview()) invalidate(); else controls(); return; }
    controls();
    if (projectsLoaded) {
      void loadTaskChoices();
      if (!base && project && !pending) void refresh(false);
    } else if (window.consoleNavigation?.view === 'workflow') void openProjects();
  }
  window.consoleSession.subscribe(connection);
  window.addEventListener('console-view', event => { if (event.detail.view === 'workflow') void openProjects(); });
  window.addEventListener('beforeunload', event => { if (pending) { event.preventDefault(); event.returnValue = ''; } });
  $('inspect').addEventListener('click', () => { $('advanced').open = true; $('source').focus(); });
  $('project').addEventListener('change', () => {
    if (!window.consoleSession.connected) { $('project').value = project; return; }
    if (pending && !window.confirm('Discard pending edits and change project?')) { $('project').value = project; return; }
    project = $('project').value; candidateEnabled = $('project').selectedOptions[0]?.dataset.runnable === 'true'; resetProjectState(); refresh(false);
  });
  $('refresh').addEventListener('click', () => refresh());
  $('source').addEventListener('input', () => { mode = 'source'; sourceDirty = true; changed(); for (const input of document.querySelectorAll('#editor-inspector select, #editor-inspector input, #editor-inspector button, #editor-references input')) input.disabled = true; });
  async function reviewProposal(proposal) {
    if (!window.consoleSession.connected || saving || trainingDrafts.size > 0 || !base?.document) return;
    if ((base.document.task_binding || graph?.task_binding) && !taskSelection) { status('Select the configured task version, then review.'); return; }
    invalidate();
    const id = project, version = generation;
    const selection = taskSelection ? clone(taskSelection) : null;
    const body = {expected_sha256: base.sha256, proposal};
    if (proposal.kind !== 'task_references' && (base.document.task_binding || graph?.task_binding)) body.task_reference_selection = selection;
    try {
      const value = await api(`${encodeURIComponent(id)}/review`, body);
      if (!current(id, version)) return;
      $('source').value = value.source; $('source').disabled = false; graph = clone(value.document); mode = 'source'; sourceDirty = false;
      // Choices depend on actual new nodes/externals: refresh projection through
      // the reviewed document using server-derived options returned by review.
      options = value.binding_options; training = value.training; selected = graph.definition.nodes.some(n => n.id === selected) ? selected : graph.definition.nodes[0]?.id;
      pending = value.source !== base.source;
      reviewed = {source: value.source, sha256: value.sha256, base: base.sha256, taskReview: value.task_reference_update,
        taskSelection: value.task_reference_update ? (proposal.kind === 'task_references' ? clone(proposal) : selection) : null};
      $('review-disclosure').open = true;
      $('diff').textContent = value.diff || '(No source changes)'; diagnostic(); render();
      $('pending').textContent = pending ? 'Pending reviewed source · not saved' : 'No source changes; review acceptance may still be required.';
      status(value.task_reference_update ? 'Inspect the Python diff and task findings. Confirm supported findings before saving.' : 'Declaration validated. Inspect the exact Python diff, then save.');
    } catch (error) {
      if (error.stale) return;
      if (!current(id, version)) return;
      if (error.value?.proposal) { const proposal = error.value.proposal; $('source').value = proposal.source; $('source').disabled = false; graph = clone(proposal.document); options = proposal.binding_options; training = proposal.training; mode = 'source'; sourceDirty = false; render(); }
      if (error.value?.current) showConflict(error.value.current);
      diagnostic(error.value?.diagnostics); status(error.message);
    }
  }
  $('review').addEventListener('click', () => reviewProposal(mode === 'document' ? {kind: 'document', document: clone(graph)} : {kind: 'source', source: $('source').value}));
  $('save').addEventListener('click', async () => {
    if (!window.consoleSession.connected || saving || !reviewed || reviewed.source !== $('source').value || !taskAccepted()) return;
    const id = project, version = generation, exact = {...reviewed};
    const body = {source: exact.source, proposal_sha256: exact.sha256, expected_sha256: exact.base};
    if (exact.taskReview) body.task_reference_acceptance = {selection: clone(exact.taskSelection),
      acknowledged_findings: exact.taskReview.findings.map(({code, reference}) => ({code, reference})), adopt_current_snapshot: taskAdopted};
    saving = true; controls();
    try {
      const saved = await api(`${encodeURIComponent(id)}/save`, body);
      if (!current(id, version)) return;
      const value = await api(encodeURIComponent(id)); if (!current(id, version)) return;
      if (value.sha256 !== saved.sha256) { showConflict(value); status('Save completed, then source changed again. Pending reviewed bytes retained.'); return; }
      adopt(value); status(saved.unchanged ? 'Source unchanged; confirmed from disk.' : 'Saved reviewed bytes and reloaded from disk. Recovery copies preserved.');
    } catch (error) {
      if (error.stale) return;
      if (!current(id, version)) return;
      if (error.value?.current) showConflict(error.value.current);
      status(error.message + ' Save is unconfirmed; pending proposal retained. Refresh to inspect disk.');
      reviewed = null;
    } finally { saving = false; controls(); }
  });
  $('discard').addEventListener('click', () => { if (conflict) adopt(conflict); });
  $('rebase').addEventListener('click', () => {
    if (!conflict) return;
    // A form proposal first becomes source via Review; a changed-base review
    // may fail before rendering, so preserve the form graph for re-review.
    base = conflict; conflict = null; $('conflict').hidden = true;
    $('revision').textContent = 'File version: ' + base.sha256.slice(0, 12);
    changed(); status('Current disk source chosen as base. Reconcile your proposal, then review again.');
  });
})();
