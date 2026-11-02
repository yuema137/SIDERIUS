/* Authored-loop state, graceful Stop/Pause and reviewed Resume. Only native receipts in status say "stopped" or "paused". */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const session = () => window.consoleSession;
  // Human-readable tuning stop reasons (HyperparamTuningOutput.termination_reason) for the pause summary.
  const TUNING_STOP_LABELS = {
    aborted_fail_rounds: 'consecutive tuning rounds failed until the failure limit',
    aborted_by_gate: 'stopped by a validity gate',
    scope_violation: 'a data scope violation',
    infrastructure_abort: 'an infrastructure or environment check failed',
  };
  // request: per selected operation. Recorded Stop/Pause comes from the server status
  // (loop.stop_requested/pause_requested, read from the worker's durable markers), so a
  // reload or another tab still sees it (M-1); the receipt decides what took effect.
  let request = null, last = null;
  // The Resume panel's host-resources fieldset (#1385), read and filled by run-scheduling.js.
  const RESOURCES = 'loop-resume-resources';
  // Typed refusals the console or host admission returns before any operation is claimed
  // (an admitted request UUID replays before these checks), so a retained request refused
  // with one can never have started and is dropped, like a 422.
  const PRE_CLAIM = new Set(['stale_review', 'resources_required', 'run_resources_conflict', 'host_ledger_missing',
    'host_ledger_required', 'parallel_budget', 'parallel_budget_required', 'resource_refused',
    'parallel_unit_exceeds_capacity', 'placement_unreachable', 'credentials', 'loop_resume']);
  // Project Python str.strip (loop_models._operator_advice), including its C0/C1
  // whitespace and excluding BOM. The controller witness checks parity with Python.
  const trimAdvice = text => text.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g, '');
  const sameReservation = (kept, review) => JSON.stringify(kept.resources ?? null) === JSON.stringify(review.resources ?? null);
  const counted = (status, verb) => status.outcome?.completed_iterations == null
    ? `${verb}; the iteration count is unavailable.`
    : `${verb} after ${status.outcome.completed_iterations} of ${status.loop.final_iteration} completed iteration${status.loop.final_iteration === 1 ? '' : 's'}.`;
  // The receipt's verified stop reason in plain words; numbers are display-rounded and the
  // exact recorded values stay available as the state's tooltip (see render).
  const number = value => window.consoleNumbers ? window.consoleNumbers.format(value) : String(value);
  function stopReason(reason, limit) {
    const after = `stopped early after iteration ${reason.iteration} of up to ${limit}`;
    if (reason.kind === 'metric_threshold') {
      return `${after}: ${reason.metric_id} reached ${number(reason.incumbent)} (threshold ${number(reason.threshold)}, ${reason.direction} is better; best at iteration ${reason.incumbent_iteration})`;
    }
    if (reason.kind === 'no_improvement') {
      const bodies = n => `${n} iteration${n === 1 ? '' : 's'}`;
      const best = reason.incumbent == null ? 'no valid score yet' : `best ${number(reason.incumbent)} at iteration ${reason.last_improvement_iteration}`;
      return `${after}: no improvement for ${bodies(reason.non_improving_bodies)} (condition: ${bodies(reason.k)}; ${best})`;
    }
    if (reason.kind === 'judge') return `${after}: the judge decided to stop`;
    return `${after}: stop condition ${reason.kind}`;
  }
  // A declared "Pause and ask me" condition paused the loop: what was met, in plain words,
  // from the receipt's verified input request (and the judge's own rationale, if it asked).
  function inputRequest(loop) {
    const asked = loop.input_request, reason = asked.reason, summary = asked.summary;
    const bodies = n => `${n} iteration${n === 1 ? '' : 's'}`;
    const best = summary.incumbent == null ? 'no valid score yet' : `best ${number(summary.incumbent)} at iteration ${summary.incumbent_iteration}, ${summary.direction} is better`;
    let met;
    if (reason.kind === 'metric_threshold') met = `${reason.metric_id} reached ${number(reason.incumbent)} (threshold ${number(reason.threshold)}, ${reason.direction} is better; best at iteration ${reason.incumbent_iteration}).`;
    else if (reason.kind === 'no_improvement') met = `No improvement for ${bodies(reason.non_improving_bodies)} (${best}).`;
    else if (reason.kind === 'judge') {
      const verdict = (loop.judge_verdicts || []).find(item => item.iteration === reason.iteration);
      met = `The judge asked for your input${verdict?.rationale ? ': ' + verdict.rationale : ''} (${best}).`;
    } else met = `Condition ${reason.kind} was met (${best}).`;
    const tried = (summary.what_was_tried || []).map(body => {
      const valid = body.validation_passed == null ? 'unknown' : body.validation_passed ? 'passed' : 'failed';
      const score = body.best_valid_score == null ? 'no valid score' : `${body.metric_id} ${number(body.best_valid_score)} (${body.direction} is better)`;
      return `Iteration ${body.iteration}: ${body.model_name}; validation ${valid}; ${score}${body.stop_reason ? '; tuning stopped: ' + (TUNING_STOP_LABELS[body.stop_reason] || body.stop_reason) : ''}.`;
    });
    const attempts = tried.length ? ` What was tried (latest ${tried.length} completed ${tried.length === 1 ? 'iteration' : 'iterations'} in this segment): ${tried.join(' ')}` : '';
    return `Waiting for your input. ${met} Paused after iteration ${summary.iteration} of ${summary.final_iteration}.${attempts}`;
  }
  // Recorded JudgeStop verdicts (B2-5): each boundary's decision, with the judge's own
  // rationale from its evidence when the call decided; an abstention says so.
  function verdictLines(loop) {
    return (loop.judge_verdicts || []).map(item => {
      const decision = item.decision === null ? 'abstained (the judge call failed)'
        : item.decision === 'stop' ? 'stop' : 'continue';
      const why = item.rationale ? ` · ${item.rationale}${item.confidence ? ` (confidence ${item.confidence})` : ''}` : '';
      return `Judge after iteration ${item.iteration}: ${decision}${why}`;
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
    // A reviewed reservation is kept with the UUID too, with the digest that binds it.
    const value = {origin: location.origin, expected_receipt_digest: review.expected_receipt_digest, request_id: crypto.randomUUID(), ...(advice ? {operator_advice: advice} : {}),
      ...(review.resources ? {resources: review.resources, expected_review_digest: review.review_digest} : {})};
    localStorage.setItem(key, JSON.stringify(value));
    return value;
  }
  const stopRecorded = status => !!(request?.stop.acknowledged || status.loop?.stop_requested);
  const pauseRecorded = status => !!(request?.pause.acknowledged || status.loop?.pause_requested);
  function describe(status) {
    const loop = status.loop, segment = status.kind === 'candidate_loop_resume' ? 'Resumed segment. ' : '';
    if (status.reason === 'loop_process_exiting') return segment + 'The worker exited, but its remaining processes are not confirmed stopped. The result is still unresolved; ending the loop and starting new work remain blocked.';
    if (status.reason === 'loop_process_exited') return segment + 'The worker exited without a result. No final iteration count is available for this segment. ' + (segment
      ? 'Open the paused predecessor to end the loop once its worker processes have stopped; Resume again is unavailable.'
      : 'This run cannot be resumed. New work can start once its worker processes have stopped.');
    if (window.operationOutcome?.cancelledBeforeStart(status)) return segment + 'Research loop segment cancelled before start: it never ran.';
    if (status.state === 'operation_failed' && !status.receipt_available) return segment + 'Research loop outcome unavailable: the operation failed without a native receipt.';
    if (!status.receipt_available) {
      let text = segment + `Research loop: up to ${loop.final_iteration} iteration${loop.final_iteration === 1 ? '' : 's'}. The iteration count is reported by the native receipt at a completed boundary.`;
      if (stopRecorded(status)) text += ' Stop requested: the current iteration completes first, and the final iteration or a native failure may still end the loop. Not yet stopped.';
      else if (pauseRecorded(status)) text += ' Pause requested: the current iteration completes first, and the final iteration, a Stop or a native failure may still end the loop. Not yet paused.';
      return text;
    }
    // Receipt body numbers (attempted, stop_reason iterations) are cumulative over the whole run,
    // so a resumed segment says so rather than reading as a segment-local count.
    return segment + outcome(status, loop) + (segment && ' Iteration numbers count the whole run, including earlier segments.');
  }
  function endedSentence(status) {
    if (status?.native_status !== 'paused' || !status.receipt_available || (status.successor_operation_id && status.reason !== 'loop_successor_failed') || !status.loop?.stop_requested) return null;
    if (status.reason === 'loop_successor_failed') return 'Ended by you after the resumed segment was interrupted.';
    return status.loop.attempted_iterations == null ? 'Ended by you at the pause.' : `Ended by you at the pause after iteration ${status.loop.attempted_iterations}.`;
  }
  function outcome(status, loop) {
    const ended = endedSentence(status);
    if (ended) return ended + ' Completed results are kept; this run cannot be resumed.';
    if (status.reason === 'loop_successor_failed') return (loop.attempted_iterations == null
      ? 'Research loop paused; the iteration count is unavailable.'
      : `Research loop paused after iteration ${loop.attempted_iterations} of ${loop.final_iteration}.`) + ' The resumed segment was interrupted without a result. End loop here to keep completed results and close the run. Resume again is unavailable.';
    if (status.native_status === 'cancelled') return 'Research loop stopped by you before it finished. Files written so far stay in the run folder; this run cannot be resumed.';
    if (status.native_status === 'stopped') return counted(status, 'Research loop stopped at a completed iteration boundary') + ' No partial iteration is kept as a result.';
    if (status.native_status === 'paused' && loop.input_request) {
      return inputRequest(loop) + (status.successor_operation_id ? ' A resumed segment continues this run.'
        : stopRecorded(status) ? ' Stop was requested; this run cannot continue.'
          : ` Review and resume to continue with iteration ${loop.input_request.summary.iteration + 1}.`);
    }
    if (status.native_status === 'paused') return counted(status, 'Research loop paused at a completed iteration boundary') + (status.successor_operation_id ? ' A resumed segment continues this run.'
      : stopRecorded(status) ? ' Stop was requested; this run cannot continue.'
        : ' No partial iteration is kept; it can be resumed from the next iteration after review.');
    if (status.native_status === 'completed' && loop.stop_reason) return `Research loop ${stopReason(loop.stop_reason, loop.final_iteration)}.`;
    if (status.native_status === 'completed') return counted(status, 'Research loop finished') + (stopRecorded(status) || pauseRecorded(status) ? ' The request did not take effect before the final iteration.' : '');
    return counted(status, `Research loop ended (${status.native_status})`);
  }
  function render(status) {
    last = status;
    const panel = $('loop-control');
    if (!status?.loop) { panel.hidden = true; return; }
    if (request?.id !== status.operation_id) {
      const blank = () => ({pending: false, acknowledged: false, error: ''});
      // resume.resources: this segment must declare host resources (the review said so).
      request = {id: status.operation_id, stop: blank(), pause: blank(), resume: {...blank(), review: null, locked: false, resources: false}};
      $('loop-resume-advice').value = '';
      window.runScheduling.fillResources(RESOURCES, null);
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
    const endable = status.native_status === 'paused' && status.reason === 'loop_successor_failed' && !status.finishing && !stopRecorded(status);
    const resume = request.resume, review = resume.review;
    $('loop-resume-group').hidden = !(resumable || endable);
    $('loop-resume-review').hidden = !resumable;
    $('loop-resume-review').disabled = resume.pending || pending || !connected;
    $('loop-end').disabled = resume.pending || pending || !connected;
    $('loop-resume').hidden = !resumable || !review;
    $('loop-resume-advice-group').hidden = !resumable || !review;
    $('loop-resume-advice').readOnly = !!resume.locked;
    // Shown only after the owner asked for it (a `resources_required` refusal, which only a
    // console with a host ledger returns) or for a retained reserved request. Not gated on
    // session().hostLedger: a Monitor deep link connects without reading /api/choices.
    $(RESOURCES).hidden = !resumable || !resume.resources;
    $(RESOURCES).disabled = !!resume.locked || resume.pending;
    $('loop-resume').disabled = resume.pending || pending || !connected || !review?.credential_readiness.ready;
    $('loop-resume-summary').textContent = !review ? '' : `Resume continues with iteration ${review.completed_iterations + 1} of ${review.final_iteration} in a new segment of the same run. ` +
      (review.credential_readiness.ready ? 'Credentials: ready (names only checked).' : 'Credentials not ready; missing: ' + (review.credential_readiness.missing_names.join(', ') || 'none') + '. ' + review.credential_readiness.instructions.join(' ')) +
      (review.resources ? ' Host resources: ' + window.runScheduling.describe(review) : '');
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
      const name = kind === 'stop' ? (last.native_status === 'paused' ? 'End loop' : 'Stop') : 'Pause';
      if (!error.stale) state.error = `${name} was not recorded: ` + error.message + (error.status ? '' : ' The outcome is unconfirmed; retrying is safe.');
    } finally {
      state.pending = false;
      if (current === request) render(last);
    }
  }
  async function reviewResume() {
    const current = request, resume = current?.resume;
    if (!last || !resume || resume.pending || current.stop.pending || stopRecorded(last) || !session().connected) return;
    // A shown fieldset is part of what is reviewed: its reservation is sent with the review.
    let reserved;
    if (!$(RESOURCES).hidden) {
      const read = window.runScheduling.readResources(RESOURCES);
      if (read.error) { resume.error = 'Resume review not sent: ' + read.error; render(last); return; }
      if (read.value) reserved = {resources: read.value};
    }
    // The fieldset is disabled while the review is pending, so the values sent are the ones shown.
    resume.pending = true; resume.error = ''; resume.review = null; render(last);
    try {
      const review = await session().request(`operations/${current.id}/loop-resume-review`, reserved);
      // Prefill: a retained (possibly already sent) request's advice and reservation, else this segment's own advice.
      const store = await storeId();
      let kept = retainedRecord(review, store);
      if (kept && !sameReservation(kept, review)) {
        // Never adopt another reservation silently. Only a typed absence proves the retained
        // UUID was never admitted; then it is dropped and this review stands.
        try {
          await session().request('operations/' + kept.request_id);
        } catch (error) {
          if (error.code !== 'unknown_operation') throw error;
          localStorage.removeItem(retainedKey(store, review.predecessor_operation_id));
          kept = null; resume.locked = false;
        }
        if (kept) resume.error = 'A Resume with other host resources was already admitted; Resume reconnects to it.';
      }
      const box = $('loop-resume-advice');
      if (kept) {
        box.value = trimAdvice(kept.operator_advice || ''); resume.locked = true;
        resume.error ||= 'An earlier Resume request is saved. Resume retries it with the advice shown.';
        if (kept.resources) { resume.resources = true; window.runScheduling.fillResources(RESOURCES, kept.resources); }
      } else if (!resume.locked) box.value = last.loop?.operator_advice || '';
      resume.review = kept ? {...review, resources: kept.resources, review_digest: kept.expected_review_digest} : review;
    } catch (error) {
      if (error.code === 'resources_required') resume.resources = true;
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
    const typed = trimAdvice($('loop-resume-advice').value);
    resume.pending = true; resume.locked = true; resume.error = ''; render(last);
    const store = await storeId();
    try {
      const kept = retained(review, store, typed);
      $('loop-resume-advice').value = trimAdvice(kept.operator_advice || '');
      if (trimAdvice(kept.operator_advice || '') !== typed) {
        // Another tab or a legacy record may have bound different advice to this UUID.
        // Show that binding before the operator chooses to replay it.
        resume.error = 'An earlier Resume request has different advice. Its saved advice is shown above. Click Resume again to retry that request.';
        return;
      }
      const body = {request_id: kept.request_id, predecessor_operation_id: review.predecessor_operation_id, expected_receipt_digest: review.expected_receipt_digest};
      if (kept.operator_advice) body.operator_advice = kept.operator_advice;
      if (kept.resources) Object.assign(body, {resources: kept.resources, expected_review_digest: kept.expected_review_digest});
      const handle = await session().request('loop-resumes', body);
      if (current === request) location.hash = 'monitor/' + handle.operation_id;
    } catch (error) {
      if (error.stale) return;
      if (error.status === 422 || PRE_CLAIM.has(error.code)) {
        // Refused before admission: nothing was claimed, so the request is not retained and
        // the advice and host resources may be edited again.
        localStorage.removeItem(retainedKey(store, review.predecessor_operation_id));
        resume.locked = false;
      }
      if (error.status) resume.review = null;
      if (error.code === 'resources_required') resume.resources = true;
      resume.error = 'Resume was not submitted: ' + error.message + (error.status ? ' Review again before retrying.' : ' The outcome is unconfirmed; retrying reuses the same request.');
    } finally {
      resume.pending = false;
      if (current === request) render(last);
    }
  }
  $('loop-end').addEventListener('click', () => {
    if (!last || last.native_status !== 'paused' || (last.successor_operation_id && last.reason !== 'loop_successor_failed') || last.finishing || stopRecorded(last) || request.stop.pending || request.resume.pending || !session().connected) return;
    if (window.confirm('End this research loop here? Completed results are kept. This run cannot be resumed.')) void control('stop');
  });
  window.loopEndedSentence = endedSentence;
  $('loop-stop').addEventListener('click', () => { void control('stop'); });
  $('loop-pause').addEventListener('click', () => { void control('pause'); });
  $('loop-resume-review').addEventListener('click', () => { void reviewResume(); });
  $('loop-resume').addEventListener('click', () => { void submitResume(); });
  // A reviewed Resume carries exactly the reviewed reservation: any edit needs a new review.
  $(RESOURCES).addEventListener('input', () => {
    const resume = request?.resume;
    if (!resume || resume.locked) return;
    if (resume.review) { resume.review = null; resume.error = 'Host resources changed. Review again before resuming.'; }
    if (last) render(last);
  });
  window.renderLoopControl = status => {
    if (status === null) { request = null; last = null; $('loop-control').hidden = true; return; }
    render(status);
  };
})();
