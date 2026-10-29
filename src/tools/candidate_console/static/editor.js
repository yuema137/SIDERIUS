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
  let inventory = [], selected = null, sourceDirty = false, reviewed = null, conflict = null, saving = false;
  // One unified draft (editor-draft.js): document edits, binding patches over their anchor, history.
  let draft = null, bindings = [], anchor = null, inspection = null, inspecting = null;
  // Red-team E-5: the last server check that failed ({key, message}); its draft state shows
  // "check failed" and a Check again action instead of waiting forever, and is not re-sent
  // automatically. Any edit changes the key, so the new state is checked as usual.
  let inspectFailure = null;
  const Outcome = window.editorSaveOutcome;
  // Pending palette nodes and new inputs (draft `nodes`/`externals`, editor-node-drafts.js); `graph` stays the
  // edited document, `display` adds them. Server nodes-draft views are cached by key; the last one is reused while checking.
  let pendingNodes = [], newExternals = [], removedNodes = [], display = null, lastNodeView = null, inspectingNode = null; const nodeViews = new Map();
  const Draft = window.editorDraft, NodeDrafts = window.editorNodeDrafts, hasBindings = () => bindings.length > 0, bindingKey = () => Draft.canonical(bindings);
  const hasNodeDraft = () => pendingNodes.length > 0 || newExternals.length > 0 || removedNodes.length > 0, isPending = id => pendingNodes.some(item => item.node === id);
  const nodeKey = () => NodeDrafts.key(draftState()), nodeView = () => nodeViews.get(nodeKey());
  // A conflict with server-inspected patches (bindings, nodes or inputs) cannot rebase.
  const pending = () => sourceDirty || !!draft?.dirty, bindingConflict = () => !!conflict && (hasBindings() || hasNodeDraft());
  const draftState = () => ({document: graph, bindings, anchor, nodes: pendingNodes, externals: newExternals, removed: removedNodes, training, loopTemplate});
  const reproject = () => { ({graph: display, inventory} = graph ? NodeDrafts.project(draftState(), nodeView() || lastNodeView) : {graph: null, inventory: []}); };
  // Draft state of one server projection; the edited document never aliases its anchor.
  const viewState = value => ({document: clone(value.document), bindings: [], training: value.training, loopTemplate: value.loop_template || null,
    anchor: {source: value.source, document: clone(value.document), inventory: clone(value.port_inventory || []), managedRoles: clone(value.managed_roles || [])}});
  const clone = value => JSON.parse(JSON.stringify(value));
  const status = message => { $('status').textContent = message; };
  const current = (id, version) => project === id && generation === version;
  const node = (tag, text, parent) => {
    const element = document.createElement(tag); element.textContent = text;
    if (parent) parent.append(element); return element;
  };
  // An invalid training/loop field draft blocks undo/redo: restoring a state would drop its typed text.
  const draftOperable = () => !!draft && !sourceDirty && !saving && !conflict && !draftsPending();
  const draftControls = Draft.mount({header: document.querySelector('#view-workflow h1'), actions: $('edit-actions'),
    undo: () => step('undo'), redo: () => step('redo'), discard: discardChanges, active: () => window.consoleNavigation?.view === 'workflow'});
  const projection = () => Object.freeze({projectId: project, candidateEnabled,
    savedSha256: base?.sha256 || null, dirty: pending(), sourceDirty,
    sourceAvailable, reusableSource: base?.document?.definition?.schema_version === 2, saving, conflict: !!conflict,
    // Page-bar presentation (editor-page-bar.js): checked proposal, task chip and pending task findings.
    reviewed: !!reviewed, reviewedTypedSource: !!reviewed?.typed, taskReview: !!taskReview(), taskSelected: !!taskSelection,
    // Comments of the file on disk that the checked bytes drop (server-computed, red-team S-1).
    removedComments: reviewed?.view?.removed_comments || [], inspectionFailed: failedNow(),
    // Every node id the draft knows (saved, pending, deleted): new instance ids avoid all of them.
    nodeIds: [...new Set([...(anchor?.document?.definition.nodes || []).map(n => n.id), ...(graph?.definition.nodes || []).map(n => n.id), ...pendingNodes.map(n => n.node)])],
    taskBinding: base?.document?.task_binding ? {package_id: base.document.task_binding.package_id, revision: base.document.task_binding.revision} : null});
  // importSource: a template's unsaved source enters the ordinary source Review (editor-templates.js).
  window.workflowEditor = Object.freeze({get state() { return projection(); }, importSource: (source, label) => {
    // Typed Python is not a draft state; folding the import would drop it beyond Undo.
    if (sourceDirty) { status('Save or revert your typed Python text first, then use a template.'); return Promise.resolve(false); }
    return reviewProposal({kind: 'source', source}, label);
  },
    // Version history (editor-versions.js): an older version's bytes become an ordinary
    // checked source proposal; Undo brings back the edits it replaced; nothing is written.
    restoreVersion: (source, label) => {
      if (draftsPending()) { status('Correct or reset the invalid field first, then restore the version.'); return Promise.resolve(false); }
      if (conflict) { status('Resolve the change on disk first, then restore the version.'); return Promise.resolve(false); }
      if (sourceDirty) { status('Save or revert your typed Python text first, then restore the version.'); return Promise.resolve(false); }
      return reviewProposal({kind: 'source', source}, `Restore version ${label}`).then(done => {
        if (done) status(`Version "${label}" is restored as unsaved changes. Save to keep it, or Undo to go back.`);
        return !!done;
      });
    },
    // "Blank workflow": delete every module in the draft (undoable); the empty state shows.
    clearAll: () => { const ids = (display?.definition.nodes || []).map(n => n.id); if (ids.length) removeNodes(ids); return ids.length; }});
  const bindingEqual = (a, b) => !!a && !!b && ['schema_version', 'package_id', 'revision', 'semantic_fingerprint', 'task_data_path_id'].every(key => a[key] === b[key]);
  const taskReview = () => reviewed?.taskReview;
  function taskAccepted() {
    const review = taskReview();
    return !review || (review.save_supported && !review.findings.some(item => item.state === 'blocked') && taskAcknowledged &&
      (!review.findings.some(item => item.code === 'current_snapshot_adoption') || taskAdopted));
  }
  const canUpdateTask = () => window.consoleSession.connected && sourceAvailable && !!base?.document && graph?.definition.schema_version === 2 &&
    !!taskSelection && !pending() && !conflict && !saving && !draftsPending();
  function renderTaskControls() {
    const savedBinding = base?.document?.task_binding;
    const matching = (taskChoices || []).filter(choice => bindingEqual(choice.binding, savedBinding));
    let message = taskMessage;
    if (taskReview()) message = taskReview().save_supported ? 'Task references reviewed, not saved. Review the findings and confirm before saving.' : 'Task reference review is blocked. Keep your draft and inspect the findings.';
    else if (pending() && !message) message = "Save existing edits first, then update workflow references. To review a bound draft, select its matching configured task version.";
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
    if (hasBindings() && choice && base?.document?.task_binding &&
        !bindingEqual(choice.binding, base.document.task_binding)) {
      status('A binding draft can only use the configured task choice matching its saved task identity.'); controls(); return;
    }
    taskSelection = choice ? {kind: 'task_references', selected_choice_id: choice.choice_id, expected_task_binding: clone(choice.binding)} : null;
    taskMessage = '';
    if (hasBindings()) { reviewed = null; controls(); return; }
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
        if (hasBindings()) controls(); else invalidate();
      }
      controls();
    } catch (error) {
      if (!error.stale && revision === window.consoleSession.revision) {
        taskChoices = null; taskSelection = null; taskMessage = 'Task choices unavailable: ' + error.message + ' Refresh task choices to retry.';
        taskAcknowledged = false; taskAdopted = false;
        if (taskReview()) invalidate(); else if (hasBindings()) controls(); else { generation++; controls(); }
      }
    } finally { if (taskLoadingRevision === revision) taskLoadingRevision = null; }
  }
  async function updateTask() {
    if (!canUpdateTask()) return;
    await reviewProposal(clone(taskSelection));
  }
  // Red-team A-2: typed Python stays pending when advanced tools are hidden; say so in the
  // beginner view (Show / Discard) instead of locking the canvas without a reason.
  function hiddenSource() {
    const typed = (sourceDirty || !!reviewed?.typed) && !window.uiSettings?.isEnabled('advanced');
    $('hidden-source').hidden = !typed;
  }
  $('hidden-source-show').addEventListener('click', () => { window.uiSettings.set('advanced', true); $('advanced').open = true; $('advanced').scrollIntoView({block: 'start'}); $('source').focus(); });
  $('hidden-source-discard').addEventListener('click', () => discardChanges());
  window.addEventListener('ui-settings-change', () => hiddenSource());
  function controls() {
    hiddenSource();
    window.dispatchEvent(new CustomEvent('workflow-editor-state', {detail: projection()}));
    const connected = window.consoleSession.connected;
    $('project').disabled = !connected || !$('project').options.length;
    const invalidTraining = draftsPending();
    const draftIncomplete = (hasBindings() && !hasNodeDraft() && !sourceDirty && !(inspection?.key === bindingKey() && inspection.status === 'complete')) ||
      (hasNodeDraft() && nodeView()?.status !== 'complete');
    $('review').disabled = !connected || saving || !graph || invalidTraining || draftIncomplete || bindingConflict() || (!!(base?.document?.task_binding || graph?.task_binding) && !taskSelection);
    $('refresh').disabled = !connected || !project;
    $('save').disabled = !connected || saving || !reviewed || reviewed.source !== $('source').value || invalidTraining || bindingConflict() || !taskAccepted() ||
      !!window.editorVersions?.nameProblem();
    // Unreviewed structured edits are not yet Python; Review renders them before source typing.
    $('source').disabled = !graph || (!sourceDirty && !reviewed && Draft.proposal(draftState()).kind !== 'source');
    const operable = draftOperable();
    draftControls.render({dirty: pending(), canUndo: operable && draft.canUndo, canRedo: operable && draft.canRedo,
      undoLabel: draft?.undoLabel, redoLabel: draft?.redoLabel, canDiscard: !!draft && !saving && !conflict && pending()});
    renderTaskControls();
    window.editorCircuit?.setEnabled(canEditCircuit(), canSelectNode());
    window.editorLoopControls?.setEnabled($('loop'), canEditLoop());
    window.editorNodePalette?.setState({enabled: canEditNodes(), pendingNode: pendingNodes.at(-1)?.node || null});
  }
  // Key of the server check the current draft state needs (null: nothing to check).
  const checkKey = () => sourceDirty ? null : hasNodeDraft() ? 'nodes:' + nodeKey() : hasBindings() ? 'bindings:' + bindingKey() : null;
  function failedNow() { return !!inspectFailure && inspectFailure.key === checkKey(); }
  const checking = () => failedNow() ? 'check failed' : 'checking';
  const pendingText = () => sourceDirty ? 'Pending source edits · not saved'
    : hasNodeDraft() ? `Pending ${NodeDrafts.summary(draftState())} · ${nodeView()?.status || checking()}`
    : hasBindings() ? `Pending binding draft · ${inspection?.key === bindingKey() ? inspection.status : checking()}`
    : draft?.dirty ? 'Pending edits · not saved' : 'No pending edits.';
  function invalidate() {
    generation++; reviewed = null; taskAcknowledged = false; taskAdopted = false; controls(); $('diff').textContent = '';
    $('pending').textContent = pendingText(); $('check-again').hidden = !failedNow();
  }
  // A failed request's reason in one sentence: a refusal's own message, otherwise what failed.
  const problem = error => Number(error?.status) >= 400 && Number(error.status) < 500 ? Outcome.sentence(error.message) : Outcome.failure(error).reason + '.';
  function checkFailed(key, error) {
    inspectFailure = {key, message: problem(error)};
    $('pending').textContent = pendingText(); $('check-again').hidden = false; controls();
    status(`Couldn't check your changes: ${inspectFailure.message} They are kept. Press Check again.`);
  }
  $('check-again').addEventListener('click', () => { inspectFailure = null; $('check-again').hidden = true; $('pending').textContent = pendingText(); controls(); inspectIfNeeded(); });
  // Every structured edit mutates the live draft document, then records one history operation.
  function changed(label = 'Edit', coalesce = null) {
    if (draft && !sourceDirty) draft.record(draftState(), label, coalesce);
    invalidate(); inspectIfNeeded();
    // A draft state inspected before (e.g. delete, then add back) has no new reply coming:
    // its cached problems replace the previous state's now.
    if (hasNodeDraft() && !sourceDirty && nodeView()) rediagnose();
  }
  const api = (path, body) => window.consoleSession.request('editor/' + path, body);
  function diagnostic(items = []) {
    // Located problems name only modules still on the canvas (a reply for an older draft may
    // name a deleted one); an empty canvas has exactly one problem to fix.
    const present = new Set((display?.definition.nodes || []).map(n => n.id));
    if (display) items = present.size ? items.filter(item => !item.node || present.has(item.node)) : items.filter(item => item.code === 'workflow_empty');
    $('diagnostics').textContent = items.map(item => `${item.code}: ${item.message}${item.line ? ` (line ${item.line})` : ''}${item.field_path ? ` at ${item.field_path.join('.')}` : ''}`).join('\n');
    // Server diagnostics only; draft problems carry node/field, source ones a line.
    window.editorProblems.render($('problems'), items, {source: window.editorProblems.focusSource, describe: problemLabels,
      select: (nodeId, field) => { if (display?.definition.nodes.some(n => n.id === nodeId)) { selected = nodeId; render(); } window.editorProblems.focusField(nodeId, field); }});
  }
  // Plain names for a located problem: the module's display name and the socket's connector name.
  const problemLabels = (nodeId, field) => {
    const item = display?.definition.nodes.find(value => value.id === nodeId);
    const option = inventory.find(value => value.node === nodeId && (value.argument || 'request') === field);
    return {module: item ? window.editorCapabilityPresentation.label(item.capability) : null,
      connector: option ? window.editorContractPresentation.describe(option.socket_contract).name : null};
  };
  // Red-team S-5: a plain sentence, then what changed on disk since the version this page
  // opened (a real line diff), then the unsaved changes; whole files only in advanced detail.
  function showConflict(value) {
    conflict = value; reviewed = null; controls();
    $('conflict').hidden = false; $('rebase').disabled = bindingConflict() || !value.document;
    $('current').textContent = value.source;
    const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    $('conflict-summary').textContent = `This workflow was saved from another tab or changed on disk (noticed at ${time}). Your unsaved changes are kept.`;
    $('conflict-diff').textContent = Outcome.lineDiff(base?.source ?? '', value.source, ['version you opened', 'on disk now']) || '(The text is the same; only the file version changed.)';
    $('conflict-proposal').textContent = hasNodeDraft() && !sourceDirty ? `Draft: ${NodeDrafts.summary(draftState())}`
      : hasBindings() && !sourceDirty
      ? bindings.map(item => `${item.source ? 'Bind' : 'Disconnect'} ${item.node}.${item.argument ?? 'request'}`).join('\n')
      : Outcome.lineDiff(base?.source ?? '', $('source').value, ['version you opened', 'your changes']) || '(Layout or settings changes only.)';
    status('This workflow changed on disk. Your unsaved changes are kept; choose how to continue below.');
  }
  function showTaskRefusal(proposal, selection) {
    $('source').value = proposal.source; sourceDirty = false;
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
  function restore(state) {
    if (Draft.canonical(state.bindings) !== bindingKey()) inspection = null;
    ({document: graph, bindings, anchor, training, loopTemplate} = state);
    pendingNodes = clone(state.nodes || []); newExternals = clone(state.externals || []); removedNodes = clone(state.removed || []);
    trainingDrafts.clear(); loopDrafts.clear(); reproject();
    if (display && !display.definition.nodes.some(n => n.id === selected)) selected = display.definition.nodes[0]?.id;
  }
  function adopt(value) {
    taskSelection = null; taskMessage = '';
    sourceAvailable = true; base = value; inspection = null; nodeViews.clear(); lastNodeView = null;
    restore(value.document ? viewState(value) : {document: null, bindings: [], anchor: null, training: value.training, loopTemplate: null});
    draft = graph ? Draft.create(draftState()) : null;
    $('source').value = value.source; sourceDirty = false; conflict = null;
    $('conflict').hidden = true;
    invalidate(); diagnostic(value.diagnostics); render();
    $('path').textContent = value.source_path;
    $('revision').textContent = 'File version: ' + value.sha256.slice(0, 12);
    $('inspect').hidden = !!graph;
    status(graph ? `Opened ${value.project_id}.` : `${value.project_id} can't be edited here: it is not a supported workflow file. Fix it in a text editor, then reload.`);
  }
  // A reviewed source, task-reference or node add/remove becomes the draft's new anchor (one undoable step).
  const foldLabel = proposal => ({source: 'Source edits', task_references: 'Task reference update',
    add_node: `Add module ${proposal.node}`, node_drafts: `Draft: ${NodeDrafts.summary(proposal)}`, remove_node: `Delete module ${proposal.nodes?.join(', ')}`})[proposal.kind];
  function fold(value, label) {
    restore(viewState(value)); sourceDirty = false; draft.record(draftState(), label);
  }
  const canSelectNode = () => window.consoleSession.connected && sourceAvailable && !!graph && !sourceDirty && !saving && !conflict;
  const canEditCircuit = () => canSelectNode() && !draftsPending();
  // An invalid limit draft must stay editable so the author can correct it.
  const canEditLoop = () => window.consoleSession.connected && sourceAvailable && !!graph && !sourceDirty && !saving && !conflict &&
    trainingDrafts.size === 0;
  function updateBindingDraft(nodeId, argument, source) {
    if (!canEditCircuit() || !base?.document || bindingConflict()) return;
    const option = inventory.find(value => value.node === nodeId && value.argument === argument);
    if (!option || (source !== null && !option.choices.some(value => JSON.stringify(value.source) === JSON.stringify(source)))) return;
    applyBinding(nodeId, argument, source);
  }
  // `source` was offered (or is a just-created input); pending sockets edit the pending node.
  function applyBinding(nodeId, argument, source, label = null) {
    // Undo label in plain words: "Connect Implement · Model plan".
    const {module, connector} = problemLabels(nodeId, argument ?? 'request');
    const what = label || `${source ? 'Connect' : 'Disconnect'} ${module || nodeId}${connector ? ` · ${connector}` : ''}`;
    if (isPending(nodeId)) {
      pendingNodes = NodeDrafts.bind(pendingNodes, nodeId, argument, source); reproject(); changed(what); render();
      status('Checking the new nodes with the workflow declaration validator…'); return true;
    }
    if (!hasBindings() && base.document.task_binding && taskSelection &&
        !bindingEqual(taskSelection.expected_task_binding, base.document.task_binding)) {
      status('Select the configured choice matching the saved task identity before editing its bindings.'); return false;
    }
    const option = inventory.find(value => value.node === nodeId && value.argument === argument);
    if (!option || (source === null && !option.bound) || JSON.stringify(option.source) === JSON.stringify(source)) return false;
    inspection = null; bindings = Draft.withBinding(bindings, anchor.inventory, nodeId, argument, source); reproject();
    changed(what); render();
    // Back on the anchor nothing is inspected, so the last draft's problems no longer apply.
    if (!hasBindings()) diagnostic();
    status(hasBindings() ? 'Checking binding draft with the workflow declaration validator…' : 'Connections match the loaded source again.'); return true;
  }
  function createExternal(external, nodeId, argument) {
    if (!canEditCircuit() || bindingConflict()) return;
    const before = newExternals; newExternals = [...newExternals, external];
    if (!applyBinding(nodeId, argument, {kind: 'external', binding: external.id}, `Create input ${external.id} for ${nodeId}.${argument ?? 'request'}`)) newExternals = before;
  }
  function inspectIfNeeded() {
    if (failedNow()) return;
    if (hasBindings() && !hasNodeDraft() && !sourceDirty && inspection?.key !== bindingKey() && inspecting !== bindingKey()) void inspectBindingDraft();
    if (hasNodeDraft() && !sourceDirty && !nodeView() && inspectingNode !== nodeKey()) void inspectNode();
  }
  // Inspection belongs to the current patch set: layout or inspector edits keep it; any patch change re-inspects.
  async function inspectBindingDraft() {
    if (!window.consoleSession.connected) return;
    const id = project, sha = base.sha256, key = bindingKey(); inspecting = key;
    const live = () => project === id && base?.sha256 === sha && bindingKey() === key;
    try {
      const value = await api(`${encodeURIComponent(id)}/draft`, {expected_sha256: sha, draft: {base_document: clone(graph), bindings: clone(bindings)}});
      if (!live()) return;
      inspection = {key, status: value.inspection.status, diagnostics: value.inspection.diagnostics,
        problems: value.inspection.problems || value.inspection.diagnostics.map(message => ({code: value.inspection.status, message}))};
      $('pending').textContent = pendingText();
      diagnostic(value.inspection.problems || value.inspection.diagnostics.map(message => ({code: value.inspection.status, message})));
      controls(); render();
      status(value.inspection.status === 'complete' ? 'Connections are complete. Save when ready.'
        : 'Some required inputs are not connected. See the problems in the bar above.');
    } catch (error) {
      if (error.stale || !live()) return;
      if (hasSourceConflict(error) && error.value?.current) showConflict(error.value.current);
      else checkFailed('bindings:' + key, error);
    } finally { if (inspecting === key) inspecting = null; }
  }
  function adoptDraftState(state, message) {
    // Undoing a Discard of typed Source text restores that text as dirty Source text.
    restore(state); sourceDirty = typeof state.sourceText === 'string'; $('source').value = sourceDirty ? state.sourceText : anchor.source;
    invalidate(); render(); inspectIfNeeded(); rediagnose(); status(message);
  }
  // Problems of the restored state from its cached server inspection (undo/redo/discard);
  // an uncached state is re-inspected by inspectIfNeeded and diagnosed on its response.
  function rediagnose() {
    const view = hasNodeDraft() && !sourceDirty ? nodeView() : null;
    if (view) diagnostic(view.problems.length ? view.problems : view.diagnostics.map(message => ({code: view.status, message})));
    else if (hasBindings() && !sourceDirty && inspection?.key === bindingKey()) diagnostic(inspection.problems || []);
    else diagnostic();
  }
  function step(direction) {
    if (draft && draftsPending()) { status('Correct or reset the invalid field first; undo and redo would drop its typed text.'); return; }
    if (!draftOperable()) return;
    const result = direction === 'undo' ? draft.undo() : draft.redo();
    if (result) adoptDraftState(result.state, `${direction === 'undo' ? 'Undid' : 'Redid'}: ${result.label}. Nothing is saved until you review and save.`);
  }
  function discardChanges() {
    if (!draft || saving || conflict || !pending()) return;
    const typed = sourceDirty ? $('source').value : null, invalid = draftsPending();
    adoptDraftState(draft.discard(typed), `Reverted to the saved version${typed === null ? '' : ', typed Python text included'}. ` +
      `Undo brings your changes back${invalid ? ' (except invalid field text)' : ''}.`);
  }
  // Node add/remove (editor-palette.js proposes): any number of nodes stay pending beside other edits;
  // saved-node removal reviews a remove_node proposal on an unedited draft. The server reviews exact bytes.
  const canEditNodes = () => canEditCircuit() && !!draft;
  function startNode(fields) {
    if (!canEditNodes()) { status('Correct the invalid field or resolve the conflict before adding a module.'); return; }
    // Inputs candidate preparation generates (per-node storage, …) are bound as managed
    // bindings in the same draft edit (editor-managed-inputs.js; roles from the server).
    const {catalog, ...item} = fields, taken = [...graph.definition.externals, ...newExternals].map(value => value.id);
    const provided = window.editorManagedInputs.provide({binding: null, arguments: [], ...item}, catalog, anchor.managedRoles || [], taken);
    pendingNodes = [...pendingNodes, provided.item]; newExternals = [...newExternals, ...provided.externals]; selected = item.node; reproject();
    changed(`Add module ${item.node}`); render();
  }
  async function inspectNode() {
    const id = project, sha = base.sha256, key = nodeKey(); inspectingNode = key;
    try {
      const value = await api(`${encodeURIComponent(id)}/nodes-draft`, {expected_sha256: sha, proposal: Draft.proposal(draftState())});
      if (project !== id || base?.sha256 !== sha) return;
      nodeViews.set(key, value); lastNodeView = value; if (nodeKey() !== key) { inspectIfNeeded(); return; }
      reproject(); invalidate(); render();
      diagnostic(value.problems.length ? value.problems : value.diagnostics.map(message => ({code: value.status, message}))); status(NodeDrafts.message(value));
    } catch (error) {
      if (error.stale || project !== id || nodeKey() !== key) return;
      if (hasSourceConflict(error) && error.value?.current) showConflict(error.value.current); else checkFailed('nodes:' + key, error);
    } finally { if (inspectingNode === key) inspectingNode = null; }
  }
  function cancelNodes(ids) {
    if (saving || conflict) return;
    const result = NodeDrafts.cancel(draftState(), ids); ({nodes: pendingNodes, bindings} = result); inspection = null; reproject();
    changed(`Cancel new node ${ids.join(', ')}`); diagnostic(); render();
    status(`New node ${ids.join(', ')} cancelled${result.disconnected.length ? `; disconnected ${result.disconnected.join(', ')}` : ''}. Undo restores it.`);
  }
  // Delete always succeeds in the draft (operator rule 2026-10-28), with no confirmation: saved
  // nodes join `removed`, every socket that read them is disconnected (a required one becomes
  // a problem), and Undo restores all of it. The server refuses only to SAVE an invalid document.
  function removeNodes(ids) {
    if (ids.every(isPending)) { cancelNodes(ids); return; }
    if (!canEditNodes()) { status('Correct the invalid field or resolve the conflict before deleting a module.'); return; }
    const saved = ids.filter(id => !isPending(id)), gone = new Set([...removedNodes, ...saved]);
    const result = NodeDrafts.cancel(draftState(), ids.filter(isPending));
    ({nodes: pendingNodes, bindings} = result);
    for (const option of anchor.inventory) {
      if (gone.has(option.node) || option.source?.kind !== 'result' || !gone.has(option.source.node)) continue;
      bindings = Draft.withBinding(bindings, anchor.inventory, option.node, option.argument, null);
    }
    for (const item of pendingNodes) for (const value of item.arguments) if (value.source?.kind === 'result' && gone.has(value.source.node)) pendingNodes = NodeDrafts.bind(pendingNodes, item.node, value.name, null);
    removedNodes = [...gone]; inspection = null; reproject();
    const names = ids.map(id => window.editorCapabilityPresentation.label(display?.definition.nodes.find(item => item.id === id)?.capability || graph.definition.nodes.find(item => item.id === id)?.capability));
    changed(`Delete ${ids.join(', ')}`); render();
    status(`Deleted ${names.join(', ')}. Undo brings ${ids.length === 1 ? 'it' : 'them'} back.`);
  }
  window.editorNodePalette?.mount($('palette'), $('graph'), {add: startNode, cancel: () => { if (pendingNodes.length) cancelNodes([pendingNodes.at(-1).node]); }});
  function renderGraph() {
    $('edges').replaceChildren();
    const id = project, document = display;
    const live = () => project === id && display === document;
    window.editorCircuit.render($('graph'), {viewKey: id, document: display, inventory, selected, enabled: canEditCircuit(), selectable: canSelectNode(),
      allowBindingChange: true, allowMove: true}, {
      remove: ids => { if (live()) removeNodes(ids); }, menu: (nodeId, event) => { if (live()) window.editorNodePalette.contextMenu(event, nodeId, removeNodes); },
      select: value => { if (live()) { selected = value; render(); } },
      bind: (nodeId, argument, source) => { if (live()) updateBindingDraft(nodeId, argument, source); },
      disconnect: (nodeId, argument) => { if (live()) updateBindingDraft(nodeId, argument, null); },
      move: (layout, label = 'Move module') => {
        if (!live() || !canEditCircuit()) return;
        for (const {node: nodeId, x, y} of NodeDrafts.moves(draftState(), layout)) {
          const item = pendingNodes.find(value => value.node === nodeId);
          if (item) { item.x = x; item.y = y; continue; }
          const position = graph.positions.find(value => value.node === nodeId);
          if (position) { position.x = x; position.y = y; } else graph.positions.push({node: nodeId, x, y});
        }
        reproject(); changed(label); render(); status('Moved. Save to keep the layout.');
      }
    });
    if (!display) return;
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
    input.addEventListener('input', () => { update(input.value); changed(`Edit ${label}`, `field:${label}`); });
  }
  function renderTraining() {
    const launch = () => (graph.training_settings.launch ||= {});
    const label = name => training.controls.find(control => control.name === name)?.label || name;
    // Each parameter action is one draft operation; typing in one field coalesces, Reset does not.
    window.editorNodeParameters.training($('inspector'), {training, drafts: trainingDrafts,
      launch: () => graph.training_settings.launch || {}, saved: base?.document?.training_settings?.launch || {}}, {
      supply: (name, value) => { launch()[name] = value; trainingDrafts.delete(name); changed(`Edit ${label(name)}`, `training:${name}`); },
      unset: (name, rerender) => { delete launch()[name]; trainingDrafts.delete(name); changed(`Reset ${label(name)}`); if (rerender) render(); },
      invalid: (name, raw) => { trainingDrafts.set(name, raw); changed(`Edit ${label(name)}`, `training:${name}`); status('Empty numbers are not saved. Enter a value or select default / None.'); },
      openSource: () => { $('advanced').open = true; $('source').focus(); if (draft?.dirty && !reviewed) status('Review inspector edits first to update the source.'); }
    });
  }
  function renderInspector() {
    $('inspector').replaceChildren(); $('references').replaceChildren();
    if (!graph) return;
    const capturedGraph = graph;
    const item = display.definition.nodes.find(n => n.id === selected);
    if (item) {
      const heading = node('div', '', $('inspector'));
      heading.className = 'inspector-heading';
      const capabilityLabel = window.editorCapabilityPresentation.append(heading, item.capability, item.id, 'inspector-capability-heading');
      heading.setAttribute('aria-label', `${capabilityLabel}, instance ${item.id}`);
      window.editorNodePalette?.inspectorActions(heading, item.id, {remove: removeNodes, enabled: canEditCircuit()});
      // Order: advice first (editor-advice.js), then inputs, then advanced detail and actions.
      window.editorAdvice?.render($('inspector'), {document: graph, item, inventory, enabled: canEditCircuit()},
        (mutate, label) => { if (graph === capturedGraph) { mutate(graph); changed(label, `advice:${item.id}`); } });
      node('h3', 'Inputs', $('inspector'));
      // Framework-supplied inputs (managed storage, …) are no user requirement: advanced Mapping details only.
      for (const option of inventory.filter(entry => entry.node === item.id && !entry.framework_supplied)) {
        // "[swatch] Connector name · Required" (spec §8.2); the field name is advanced detail.
        const state = `${option.required ? 'Required' : 'Optional'}${option.bound ? '' : ' · Not connected'}`;
        const label = window.editorInspectorRows.label($('inspector'), option, state);
        const select = document.createElement('select'); label.append(select);
        label.classList.toggle('field-problem', option.required && !option.bound);
        if (!option.bound) {
          const empty = node('option', 'Not connected', select);
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
        // An unlink icon per row (tour #15), never a full-size primary button.
        const disconnect = node('button', '', $('inspector'));
        disconnect.type = 'button'; disconnect.className = 'editor-disconnect secondary icon-button'; disconnect.title = 'Disconnect';
        disconnect.append(window.consoleIcons?.make('unlink', 16) || ''); node('span', 'Disconnect', disconnect).className = 'sr-only';
        disconnect.setAttribute('aria-label', `Disconnect ${item.id}.${option.argument || 'request'}`);
        disconnect.disabled = !option.bound || bindingConflict();
        disconnect.hidden = !option.bound;
        disconnect.addEventListener('click', () => { if (graph === capturedGraph) updateBindingDraft(item.id, option.argument, null); });
        window.editorExternalInputs?.render($('inspector'), {option, nodeId: item.id, reusable: graph.definition.schema_version === 2, enabled: canEditCircuit() && !bindingConflict(),
          taken: new Set([...graph.definition.externals, ...newExternals].map(value => value.id)), ready: render}, createExternal);
      }
      if (item.capability === 'tuning' && training) renderTraining();
      const loop = graph.definition.loop;
      if (loop && [loop.feedback.source.node, loop.feedback.target].includes(item.id)) window.editorNodeParameters.loopPointer($('inspector'), loop, item.id, () => { $('loop').scrollIntoView({block: 'start'}); $('loop').querySelector('input, button')?.focus(); });
      if (item.capability === 'tuning') window.editorNodeParameters.modelOwner($('inspector'), graph.definition.task, graph.task_binding);
      // Advanced (Settings) protocol detail, then node actions, after advice and inputs.
      const mapping = node('details', '', $('inspector')); mapping.className = 'inspector-mapping'; mapping.dataset.uiFlag = 'advanced';
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
    }
    for (const key of Object.keys(graph.definition.task)) field($('references'), `task.${key}`, graph.definition.task[key], value => { graph.definition.task[key] = value; });
    for (const external of [...graph.definition.externals, ...newExternals]) {
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
    // editorDraft.proposal reviews loop-only edits as a typed loop patch on the anchor source.
    const edit = message => { changed('Edit research loop'); render(); status(message); };
    window.editorLoopControls.render($('loop'), {loop: graph.definition.loop || null, template: loopTemplate,
      drafts: loopDrafts, nodes: display.definition.nodes, profile: graph.execution_profile || null, enabled: canEditLoop()}, {
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
        changed('Edit iteration limit', 'loop:limit');
      },
      // Stop-condition edits (editor-loop-controls.js) mutate only the live draft loop.
      edit: (mutate, message, rerender = false) => {
        if (!live() || !graph.definition.loop) return;
        mutate(graph.definition.loop); changed('Edit stop conditions', rerender ? null : 'loop:stop'); if (rerender) render(); status(message);
      }
    });
  }
  function render() {
    renderGraph(); renderInspector(); renderLoop();
    if (sourceDirty) for (const input of document.querySelectorAll('#editor-inspector select, #editor-inspector input, #editor-inspector button, #editor-references input')) input.disabled = true;
    if (bindingConflict() || saving) for (const input of document.querySelectorAll('#editor-inspector select[data-node], #editor-inspector .editor-disconnect')) input.disabled = true;
    controls();
  }
  function resetProjectState() {
    taskSelection = null; taskMessage = '';
    sourceAvailable = false; sourceDirty = false;
    trainingDrafts.clear(); loopDrafts.clear();
    base = null; graph = null; conflict = null; reviewed = null; inventory = []; training = null; loopTemplate = null; selected = null;
    draft = null; bindings = []; anchor = null; inspection = null; pendingNodes = []; newExternals = []; removedNodes = []; display = null; lastNodeView = null; nodeViews.clear();
    $('conflict').hidden = true; $('rebase').disabled = true;
    $('source').value = ''; $('source').disabled = true;
    $('current').textContent = ''; $('conflict-diff').textContent = '';
    $('path').textContent = ''; $('revision').textContent = '';
    invalidate(); diagnostic(); render(); status('Opening selected project…');
  }
  async function refresh(ask = true) {
    if (!window.consoleSession.connected) return;
    if (pending() && ask && !window.confirm('Discard pending edits and refresh from disk?')) return;
    const id = project; invalidate(); const version = generation;
    try { const value = await api(encodeURIComponent(id)); if (current(id, version)) adopt(value); }
    catch (error) {
      if (error.stale) return;
      // Red-team E-4: the server names the reason and the path (not found, not readable, too large).
      if (current(id, version)) { sourceAvailable = false; controls(); status(`Can't open ${id}: ${problem(error)}${pending() ? ' Your unsaved changes are kept.' : ''}`); }
    }
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
      if (!base && project && !pending()) void refresh(false);
    } else if (['workflow', 'run'].includes(window.consoleNavigation?.view)) void openProjects();
  }
  window.consoleSession.subscribe(connection);
  window.addEventListener('console-view', event => { if (['workflow', 'run'].includes(event.detail.view)) void openProjects(); });
  // The version name field (editor-versions.js) refuses invisible characters and used names as typed.
  window.addEventListener('editor-version-name', () => controls());
  window.addEventListener('beforeunload', event => { if (pending()) { event.preventDefault(); event.returnValue = ''; } });
  $('inspect').addEventListener('click', () => { $('advanced').open = true; $('source').focus(); });
  $('project').addEventListener('change', () => {
    if (!window.consoleSession.connected) { $('project').value = project; return; }
    if (pending() && !window.confirm('Discard pending edits and change project?')) { $('project').value = project; return; }
    project = $('project').value; candidateEnabled = $('project').selectedOptions[0]?.dataset.runnable === 'true'; resetProjectState(); refresh(false);
  });
  $('refresh').addEventListener('click', () => refresh());
  $('source').addEventListener('input', () => { sourceDirty = true; invalidate(); for (const input of document.querySelectorAll('#editor-inspector select, #editor-inspector input, #editor-inspector button, #editor-references input')) input.disabled = true; });
  async function reviewProposal(proposal, label = null) {
    if (!window.consoleSession.connected || saving || draftsPending() || !base?.document) return;
    if (proposal.kind === 'draft' && !(inspection?.key === bindingKey() && inspection.status === 'complete')) {
      status('The binding draft must pass declaration validation before review.'); return;
    }
    if ((base.document.task_binding || graph?.task_binding) && !taskSelection) { status('Select the configured task version, then review.'); return; }
    invalidate();
    const id = project, version = generation, typed = proposal.kind === 'source' && sourceDirty;
    const selection = taskSelection ? clone(taskSelection) : null;
    const body = {expected_sha256: base.sha256, proposal};
    if (proposal.kind !== 'task_references' && (base.document.task_binding || graph?.task_binding)) body.task_reference_selection = selection;
    try {
      const value = await api(`${encodeURIComponent(id)}/review`, body);
      if (!current(id, version)) return;
      // Source text may add nodes/externals: its reviewed projection becomes the draft anchor.
      // Structured drafts stay as edited, so later edits, undo and Discard keep working on them.
      if (foldLabel(proposal)) fold(value, label || foldLabel(proposal));
      else training = value.training;
      $('source').value = value.source; sourceDirty = false;
      reviewed = {source: value.source, sha256: value.sha256, base: base.sha256, taskReview: value.task_reference_update, typed, view: value,
        taskSelection: value.task_reference_update ? (proposal.kind === 'task_references' ? clone(proposal) : selection) : null};
      $('review-disclosure').open = true;
      $('diff').textContent = value.diff || '(No source changes)'; diagnostic(); render();
      $('pending').textContent = value.source !== base.source ? 'Pending changes · checked, not saved yet' : 'No changes to the file; the task findings may still need confirming.';
      status(value.node_edit ? value.node_edit.message + ' Name the version, then save.' : value.task_reference_update ? 'Checked. Confirm the task findings, then save.' : 'Checked. Name the version, then save.');
      return true;
    } catch (error) {
      if (error.stale) return;
      if (!current(id, version)) return;
      if (hasSourceConflict(error) && error.value?.current) {
        showConflict(error.value.current);
        diagnostic(error.value?.diagnostics); status(error.message); return;
      }
      const refused = error.value?.proposal;
      if (refused && ['source', 'task_references'].includes(proposal.kind)) fold(refused, label || foldLabel(proposal));
      if (refused) { $('source').value = refused.source; sourceDirty = false; }
      if (refused?.task_reference_update) showTaskRefusal(refused, selection || refused);
      else if (proposal.kind === 'draft' && ['draft_incomplete', 'draft_invalid'].includes(error.code)) {
        inspection = {key: Draft.canonical(proposal.draft.bindings), status: error.code.slice('draft_'.length), diagnostics: [error.message]};
      }
      $('pending').textContent = pendingText(); render();
      diagnostic(error.value?.diagnostics);
      status(proposal.kind === 'loop' ? `Review refused the research loop: ${error.message}.${proposal.loop?.stop_conditions?.length && loopDeclarationRefusal(error) ? ' ' + window.editorLoopControls.refusalHint : ''}` : error.message);
    }
  }
  $('review').addEventListener('click', () => { if (graph) void reviewProposal(sourceDirty ? {kind: 'source', source: $('source').value} : Draft.proposal(draftState())); });
  $('save').addEventListener('click', async () => {
    if (!window.consoleSession.connected || saving || !reviewed || reviewed.source !== $('source').value || !taskAccepted()) return;
    const id = project, version = generation, exact = {...reviewed};
    const body = {source: exact.source, proposal_sha256: exact.sha256, expected_sha256: exact.base};
    const versionName = window.editorVersions?.saveName(); if (versionName) body.version_name = versionName;
    if (exact.taskReview) body.task_reference_acceptance = {selection: clone(exact.taskSelection),
      acknowledged_findings: exact.taskReview.findings.map(({code, reference}) => ({code, reference})), adopt_current_snapshot: taskAdopted};
    saving = true; controls();
    try {
      let saved;
      try { saved = await api(`${encodeURIComponent(id)}/save`, body); } catch (error) {
        if (!error.stale && current(id, version)) await saveFailed(error, exact, id, version);
        return;
      }
      if (!current(id, version)) return;
      const done = saved.unchanged ? 'Nothing to save: the file on disk already matches.' : `Saved as "${saved.version_name}".`;
      let value;
      try { value = await api(encodeURIComponent(id)); } catch (error) {
        if (error.stale || !current(id, version)) return;
        // Red-team S-2: the save itself succeeded. The checked bytes are the saved version,
        // so the next save starts from them instead of reporting the user's own save as a conflict.
        adoptSaved(exact, saved.sha256);
        status(`${done} Reloading the file afterwards failed: ${problem(error)} Reload the page to see it from disk.`); return;
      }
      if (!current(id, version)) return;
      if (value.sha256 !== saved.sha256) {
        adoptSaved(exact, saved.sha256); showConflict(value);
        status(`${done} The file then changed on disk again; choose how to continue below.`); return;
      }
      adopt(value); status(done);
    } finally { saving = false; controls(); }
  });
  // The saved state from the checked review when the file could not be re-read (S-2). A
  // retained task refusal carries no review projection: its base then stays, and a later
  // Save reports the saved bytes on disk as already saved (saveFailed), never a conflict.
  function adoptSaved(exact, sha256) {
    if (exact.view) adopt({...exact.view, sha256, project_id: project, source_path: base.source_path, diagnostics: []});
    else reviewed = null;
  }
  // One plain sentence per outcome (editor-save-outcome.js). A refusal (4xx) wrote nothing,
  // so the checked proposal and the open Save step stay ready for another try (S-4).
  async function saveFailed(error, exact, id, version) {
    // Source bytes were published; only the version record write failed.
    if (error.code === 'version_record_not_updated' && error.value?.current) { adopt(error.value.current); status(Outcome.sentence(error.message)); return; }
    if (hasSourceConflict(error) && error.value?.current) {
      // The file on disk already holds exactly these checked bytes: that is this save, not a conflict.
      if (error.value.current.sha256 === exact.sha256) { adopt(error.value.current); status('Saved: the file on disk already has your checked changes.'); return; }
      showConflict(error.value.current); return;
    }
    if (error.value?.proposal?.task_reference_update) {
      showTaskRefusal(error.value.proposal, exact.taskSelection);
      status(`Not saved. ${Outcome.sentence(error.message)} Correct the task sources, then save again.`); return;
    }
    const outcome = Outcome.failure(error);
    if (outcome.known) { if (error.code === 'proposal') reviewed = null; status(outcome.message); return; }
    // 5xx, an unreadable reply or no reply: read the file to learn whether the save happened.
    let value;
    try { value = await api(encodeURIComponent(id)); } catch (readError) {
      if (readError.stale || !current(id, version)) return;
      status(`${outcome.reason}, and the file could not be re-read, so it is unknown whether it saved. Your changes are kept; reload the page to check.`); return;
    }
    if (!current(id, version)) return;
    if (value.sha256 === exact.sha256) { adopt(value); status(`Saved (confirmed from disk). ${outcome.reason}, so the version name may not be recorded.`); }
    else if (value.sha256 === exact.base) status(`Not saved: ${outcome.reason.toLowerCase()}. The file on disk is unchanged and your changes are kept; press Save version to try again.`);
    else showConflict(value);
  }
  $('discard').addEventListener('click', () => { if (conflict) { const value = conflict; adopt(value); status(`Reloaded ${value.project_id} from disk. Your unsaved changes were dropped.`); } });
  $('rebase').addEventListener('click', () => {
    if (!conflict || bindingConflict()) return;
    // Structured edits are re-applied onto the disk projection, so later proposals keep the
    // newer disk change; history restarts there (older states hold the superseded source).
    // Pending Source text (typed, or reviewed into the anchor) is a whole-file proposal: kept as is.
    const loaded = viewState(conflict), text = sourceDirty || (!!anchor && anchor.source !== base.source);
    const rebased = draft && !text ? Draft.reapply(base.document || anchor.document, draftState(), loaded) : null;
    base = conflict; conflict = null; $('conflict').hidden = true;
    $('revision').textContent = 'File version: ' + base.sha256.slice(0, 12);
    if (!draft) { invalidate(); status('The latest version is now the base. Reconcile your changes, then press Save to check them.'); return; }
    if (text) {
      draft.rebase(loaded, draftState(), 'Keep pending source on the current disk version'); invalidate();
      status('The latest version is now the base. Your typed Python text still replaces the whole file and does not include the change on disk; merge it by hand, or Revert to saved.');
      return;
    }
    draft.rebase(loaded, rebased.state, 'Re-apply edits on the current disk version');
    restore(rebased.state); $('source').value = anchor.source; invalidate(); render();
    status('Your changes are reapplied onto the latest version.' +
      (rebased.conflicts.length ? ` Both changed ${rebased.conflicts.join(', ')}; your value was kept.` : '') + ' Press Save to check them; the Save step lists any comment that saving would remove.');
  });
})();
