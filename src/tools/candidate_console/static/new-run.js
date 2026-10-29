/* Step 1 of Run: saved source -> explicit preparation -> handoff to the prepared run.
 * The retained preparation is observed automatically while the Run view is open
 * (R-1/R-2); effectful actions (Prepare, Retry, Forget) stay explicit. */
(() => {
  'use strict';
  const $ = id => document.getElementById('new-run-' + id);
  const session = window.consoleSession;
  const coordinator = window.reusableIntents;
  const POLL_MS = 2000;
  let editor = window.workflowEditor.state;
  let generation = 0, review = null, busy = false, checking = false, intent = null, operation = null;
  let ids = null, tasksRevision = null, nameTouched = false, problem = '';
  // Bytes of the intent this page created; only that one auto-opens when prepared.
  let createdHere = null, openedFor = null;
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
  const prepared = () => operation?.kind === 'prepare_reusable' &&
    operation?.state === 'completed' && operation?.receipt_available &&
    operation?.native_status === 'prepared';
  const evidence = () => intent ? coordinator.state('preparation', intent) : null;
  // Distinct, readable default: <project>-<yyyymmdd-hhmmss> (local time; seconds keep two
  // runs prepared within the same minute apart, L-6).
  function defaultName() {
    const now = new Date(), two = value => String(value).padStart(2, '0');
    const stamp = `${now.getFullYear()}${two(now.getMonth() + 1)}${two(now.getDate())}-${two(now.getHours())}${two(now.getMinutes())}${two(now.getSeconds())}`;
    return `${editor.projectId || 'run'}-${stamp}`;
  }
  function suggestName() {
    if (!nameTouched && !intent) $('name').value = defaultName();
  }
  function credentials(readiness) {
    const line = $('credentials');
    line.hidden = !readiness;
    if (!readiness) return;
    line.toggleAttribute('data-ready', readiness.ready);
    line.textContent = readiness.ready
      ? (readiness.file_status === 'not_needed' ? 'No credentials are configured for this task.' : 'Credentials: the configured names are present (names only checked).')
      : `Launch will need credentials: ${[...readiness.missing_names, ...readiness.omitted_names].join(', ') || 'see below'} missing. ${readiness.instructions.join(' ')} You can still prepare now.`;
  }
  function controls() {
    const state = evidence();
    // One primary per state: Check inputs, then Prepare (re-checking stays available).
    $('review').hidden = !!intent;
    $('review').classList.toggle('secondary', !!review);
    $('review').textContent = review ? 'Check again' : 'Check inputs';
    $('prepare').hidden = !review || !!intent;
    $('review').disabled = !ready() || !$('task').value || !$('name').value || busy;
    $('prepare').disabled = !ready() || !review || busy || !!intent || !coordinator.eligible();
    $('task').disabled = $('name').disabled = !!intent;
    $('check').disabled = !session.connected || !intent || busy;
    const unresolved = !!intent && !prepared() && !state?.released;
    $('retry').hidden = !(unresolved && (problem === 'unknown' || problem === 'unresolved'));
    $('retry').disabled = !session.connected || !intent || busy;
    const dismissible = !!intent && coordinator.dismissible('preparation', intent);
    $('dismiss').hidden = !dismissible;
    $('dismiss').disabled = !session.connected || !intent || busy || !dismissible;
    $('dismiss').textContent = state?.forgettable && !state.released && !state.refused ? 'Forget this operation' : 'Start over';
    $('open').hidden = !intent || !prepared();
    $('open').disabled = !session.connected || !intent || busy ||
      !coordinator.same('preparation', intent) || !prepared();
    $('prerequisites').textContent = !session.connected ? 'Connect to prepare a run.'
      : intent ? 'This run uses the task and name below; start over to change them.'
      : ready() ? 'Choose the task and resources, then check the inputs.'
        : 'Open a runnable project and save your edits first.';
    window.dispatchEvent(new CustomEvent('new-run-gate', {detail: {ready: !!ready()}}));
    window.dispatchEvent(new CustomEvent('run-step-state', {detail: {
      source: 'prepare', reviewed: !!review, intent: !!intent, prepared: prepared(), problem
    }}));
  }
  function invalidate() {
    generation++;
    review = null;
    $('details').textContent = '';
    credentials(null);
    status('');
    controls();
  }
  function retained() {
    $('intent').hidden = !intent;
    if (!intent) return;
    const id = intent.payload.selection.preparation_operation_id;
    $('operation-id').textContent = id;
    $('monitor').href = '#monitor/' + id;
    $('task').value = intent.payload.selection.task_id;
    $('name').value = intent.payload.selection.run_name;
    $('operation-status').textContent = 'Checking this preparation…';
  }
  function restore() {
    try {
      const stored = coordinator.read('preparation')?.value || null;
      if (JSON.stringify(stored) !== JSON.stringify(intent)) {
        intent = stored;
        operation = null;
        problem = '';
        retained();
        if (!intent) suggestName();
        if (intent) void check();
      }
    } catch (_) { status('Saved preparation in this browser is unreadable. Clear this site\'s storage, then reload.'); }
    controls();
  }
  // One plain sentence per observed state; raw enums stay in Monitor's developer facts.
  function describe(value) {
    if (!value.state) return value.observation === 'existing' ? 'This preparation already exists (no second one was created); checking its status…'
      : value.observation === 'operation_failed' ? 'Preparation did not start. Start over to try again.' : 'Sent. Preparing…';
    if (value.state === 'starting' || value.state === 'active' || value.finishing) return 'Preparing… This usually takes under a minute.';
    // B8-2: the store reports `unknown` until the worker records its identity or outcome;
    // that is not a finished preparation and never reads as a failure.
    if (value.state === 'unknown' && !value.receipt_available) {
      return value.process?.reason === 'missing_identity' ? 'Preparing… This usually takes under a minute.' : 'Checking status…';
    }
    if (value.state === 'operation_failed') return value.reason === 'spawn_failed'
      ? 'Preparation did not start: the worker could not be launched. Start over to try again.'
      : 'Preparation failed. Its evidence is kept in Monitor; start over to try again.';
    if (prepared()) return 'Prepared. Review and launch it in step 2.';
    return `Preparation finished without a prepared run (${value.native_status || 'no result'}). Its evidence is kept in Monitor; start over to try again.`;
  }
  function display(value, exact) {
    if (!coordinator.observe('preparation', exact, value)) return;
    operation = value;
    problem = '';
    $('operation-status').textContent = describe(value);
    controls();
    if (prepared() && createdHere === JSON.stringify(exact) && openedFor !== createdHere) {
      openedFor = createdHere;
      $('open').click();
    }
  }
  function unresolvedMessage(error) {
    if (error.code === 'unknown_operation') {
      if (evidence()?.confirming) return 'This console has no record of this preparation yet. Checking once more before offering Forget…';
      return evidence()?.forgettable
        ? 'This console still has no record of this preparation after Retry. Nothing is running for it here: forget it to start over.'
        : 'This console has no record of this preparation. Retry sends the same request again; it never creates a second one.';
    }
    if (error.unreachable) return 'Can\'t check: the server is unreachable. Retrying…';
    return 'Can\'t confirm this preparation yet (' + error.message + '). Keep it; checking again…';
  }
  async function dispatch(initial = false) {
    if (!session.connected || busy || !intent || !coordinator.same('preparation', intent)) return;
    const exact = intent;
    busy = true;
    controls();
    try {
      coordinator.dispatching('preparation', exact);
      const value = await api('prepare', exact.payload, exact.project);
      if (intent === exact) display(value, exact);
    }
    catch (error) {
      if (!error.stale && intent === exact && coordinator.same('preparation', exact)) {
        const refused = initial === true && error.value?.error?.admission_not_attempted === true;
        coordinator.observe('preparation', exact, null, refused);
        problem = refused ? 'refused' : 'unresolved';
        $('operation-status').textContent = error.message + (refused
          ? ' Nothing was started (the request did not attempt admission). Start over and check the inputs again.'
          : ' The outcome is unconfirmed; this page keeps checking. Retry sends the same request.');
      }
    } finally {
      busy = false;
      controls();
    }
  }
  async function check() {
    if (!session.connected || checking || busy || !intent || !coordinator.same('preparation', intent)) return;
    const exact = intent;
    checking = true;
    try {
      const value = await session.request('operations/' + exact.payload.selection.preparation_operation_id);
      if (intent === exact) display(value, exact);
    }
    catch (error) {
      if (!error.stale && intent === exact && coordinator.same('preparation', exact)) {
        if (error.code === 'unknown_operation') { coordinator.observeUnknown('preparation', exact); problem = 'unknown'; }
        else if (problem !== 'refused') problem = 'unresolved';
        $('operation-status').textContent = unresolvedMessage(error);
      }
    }
    finally {
      checking = false;
      controls();
    }
  }
  // Poll while the Run view shows an unreleased preparation; stop on release or a settled
  // typed unknown (Retry restarts it), and pause while the tab is hidden.
  setInterval(() => {
    const state = evidence();
    if (!intent || !session.connected || document.hidden || window.consoleNavigation?.view !== 'run') return;
    // An unknown read keeps polling only while a second read is still needed (L-5).
    if (state?.released || problem === 'refused' || (problem === 'unknown' && !state?.confirming)) return;
    void check();
  }, POLL_MS);
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
      if (intent && ![...$('task').options].some(v => v.value === intent.payload.selection.task_id)) {
        $('task').append(option(intent.payload.selection.task_id, intent.payload.selection.task_id));
      }
      if ([...$('task').options].some(v => v.value === previous)) $('task').value = previous;
      if (intent) $('task').value = intent.payload.selection.task_id;
      else if ($('task').value !== previous) invalidate();
      if (!choices.length) status('No task is configured for runs of saved workflows on this console.');
    } catch (error) { if (!error.stale && current(version, revision, project)) { tasksRevision = null; status(error.message); } }
    controls();
  }
  window.addEventListener('workflow-editor-state', event => {
    const previous = JSON.stringify(editor), project = editor.projectId; editor = event.detail;
    if (editor.projectId !== project) { nameTouched = false; suggestName(); }
    if (JSON.stringify(editor) !== previous) { invalidate(); if (session.connected) void tasks(); }
  });
  session.subscribe(() => {
    invalidate(); tasksRevision = null;
    if (session.connected) { void tasks(); if (intent) void check(); }
  });
  window.addEventListener('console-view', event => {
    if (['workflow', 'run'].includes(event.detail.view)) void tasks();
    if (event.detail.view === 'run' && intent) void check();
  });
  $('task').addEventListener('change', invalidate);
  $('name').addEventListener('input', () => { nameTouched = true; invalidate(); });
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
    status('Checking inputs…');
    try {
      const value = await api('review', selection, project);
      if (!current(version, revision, project) || !ready()) return;
      review = value;
      $('details').textContent = [
        `${value.effects}`,
        `Source: ${value.source_path}`,
        `Saved source version verified: ${value.source_version_name ? `"${value.source_version_name}"` : 'current file'} (${value.selection.expected_source_sha256.slice(0, 12)}).`,
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
      credentials(value.credential_readiness);
      status('Inputs checked. Prepare copies the saved workflow and its inputs; it does not start the run.');
      void window.consoleSettings?.originLines(selection.task_id, {llm_profile: value.llm_config_file, data_root: value.data_root}).then(lines => {
        if (lines.length && review === value) $('details').textContent += '\n' + lines.join('\n');
      });
    } catch (error) { if (!error.stale && current(version, revision, project)) status('Inputs not accepted: ' + error.message); }
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
    catch (_) { status('Prepare not sent: this browser could not keep the request, or another run on this project is unresolved.'); return; }
    intent = exact;
    createdHere = JSON.stringify(exact);
    operation = null;
    problem = '';
    retained();
    $('operation-status').textContent = 'Sending…';
    await dispatch(true);
  });
  $('retry').addEventListener('click', () => { problem = ''; void dispatch(false); });
  $('check').addEventListener('click', () => { void check(); });
  // Start over (B8-4): clears step 1 and tells step 2 to drop the prepared run it shows,
  // so an older capture is never left ready to launch. Step 2 keeps a retained launch.
  function startOver() {
    if (!session.connected || busy) return false;
    if (!intent) { window.dispatchEvent(new CustomEvent('run-start-over')); invalidate(); return true; }
    const state = evidence();
    if (state?.forgettable && !state.released && !state.refused &&
        !window.confirm('Forget this preparation in this browser? This console has no record of it, so nothing is stopped or deleted.')) return false;
    try { coordinator.dismiss('preparation', intent); }
    catch (_) { status('This preparation changed or its outcome is unconfirmed; it is kept.'); return false; }
    intent = null;
    operation = null;
    ids = null;
    problem = '';
    nameTouched = false;
    retained();
    invalidate();
    suggestName();
    window.dispatchEvent(new CustomEvent('run-start-over'));
    return true;
  }
  $('dismiss').addEventListener('click', () => { void startOver(); });
  // Step 2's "Prepare the current version" (B8-3) starts step 1 over for the saved version.
  window.addEventListener('run-prepare-current', () => {
    if (!startOver()) { status('Finish or start over the preparation above first.'); return; }
    document.getElementById('run-entry').scrollIntoView({block: 'start'});
    $('review').focus();
  });
  $('open').addEventListener('click', () => {
    if ($('open').disabled || !coordinator.same('preparation', intent)) return;
    const selection = intent.payload.selection;
    void window.reusableCandidate.openPrepared({project: intent.project, task: selection.task_id, run: selection.run_id,
      sourceVersion: intent.source_version || null});
  });
  coordinator.subscribe(restore);
  suggestName();
  restore();
})();
