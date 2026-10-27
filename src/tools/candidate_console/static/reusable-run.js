/* Prepared capture consumption. Native request and credentials remain server-owned. */
(() => {
  'use strict';
  const $ = id => document.getElementById('capture-' + id);
  const session = window.consoleSession, coordinator = window.reusableIntents;
  let editor = window.workflowEditor.state, generation = 0, selected = null, review = null;
  let handoffGeneration = -1;
  let tasksRevision = null, cursor = null, busy = false, intent = null, terminal = false, refusedInitial = false, storageProblem = false;
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
  function controls() {
    const enabled = session.connected && editor.candidateEnabled && !!editor.projectId && !busy;
    $('task').disabled = !enabled;
    $('refresh').disabled = !enabled || !$('task').value;
    $('more').disabled = !enabled || !cursor;
    $('run').disabled = !enabled;
    $('open').disabled = !enabled || !$('run').value;
    $('review').disabled = !enabled || !selected;
    $('launch').disabled = !enabled || !review?.credential_readiness.ready || !!intent || storageProblem || !coordinator.eligible();
    $('check').disabled = !session.connected || !intent || busy;
    $('retry').disabled = !session.connected || !intent || busy;
    $('finish').disabled = !session.connected || !intent || busy ||
      !coordinator.dismissible('candidate', intent);
    sourceState();
  }
  function invalidate() { generation++; selected = null; review = null; $('summary').replaceChildren(); $('details').textContent = ''; controls(); }
  function showIntent() {
    $('intent').hidden = !intent;
    if (!intent) return;
    $('operation-id').textContent = intent.payload.candidate_operation_id;
    $('operation-status').textContent = 'Retained launch intent. Check status or explicitly retry this same operation.';
    $('monitor').href = '#slow-control/' + intent.payload.candidate_operation_id;
  }
  try {
    intent = coordinator.read('candidate')?.value || null;
  } catch (_) { storageProblem = true; status('Retained launch storage is unavailable or invalid. Resolve browser storage before starting a candidate.'); }
  showIntent();
  function displayOperation(value) {
    const state = value.state || value.observation;
    if (!coordinator.observe('candidate', intent, value)) return;
    terminal = coordinator.dismissible('candidate', intent);
    $('operation-status').textContent = `Operation ${state}${value.native_status ? ' · Native ' + value.native_status : ''}.`;
    $('monitor').hidden = false; $('finish').hidden = !terminal; $('finish').textContent = 'Dismiss completed operation'; controls();
  }
  async function launchRetained(initial = false) {
    if (!session.connected || !intent || busy || !coordinator.same('candidate', intent)) return;
    refusedInitial = false; $('finish').hidden = true; busy = true; controls();
    const exact = intent;
    try { const value = await api('/launch', exact.payload, exact.project); if (intent === exact && coordinator.same('candidate', exact)) displayOperation(value); }
    catch (error) { if (!error.stale && intent === exact && coordinator.same('candidate', exact)) {
      refusedInitial = initial === true && error.value?.error?.admission_not_attempted === true;
      coordinator.observe('candidate', exact, null, refusedInitial);
      $('operation-status').textContent = error.message + (refusedInitial ? ' This dispatch did not attempt admission. Discard this refused intent to review again.' : ' Outcome unconfirmed; retain this UUID and check status or retry.');
      $('finish').hidden = !refusedInitial; $('finish').textContent = refusedInitial ? 'Discard refused launch and review again' : 'Dismiss completed operation';
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
      status(page.captures.length ? 'Choose a capture explicitly. Listing does not verify candidate acceptance.' : 'No prepared captures found. Use New run above to prepare saved source.');
    } catch (error) { if (!error.stale && current(version, revision)) status(error.message); }
    controls();
  }
  async function loadTasks() {
    if (!session.connected || tasksRevision === session.revision) return;
    const revision = session.revision, version = generation; tasksRevision = revision;
    try {
      const tasks = await session.request('choices');
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
      if (!$('task').value) status(tasks.some(task => task.reusable_runs_root)
        ? 'Choose a task to list prepared runs.' : 'Reusable captures are not configured for any task.');
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
  session.subscribe(() => { if (!session.connected) { generation++; review = null; $('summary').replaceChildren(); $('details').textContent = ''; } controls(); if (session.connected && window.consoleNavigation?.view === 'workflow') void loadTasks(); });
  window.addEventListener('console-view', event => { if (event.detail.view === 'workflow') void loadTasks(); });
  $('task').addEventListener('change', () => { invalidate(); $('run').replaceChildren(option('', 'Choose a prepared run')); void list(); });
  $('run').addEventListener('change', invalidate);
  $('refresh').addEventListener('click', () => { generation++; void list(); });
  $('more').addEventListener('click', () => { generation++; void list(true); });
  $('open').addEventListener('click', async () => {
    if (!session.connected || busy || !$('run').value) return;
    invalidate(); const version = generation, revision = session.revision;
    try { const value = await api('/select', {task_id: $('task').value, run_id: $('run').value}); if (!current(version, revision)) return; selected = value; status('Prepared capture selected. Review before launch.'); }
    catch (error) { if (!error.stale && current(version, revision)) status(error.message); }
    controls();
  });
  $('review').addEventListener('click', async () => {
    if (!session.connected || !selected) return;
    const version = ++generation, revision = session.revision; review = null; $('summary').replaceChildren(); $('details').textContent = ''; controls();
    try {
      const value = await api('/review', selected); if (!current(version, revision)) return; review = value;
      const profile = value.execution_profile === 'native-proposal-families/v1'
        ? ' Independent proposal instances executed serially.'
        : (value.execution_profile === 'native-literature-candidate/v1'
          ? ' Native literature review feeds one proposal, implementation and validation.'
          : (value.execution_profile === 'native-interpretation-candidate/v1'
            ? ' Native interpretation feeds one proposal, implementation, validation and tuning.'
            : (value.execution_profile ? ' Proposal fanout executed serially.' : '')));
      const nodes = value.nodes.map(item => item[0]).join(value.execution_profile ? ', ' : ' → ');
      $('summary').textContent = `${value.run_name} · ${value.task_label} · Captured workflow.${profile} Nodes: ${nodes}. ${value.credential_readiness.ready ? 'Configured credentials ready (presence only).' : value.credential_readiness.instructions.join(' ')}`;
      const routes = value.routes.map(route => `${route.node_id}: ${route.provider || 'unresolved'} / ${route.model || 'unresolved'}`).join('\n');
      $('details').textContent = `Task manifest: ${value.task_manifest}\nDataset: ${value.data_root}\nLLM config: ${value.llm_config_file}\nInputs: ${value.inputs}\nWorkspace: ${value.workspace}\nRoutes:\n${routes}\nTimeout: ${value.candidate_timeout_seconds} s\nNetwork: ${value.network}\nDevices: ${value.devices.join(', ') || 'none'}\nEnvironment names: ${value.environment_names.join(', ') || 'none'}\nRead-only paths:\n${value.read_only.join('\n')}\nOutput types: ${value.allowed_output_types?.join(', ') || 'unconstrained'}\nProposal advice: ${value.proposal_advice || 'none'}\nImplementation advice: ${value.implementation_advice || 'none'}\nValidation advice: ${value.validation_advice || 'none'}\nSource: ${value.source_path}\nSource version: ${value.source_sha256}\nComposition: ${value.composition_fingerprint}\nRequest: ${value.request_digest}`;
      if (value.literature_settings && Object.keys(value.literature_settings).length) {
        $('details').textContent += '\nCaptured literature settings (omitted fields use native defaults):\n' + JSON.stringify(value.literature_settings, null, 2);
      }
      const workspace = document.createElement('p'); workspace.textContent = 'Output workspace: ' + value.workspace; $('summary').append(workspace);
      const routeSummary = document.createElement('p'); routeSummary.textContent = 'Model routes: ' + value.routes.map(route => `${route.node_id} → ${route.provider || '?'} / ${route.model || '?'}`).join('; '); $('summary').append(routeSummary);
      status('Capture reviewed. Launch runs the captured stages, inputs and configured model routes.');
    } catch (error) { if (!error.stale && current(version, revision)) status(error.message); }
    controls();
  });
  $('launch').addEventListener('click', async () => {
    if (!session.connected || !review?.credential_readiness.ready || intent || busy || storageProblem || !coordinator.eligible()) return;
    const exact = {version: 1, origin: location.origin, project: editor.projectId,
      payload: {selection: review.selection, expected_request_digest: review.request_digest, candidate_operation_id: crypto.randomUUID()}};
    try { coordinator.save('candidate', exact); }
    catch (_) { status('Launch not sent: browser could not retain the exact operation intent.'); return; }
    intent = exact; terminal = false; showIntent(); controls(); await launchRetained(true);
  });
  $('retry').addEventListener('click', () => launchRetained(false));
  $('check').addEventListener('click', async () => {
    if (!session.connected || !intent || busy || !coordinator.same('candidate', intent)) return;
    const exact = intent; busy = true; controls();
    try { const value = await session.request('operations/' + exact.payload.candidate_operation_id); if (intent === exact && coordinator.same('candidate', exact)) displayOperation(value); }
    catch (error) { if (!error.stale && intent === exact && coordinator.same('candidate', exact)) $('operation-status').textContent = error.message + ' Keep the same UUID; absence is not permission to create a replacement.'; }
    finally { busy = false; controls(); }
  });
  $('finish').addEventListener('click', () => {
    if (!(terminal || refusedInitial) || busy || !session.connected) return;
    try { coordinator.dismiss('candidate', intent); } catch (_) { $('operation-status').textContent = 'Intent changed or release is unconfirmed. Check status.'; return; }
    intent = null; terminal = false; refusedInitial = false; $('intent').hidden = true; invalidate();
  });
  coordinator.subscribe(() => {
    try {
      const stored = coordinator.read('candidate')?.value || null;
      if (JSON.stringify(stored) !== JSON.stringify(intent)) { intent = stored; terminal = false; refusedInitial = false; showIntent(); }
      storageProblem = false;
    } catch (_) { storageProblem = true; }
    controls();
  });
  window.reusableCandidate = Object.freeze({async openPrepared(context) {
    if (!session.connected || editor.projectId !== context.project) { status('Select the retained project in Workflow before opening this run.'); return; }
    const captureHeading = document.getElementById('capture-heading');
    captureHeading.closest('.workflow-run-details').open = true;
    captureHeading.scrollIntoView({block: 'start'});
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
      selected = value; status('Prepared run opened. Explicitly Review capture, then Launch.');
      tasksRevision = null;
      void loadTasks();
    } catch (error) { if (!error.stale && current(version, revision)) status(error.message); }
    controls();
  }});
  controls();
})();
