/* Authored-loop state, graceful Stop/Pause and reviewed Resume. Only native receipts in status say "stopped" or "paused". */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const session = () => window.consoleSession;
  // request: per selected operation. Recorded Stop/Pause comes from the server status
  // (loop.stop_requested/pause_requested, read from the worker's durable markers), so a
  // reload or another tab still sees it (M-1); the receipt decides what took effect.
  let request = null, last = null;
  const counted = (loop, verb) => loop.attempted_iterations == null
    ? `${verb}; the body count is unavailable.`
    : `${verb} after ${loop.attempted_iterations} of ${loop.final_iteration} bod${loop.final_iteration === 1 ? 'y' : 'ies'}.`;
  // The receipt's verified stop reason in plain words; numbers are display-rounded and the
  // exact recorded values stay available as the state's tooltip (see render).
  const number = value => window.consoleNumbers ? window.consoleNumbers.format(value) : String(value);
  function stopReason(reason, limit) {
    const after = `stopped early after body ${reason.iteration} of up to ${limit}`;
    if (reason.kind === 'metric_threshold') {
      return `${after}: ${reason.metric_id} reached ${number(reason.incumbent)} (threshold ${number(reason.threshold)}, ${reason.direction} is better; best at body ${reason.incumbent_iteration})`;
    }
    if (reason.kind === 'no_improvement') {
      const bodies = n => `${n} bod${n === 1 ? 'y' : 'ies'}`;
      const best = reason.incumbent == null ? 'no valid score yet' : `best ${number(reason.incumbent)} at body ${reason.last_improvement_iteration}`;
      return `${after}: no improvement for ${bodies(reason.non_improving_bodies)} (condition: ${bodies(reason.k)}; ${best})`;
    }
    return `${after}: stop condition ${reason.kind}`;
  }
  // Keyed by the operations store (SEC-4): an id retained for another console's store is
  // never reused here. Legacy per-origin keys are still read so a pending retry replays.
  const legacyKey = id => 'siderius.loop-resume.v1:' + id.toLowerCase();
  const retainedKey = (store, id) => `siderius.loop-resume.v2/${store}/${id.toLowerCase()}`;
  async function storeId() {
    return session().operationsStoreId || (await session().choices()).operations_store_id;
  }
  function retained(review, store) {
    // One client-generated request UUID per reviewed paused receipt survives reloads, so a retry
    // after an unconfirmed outcome reuses it and the owner replays instead of reserving twice.
    const key = retainedKey(store, review.predecessor_operation_id);
    try {
      const legacy = JSON.parse(localStorage.getItem(legacyKey(review.predecessor_operation_id)) || 'null');
      if (legacy?.origin === location.origin && legacy.expected_receipt_digest === review.expected_receipt_digest && localStorage.getItem(key) === null) {
        localStorage.setItem(key, JSON.stringify(legacy));
        localStorage.removeItem(legacyKey(review.predecessor_operation_id));
      }
    } catch (_) { /* An unreadable legacy record is ignored. */ }
    try {
      const value = JSON.parse(localStorage.getItem(key) || 'null');
      if (value?.origin === location.origin && value.expected_receipt_digest === review.expected_receipt_digest) return value.request_id;
    } catch (_) { /* An unreadable record is replaced below. */ }
    const value = {origin: location.origin, expected_receipt_digest: review.expected_receipt_digest, request_id: crypto.randomUUID()};
    localStorage.setItem(key, JSON.stringify(value));
    return value.request_id;
  }
  const stopRecorded = status => !!(request?.stop.acknowledged || status.loop?.stop_requested);
  const pauseRecorded = status => !!(request?.pause.acknowledged || status.loop?.pause_requested);
  function describe(status) {
    const loop = status.loop, segment = status.kind === 'candidate_loop_resume' ? 'Resumed segment. ' : '';
    if (status.state === 'operation_failed' && !status.receipt_available) return segment + 'Research loop outcome unavailable: the operation failed without a native receipt.';
    if (!status.receipt_available) {
      let text = segment + `Research loop: up to ${loop.final_iteration} bod${loop.final_iteration === 1 ? 'y' : 'ies'}. The body count is reported by the native receipt at a completed boundary.`;
      if (stopRecorded(status)) text += ' Stop requested: the current body completes first, and the final iteration or a native failure may still end the loop. Not yet stopped.';
      else if (pauseRecorded(status)) text += ' Pause requested: the current body completes first, and the final iteration, a Stop or a native failure may still end the loop. Not yet paused.';
      return text;
    }
    // Receipt body numbers (attempted, stop_reason iterations) are cumulative over the whole run,
    // so a resumed segment says so rather than reading as a segment-local count.
    return segment + outcome(status, loop) + (segment && ' Body numbers count the whole run, including earlier segments.');
  }
  function outcome(status, loop) {
    if (status.native_status === 'cancelled') return 'Research loop stopped by you before it finished. Files written so far stay in the run folder; this run cannot be resumed.';
    if (status.native_status === 'stopped') return counted(loop, 'Research loop stopped at a completed body boundary') + ' No partial body is kept as a result.';
    if (status.native_status === 'paused') return counted(loop, 'Research loop paused at a completed body boundary') + (status.successor_operation_id ? ' A resumed segment continues this run.' : ' No partial body is kept; it can be resumed from the next body after review.');
    if (status.native_status === 'completed' && loop.stop_reason) return `Research loop ${stopReason(loop.stop_reason, loop.final_iteration)}.`;
    if (status.native_status === 'completed') return counted(loop, 'Research loop finished') + (stopRecorded(status) || pauseRecorded(status) ? ' The request did not take effect before the final iteration.' : '');
    return counted(loop, `Research loop ended (${status.native_status})`);
  }
  function render(status) {
    last = status;
    const panel = $('loop-control');
    if (!status?.loop) { panel.hidden = true; return; }
    if (request?.id !== status.operation_id) {
      const blank = () => ({pending: false, acknowledged: false, error: ''});
      request = {id: status.operation_id, stop: blank(), pause: blank(), resume: {...blank(), review: null}};
    }
    panel.hidden = false;
    $('loop-state').textContent = describe(status);
    const reason = status.receipt_available ? status.loop.stop_reason : null;
    const exact = reason ? ['incumbent', 'threshold'].filter(key => typeof reason[key] === 'number').map(key => `${key} ${reason[key]}`) : [];
    if (exact.length) $('loop-state').title = 'Exact recorded values: ' + exact.join(', '); else $('loop-state').removeAttribute('title');
    const connected = session().connected;
    // After Stop run, boundary controls no longer apply: the whole run is being cancelled.
    const running = status.state === 'active' && !status.receipt_available && !status.cancel_requested;
    const pending = request.stop.pending || request.pause.pending;
    $('loop-stop-group').hidden = !(running && !stopRecorded(status));
    $('loop-pause-group').hidden = !(running && !stopRecorded(status) && !pauseRecorded(status));
    $('loop-stop').disabled = $('loop-pause').disabled = pending || !connected;
    $('loop-stop-status').textContent = !running ? '' : request.stop.pending ? 'Submitting Stop request…' : request.pause.pending ? 'Submitting Pause request…' : request.stop.error || request.pause.error;

    const successor = status.successor_operation_id;
    const link = $('loop-successor');
    $('loop-continued').hidden = !successor;
    if (successor) {
      link.textContent = successor; link.href = '#monitor/' + successor;
      localStorage.removeItem(legacyKey(status.operation_id));
      if (session().operationsStoreId) localStorage.removeItem(retainedKey(session().operationsStoreId, status.operation_id));
    }
    const resumable = status.native_status === 'paused' && !successor && !status.finishing;
    const resume = request.resume, review = resume.review;
    $('loop-resume-group').hidden = !resumable;
    $('loop-resume-review').disabled = resume.pending || !connected;
    $('loop-resume').hidden = !review;
    $('loop-resume').disabled = resume.pending || !connected || !review?.credential_readiness.ready;
    $('loop-resume-summary').textContent = !review ? '' : `Resume continues with body ${review.completed_iterations + 1} of ${review.final_iteration} in a new segment of the same run. ` +
      (review.credential_readiness.ready ? 'Credentials: ready (names only checked).' : 'Credentials not ready; missing: ' + (review.credential_readiness.missing_names.join(', ') || 'none') + '. ' + review.credential_readiness.instructions.join(' '));
    $('loop-resume-status').textContent = !resumable ? '' : resume.pending ? 'Submitting…' : resume.error;
  }
  async function control(kind) {
    const current = request, state = current?.[kind];
    if (!last || !state || current.stop.pending || current.pause.pending || state.acknowledged || !session().connected) return;
    state.pending = true; current.stop.error = current.pause.error = ''; render(last);
    try {
      await session().request(`operations/${current.id}/loop-${kind}`, {});
      state.acknowledged = true;
    } catch (error) {
      const name = kind === 'stop' ? 'Stop' : 'Pause';
      if (!error.stale) state.error = `${name} was not recorded: ` + error.message + (error.status ? '' : ' The outcome is unconfirmed; retrying is safe.');
    } finally {
      state.pending = false;
      if (current === request) render(last);
    }
  }
  async function reviewResume() {
    const current = request, resume = current?.resume;
    if (!last || !resume || resume.pending || !session().connected) return;
    resume.pending = true; resume.error = ''; resume.review = null; render(last);
    try {
      resume.review = await session().request(`operations/${current.id}/loop-resume-review`);
    } catch (error) {
      if (!error.stale) resume.error = 'Resume review refused: ' + error.message;
    } finally {
      resume.pending = false;
      if (current === request) render(last);
    }
  }
  async function submitResume() {
    const current = request, resume = current?.resume, review = resume?.review;
    if (!last || !review || resume.pending || !review.credential_readiness.ready || !session().connected) return;
    resume.pending = true; resume.error = ''; render(last);
    try {
      const handle = await session().request('loop-resumes', {request_id: retained(review, await storeId()), predecessor_operation_id: review.predecessor_operation_id, expected_receipt_digest: review.expected_receipt_digest});
      if (current === request) location.hash = 'monitor/' + handle.operation_id;
    } catch (error) {
      if (error.stale) return;
      if (error.status) resume.review = null;
      resume.error = 'Resume was not submitted: ' + error.message + (error.status ? ' Review again before retrying.' : ' The outcome is unconfirmed; retrying reuses the same request.');
    } finally {
      resume.pending = false;
      if (current === request) render(last);
    }
  }
  $('loop-stop').addEventListener('click', () => { void control('stop'); });
  $('loop-pause').addEventListener('click', () => { void control('pause'); });
  $('loop-resume-review').addEventListener('click', () => { void reviewResume(); });
  $('loop-resume').addEventListener('click', () => { void submitResume(); });
  window.renderLoopControl = status => {
    if (status === null) { request = null; last = null; $('loop-control').hidden = true; return; }
    render(status);
  };
})();
