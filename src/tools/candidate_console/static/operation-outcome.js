/* One plain outcome sentence per operation observation (M-2). Raw state and native
 * enums stay in developer facts; Run, Monitor status and the operation list share this. */
(() => {
  'use strict';
  const subject = kind => ({
    prepare: 'Preparation', prepare_reusable: 'Preparation', candidate: 'Run',
    candidate_loop_resume: 'Resumed run', native_chain: 'Native chain', native_chain_resume: 'Resumed native chain'
  })[kind] || 'Operation';
  // `value` is a StatusView or an operation-list item (state, native_status, kind, and
  // optionally finishing, process, reason, validation_passed).
  function sentence(value) {
    const what = subject(value.kind), native = value.native_status;
    if (!value.state) return `${what} request accepted; waiting for its first status.`;
    // B3-5b: waiting in the host ledger for the GPU, memory or CPU it declared.
    if (value.state === 'queued') return `${what} is queued: it starts by itself when earlier runs free the host resources it needs.`;
    if (value.state === 'active' || value.finishing) return `${what} in progress.`;
    if (cancelledBeforeStart(value)) return `${what} cancelled before start: it never ran, and nothing was produced.`;
    if (value.state === 'operation_failed' && value.reason === 'loop_process_exited') return `${what} was interrupted: its worker exited without reporting a result. ` + (value.kind === 'candidate_loop_resume'
      ? 'Open the paused predecessor to end the loop once its worker processes have stopped. This segment cannot be resumed.'
      : 'This run cannot be resumed. New work can start once its worker processes have stopped.');
    if (value.state === 'operation_failed') return value.reason === 'spawn_failed'
      ? `${what} did not start: the worker could not be launched.`
      : `${what} failed before reporting a result.`;
    // Before the worker records its process identity the store reports `unknown` (L-6).
    if (value.state === 'unknown' && value.process?.reason === 'missing_identity') return `${what} is starting.`;
    if (value.state !== 'completed') return `${what}: its status cannot be determined right now.`;
    const preparation = value.kind === 'prepare' || value.kind === 'prepare_reusable';
    if (preparation && native === 'prepared') return 'Prepared and ready to launch.';
    if (native === 'accepted' || (native === 'completed' && value.validation_passed === true)) {
      return `Finished: the ${what === 'Run' ? 'candidate' : what.toLowerCase()} passed validation.`;
    }
    if (native === 'rejected' || value.validation_passed === false) {
      return 'Finished: validation rejected the candidate.';
    }
    if (native === 'cancelled') return 'Stopped on request before finishing; no candidate result was produced.';
    if (native === 'stopped') return 'Finished: stopped at a completed body boundary.';
    if (native === 'paused') return 'Paused at a completed body boundary.';
    if (native === 'completed') return 'Finished.';
    // Typed native failures in plain words (L-2, #1145); the cause line comes from the log.
    const noun = what.toLowerCase();
    if (native === 'failed') return `Failed: the ${noun} stopped with an error before finishing.`;
    if (native === 'timed_out') return `Failed: the ${noun} reached its time limit and was stopped.`;
    if (native === 'interrupted') return `Failed: the ${noun} was interrupted before finishing.`;
    if (preparation) return `Preparation finished without a prepared run (${native || 'no result'}).`;
    return `Finished with status ${native || 'unknown'}.`;
  }
  // How an observed operation ended when it did not succeed or is waiting (#1145): the
  // Run page's next-step line names it instead of "finished" or "preparing". A paused
  // research loop is `paused_for_input` (a "Pause and ask me" condition), `paused`
  // (operator Pause), `paused_stop_requested` (Stop recorded: it cannot continue) or
  // `resumed` (a resumed segment continues it). `null` while it is still running,
  // unresolved, or ended normally (prepared, accepted, rejected, stopped or completed).
  function ending(value) {
    if (value?.state === 'operation_failed') {
      return value.reason === 'spawn_failed' ? 'not_started'
        : cancelledBeforeStart(value) ? 'cancelled_before_start' : 'operation_failed';
    }
    if (value?.state !== 'completed') return null;
    const native = value.native_status;
    if (native === 'paused') {
      return value.successor_operation_id ? 'resumed' : value.loop?.stop_requested ? 'paused_stop_requested'
        : value.loop?.input_request ? 'paused_for_input' : 'paused';
    }
    if (['failed', 'timed_out', 'interrupted', 'cancelled'].includes(native)) return native;
    // A preparation is either prepared or it failed; any other result is not a run.
    if ((value.kind === 'prepare' || value.kind === 'prepare_reusable') && native !== 'prepared') return 'failed';
    return null;
  }
  // A queued run the operator cancelled is a deliberate outcome, not a failure (#1074).
  function cancelledBeforeStart(value) {
    return value?.state === 'operation_failed' && value.reason === 'cancelled_while_queued';
  }
  const failed = value => (value?.state === 'operation_failed' && !cancelledBeforeStart(value)) ||
    ['failed', 'timed_out', 'interrupted'].includes(value?.native_status);
  // The last exception line a native or worker log printed, for example
  // "FormalLaunchPolicyError: a formal launch must declare …". Display only: it is the
  // same private log text Monitor already shows (SEC-1), shortened to one line.
  function cause(text) {
    const lines = String(text || '').split('\n').map(line => line.trim());
    const found = lines.filter(line => /^[A-Za-z_][\w.]*(Error|Exception|Failure|Refusal)\b:/.test(line)).at(-1);
    if (!found) return null;
    if (found.length <= 300) return found;
    // Cut at the last word boundary that fits, never inside a word (walkthrough N2).
    const space = found.lastIndexOf(' ', 299);
    return (space > 0 ? found.slice(0, space) : found.slice(0, 299)).replace(/[\s,;:(]+$/, '') + '…';
  }
  // L-2: one cause line for a failed operation, read once from the last 64 KiB of its
  // native, then operation, log (the same text Monitor shows). `request` is
  // consoleSession.request; a stale session ends the read with no cause.
  async function readCause(request, id) {
    for (const kind of ['native', 'operation']) {
      try {
        const head = await request(`operations/${id}/log?kind=${kind}&offset=0&max_bytes=1`);
        if (head.missing) continue;
        const offset = Math.max(0, head.observed_size - 65536);
        const tail = await request(`operations/${id}/log?kind=${kind}&offset=${offset}&max_bytes=65536`);
        const found = cause(tail.text);
        if (found) return found;
      } catch (error) { if (error.stale) return null; }
    }
    return null;
  }
  const plural = (count, one, many = one + 's') => `${count} ${count === 1 ? one : many}`;
  const terminal = value => ['completed', 'operation_failed'].includes(value?.state) &&
    value.process?.status === 'exited' && !value.finishing;
  window.operationOutcome = Object.freeze({sentence, terminal, failed, cause, plural, cancelledBeforeStart, ending, readCause});
})();
