/* Ordinary-file editor: native schemas/catalog stay server-owned. */
(() => {
  'use strict';
  const $ = id => document.getElementById(`editor-${id}`);
  let candidateEnabled = false, sourceAvailable = false;
  let project = '', generation = 0, base = null, graph = null;
  let training = null, loopTemplate = null;
  let taskChoices = null, taskSelection = null, taskMessage = '', taskLoadingRevision = null;
  let taskAcknowledged = false, taskAdopted = false;
  const trainingDrafts = new Map();
  // Invalid research-loop field drafts (limit, stop conditions); like training drafts they block Review.
  const loopDrafts = new Map();
  const draftsPending = () => trainingDrafts.size > 0 || loopDrafts.size > 0;
  let inventory = [], selected = null, pending = false, sourceDirty = false, mode = 'source', reviewed = null, conflict = null, saving = false;
  let bindingDraft = null, bindingDraftConflict = false;
  const clone = value => JSON.parse(JSON.stringify(value));
  const status = message => { $('status').textContent = message; };
  const current = (id, version) => project === id && generation === version;
  const node = (tag, text, parent) => {
    const element = document.createElement(tag); element.textContent = text;
    if (parent) parent.append(element); return element;
  };
  const cancelDraftButton = node('button', 'Cancel binding draft', $('pending').parentElement);
  cancelDraftButton.id = 'editor-cancel-binding-draft'; cancelDraftButton.type = 'button'; cancelDraftButton.hidden = true;
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
    !!taskSelection && !pending && !conflict && !saving && !draftsPending();
  function renderTaskControls() {
    const savedBinding = base?.document?.task_binding;
    const matching = (taskChoices || []).filter(choice => bindingEqual(choice.binding, savedBinding));
    let message = taskMessage;
    if (taskReview()) message = taskReview().save_supported ? 'Task references reviewed, not saved. Review the findings and confirm before saving.' : 'Task reference review is blocked. Keep your draft and inspect the findings.';
    else if (pending && !message) message = "Save existing edits first, then update workflow references. To review a bound draft, select its matching configured task version.";
    // The view explains an empty or unloaded choice list next to the saved task state.
    else if (!taskChoices?.length && !message) message = '';
    else if (savedBinding && !matching.length && !taskSelection && !message) message = 'No configured choice matches the saved binding. Configure a matching choice before reviewing bound edits.';
    else if (!message) message = 'Choose a version, then explicitly update, review and save. Choosing alone does not change source. Switching checked versions requires a supported fresh candidate.';
    window.editorTaskControls.render($('task-controls'), {choices: taskChoices, selection: taskSelection, matching, savedBinding,
      connected: window.consoleSession.connected, projectOpen: !!base?.document, saving, canUpdate: canUpdateTask(), message, review: taskReview(),
      acknowledged: taskAcknowledged, adopted: taskAdopted}, {
      select: selectTask, update: updateTask, refresh: () => loadTaskChoices(),
      acknowledge: value => { taskAcknowledged = value; controls(); },
      adopt: value => { taskAdopted = value; controls(); }
    });
  }
  function selectTask(choiceId) {
    if (!window.consoleSession.connected || saving) return;
    const choice = taskChoices?.find(item => item.choice_id === choiceId);
    if (mode === 'binding-draft' && choice && base?.document?.task_binding &&
        !bindingEqual(choice.binding, base.document.task_binding)) {
      status('A binding draft can only use the configured task choice matching its saved task identity.'); controls(); return;
    }
    taskSelection = choice ? {kind: 'task_references', selected_choice_id: choice.choice_id, expected_task_binding: clone(choice.binding)} : null;
    taskMessage = '';
    if (mode === 'binding-draft') { reviewed = null; controls(); return; }
    invalidate();
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
        if (mode === 'binding-draft') controls(); else invalidate();
      }
      controls();
    } catch (error) {
      if (!error.stale && revision === window.consoleSession.revision) {
        taskChoices = null; taskSelection = null; taskMessage = 'Task choices unavailable: ' + error.message + ' Refresh task choices to retry.';
        taskAcknowledged = false; taskAdopted = false;
        if (taskReview()) invalidate(); else if (mode === 'binding-draft') controls(); else { generation++; controls(); }
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
    const invalidTraining = draftsPending();
    const draftIncomplete = mode === 'binding-draft' && bindingDraft?.inspection?.status !== 'complete';
    $('review').disabled = !connected || saving || !graph || invalidTraining || draftIncomplete || bindingDraftConflict || (!!(base?.document?.task_binding || graph?.task_binding) && !taskSelection);
    $('refresh').disabled = !connected || !project;
    $('save').disabled = !connected || saving || !reviewed || reviewed.source !== $('source').value || invalidTraining || bindingDraftConflict || !taskAccepted();
    cancelDraftButton.hidden = !bindingDraft || bindingDraftConflict;
    cancelDraftButton.disabled = !connected || saving;
    renderTaskControls();
    window.editorCircuit?.setEnabled(canEditCircuit());
    window.editorLoopControls?.setEnabled($('loop'), canEditLoop());
  }
  function invalidate() {
    generation++; reviewed = null; taskAcknowledged = false; taskAdopted = false; controls(); $('diff').textContent = '';
    $('pending').textContent = bindingDraft
      ? `Pending binding draft · ${bindingDraft.inspection?.status || 'checking'}`
      : pending ? (mode === 'document' ? 'Pending inspector edits · Review changes to update Python source before editing it.'
        : mode === 'loop' ? 'Pending research-loop edits · Review changes to update Python source before editing it.' : 'Pending source edits · not saved') : 'No pending edits.';
  }
  function changed() { pending = true; $('source').disabled = ['document', 'loop', 'binding-draft'].includes(mode); invalidate(); }
  const api = (path, body) => window.consoleSession.request('editor/' + path, body);
  function diagnostic(items = []) { $('diagnostics').textContent = items.map(item => `${item.code}: ${item.message}${item.line ? ` (line ${item.line})` : ''}${item.field_path ? ` at ${item.field_path.join('.')}` : ''}`).join('\n'); }
  function showConflict(value, isBindingDraft = false) {
    bindingDraftConflict = isBindingDraft;
    conflict = value; reviewed = null; controls();
    $('conflict').hidden = false; $('rebase').disabled = isBindingDraft || !value.document;
    $('current').textContent = value.source;
    const proposal = bindingDraft
      ? bindingDraft.bindings.map(item => `${item.source ? 'Bind' : 'Disconnect'} ${item.node}.${item.argument ?? 'request'}`).join('\n')
      : $('source').value;
    $('conflict-diff').textContent = `Current disk file version: ${value.sha256.slice(0, 12)}\n--- Current disk source\n${value.source.split('\n').map(line => '- ' + line).join('\n')}\n+++ Pending proposal\n${proposal.split('\n').map(line => '+ ' + line).join('\n')}`;
    status('Source changed. Pending proposal preserved; inspect current source before choosing a new base.');
  }
  function showTaskRefusal(proposal, selection) {
    $('source').value = proposal.source; $('source').disabled = false;
    graph = clone(proposal.document); inventory = proposal.port_inventory || []; training = proposal.training; loopTemplate = proposal.loop_template || null;
    mode = 'source'; sourceDirty = false; pending = proposal.source !== base.source;
    taskAcknowledged = false; taskAdopted = false;
    reviewed = {source: proposal.source, sha256: proposal.sha256, base: base.sha256,
      taskReview: proposal.task_reference_update, taskSelection: clone(selection)};
    $('diff').textContent = proposal.diff || '(No source changes)';
    diagnostic(); render();
  }
  // Only a 422 refusal of the loop's fields (request schema) or of the declaration at its
  // definition earns the stop-condition hint; auth, size, conflict and source-text errors do not.
  const loopDeclarationRefusal = error => error.status === 422 && (error.code === 'validation' ||
    (error.code === 'source' && (error.value?.diagnostics || []).some(item => item.code === 'validation' && item.field_path?.[0] === 'definition')));
  const hasSourceConflict = error => error.code === 'conflict' ||
    (error.value?.current && error.value.current.sha256 !== base?.sha256);
  function adopt(value) {
    trainingDrafts.clear(); loopDrafts.clear();
    taskSelection = null; taskMessage = '';
    bindingDraft = null; bindingDraftConflict = false;
    sourceAvailable = true; base = value; graph = value.document ? clone(value.document) : null; inventory = value.port_inventory || []; training = value.training; loopTemplate = value.loop_template || null;
    $('source').value = value.source; $('source').disabled = !graph; mode = 'source'; sourceDirty = false; pending = false; conflict = null;
    $('conflict').hidden = true; selected = graph?.definition.nodes.some(n => n.id === selected) ? selected : graph?.definition.nodes[0]?.id;
    invalidate(); diagnostic(value.diagnostics); render();
    $('path').textContent = value.source_path;
    $('revision').textContent = 'File version: ' + value.sha256.slice(0, 12);
    $('inspect').hidden = !!graph;
    status(graph ? 'Opened supported declaration. References remain literal.' : 'Unsupported source is read-only. Repair externally, then refresh.');
  }
  const canEditCircuit = () => window.consoleSession.connected && sourceAvailable && !!graph && !sourceDirty && !saving && !conflict && !draftsPending();
  // An invalid limit draft must stay editable so the author can correct it.
  const canEditLoop = () => window.consoleSession.connected && sourceAvailable && !!graph && !sourceDirty && !saving && !conflict &&
    mode !== 'binding-draft' && trainingDrafts.size === 0;
  function projectBindingDraft() {
    inventory = clone(base.port_inventory || []);
    for (const option of inventory) {
      const patch = bindingDraft?.bindings.find(value => value.node === option.node && value.argument === option.argument);
      if (!patch) continue;
      option.source = patch.source ? clone(patch.source) : null;
      option.bound = patch.source !== null;
    }
  }
  function updateBindingDraft(nodeId, argument, source) {
    if (!canEditCircuit() || !base?.document || bindingDraftConflict) return;
    if (!bindingDraft && base.document.task_binding && taskSelection &&
        !bindingEqual(taskSelection.expected_task_binding, base.document.task_binding)) {
      status('Select the configured choice matching the saved task identity before editing its bindings.'); return;
    }
    if (pending && mode !== 'binding-draft') {
      status('Review/save or discard the current edits before starting a connection draft.'); return;
    }
    const option = inventory.find(value => value.node === nodeId && value.argument === argument);
    if (!option) return;
    if (source !== null && !option.choices.some(value => JSON.stringify(value.source) === JSON.stringify(source))) return;
    if (source === null && !option.bound) return;
    if (JSON.stringify(option.source) === JSON.stringify(source)) return;
    bindingDraft ||= {base_document: clone(base.document), bindings: [], inspection: null};
    const index = bindingDraft.bindings.findIndex(value => value.node === nodeId && value.argument === argument);
    if (JSON.stringify(base.port_inventory?.find(value => value.node === nodeId && value.argument === argument)?.source ?? null) === JSON.stringify(source)) {
      if (index >= 0) bindingDraft.bindings.splice(index, 1);
    } else {
      const patch = {node: nodeId, argument, source: source ? clone(source) : null};
      if (index >= 0) bindingDraft.bindings[index] = patch; else bindingDraft.bindings.push(patch);
    }
    mode = 'binding-draft'; pending = true; reviewed = null; projectBindingDraft(); changed(); render();
    if (bindingDraft.bindings.length === 0) { cancelBindingDraft(); return; }
    bindingDraft.inspection = null; controls();
    status('Checking binding draft with the workflow declaration validator…');
    void inspectBindingDraft();
  }
  async function inspectBindingDraft() {
    if (!bindingDraft || mode !== 'binding-draft' || !window.consoleSession.connected) return;
    const id = project, version = generation;
    const request = {base_document: clone(bindingDraft.base_document), bindings: clone(bindingDraft.bindings)};
    try {
      const value = await api(`${encodeURIComponent(id)}/draft`, {expected_sha256: base.sha256, draft: request});
      if (!current(id, version) || mode !== 'binding-draft') return;
      bindingDraft = {...value.draft, inspection: value.inspection}; projectBindingDraft();
      $('pending').textContent = `Pending binding draft · ${value.inspection.status}`;
      diagnostic(value.inspection.diagnostics.map(message => ({code: value.inspection.status, message})));
      controls(); render();
      status(value.inspection.status === 'complete'
        ? 'Declaration valid; execution readiness is not checked. Review the exact Python changes before saving.'
        : `${value.inspection.status}: ${value.inspection.diagnostics.join(' ')}`);
    } catch (error) {
      if (error.stale || !current(id, version)) return;
      if (hasSourceConflict(error) && error.value?.current) showConflict(error.value.current, true);
      else status(error.message + ' The connection draft remains local and unchanged.');
    }
  }
  function cancelBindingDraft() {
    if (!bindingDraft || bindingDraftConflict || saving) return;
    generation++; bindingDraft = null; bindingDraftConflict = false; conflict = null;
    mode = 'source'; pending = false; reviewed = null; sourceDirty = false;
    graph = base?.document ? clone(base.document) : null; inventory = base?.port_inventory || [];
    $('source').value = base?.source || ''; $('source').disabled = !graph;
    $('pending').textContent = 'No pending edits.';
    diagnostic(); $('conflict').hidden = true; $('rebase').disabled = true;
    render(); status('Binding draft cancelled. Saved workflow source is unchanged.');
  }
  cancelDraftButton.addEventListener('click', cancelBindingDraft);
  function renderGraph() {
    $('edges').replaceChildren();
    const id = project, document = graph;
    const live = () => project === id && graph === document;
    window.editorCircuit.render($('graph'), {viewKey: id, document: graph, inventory, selected, enabled: canEditCircuit(),
      allowBindingChange: !pending || mode === 'binding-draft', allowMove: mode !== 'binding-draft'}, {
      select: value => { if (live()) { selected = value; render(); } },
      bind: (nodeId, argument, source) => { if (live()) updateBindingDraft(nodeId, argument, source); },
      disconnect: (nodeId, argument) => { if (live()) updateBindingDraft(nodeId, argument, null); },
      move: layout => {
        if (!live() || !canEditCircuit()) return;
        if (mode === 'binding-draft') { status('Cancel or review the binding draft before changing node positions.'); return; }
        for (const {node: nodeId, x, y} of layout) {
          const position = graph.positions.find(value => value.node === nodeId);
          if (position) { position.x = x; position.y = y; } else graph.positions.push({node: nodeId, x, y});
        }
        mode = 'document'; changed(); render(); status('Node position changed locally. Review and save to keep the layout.');
      }
    });
    if (!graph) return;
    for (const option of inventory) {
      const destination = `${option.node}.${option.argument ?? 'request'}`;
      const source = option.source;
      const mapping = source
        ? `${source.kind === 'external' ? `external:${source.binding}` : `${source.node}.${source.port}`} → ${destination}`
        : `${option.required ? 'Required' : 'Optional'} · unbound → ${destination}`;
      node('li', mapping, $('edges'));
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
    advanced.addEventListener('click', () => { $('advanced').open = true; $('source').focus(); if (mode === 'document' || mode === 'loop') status('Review inspector edits first to update the source.'); });
  }
  function renderInspector() {
    $('inspector').replaceChildren(); $('references').replaceChildren();
    if (!graph) return;
    const capturedGraph = graph;
    const item = graph.definition.nodes.find(n => n.id === selected);
    if (item) {
      const heading = node('div', '', $('inspector'));
      const capabilityLabel = window.editorCapabilityPresentation.append(heading, item.capability, item.id, 'inspector-capability-heading');
      heading.setAttribute('aria-label', `${capabilityLabel}, instance ${item.id}`);
      const mapping = node('details', '', $('inspector')); mapping.className = 'inspector-mapping';
      node('summary', 'Mapping details', mapping);
      const mappingList = node('dl', '', mapping); mappingList.className = 'inspector-mapping-list';
      node('dt', 'Capability ID', mappingList); node('dd', item.capability, mappingList);
      node('dt', 'Instance ID', mappingList); node('dd', item.id, mappingList);
      if (item.request.kind === 'protocol') { node('dt', 'Protocol', mappingList); node('dd', item.request.protocol, mappingList); }
      const protocolMapping = inventory.find(entry => entry.node === item.id)?.protocol_mapping;
      if (protocolMapping) {
        node('dt', 'Protocol owner', mappingList); node('dd', protocolMapping.owner, mappingList);
        node('dt', 'Mapped input contract', mappingList); node('dd', protocolMapping.output_contract.id, mappingList);
      }
      for (const option of inventory.filter(entry => entry.node === item.id)) {
        node('dt', option.argument || 'Request', mappingList);
        node('dd', option.source ? (option.source.kind === 'external' ? `external:${option.source.binding}` : `${option.source.node}.${option.source.port}`) : 'unbound', mappingList);
      }
      if (item.capability === 'tuning' && training) renderTraining();
      for (const option of inventory.filter(entry => entry.node === item.id)) {
        const state = option.bound ? 'bound' : option.required ? 'Required · unbound' : 'Optional · unbound';
        const label = node('label', `${option.argument || 'Request'} · ${option.socket_contract.id} · ${state}`, $('inspector'));
        const select = document.createElement('select'); label.append(select);
        if (!option.bound) {
          const empty = node('option', option.required ? 'Required input is unbound' : 'Unbound (optional)', select);
          empty.value = ''; empty.disabled = true; empty.selected = true;
        }
        option.choices.forEach((choice, index) => {
          const el = node('option', choice.label, select); el.value = String(index);
          el.title = `${choice.contract.id}: ${choice.contract.native_type}`;
          if (option.source && JSON.stringify(choice.source) === JSON.stringify(option.source)) el.selected = true;
        });
        select.title = `${option.socket_contract.native_type}${option.protocol_mapping ? `; mapped by ${option.protocol_mapping.owner} (${option.protocol_mapping.id}) to ${option.protocol_mapping.output_contract.id}` : ''}`;
        select.setAttribute('aria-label', `${item.id}.${option.argument || 'request'} ${option.required ? 'required' : 'optional'} input, ${option.socket_contract.native_type}`);
        select.dataset.node = item.id; select.dataset.argument = option.argument || 'request';
        select.addEventListener('change', () => {
          if (graph === capturedGraph && select.value !== '') updateBindingDraft(item.id, option.argument, option.choices[Number(select.value)].source);
        });
        const disconnect = node('button', 'Disconnect', $('inspector'));
        disconnect.type = 'button'; disconnect.className = 'editor-disconnect';
        disconnect.setAttribute('aria-label', `Disconnect ${item.id}.${option.argument || 'request'}`);
        disconnect.disabled = !option.bound || bindingDraftConflict || (pending && mode !== 'binding-draft');
        disconnect.hidden = !option.bound;
        disconnect.addEventListener('click', () => { if (graph === capturedGraph) updateBindingDraft(item.id, option.argument, null); });
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
  function renderLoop() {
    if (!graph) { $('loop').replaceChildren(); return; }
    const capturedGraph = graph;
    const live = () => graph === capturedGraph && canEditLoop();
    // Loop-only edits are reviewed as a typed loop patch on the exact current
    // source; with other inspector edits pending, the whole document carries them.
    const loopMode = () => { if (mode !== 'document') mode = 'loop'; };
    const edit = message => { loopMode(); changed(); render(); status(message); };
    window.editorLoopControls.render($('loop'), {loop: graph.definition.loop || null, template: loopTemplate,
      drafts: loopDrafts, nodes: graph.definition.nodes, profile: graph.execution_profile || null, enabled: canEditLoop()}, {
      add: () => {
        if (!live() || graph.definition.loop || !loopTemplate) return;
        graph.definition.loop = clone(loopTemplate);
        edit(`Research loop added locally (final iteration ${loopTemplate.final_iteration}). Review and save to update the source.`);
      },
      remove: () => {
        if (!live() || !graph.definition.loop) return;
        delete graph.definition.loop; loopDrafts.clear();
        edit('Research loop removed locally. Review and save to update the source.');
      },
      limit: input => {
        if (!live() || !graph.definition.loop) return;
        input.setCustomValidity('');
        if (input.value.trim() !== '' && Number.isInteger(input.valueAsNumber) && input.checkValidity()) {
          graph.definition.loop.final_iteration = input.valueAsNumber; loopDrafts.delete('final_iteration');
          status('Iteration limit changed locally. Review and save to update the source.');
        } else {
          loopDrafts.set('final_iteration', input.value); input.setCustomValidity('Enter a whole number of at least 1.');
          status('Invalid iteration limits are not reviewed. Enter a whole number of at least 1.');
        }
        loopMode(); changed();
      },
      // Stop-condition edits (editor-loop-controls.js) mutate only the live draft loop.
      edit: (mutate, message, rerender = false) => {
        if (!live() || !graph.definition.loop) return;
        mutate(graph.definition.loop); loopMode(); changed(); if (rerender) render(); status(message);
      }
    });
  }
  function render() {
    renderGraph(); renderInspector(); renderLoop();
    if (sourceDirty) for (const input of document.querySelectorAll('#editor-inspector select, #editor-inspector input, #editor-inspector button, #editor-references input')) input.disabled = true;
    if (pending && mode !== 'binding-draft') for (const input of document.querySelectorAll('#editor-inspector select[data-node], #editor-inspector .editor-disconnect')) input.disabled = true;
    if (mode === 'binding-draft') for (const input of document.querySelectorAll('#editor-inspector select, #editor-inspector input, #editor-inspector button, #editor-references input')) {
      if (!input.matches('select[data-node], .editor-disconnect')) input.disabled = true;
      else input.disabled = bindingDraftConflict || saving;
    }
    controls();
  }
  function resetProjectState() {
    taskSelection = null; taskMessage = '';
    sourceAvailable = false; pending = false; sourceDirty = false; mode = 'source';
    trainingDrafts.clear(); loopDrafts.clear();
    base = null; graph = null; conflict = null; reviewed = null; inventory = []; training = null; loopTemplate = null; selected = null;
    bindingDraft = null; bindingDraftConflict = false;
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
    } else if (['workflow', 'run'].includes(window.consoleNavigation?.view)) void openProjects();
  }
  window.consoleSession.subscribe(connection);
  window.addEventListener('console-view', event => { if (['workflow', 'run'].includes(event.detail.view)) void openProjects(); });
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
    if (!window.consoleSession.connected || saving || draftsPending() || !base?.document) return;
    if (proposal.kind === 'draft' && bindingDraft?.inspection?.status !== 'complete') {
      status('The binding draft must pass declaration validation before review.'); return;
    }
    if ((base.document.task_binding || graph?.task_binding) && !taskSelection) { status('Select the configured task version, then review.'); return; }
    invalidate();
    const id = project, version = generation;
    const selection = taskSelection ? clone(taskSelection) : null;
    const body = {expected_sha256: base.sha256, proposal};
    if (proposal.kind !== 'task_references' && (base.document.task_binding || graph?.task_binding)) body.task_reference_selection = selection;
    try {
      const value = await api(`${encodeURIComponent(id)}/review`, body);
      if (!current(id, version)) return;
      bindingDraft = null; bindingDraftConflict = false;
      $('source').value = value.source; $('source').disabled = false; graph = clone(value.document); mode = 'source'; sourceDirty = false;
      // Choices depend on actual new nodes/externals: refresh projection through
      // the reviewed document using server-derived options returned by review.
      inventory = value.port_inventory || []; training = value.training; loopTemplate = value.loop_template || null; selected = graph.definition.nodes.some(n => n.id === selected) ? selected : graph.definition.nodes[0]?.id;
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
      if (hasSourceConflict(error) && error.value?.current) {
        showConflict(error.value.current, mode === 'binding-draft');
        diagnostic(error.value?.diagnostics); status(error.message); return;
      }
      if (error.value?.proposal) { const proposal = error.value.proposal; bindingDraft = null; bindingDraftConflict = false; $('source').value = proposal.source; $('source').disabled = false; graph = clone(proposal.document); inventory = proposal.port_inventory || []; training = proposal.training; loopTemplate = proposal.loop_template || null; mode = 'source'; sourceDirty = false; render(); }
      if (error.value?.proposal?.task_reference_update) showTaskRefusal(error.value.proposal, selection || error.value.proposal);
      else if (mode === 'binding-draft' && ['draft_incomplete', 'draft_invalid'].includes(error.code)) {
        bindingDraft.inspection = {status: error.code.slice('draft_'.length), diagnostics: [error.message]};
        controls(); render();
      }
      diagnostic(error.value?.diagnostics);
      status(proposal.kind === 'loop' ? `Review refused the research loop: ${error.message}.${proposal.loop?.stop_conditions?.length && loopDeclarationRefusal(error) ? ' ' + window.editorLoopControls.refusalHint : ''}` : error.message);
    }
  }
  $('review').addEventListener('click', () => reviewProposal(mode === 'binding-draft'
    ? {kind: 'draft', draft: {base_document: clone(bindingDraft.base_document), bindings: clone(bindingDraft.bindings)}}
    : mode === 'document' ? {kind: 'document', document: clone(graph)}
    : mode === 'loop' ? {kind: 'loop', source: $('source').value, loop: graph.definition.loop ? clone(graph.definition.loop) : null}
    : {kind: 'source', source: $('source').value}));
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
      if (hasSourceConflict(error) && error.value?.current) { showConflict(error.value.current); reviewed = null; }
      else if (error.value?.proposal?.task_reference_update) {
        showTaskRefusal(error.value.proposal, exact.taskSelection);
        status(error.message + ' Task reference save refused; pending proposal retained. Correct the task sources and review again.');
        return;
      } else reviewed = null;
      status(error.message + ' Save is unconfirmed; pending proposal retained. Refresh to inspect disk.');
    } finally { saving = false; controls(); }
  });
  $('discard').addEventListener('click', () => { if (conflict) adopt(conflict); });
  $('rebase').addEventListener('click', () => {
    if (!conflict || bindingDraftConflict) return;
    // A form proposal first becomes source via Review; a changed-base review
    // may fail before rendering, so preserve the form graph for re-review.
    base = conflict; conflict = null; $('conflict').hidden = true;
    $('revision').textContent = 'File version: ' + base.sha256.slice(0, 12);
    changed(); status('Current disk source chosen as base. Reconcile your proposal, then review again.');
  });
})();
