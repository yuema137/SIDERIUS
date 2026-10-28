/* Steps 2-3 of Run: prepared capture review and launch. Native request and credentials
 * remain server-owned. The retained launch is observed automatically while Run is open. */
(() => {
  'use strict';
  const $ = id => document.getElementById('capture-' + id);
  const session = window.consoleSession, coordinator = window.reusableIntents;
  const profileDescriptions = {
    'native-proposal-families/v1': ' Independent proposal instances executed serially.',
    'native-literature-candidate/v1': ' Native literature review feeds one proposal, implementation and validation.',
    'native-interpretation-candidate/v1': ' Native interpretation feeds one proposal, implementation, validation and tuning.',
  };
  // The reviewed request's authored loop bound decides how many bodies a launch may run.
  function researchLoop(value) {
    if (!value.loop) return 'Research loop: none (one workflow body).';
    const capability = id => window.editorCapabilityPresentation.label(value.nodes.find(item => item[0] === id)?.[1]);
    const edge = value.loop.feedback;
    const stops = (value.loop.stop_conditions || []).map(stopCondition);
    return `Research loop: up to ${value.loop.final_iteration} iteration${value.loop.final_iteration === 1 ? '' : 's'} · feedback ${capability(edge.source.node)} ${edge.source.node} → ${capability(edge.target)} ${edge.target}${stops.length ? ' · stops early when ' + stops.join(' or ') : ''}.`;
  }
  function stopCondition(condition) {
    if (condition.kind === 'metric_threshold') return `${condition.metric_id} reaches ${condition.threshold} (task metric direction)`;
    if (condition.kind === 'no_improvement') return `${condition.completed_bodies} completed bod${condition.completed_bodies === 1 ? 'y' : 'ies'} pass without improvement`;
    return `unsupported condition ${condition.kind}`;
  }
  let editor = window.workflowEditor.state, generation = 0, selected = null, review = null;
  let handoffGeneration = -1;
  let tasksRevision = null, cursor = null, busy = false, checking = false, intent = null, terminal = false, refusedInitial = false, storageProblem = false;
  let problem = '', observed = null;
  const POLL_MS = 2000;
  const evidence = () => intent ? coordinator.state('candidate', intent) : null;
  const status = message => { $('status').textContent = message; };
  const api = (suffix, body, project = editor.projectId) => session.request(`editor/${encodeURIComponent(project)}/reusable-captures${suffix}`, body);
  const current = (version, revision) => generation === version && session.revision === revision;
  const option = (value, text) => { const el = document.createElement('option'); el.value = value; el.textContent = text; return el; };
  function sourceState() {
    if (!review) { $('source').textContent = selected ? 'Capture selected. Review its saved source version.' : ''; return; }
    let comparison = !editor.sourceAvailable ? 'Current source unavailable.' : editor.savedSha256 === review.source_sha256 ? 'Saved source matches capture.' : 'Current saved source differs.';
    if (editor.dirty) comparison += ' Unsaved draft edits are separate from this capture.';
    if (editor.conflict) comparison += ' Disk source conflict is unresolved.';
    $('source').textContent = `Captured source ${review.source_sha256.slice(0, 12)}. ${comparison} Launch uses this captured version.`;
  }
  // Why Launch is disabled, in one inline sentence beside it (R-2); never a tooltip.
  function launchReason(enabled) {
    if (!session.connected) return session.reachable === false ? 'Can\'t check: the server is unreachable.' : 'Connect to launch.';
    if (!enabled) return busy ? 'Working…' : 'Open a runnable project first.';
    if (intent) return '';
    if (storageProblem) return 'This browser\'s saved run state is unreadable; clear this site\'s storage, then reload.';
    if (!selected) return '';
    if (!review) return 'Review the prepared run first.';
    if (!review.credential_readiness.ready) return 'Cannot launch: credentials are not ready (see above).';
    if (!coordinator.eligible()) return 'Waiting for the preparation status…';
    return '';
  }
  function controls() {
    const enabled = session.connected && editor.candidateEnabled && !!editor.projectId && !busy;
    $('task').disabled = !enabled;
    $('refresh').disabled = !enabled || !$('task').value;
    $('more').disabled = !enabled || !cursor;
    $('run').disabled = !enabled;
    $('open').disabled = !enabled || !$('run').value;
    $('review').disabled = !enabled || !selected;
    $('review').hidden = !!intent;
    $('launch').hidden = !!intent;
    $('launch').disabled = !enabled || !review?.credential_readiness.ready || !!intent || storageProblem || !coordinator.eligible();
    $('launch-reason').textContent = launchReason(enabled);
    $('check').disabled = !session.connected || !intent || busy;
    const state = evidence();
    $('retry').hidden = !(intent && !state?.released && (problem === 'unknown' || problem === 'unresolved'));
    $('retry').disabled = !session.connected || !intent || busy;
    const dismissible = !!intent && coordinator.dismissible('candidate', intent);
    $('finish').hidden = !dismissible;
    $('finish').disabled = !session.connected || !intent || busy || !dismissible;
    $('finish').textContent = state?.refused ? 'Discard refused launch and review again'
      : state?.forgettable && !state.released ? 'Forget this operation' : 'Start another run';
    sourceState();
    window.dispatchEvent(new CustomEvent('run-step-state', {detail: {
      source: 'launch', selected: !!selected, reviewed: !!review, intent: !!intent, problem,
      running: !!intent && !state?.released && !problem, finished: !!state?.released
    }}));
  }
  function credentials(readiness) {
    const line = $('credentials');
    line.hidden = !readiness;
    if (!readiness) return;
    line.toggleAttribute('data-ready', readiness.ready);
    const missing = [...readiness.missing_names, ...readiness.omitted_names];
    line.textContent = readiness.ready
      ? 'Credentials ready (names only checked; no value is shown or sent to this page).'
      : `Credentials not ready${missing.length ? ': missing ' + missing.join(', ') : ''}. ${readiness.instructions.join(' ')}`;
  }
  function invalidate() { generation++; selected = null; review = null; $('summary').replaceChildren(); $('details').textContent = ''; credentials(null); controls(); }
  function showIntent() {
    $('intent').hidden = !intent;
    problem = ''; observed = null;
    if (!intent) return;
    $('operation-id').textContent = intent.payload.candidate_operation_id;
    $('operation-status').textContent = 'Checking this run…';
    $('monitor').href = '#monitor/' + intent.payload.candidate_operation_id;
    $('monitor').hidden = false;
  }
  try {
    intent = coordinator.read('candidate')?.value || null;
  } catch (_) { storageProblem = true; status('This browser\'s saved run state is unreadable. Clear this site\'s storage, then reload.'); }
  showIntent();
  function displayOperation(value) {
    if (!coordinator.observe('candidate', intent, value)) return;
    observed = value; problem = '';
    terminal = coordinator.dismissible('candidate', intent);
    const sentence = !value.state && value.observation === 'existing'
      ? 'This run already exists (no second one was started); checking its status…'
      : window.operationOutcome.sentence(value);
    $('operation-status').textContent = sentence + (terminal ? ' Details and logs are in Monitor.' : ' Follow it in Monitor.');
    controls();
  }
  function unresolvedMessage(error) {
    if (error.code === 'unknown_operation') {
      return evidence()?.forgettable
        ? 'This console still has no record of this run after Retry. Nothing is running for it here: forget it to start another run.'
        : 'This console has no record of this run. Retry sends the same launch again; it never starts a second run.';
    }
    if (error.unreachable) return 'Can\'t check: the server is unreachable. Retrying…';
    return 'Can\'t confirm this run yet (' + error.message + '). Keep it; checking again…';
  }
  async function launchRetained(initial = false) {
    if (!session.connected || !intent || busy || !coordinator.same('candidate', intent)) return;
    refusedInitial = false; busy = true; controls();
    const exact = intent;
    try {
      coordinator.dispatching('candidate', exact);
      const value = await api('/launch', exact.payload, exact.project); if (intent === exact && coordinator.same('candidate', exact)) displayOperation(value);
    }
    catch (error) { if (!error.stale && intent === exact && coordinator.same('candidate', exact)) {
      refusedInitial = initial === true && error.value?.error?.admission_not_attempted === true;
      coordinator.observe('candidate', exact, null, refusedInitial);
      problem = refusedInitial ? 'refused' : 'unresolved';
      $('operation-status').textContent = error.message + (refusedInitial ? ' Nothing was started (the launch did not attempt admission). Discard it and review again.' : ' The outcome is unconfirmed; this page keeps checking. Retry sends the same launch.');
    } }
    finally { busy = false; controls(); }
  }
  async function list(append = false) {
    if (!session.connected || !editor.candidateEnabled || !$('task').value) return;
    const version = generation, revision = session.revision;
    try {
      const page = await api(`?task_id=${encodeURIComponent($('task').value)}${append && cursor ? '&cursor=' + cursor : ''}`);
      if (!current(version, revision)) return;
      const previous = $('run').value;
      if (!append) $('run').replaceChildren(option('', 'Choose a prepared run'));
      for (const item of page.captures) {
        const el = option(item.run_id, `${item.run_name || 'Unavailable capture'} · ${item.run_id}`);
        el.disabled = !item.available; $('run').append(el);
      }
      if (previous) {
        if (![...$('run').options].some(item => item.value === previous)) { const missing = option(previous, `Unavailable selected capture · ${previous}`); missing.disabled = true; $('run').append(missing); }
        $('run').value = previous;
      }
      cursor = page.next_cursor; $('more').hidden = !cursor;
      $('guidance').textContent = page.captures.length ? 'Earlier preparations of this project, newest first. Listing does not verify them.' : 'No earlier prepared runs for this task.';
      if (!selected && !intent) status('Prepare a run in step 1, or open an earlier prepared run below.');
    } catch (error) { if (!error.stale && current(version, revision)) status(error.message); }
    controls();
  }
  async function loadTasks() {
    if (!session.connected || tasksRevision === session.revision) return;
    const revision = session.revision, version = generation; tasksRevision = revision;
    try {
      const tasks = (await session.choices()).tasks;
      if (!current(version, revision)) {
        if (version < handoffGeneration) return;
        tasksRevision = null;
        void loadTasks();
        return;
      }
      const previous = $('task').value;
      $('task').replaceChildren(option('', 'Choose task and resources'), ...tasks.filter(task => task.reusable_runs_root).map(task => option(task.task_id, task.label)));
      if ([...$('task').options].some(item => item.value === previous)) $('task').value = previous;
      if ($('task').value !== previous) invalidate();
      if (!$('task').value && !selected && !intent && editor.candidateEnabled) status(tasks.some(task => task.reusable_runs_root)
        ? 'Prepare a run in step 1, or open an earlier prepared run below.' : 'No task is configured for runs of saved workflows on this console.');
      else if (editor.candidateEnabled && !selected) await list();
    } catch (error) { if (!error.stale) { tasksRevision = null; status(error.message); } }
    controls();
  }
  window.addEventListener('workflow-editor-state', event => {
    const previous = editor; editor = event.detail;
    if (previous.savedSha256 !== editor.savedSha256 || previous.saving !== editor.saving) {
      generation++;
      if (session.connected && editor.sourceAvailable && !editor.saving && !selected) void list();
    }
    if (previous.projectId !== editor.projectId) { invalidate(); $('run').replaceChildren(option('', 'Choose a prepared run')); if (session.connected) void list(); }
    if (!editor.candidateEnabled && editor.projectId) status('This project is editable but not enabled for candidate runs.');
    controls();
  });
  session.subscribe(() => {
    if (!session.connected) { generation++; review = null; $('summary').replaceChildren(); $('details').textContent = ''; credentials(null); }
    controls();
    if (session.connected && ['workflow', 'run'].includes(window.consoleNavigation?.view)) void loadTasks();
    if (session.connected) { void checkPreparation(); if (intent) void check(); }
  });
  window.addEventListener('console-view', event => {
    if (['workflow', 'run'].includes(event.detail.view)) void loadTasks();
    if (event.detail.view === 'run' && session.connected) { void checkPreparation(); if (intent) void check(); }
  });
  window.addEventListener('console-reachability', () => controls());
  $('task').addEventListener('change', () => { invalidate(); $('run').replaceChildren(option('', 'Choose a prepared run')); void list(); });
  $('run').addEventListener('change', invalidate);
  $('refresh').addEventListener('click', () => { generation++; void list(); });
  $('more').addEventListener('click', () => { generation++; void list(true); });
  $('open').addEventListener('click', async () => {
    if (!session.connected || busy || !$('run').value) return;
    invalidate(); const version = generation, revision = session.revision;
    try { const value = await api('/select', {task_id: $('task').value, run_id: $('run').value}); if (!current(version, revision)) return; selected = value; status('Prepared run opened. Review it, then launch.'); }
    catch (error) { if (!error.stale && current(version, revision)) status(error.message); }
    controls();
  });
  $('review').addEventListener('click', async () => {
    if (!session.connected || !selected) return;
    const version = ++generation, revision = session.revision; review = null; $('summary').replaceChildren(); $('details').textContent = ''; controls();
    try {
      const value = await api('/review', selected); if (!current(version, revision)) return; review = value;
      const profile = profileDescriptions[value.execution_profile]
        || (value.execution_profile ? ' Proposal fanout executed serially.' : '');
      const nodes = value.nodes.map(item => item[0]).join(value.execution_profile ? ', ' : ' → ');
      $('summary').textContent = `${value.run_name} · ${value.task_label} · Captured workflow.${profile} Nodes: ${nodes}.`;
      credentials(value.credential_readiness);
      const routes = value.routes.map(route => `${route.node_id}: ${route.provider || 'unresolved'} / ${route.model || 'unresolved'}`).join('\n');
      $('details').textContent = `Task manifest: ${value.task_manifest}\nDataset: ${value.data_root}\nLLM config: ${value.llm_config_file}\nInputs: ${value.inputs}\nWorkspace: ${value.workspace}\nRoutes:\n${routes}\nTimeout: ${value.candidate_timeout_seconds} s\nNetwork: ${value.network}\nDevices: ${value.devices.join(', ') || 'none'}\nEnvironment names: ${value.environment_names.join(', ') || 'none'}\nRead-only paths:\n${value.read_only.join('\n')}\nOutput types: ${value.allowed_output_types?.join(', ') || 'unconstrained'}\nProposal advice: ${value.proposal_advice || 'none'}\nImplementation advice: ${value.implementation_advice || 'none'}\nValidation advice: ${value.validation_advice || 'none'}\nSource: ${value.source_path}\nSource version: ${value.source_sha256}\nComposition: ${value.composition_fingerprint}\nRequest: ${value.request_digest}\n${researchLoop(value)}`;
      if (value.literature_settings && Object.keys(value.literature_settings).length) {
        $('details').textContent += '\nCaptured literature settings (omitted fields use native defaults):\n' + JSON.stringify(value.literature_settings, null, 2);
      }
      const workspace = document.createElement('p'); workspace.textContent = 'Output workspace: ' + value.workspace; $('summary').append(workspace);
      const loop = document.createElement('p'); loop.id = 'capture-loop'; loop.textContent = researchLoop(value); $('summary').append(loop);
      const routeSummary = document.createElement('p'); routeSummary.textContent = 'Model routes: ' + value.routes.map(route => `${route.node_id} → ${route.provider || '?'} / ${route.model || '?'}`).join('; '); $('summary').append(routeSummary);
      status(value.credential_readiness.ready
        ? 'Reviewed. Launch runs the captured stages, inputs and model routes, and may call paid model APIs.'
        : 'Cannot launch yet: credentials are not ready. Fix them, then review again.');
    } catch (error) { if (!error.stale && current(version, revision)) status(error.message); }
    controls();
  });
  $('launch').addEventListener('click', async () => {
    if (!session.connected || !review?.credential_readiness.ready || intent || busy || storageProblem || !coordinator.eligible()) return;
    const exact = {version: 1, origin: location.origin, project: editor.projectId,
      payload: {selection: review.selection, expected_request_digest: review.request_digest, candidate_operation_id: crypto.randomUUID()}};
    try { coordinator.save('candidate', exact); }
    catch (_) { status('Launch not sent: this browser could not keep the launch request.'); return; }
    intent = exact; terminal = false; showIntent(); controls(); await launchRetained(true);
  });
  $('retry').addEventListener('click', () => { problem = ''; void launchRetained(false); });
  async function check() {
    if (!session.connected || !intent || busy || checking || !coordinator.same('candidate', intent)) return;
    const exact = intent; checking = true;
    try { const value = await session.request('operations/' + exact.payload.candidate_operation_id); if (intent === exact && coordinator.same('candidate', exact)) displayOperation(value); }
    catch (error) { if (!error.stale && intent === exact && coordinator.same('candidate', exact)) {
      if (error.code === 'unknown_operation') { coordinator.observeUnknown('candidate', exact); problem = 'unknown'; }
      else if (problem !== 'refused') problem = 'unresolved';
      $('operation-status').textContent = unresolvedMessage(error);
    } }
    finally { checking = false; controls(); }
  }
  $('check').addEventListener('click', () => { void check(); });
  // The preparation record's release is evidence for Launch eligibility; read it too, so
  // Launch never waits for a manual "Check status" after a reload (R-2).
  async function checkPreparation() {
    let record = null;
    try { record = coordinator.read('preparation'); } catch (_) { return; }
    if (!record || !session.connected || coordinator.state('preparation', record.value)?.released) return;
    try {
      const value = await session.request('operations/' + record.value.payload.selection.preparation_operation_id);
      coordinator.observe('preparation', record.value, value);
    } catch (error) {
      if (!error.stale && error.code === 'unknown_operation') coordinator.observeUnknown('preparation', record.value);
    }
  }
  setInterval(() => {
    if (!session.connected || document.hidden || window.consoleNavigation?.view !== 'run') return;
    const state = evidence();
    if (intent && !state?.released && problem !== 'unknown' && problem !== 'refused') void check();
  }, POLL_MS);
  $('finish').addEventListener('click', () => {
    if (busy || !session.connected || !intent || !coordinator.dismissible('candidate', intent)) return;
    const state = evidence();
    if (state?.forgettable && !state.released && !state.refused &&
        !window.confirm('Forget this run in this browser? This console has no record of it, so nothing is stopped or deleted.')) return;
    try { coordinator.dismiss('candidate', intent); } catch (_) { $('operation-status').textContent = 'This run changed or its outcome is unconfirmed; it is kept.'; return; }
    intent = null; terminal = false; refusedInitial = false; problem = ''; $('intent').hidden = true; invalidate();
  });
  coordinator.subscribe(() => {
    try {
      const stored = coordinator.read('candidate')?.value || null;
      if (JSON.stringify(stored) !== JSON.stringify(intent)) { intent = stored; terminal = false; refusedInitial = false; showIntent(); if (intent) void check(); }
      storageProblem = false;
    } catch (_) { storageProblem = true; }
    controls();
  });
  window.reusableCandidate = Object.freeze({async openPrepared(context) {
    if (!session.connected || editor.projectId !== context.project) { status('Select the retained project in Workflow before opening this run.'); return; }
    const captureHeading = document.getElementById('capture-heading');
    // Scroll only once the Run panel is visible: the hashchange route runs asynchronously.
    const scroll = () => requestAnimationFrame(() => captureHeading.scrollIntoView({block: 'start'}));
    if (window.consoleNavigation.view !== 'run') {
      window.addEventListener('console-view', scroll, {once: true}); location.hash = 'run';
    } else scroll();
    invalidate(); handoffGeneration = generation; tasksRevision = session.revision;
    const version = generation, revision = session.revision;
    if (![...$('task').options].some(item => item.value === context.task)) {
      $('task').append(option(context.task, context.task));
    }
    $('task').value = context.task;
    $('run').replaceChildren(option(context.run, context.run));
    try {
      const value = await api('/select', {task_id: context.task, run_id: context.run}, context.project);
      if (!current(version, revision)) return;
      selected = value; status('Prepared run opened. Review it, then launch.');
      tasksRevision = null;
      void loadTasks();
    } catch (error) { if (!error.stale && current(version, revision)) status(error.message); }
    controls();
  }});
  controls();
})();
