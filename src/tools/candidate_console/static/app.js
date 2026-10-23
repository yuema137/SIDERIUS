/* Native service owns execution and identity; page collects explicit requests and renders observations. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let token = '', choices = [], preparation = null, review = null, launch = null;
  let monitorId = '', cursor = 0, logText = '', polling = false, connected = false;
  let monitorEpoch = 0, generation = 0;
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const say = (id, value) => { if (document.getElementById(id).textContent !== value) document.getElementById(id).textContent = value; };
  const remember = id => { try { localStorage.setItem('siderius.operation_id', id); } catch { /* Storage may be unavailable. */ } };
  try { $('operation-id').value = localStorage.getItem('siderius.operation_id') || ''; } catch { /* Optional convenience. */ }

  async function api(path, body) {
    const response = await fetch('/api/' + path, {
      method: body === undefined ? 'GET' : 'POST', cache: 'no-store', credentials: 'omit',
      headers: { Authorization: 'Bearer ' + token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(result.error?.message || 'The console refused this request.');
      error.status = response.status;
      error.code = result.error?.code;
      throw error;
    }
    return result;
  }
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
    say('limits', task ? `Preparation limit: ${task.preparation_timeout_seconds}s · Candidate limit: ${task.candidate_timeout_seconds}s` : '');
  }
  function controls() {
    $('draft').disabled = !connected || preparation !== null;
    $('prepare-button').disabled = !connected || !!preparation?.pending || !!preparation?.accepted;
    say('prepare-button', preparation ? (preparation.pending ? 'Submitting preparation…' : preparation.accepted ? 'Preparation submitted' : 'Retry same preparation') : 'Prepare request');
    $('new-preparation').disabled = !connected || !!preparation?.pending || !!launch?.pending;
    $('launch-button').disabled = !connected || !review || !!launch?.pending || !!launch?.accepted;
    say('launch-button', launch ? (launch.pending ? 'Submitting candidate…' : launch.accepted ? 'Candidate submitted' : 'Retry same candidate launch') : 'Launch candidate');
    $('monitor-button').disabled = !connected;
  }
  $('task').addEventListener('change', limits);
  $('access-form').addEventListener('submit', async event => {
    event.preventDefault();
    token = $('token').value.trim(); $('token').value = '';
    connected = false; controls(); say('access-status', 'Connecting…');
    try {
      choices = await api('choices');
      $('task').replaceChildren();
      for (const task of choices) {
        const option = document.createElement('option'); option.value = task.task_id; option.textContent = task.label; $('task').append(option);
      }
      if (preparation) {
        const submittedTask = preparation.payload.task_id;
        if (!choices.some(task => task.task_id === submittedTask)) {
          const option = document.createElement("option"); option.value = submittedTask; option.textContent = "Submitted task: " + submittedTask; document.getElementById("task").append(option);
        }
        document.getElementById("task").value = submittedTask;
      }
      connected = true; limits(); say('access-status', 'Connected. Observations refresh every 2 seconds while this page is visible.');
      await poll();
    } catch (error) { say('access-status', 'Connection failed: ' + error.message); }
    controls();
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
      say('prepare-status', 'Submission outcome is unconfirmed or refused: ' + error.message + '. Read this UUID or retry the same request; use New preparation to change inputs.');
    } finally { current.pending = false; controls(); }
  });
  function describe(status) {
    const native = status.native_status ? ' · Native: ' + status.native_status : '';
    const finishing = status.finishing ? ' · Finishing: Native result is available; the wrapper is still finishing.' : '';
    return `State: ${status.state}${native}${finishing}`;
  }
  async function readPreparation() {
    if (!preparation?.accepted || preparation.reviewBlocked || review) return;
    const current = preparation, currentGeneration = generation;
    try {
      const status = await api('operations/' + current.id);
      if (current !== preparation) return;
      say('prepare-status', describe(status));
      if (status.state === 'completed' && status.receipt_available) {
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
          ['Network', result.network], ['Devices', result.devices.join(', ') || '(none)'], ['Environment names', result.environment_names.join(', ') || '(none)'], ['Read-only paths', result.read_only.join('\n') || '(none)'] ]);
        say('review-status', 'Prepared request loaded. Review the concrete facts before launching.'); controls();
      }
    } catch (error) {
      if (current === preparation) say('prepare-status', 'Observation stale or review unavailable: ' + error.message + '. This does not establish whether the operation stopped.');
    }
  }
  $('launch-button').addEventListener('click', async () => {
    if (!connected || !review || launch?.pending || launch?.accepted) return;
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
      if (['stale_review', 'integrity', 'task_policy', 'conflict', 'not_prepared'].includes(error.code)) {
        preparation.reviewBlocked = true;
        review = null;
        say('review-status', 'Launch refused. The review may be stale or the request conflicts. Read the candidate UUID for an existing admission; otherwise create and review a new preparation.');
      }
      say('launch-status', 'Submission outcome is unconfirmed or refused: ' + error.message + '. No automatic retry will occur.');
    } finally { current.pending = false; controls(); }
  });
  function setMonitor(id) {
    monitorEpoch++; monitorId = id; cursor = 0; logText = ''; say('log', ''); $('operation-id').value = id; remember(id); $('operation-facts').replaceChildren();
    say('monitor-status', 'Reading operation ' + id + '…');
  }
  $('monitor-form').addEventListener('submit', async event => {
    event.preventDefault(); const id = $('operation-id').value.trim();
    if (!uuid.test(id)) { say('monitor-status', 'Enter a complete operation UUID.'); $('operation-id').focus(); return; }
    setMonitor(id); await poll();
  });
  $('log-kind').addEventListener('change', () => { monitorEpoch++; cursor = 0; logText = ''; say('log', ''); void poll(); });
  async function readMonitor() {
    if (!monitorId) return;
    const id = monitorId, epoch = monitorEpoch, kind = $('log-kind').value;
    try {
      const status = await api('operations/' + id);
      if (epoch !== monitorEpoch) return;
      say('monitor-status', describe(status));
      facts($('operation-facts'), [['Operation UUID', status.operation_id], ['Kind', status.kind], ['Observed at', status.observed_at],
        ['Process observation', `${status.process.status}: ${status.process.reason || '(no reason supplied)'}`], ['Native ID', status.native_id],
        ['Validation passed', status.validation_passed === null ? 'Not available' : String(status.validation_passed)], ['Reason', status.reason || '(none)'], ['Native receipt available', String(status.receipt_available)]]);
      const chunk = await api(`operations/${id}/log?kind=${kind}&offset=${cursor}&max_bytes=65536`);
      if (epoch !== monitorEpoch) return;
      cursor = chunk.next_offset;
      logText = (chunk.truncated ? '[Source log truncated; cursor reset by server]\n' : '') + logText + chunk.text;
      if (logText.length > 262144) logText = '[Earlier displayed text omitted]\n' + logText.slice(-262144);
      say('log', logText);
      say('log-status', chunk.missing ? 'Log not available yet.' : `Log observed: ${chunk.observed_size} source bytes · Next byte offset: ${cursor}`);
    } catch (error) {
      if (epoch === monitorEpoch) say('monitor-status', 'Observation stale or unavailable: ' + error.message + '. Last displayed facts are retained; disconnection does not mean stopped.');
    }
  }
  async function poll() {
    if (!connected || document.hidden || polling) return;
    polling = true;
    try { await Promise.all([readPreparation(), readMonitor()]); } finally { polling = false; }
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void poll(); });
  setInterval(() => { void poll(); }, 2000);
  controls();
})();
