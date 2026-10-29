/* Native service owns execution and identity; page collects explicit requests and renders observations. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let choices = [], preparation = null, review = null, launch = null;
  let monitorId = '', cursor = 0, logText = '', polling = false, connected = false, graphResultsAttemptedFor = '';
  let monitorEpoch = 0, generation = 0, invalidRoute = false;
  // Monitor stops reading an operation after one full read of a terminal state (M-5) or a
  // typed unknown_operation (M-3); re-entering its route reads it once more.
  let settled = '', lastStatus = null;
  // Display only: strip ANSI CSI sequences (colour/cursor codes); the source log is unchanged (M-6).
  const plainLog = text => text.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '');
  const localTime = value => { const time = new Date(value); return Number.isNaN(time.getTime()) ? String(value) : time.toLocaleString(); };
  function observedLine(id, status, final) {
    const element = document.getElementById('operation-observed');
    const at = status?.observed_at;
    const paused = status?.native_status === 'paused' && !window.loopEndedSentence(status);
    say('operation-observed', (paused ? 'Current status · observed ' : final ? 'Final status · observed ' : 'Observed ') + (at ? localTime(at) : 'unavailable'));
    if (at) element.title = 'Operation ' + id + ' · ' + at; else element.title = 'Operation ' + id;
  }
  const say = (id, value) => { if (document.getElementById(id).textContent !== value) document.getElementById(id).textContent = value; };
  const remember = id => { try { localStorage.setItem('siderius.operation_id', id); } catch { /* Storage may be unavailable. */ } };
  try { $('operation-id').value = localStorage.getItem('siderius.operation_id') || ''; if ($('operation-id').value) say('remembered-operation', 'Last opened on this browser.'); } catch { /* Optional convenience. */ }

  const api = (path, body) => window.consoleSession.request(path, body);
  const monitorStop = window.operationStop.mount('operation-stop');
  function facts(element, rows) {
    element.replaceChildren();
    for (const [label, value] of rows) {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label;
      dd.textContent = value == null ? 'Not available' : String(value);
      element.append(dt, dd);
    }
  }
  function limits() {
    const task = choices.find(item => item.task_id === $('task').value);
    facts($('configured-paths'), task ? [ ['Task manifest', task.task_manifest], ['Data root', task.data_root], ['Model profile', task.llm_config_file], ['Preparation output parent', task.preparation_root], ['Candidate output parent', task.candidate_root] ] : []);
    say('limits', task ? `Preparation limit: ${task.preparation_timeout_seconds}s · Candidate limit: ${task.candidate_timeout_seconds}s` : '');
  }
  function controls() {
    $('draft').disabled = !connected || !choices.length || preparation !== null;
    $('prepare-button').disabled = !connected || !choices.length || !!preparation?.pending || !!preparation?.accepted;
    say('prepare-button', preparation ? (preparation.pending ? 'Submitting preparation…' : preparation.accepted ? 'Preparation submitted' : 'Retry same preparation') : 'Prepare request');
    $('new-preparation').disabled = !connected || !!preparation?.pending || !!launch?.pending;
    $('launch-button').disabled = !connected || !review || !review.credential_readiness?.ready || !!launch?.pending || !!launch?.accepted;
    say('launch-button', launch ? (launch.pending ? 'Submitting candidate…' : launch.accepted ? 'Candidate submitted' : 'Retry same candidate launch') : 'Launch candidate');
    $('refresh-review').disabled = !connected || !review || !!launch?.pending || !!launch?.accepted;
    $('monitor-button').disabled = !connected;
  }
  $('task').addEventListener('change', limits);
  async function loadChoices() {
    const selectedTask = $('task').value;
    try {
      choices = (await window.consoleSession.choices()).tasks;
      $('task').replaceChildren();
      for (const task of choices) {
        const option = document.createElement('option'); option.value = task.task_id; option.textContent = task.label; $('task').append(option);
      }
      if (choices.some(task => task.task_id === selectedTask)) $('task').value = selectedTask;
      if (preparation) {
        const submittedTask = preparation.payload.task_id;
        if (!choices.some(task => task.task_id === submittedTask)) {
          const option = document.createElement("option"); option.value = submittedTask; option.textContent = "Submitted task: " + submittedTask; document.getElementById("task").append(option);
        }
        document.getElementById("task").value = submittedTask;
      }
      limits();
      if (!choices.length) say('prepare-status', 'No candidate tasks configured. Native captures and known-UUID monitoring remain available.');
    } catch (error) {
      if (!error.stale) say('prepare-status', 'Configured tasks unavailable: ' + error.message);
    }
    controls();
  }
  window.consoleSession.subscribe(state => {
    connected = state.connected; monitorEpoch++;
    controls();
    if (connected) { if (window.consoleNavigation?.view !== 'monitor') void loadChoices(); void poll(); }
    else {
      if (monitorId) say('monitor-status', 'Observation unconfirmed. Reconnect to refresh; last displayed facts are retained.');
      if (preparation?.pending) say('prepare-status', 'Submission unconfirmed after connection change. Read this UUID or retry the same frozen request.');
      if (launch?.pending) say('launch-status', 'Submission unconfirmed after connection change. Read this UUID or retry the same frozen request.');
    }
  });
  window.addEventListener('console-view', event => {
    invalidRoute = !event.detail.valid;
    if (invalidRoute) { monitorEpoch++; return; }
    if (event.detail.operation) setMonitor(event.detail.operation);
    if (event.detail.view === 'monitor') settled = '';
    if (connected && event.detail.view === 'home' && !choices.length) void loadChoices();
    if (connected) void poll();
  });
  $('new-preparation').addEventListener('click', () => {
    generation++; preparation = null; review = null; launch = null;
    $('review').replaceChildren(); say('prepare-id', ''); say('candidate-id', '');
    say('prepare-status', 'Edit the draft, then explicitly prepare a new request.');
    say('review-status', 'A new preparation is required before another launch.');
    say('launch-status', 'No candidate launch submitted.'); controls(); $('task').focus();
  });
  $('prepare-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!connected || preparation?.pending || preparation?.accepted) return;
    if (!preparation) {
      const advice = id => $(id).value || null;
      const id = crypto.randomUUID();
      preparation = { id, pending: false, accepted: false, payload: { operation_id: id, task_id: $('task').value, run_name: $('run-name').value,
        proposal_advice: advice('proposal-advice'), implementation_advice: advice('implementation-advice'), validation_advice: advice('validation-advice') } };
      say('prepare-id', 'Preparation UUID: ' + id); remember(id);
    }
    const current = preparation;
    current.pending = true; controls(); say('prepare-status', 'Submitting preparation. The draft is frozen for safe retries.');
    try {
      const handle = await api('preparations', current.payload);
      current.accepted = true;
      say('prepare-status', 'Preparation submission observed: ' + handle.observation + '. Reading native status…');
      setMonitor(current.id); await poll();
    } catch (error) {
      if (error.stale) return;
      say('prepare-status', 'Submission outcome is unconfirmed or refused: ' + error.message + '. Read this UUID or retry the same request; use New preparation to change inputs.');
    } finally { current.pending = false; controls(); }
  });
  function describe(status) {
    const native = status.native_status ? ' · Native: ' + status.native_status : '';
    const finishing = status.finishing ? ' · Finishing: Native result is available; the wrapper is still finishing.' : '';
    return `State: ${status.state}${native}${finishing}`;
  }
  $('refresh-review').addEventListener('click', async () => { review = null; controls(); await readPreparation(); });
  async function readPreparation() {
    if (!preparation?.accepted || preparation.reviewBlocked || review) return;
    const current = preparation, currentGeneration = generation;
    try {
      const status = await api('operations/' + current.id);
      if (current !== preparation) return;
      say('prepare-status', describe(status));
      if (status.kind === 'prepare' && status.state === 'completed' && status.receipt_available) {
        const result = await api('preparations/' + current.id + '/review');
        if (currentGeneration !== generation) return;
        review = result;
        const dl = document.createElement('dl'); dl.className = 'facts'; $('review').replaceChildren(dl);
        facts(dl, [ ['Task', `${result.task_label} (${result.task_id})`], ['Run name', result.run_name], ['Preparation UUID', result.prepare_operation_id],
          ['Stages', result.stages.join(' → ')],
          ['Routes', result.routes.map(route => `${route.node_id}: ${route.provider} / ${route.model}`).join('\n')],
          ['Proposal advice', result.proposal_advice || '(none)'], ['Implementation advice', result.implementation_advice || '(none)'], ['Validation advice', result.validation_advice || '(none)'],
          ['Task manifest', result.task_manifest], ['Data root', result.data_root], ['Candidate workspace', result.candidate_workspace],
          ['Preparation timeout', result.preparation_timeout_seconds + 's'], ['Candidate timeout', result.candidate_timeout_seconds + 's'],
          ['Network', result.network], ['Devices', result.devices.join(', ') || '(none)'], ['Environment names', result.environment_names.join(', ') || '(none)'], ['Read-only paths', result.read_only.join('\n') || '(none)'],
          ['Required provider names', result.credential_readiness.required_names.join(', ') || '(none)'],
          ['Omitted from candidate_environment_names', result.credential_readiness.omitted_names.join(', ') || '(none)'],
          ['Unresolved credential routes', result.credential_readiness.unresolved_routes.join(', ') || '(none)'],
          ['Selected credential_file', result.credential_readiness.file_status],
          ['Present names', result.credential_readiness.present_names.join(', ') || '(none)'],
          ['Missing or empty names', result.credential_readiness.missing_names.join(', ') || '(none)'],
          ['Repair', result.credential_readiness.instructions.join('\n') || '(none)'] ]);
        say('review-status', 'Prepared request loaded. ' + (result.credential_readiness.ready ? 'Name presence checked; review before launching. This does not verify provider access or billing.' : 'Launch blocked. Follow the repair instructions, then Refresh readiness.')); controls();
      }
    } catch (error) {
      if (error.stale) return;
      if (current === preparation) say('prepare-status', 'Observation stale or review unavailable: ' + error.message + '. This does not establish whether the operation stopped.');
    }
  }
  $('launch-button').addEventListener('click', async () => {
    if (!connected || !review || !review.credential_readiness?.ready || launch?.pending || launch?.accepted) return;
    if (!launch) {
      const id = crypto.randomUUID();
      launch = { id, pending: false, accepted: false, payload: { candidate_operation_id: id, prepare_operation_id: review.prepare_operation_id, expected_prepared_digest: review.prepared_digest } };
      say('candidate-id', 'Candidate UUID: ' + id); remember(id);
    }
    const current = launch; current.pending = true; controls();
    say('launch-status', 'Submitting the explicitly reviewed candidate…');
    try {
      const handle = await api('candidates', current.payload); current.accepted = true;
      say('launch-status', 'Candidate submission observed: ' + handle.observation + '. Read status below for the native outcome.'); setMonitor(current.id); await poll();
    } catch (error) {
      if (error.stale) return;
      if (['stale_review', 'integrity', 'task_policy', 'conflict', 'not_prepared'].includes(error.code)) {
        preparation.reviewBlocked = true;
        review = null;
        say('review-status', 'Launch refused. The review may be stale or the request conflicts. Read the candidate UUID for an existing admission; otherwise create and review a new preparation.');
      }
      say('launch-status', 'Submission outcome is unconfirmed or refused: ' + error.message + '. No automatic retry will occur.');
    } finally { current.pending = false; controls(); }
  });
  function setMonitor(id) {
    if (monitorId.toLowerCase() === id.toLowerCase()) return;
    monitorEpoch++; settled = ''; lastStatus = null; $('monitor-cause').hidden = true; window.renderNativeChain(null); window.renderGraphResults(null); window.renderLoopControl(null); monitorStop.render(null); monitorId = id; graphResultsAttemptedFor = ''; cursor = 0; logText = ''; say('log', ''); $('operation-id').value = id; remember(id); $('operation-facts').replaceChildren();
    $('token-rows').replaceChildren(); $('tokens-table').hidden = true; say('tokens-times', ''); say('tokens-provenance', '');
    say('remembered-operation', '');
    observedLine(id, null, false);
    say('tokens-status', 'Reading reported tokens…');
    say('monitor-status', 'Reading operation ' + id + '…');
  }
  $('monitor-form').addEventListener('submit', async event => {
    event.preventDefault(); const id = $('operation-id').value.trim();
    if (!window.consoleNavigation.isOperationId(id)) { say('monitor-status', 'Enter a complete operation UUID.'); $('operation-id').focus(); return; }
    // An explicit Read always re-reads, also for an operation already settled.
    setMonitor(id); settled = ''; location.hash = 'monitor/' + id; await poll();
  });
  window.addEventListener('loop-control-changed', event => {
    if (event.detail.operation_id === monitorId) { monitorEpoch++; settled = ''; void poll(); }
  });
  $('log-kind').addEventListener('change', () => { monitorEpoch++; cursor = 0; logText = ''; say('log', ''); void poll(); });
  async function readMonitor() {
    if (!monitorId || settled === monitorId) return;
    const id = monitorId, epoch = monitorEpoch, kind = $('log-kind').value;
    let terminal = false;
    try {
      const status = await api('operations/' + id);
      if (epoch !== monitorEpoch) return;
      terminal = window.operationOutcome.terminal(status); lastStatus = status;
      window.renderNativeChain(status); window.renderLoopControl(status); monitorStop.render(status);
      // One plain outcome sentence (M-2); the raw enums stay in developer facts.
      const finishing = status.finishing ? ' The result is in; the worker is still finishing.' : '';
      say('monitor-status', (window.loopEndedSentence(status) || window.operationOutcome.sentence(status)) + finishing);
      observedLine(id, status, terminal);
      facts($('operation-facts'), [['Operation UUID', status.operation_id], ['Kind', status.kind], ['State', status.state], ['Native status', status.native_status || '(none)'], ['Observed at', status.observed_at],
        ['Process observation', `${status.process.status}: ${status.process.reason || '(no reason supplied)'}`], ['Native ID', status.native_id],
        ['Validation passed', status.validation_passed === null ? 'Not available' : String(status.validation_passed)], ['Reason', status.reason || '(none)'], ['Native receipt available', String(status.receipt_available)], ['Seed', status.seed]]);
      if (['candidate', 'candidate_loop_resume'].includes(status.kind) && status.state === 'completed' && graphResultsAttemptedFor !== id) {
        graphResultsAttemptedFor = id;
        try {
          const projection = await api(`operations/${id}/graph-results`);
          if (epoch !== monitorEpoch) return;
          window.renderGraphResults(projection);
        } catch (error) {
          if (epoch !== monitorEpoch) return;
          // Only a server verdict is final; disconnection retries on the existing poll.
          if (![404, 409].includes(error.status)) graphResultsAttemptedFor = '';
          if (!error.stale) window.renderGraphResults(null, error.status === 409 ? 'Workflow results could not be verified for this operation; no score is shown.' : 'Workflow results are unavailable for this operation.');
        }
      }
      const chunk = await api(`operations/${id}/log?kind=${kind}&offset=${cursor}&max_bytes=65536`);
      if (epoch !== monitorEpoch) return;
      cursor = chunk.next_offset;
      logText = (chunk.truncated ? '[Source log truncated; cursor reset by server]\n' : '') + logText + plainLog(chunk.text);
      if (logText.length > 262144) logText = '[Earlier displayed text omitted]\n' + logText.slice(-262144);
      say('log', logText);
      // L-2: a failed run names its cause in one line, taken from the log shown below.
      const failure = window.operationOutcome.failed(lastStatus) ? window.operationOutcome.cause(logText) : null;
      $('monitor-cause').hidden = !failure;
      say('monitor-cause', failure ? 'Cause (from the log): ' + failure : '');
      say('log-status', chunk.missing ? 'Log not available yet.' : `Log observed: ${chunk.observed_size} source bytes · Next byte offset: ${cursor}`);
      // One full read after a terminal state, then no further polling of this operation.
      if (terminal && epoch === monitorEpoch && (chunk.missing || cursor >= chunk.observed_size)) settled = id;
    } catch (error) {
      if (error.stale) return;
      if (epoch !== monitorEpoch) return;
      monitorStop.observation(true);
      if (error.code === 'unknown_operation') {
        settled = id;
        say('monitor-status', 'This console has no operation with this ID. It may belong to another console or operation store.');
        return;
      }
      say('monitor-status', (error.unreachable ? 'Can\'t check: the server is unreachable. ' : 'Observation stale or unavailable: ' + error.message + '. ') + 'Last displayed facts are retained; disconnection does not mean stopped.');
    }
  }
  async function readTokens() {
    if (!monitorId || settled === monitorId) return;
    const id = monitorId, epoch = monitorEpoch;
    try {
      const snapshot = await api(`operations/${id}/tokens`);
      if (epoch !== monitorEpoch) return;
      window.presentTokenSnapshot(snapshot, {rows: $('token-rows'), table: $('tokens-table'), status: $('tokens-status'),
        provenance: $('tokens-provenance'), times: $('tokens-times')});
    } catch (error) {
      if (error.stale) return;
      if (epoch === monitorEpoch) say('tokens-status', 'Reported tokens stale or unavailable: ' + error.message + '. Last observations for this operation are retained. Disconnection does not mean zero usage or stopped.');
    }
  }
  async function poll() {
    if (!connected || document.hidden || polling || invalidRoute) return;
    polling = true;
    try { await Promise.all([readPreparation(), readMonitor(), readTokens()]); } finally { polling = false; }
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void poll(); });
  setInterval(() => { void poll(); }, 2000);
  controls();
})();
