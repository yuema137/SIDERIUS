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
    if (reason.kind === 'judge') return `${after}: the judge decided to stop`;
    return `${after}: stop condition ${reason.kind}`;
  }
  // A declared "Pause and ask me" condition paused the loop: what was met, in plain words,
  // from the receipt's verified input request (and the judge's own rationale, if it asked).
  function inputRequest(loop) {
    const asked = loop.input_request, reason = asked.reason, summary = asked.summary;
    const bodies = n => `${n} bod${n === 1 ? 'y' : 'ies'}`;
    const best = summary.incumbent == null ? 'no valid score yet' : `best ${number(summary.incumbent)} at body ${summary.incumbent_iteration}, ${summary.direction} is better`;
    let met;
    if (reason.kind === 'metric_threshold') met = `${reason.metric_id} reached ${number(reason.incumbent)} (threshold ${number(reason.threshold)}, ${reason.direction} is better; best at body ${reason.incumbent_iteration}).`;
    else if (reason.kind === 'no_improvement') met = `No improvement for ${bodies(reason.non_improving_bodies)} (${best}).`;
    else if (reason.kind === 'judge') {
      const verdict = (loop.judge_verdicts || []).find(item => item.iteration === reason.iteration);
      met = `The judge asked for your input${verdict?.rationale ? ': ' + verdict.rationale : ''} (${best}).`;
    } else met = `Condition ${reason.kind} was met (${best}).`;
    return `Waiting for your input. ${met} Paused after body ${summary.iteration} of ${summary.final_iteration}.`;
  }
  // Recorded JudgeStop verdicts (B2-5): each boundary's decision, with the judge's own
  // rationale from its evidence when the call decided; an abstention says so.
  function verdictLines(loop) {
    return (loop.judge_verdicts || []).map(item => {
      const decision = item.decision === null ? 'abstained (the judge call failed)'
        : item.decision === 'stop' ? 'stop' : 'continue';
      const why = item.rationale ? ` · ${item.rationale}${item.confidence ? ` (confidence ${item.confidence})` : ''}` : '';
      return `Judge after body ${item.iteration}: ${decision}${why}`;
    });
  }
  // Keyed by the operations store (SEC-4): an id retained for another console's store is
  // never reused here. Legacy per-origin keys are still read so a pending retry replays.
  const legacyKey = id => 'siderius.loop-resume.v1:' + id.toLowerCase();
  const retainedKey = (store, id) => `siderius.loop-resume.v2/${store}/${id.toLowerCase()}`;
  async function storeId() {
    return session().operationsStoreId || (await session().choices()).operations_store_id;
  }
  // The retained record for a reviewed paused receipt, or null. It holds the request UUID and
  // the advice sent with it, so a retry after an unconfirmed outcome is byte-identical.
  function retainedRecord(review, store) {
    try {
      const value = JSON.parse(localStorage.getItem(retainedKey(store, review.predecessor_operation_id)) || 'null');
      if (value?.origin === location.origin && value.expected_receipt_digest === review.expected_receipt_digest) return value;
    } catch (_) { /* An unreadable record is replaced on submission. */ }
    return null;
  }
  function retained(review, store, advice) {
    // One client-generated request UUID per reviewed paused receipt survives reloads, so a retry
    // after an unconfirmed outcome reuses it (and its advice) and the owner replays instead of
    // reserving twice.
    const key = retainedKey(store, review.predecessor_operation_id);
    try {
      const legacy = JSON.parse(localStorage.getItem(legacyKey(review.predecessor_operation_id)) || 'null');
      if (legacy?.origin === location.origin && legacy.expected_receipt_digest === review.expected_receipt_digest && localStorage.getItem(key) === null) {
        localStorage.setItem(key, JSON.stringify(legacy));
        localStorage.removeItem(legacyKey(review.predecessor_operation_id));
      }
    } catch (_) { /* An unreadable legacy record is ignored. */ }
    const prior = retainedRecord(review, store);
    if (prior) return prior;
    const value = {origin: location.origin, expected_receipt_digest: review.expected_receipt_digest, request_id: crypto.randomUUID(), ...(advice ? {operator_advice: advice} : {})};
    localStorage.setItem(key, JSON.stringify(value));
    return value;
  }
  const stopRecorded = status => !!(request?.stop.acknowledged || status.loop?.stop_requested);
  const pauseRecorded = status => !!(request?.pause.acknowledged || status.loop?.pause_requested);
  function describe(status) {
    const loop = status.loop, segment = status.kind === 'candidate_loop_resume' ? 'Resumed segment. ' : '';
    if (window.operationOutcome?.cancelledBeforeStart(status)) return segment + 'Research loop segment cancelled before start: it never ran.';
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
  function endedSentence(status) {
    if (status?.native_status !== 'paused' || !status.receipt_available || status.successor_operation_id || !status.loop?.stop_requested) return null;
    return status.loop.attempted_iterations == null ? 'Ended by you at the pause.' : `Ended by you at the pause after body ${status.loop.attempted_iterations}.`;
  }
  function outcome(status, loop) {
    const ended = endedSentence(status);
    if (ended) return ended + ' Completed results are kept; this run cannot be resumed.';
    if (status.native_status === 'cancelled') return 'Research loop stopped by you before it finished. Files written so far stay in the run folder; this run cannot be resumed.';
    if (status.native_status === 'stopped') return counted(loop, 'Research loop stopped at a completed body boundary') + ' No partial body is kept as a result.';
    if (status.native_status === 'paused' && loop.input_request) {
      return inputRequest(loop) + (status.successor_operation_id ? ' A resumed segment continues this run.'
        : stopRecorded(status) ? ' Stop was requested; this run cannot continue.'
          : ` Review and resume to continue with body ${loop.input_request.summary.iteration + 1}.`);
    }
    if (status.native_status === 'paused') return counted(loop, 'Research loop paused at a completed body boundary') + (status.successor_operation_id ? ' A resumed segment continues this run.'
      : stopRecorded(status) ? ' Stop was requested; this run cannot continue.'
        : ' No partial body is kept; it can be resumed from the next body after review.');
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
      request = {id: status.operation_id, stop: blank(), pause: blank(), resume: {...blank(), review: null, locked: false}};
      $('loop-resume-advice').value = '';
    }
    panel.hidden = false;
    $('loop-state').textContent = describe(status);
    // Untrusted operator text: rendered as text only, never as markup.
    const given = status.loop.operator_advice;
    $('loop-advice').hidden = !given;
    $('loop-advice').textContent = given ? 'Resumed with your advice: ' + given : '';
    const verdicts = status.receipt_available ? verdictLines(status.loop) : [];
    $('loop-judge').hidden = !verdicts.length;
    $('loop-judge').replaceChildren(...verdicts.map(text => { const item = document.createElement('li'); item.textContent = text; return item; }));
    const reason = status.receipt_available ? (status.loop.stop_reason || status.loop.input_request?.reason) : null;
    const exact = reason ? ['incumbent', 'threshold'].filter(key => typeof reason[key] === 'number').map(key => `${key} ${reason[key]}`) : [];
    if (exact.length) $('loop-state').title = 'Exact recorded values: ' + exact.join(', '); else $('loop-state').removeAttribute('title');
    const connected = session().connected;
    // After Stop run, boundary controls no longer apply: the whole run is being cancelled.
    const running = status.state === 'active' && !status.receipt_available && !status.cancel_requested;
    const pending = request.stop.pending || request.pause.pending;
    $('loop-stop-group').hidden = !(running && !stopRecorded(status));
    $('loop-pause-group').hidden = !(running && !stopRecorded(status) && !pauseRecorded(status));
    $('loop-stop').disabled = $('loop-pause').disabled = pending || !connected;
    $('loop-stop-status').textContent = !(running || status.native_status === 'paused') ? '' : request.stop.pending ? 'Submitting Stop request…' : request.pause.pending ? 'Submitting Pause request…' : request.stop.error || request.pause.error;

    const successor = status.successor_operation_id;
    const link = $('loop-successor');
    $('loop-continued').hidden = !successor;
    if (successor) {
      link.textContent = successor; link.href = '#monitor/' + successor;
      localStorage.removeItem(legacyKey(status.operation_id));
      if (session().operationsStoreId) localStorage.removeItem(retainedKey(session().operationsStoreId, status.operation_id));
    }
    // A recorded Stop makes a paused run terminal: the owner refuses Resume, so none is offered.
    const resumable = status.native_status === 'paused' && !successor && !status.finishing && !stopRecorded(status);
    const resume = request.resume, review = resume.review;
    $('loop-resume-group').hidden = !resumable;
    $('loop-resume-review').disabled = resume.pending || pending || !connected;
    $('loop-end').disabled = resume.pending || pending || !connected;
    $('loop-resume').hidden = !review;
    $('loop-resume-advice-group').hidden = !review;
    $('loop-resume-advice').readOnly = !!resume.locked;
    $('loop-resume').disabled = resume.pending || pending || !connected || !review?.credential_readiness.ready;
    $('loop-resume-summary').textContent = !review ? '' : `Resume continues with body ${review.completed_iterations + 1} of ${review.final_iteration} in a new segment of the same run. ` +
      (review.credential_readiness.ready ? 'Credentials: ready (names only checked).' : 'Credentials not ready; missing: ' + (review.credential_readiness.missing_names.join(', ') || 'none') + '. ' + review.credential_readiness.instructions.join(' '));
    $('loop-resume-status').textContent = !resumable ? '' : resume.pending ? 'Submitting…' : resume.error;
  }
  async function control(kind) {
    const current = request, state = current?.[kind];
    if (!last || !state || current.stop.pending || current.pause.pending || current.resume.pending || state.acknowledged || !session().connected) return;
    state.pending = true; current.stop.error = current.pause.error = ''; render(last);
    try {
      await session().request(`operations/${current.id}/loop-${kind}`, {});
      state.acknowledged = true;
      if (current === request && last.native_status === 'paused') {
        window.dispatchEvent(new CustomEvent('loop-control-changed', {detail: {operation_id: current.id}}));
      }
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
    if (!last || !resume || resume.pending || current.stop.pending || stopRecorded(last) || !session().connected) return;
    resume.pending = true; resume.error = ''; resume.review = null; render(last);
    try {
      resume.review = await session().request(`operations/${current.id}/loop-resume-review`);
      // Prefill: a retained (possibly already sent) request's advice, else this segment's own.
      const kept = retainedRecord(resume.review, await storeId());
      const box = $('loop-resume-advice');
      if (kept) { box.value = kept.operator_advice || ''; resume.locked = true; }
      else if (!resume.locked) box.value = last.loop?.operator_advice || '';
    } catch (error) {
      if (!error.stale) resume.error = 'Resume review refused: ' + error.message;
    } finally {
      resume.pending = false;
      if (current === request) render(last);
    }
  }
  async function submitResume() {
    const current = request, resume = current?.resume, review = resume?.review;
    if (!last || !review || resume.pending || current.stop.pending || stopRecorded(last) || !review.credential_readiness.ready || !session().connected) return;
    // The advice is fixed at the first attempt: a retry resends exactly the retained text.
    const typed = $('loop-resume-advice').value.trim();
    resume.pending = true; resume.locked = true; resume.error = ''; render(last);
    const store = await storeId();
    try {
      const kept = retained(review, store, typed);
      $('loop-resume-advice').value = kept.operator_advice || '';
      const body = {request_id: kept.request_id, predecessor_operation_id: review.predecessor_operation_id, expected_receipt_digest: review.expected_receipt_digest};
      if (kept.operator_advice) body.operator_advice = kept.operator_advice;
      const handle = await session().request('loop-resumes', body);
      if (current === request) location.hash = 'monitor/' + handle.operation_id;
    } catch (error) {
      if (error.stale) return;
      if (error.status === 422) {
        // Refused before admission: nothing was reserved, so the advice may be edited again.
        localStorage.removeItem(retainedKey(store, review.predecessor_operation_id));
        resume.locked = false;
      }
      if (error.status) resume.review = null;
      resume.error = 'Resume was not submitted: ' + error.message + (error.status ? ' Review again before retrying.' : ' The outcome is unconfirmed; retrying reuses the same request.');
    } finally {
      resume.pending = false;
      if (current === request) render(last);
    }
  }
  $('loop-end').addEventListener('click', () => {
    if (!last || last.native_status !== 'paused' || last.successor_operation_id || last.finishing || stopRecorded(last) || request.stop.pending || request.resume.pending || !session().connected) return;
    if (window.confirm('End this research loop here? Completed results are kept. This run cannot be resumed.')) void control('stop');
  });
  window.loopEndedSentence = endedSentence;
  $('loop-stop').addEventListener('click', () => { void control('stop'); });
  $('loop-pause').addEventListener('click', () => { void control('pause'); });
  $('loop-resume-review').addEventListener('click', () => { void reviewResume(); });
  $('loop-resume').addEventListener('click', () => { void submitResume(); });
  window.renderLoopControl = status => {
    if (status === null) { request = null; last = null; $('loop-control').hidden = true; return; }
    render(status);
  };
})();
