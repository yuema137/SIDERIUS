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
    if (value.state === 'active' || value.finishing) return `${what} in progress.`;
    if (value.state === 'operation_failed') return value.reason === 'spawn_failed'
      ? `${what} did not start: the worker could not be launched.`
      : `${what} failed before reporting a result.`;
    // Before the worker records its process identity the store reports `unknown` (L-6).
    if (value.state === 'unknown' && value.process?.reason === 'missing_identity') return `${what} is starting.`;
    if (value.state !== 'completed') return `${what}: its status cannot be determined right now.`;
    if (value.kind === 'prepare' || value.kind === 'prepare_reusable') {
      return native === 'prepared' ? 'Prepared and ready to launch.' : `Preparation finished without a prepared run (${native || 'no result'}).`;
    }
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
    // Typed native failures in plain words (L-2); the cause line comes from the log.
    if (native === 'failed') return `Failed: the ${what === 'Run' ? 'run' : what.toLowerCase()} stopped with an error before finishing.`;
    if (native === 'timed_out') return 'Failed: the run reached its time limit and was stopped.';
    if (native === 'interrupted') return 'Failed: the run was interrupted before finishing.';
    return `Finished with status ${native || 'unknown'}.`;
  }
  const failed = value => value?.state === 'operation_failed' ||
    ['failed', 'timed_out', 'interrupted'].includes(value?.native_status);
  // The last exception line a native or worker log printed, for example
  // "FormalLaunchPolicyError: a formal launch must declare …". Display only: it is the
  // same private log text Monitor already shows (SEC-1), shortened to one line.
  function cause(text) {
    const lines = String(text || '').split('\n').map(line => line.trim());
    const found = lines.filter(line => /^[A-Za-z_][\w.]*(Error|Exception|Failure|Refusal)\b:/.test(line)).at(-1);
    if (!found) return null;
    return found.length > 300 ? found.slice(0, 297) + '…' : found;
  }
  const plural = (count, one, many = one + 's') => `${count} ${count === 1 ? one : many}`;
  const terminal = value => ['completed', 'operation_failed'].includes(value?.state) &&
    value.process?.status === 'exited' && !value.finishing;
  window.operationOutcome = Object.freeze({sentence, terminal, failed, cause, plural});
})();
