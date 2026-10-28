/* Saved source -> explicit preparation -> explicit captured-run handoff. */
(() => {
  'use strict';
  const $ = id => document.getElementById('new-run-' + id);
  const session = window.consoleSession;
  const coordinator = window.reusableIntents;
  let editor = window.workflowEditor.state;
  let generation = 0, review = null, busy = false, intent = null, operation = null;
  let ids = null, tasksRevision = null;
  function option(value, text) {
    const el = document.createElement('option');
    el.value = value;
    el.textContent = text;
    return el;
  }
  const status = text => { $('status').textContent = text; };
  const ready = () => session.connected && editor.candidateEnabled &&
    editor.sourceAvailable && editor.reusableSource && editor.savedSha256 &&
    !editor.dirty && !editor.sourceDirty && !editor.conflict && !editor.saving;
  // The single Run gate: page guidance reads it and never re-derives eligibility.
  window.newRunGate = Object.freeze({get ready() { return !!ready(); }});
  const current = (version, revision, project) =>
    generation === version && session.revision === revision && editor.projectId === project;
  const api = (suffix, body, project = editor.projectId) =>
    session.request(`editor/${encodeURIComponent(project)}/reusable-preparations/${suffix}`, body);
  function controls() {
    $('review').disabled = !ready() || !$('task').value || !$('name').value || busy;
    $('prepare').disabled = !ready() || !review || busy || !!intent || !coordinator.eligible();
    $('check').disabled = !session.connected || !intent || busy;
    $('retry').disabled = !session.connected || !intent || busy;
    $('dismiss').disabled = !session.connected || !intent || busy || !coordinator.dismissible('preparation', intent);
    const prepared = operation?.kind === 'prepare_reusable' &&
      operation?.state === 'completed' && operation?.receipt_available &&
      operation?.native_status === 'prepared';
    $('open').disabled = !session.connected || !intent || busy ||
      !coordinator.same('preparation', intent) || !prepared;
    $('prerequisites').textContent = ready()
      ? 'Saved source ready. Choose a configured task and resource set, then review preparation.'
      : 'Select a runnable project with supported reusable source. Save edits and resolve conflicts before preparation.';
    window.dispatchEvent(new CustomEvent('new-run-gate', {detail: {ready: !!ready()}}));
  }
  function invalidate() {
    generation++;
    review = null;
    $('details').textContent = '';
    status('Inputs changed. Review preparation again.');
    controls();
  }
  function retained() {
    $('intent').hidden = !intent;
    if (!intent) return;
    const id = intent.payload.selection.preparation_operation_id;
    $('operation-id').textContent = id;
    $('monitor').href = '#monitor/' + id;
    // Display-only: a malformed stored version (hand-edited storage) is ignored.
    const stored = intent.source_version;
    const version = stored && typeof stored === 'object' && typeof stored.sha256 === 'string' &&
      /^[0-9a-f]{64}$/.test(stored.sha256) && (stored.name === null || stored.name === undefined || typeof stored.name === 'string')
      ? stored : null;
    const named = version ? ` for source version ${version.name ? `"${version.name}"` : 'unnamed'} (${version.sha256.slice(0, 12)})` : '';
    $('operation-status').textContent = `Retained preparation intent${named}. Check or retry this exact operation; current editor changes are separate.`;
  }
  function restore() {
    try {
      const stored = coordinator.read('preparation')?.value || null;
      if (JSON.stringify(stored) !== JSON.stringify(intent)) {
        intent = stored;
        operation = null;
        retained();
      }
    } catch (_) { status('Preparation storage unavailable or invalid. Resolve browser storage before dispatch.'); }
    controls();
  }
  function display(value, exact) {
    if (!coordinator.observe('preparation', exact, value)) return;
    operation = value;
    const native = value.native_status ? ' · Native ' + value.native_status : '';
    const outcome = value.native_status && value.native_status !== 'prepared'
      ? 'This run did not prepare successfully; preserve its evidence.'
      : 'Preparation never launches a candidate automatically.';
    $('operation-status').textContent = `Operation ${value.state || value.observation}${native}. ${outcome}`;
    controls();
  }
  async function dispatch(initial = false) {
    if (!session.connected || busy || !intent || !coordinator.same('preparation', intent)) return;
    const exact = intent;
    busy = true;
    controls();
    try {
      const value = await api('prepare', exact.payload, exact.project);
      if (intent === exact) display(value, exact);
    }
    catch (error) {
      if (!error.stale && intent === exact && coordinator.same('preparation', exact)) {
        const refused = initial === true && error.value?.error?.admission_not_attempted === true;
        coordinator.observe('preparation', exact, null, refused);
        const guidance = refused
          ? ' This dispatch did not attempt admission. Explicitly discard and review again.'
          : ' Outcome unresolved. Retain this UUID and check or retry.';
        $('operation-status').textContent = error.message + guidance;
      }
    } finally {
      busy = false;
      controls();
    }
  }
  async function tasks() {
    if (!session.connected || !['workflow', 'run'].includes(window.consoleNavigation?.view) || tasksRevision === session.revision) return;
    const version = generation;
    const revision = session.revision;
    const project = editor.projectId;
    tasksRevision = revision;
    try {
      const values = (await session.choices()).tasks;
      if (!current(version, revision, project)) {
        tasksRevision = null;
        void tasks();
        return;
      }
      const previous = $('task').value;
      const choices = values.filter(v => v.reusable_runs_root).map(v => option(v.task_id, v.label));
      $('task').replaceChildren(option('', 'Choose task and resources'), ...choices);
      if ([...$('task').options].some(v => v.value === previous)) $('task').value = previous;
      if ($('task').value !== previous) invalidate();
    } catch (error) { if (!error.stale && current(version, revision, project)) { tasksRevision = null; status(error.message); } }
    controls();
  }
  window.addEventListener('workflow-editor-state', event => {
    const previous = JSON.stringify(editor); editor = event.detail;
    if (JSON.stringify(editor) !== previous) { invalidate(); if (session.connected) void tasks(); }
  });
  session.subscribe(() => { invalidate(); tasksRevision = null; if (session.connected) void tasks(); });
  window.addEventListener('console-view', event => { if (['workflow', 'run'].includes(event.detail.view)) void tasks(); });
  $('task').addEventListener('change', invalidate); $('name').addEventListener('input', invalidate);
  $('review').addEventListener('click', async () => {
    if (!ready() || busy || !$('task').value || !$('name').value) return;
    ids ||= {run_id: crypto.randomUUID(), preparation_operation_id: crypto.randomUUID()};
    invalidate();
    const version = generation;
    const revision = session.revision;
    const project = editor.projectId;
    const selection = {
      task_id: $('task').value, run_name: $('name').value, ...ids,
      expected_source_sha256: editor.savedSha256
    };
    try {
      const value = await api('review', selection, project);
      if (!current(version, revision, project) || !ready()) return;
      review = value;
      $('details').textContent = [
        `${value.effects}`,
        `Source: ${value.source_path}`,
        `Saved source version verified: ${value.source_version_name ? `"${value.source_version_name}"` : 'unnamed'} (${value.selection.expected_source_sha256.slice(0, 12)}).`,
        `Task: ${value.task_label}`,
        `Manifest: ${value.task_manifest}`,
        `Data: ${value.data_root}`,
        `LLM config: ${value.llm_config_file}`,
        `Inputs: ${value.inputs}`,
        `Workspace: ${value.workspace}`,
        `Preparation timeout: ${value.preparation_timeout_seconds} s`,
        `Candidate timeout: ${value.candidate_timeout_seconds} s`,
        `Candidate network: ${value.network}`,
        `Devices: ${value.devices.join(', ') || 'none'}`,
        `Environment names: ${value.environment_names.join(', ') || 'none'}`,
        `Read-only paths: ${value.read_only.join(', ') || 'none'}`,
      ].join('\n');
      status('Preparation reviewed. Prepare creates captured inputs; credentials are checked later at candidate review.');
    } catch (error) { if (!error.stale && current(version, revision, project)) status(error.message); }
    controls();
  });
  $('prepare').addEventListener('click', async () => {
    if (!ready() || !review || busy || intent || !coordinator.eligible()) return;
    const exact = {
      version: 1, origin: location.origin, project: editor.projectId,
      // Display record only; payload binds the SHA-256 exactly as before.
      source_version: {name: review.source_version_name ?? null, sha256: review.selection.expected_source_sha256},
      payload: {selection: review.selection, expectation: review.expectation}
    };
    try { coordinator.save('preparation', exact); }
    catch (_) { status('Prepare not sent: exact intent could not be retained or another operation is unresolved.'); return; }
    intent = exact;
    operation = null;
    retained();
    await dispatch(true);
  });
  $('retry').addEventListener('click', () => dispatch(false));
  $('check').addEventListener('click', async () => {
    if (!session.connected || busy || !intent || !coordinator.same('preparation', intent)) return;
    const exact = intent;
    busy = true;
    controls();
    try {
      const value = await session.request('operations/' + exact.payload.selection.preparation_operation_id);
      if (intent === exact) display(value, exact);
    }
    catch (error) {
      if (!error.stale && intent === exact && coordinator.same('preparation', exact)) {
        $('operation-status').textContent = error.message +
          ' Keep this UUID; absence does not establish a safe replacement.';
      }
    }
    finally {
      busy = false;
      controls();
    }
  });
  $('dismiss').addEventListener('click', () => {
    if (!session.connected || busy || !intent) return;
    try { coordinator.dismiss('preparation', intent); }
    catch (_) { status('Intent changed or release is unconfirmed. Check status.'); return; }
    intent = null;
    operation = null;
    ids = null;
    retained();
    invalidate();
  });
  $('open').addEventListener('click', () => {
    if ($('open').disabled || !coordinator.same('preparation', intent)) return;
    const selection = intent.payload.selection;
    void window.reusableCandidate.openPrepared({project: intent.project, task: selection.task_id, run: selection.run_id});
  });
  coordinator.subscribe(restore);
  restore();
})();
