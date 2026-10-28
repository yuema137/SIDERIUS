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
    if (value.state === 'active' || value.finishing) return `${what} is running.`;
    if (value.state === 'operation_failed') return value.reason === 'spawn_failed'
      ? `${what} did not start: the worker could not be launched.`
      : `${what} failed before reporting a result.`;
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
    if (native === 'stopped') return 'Finished: stopped at a completed body boundary.';
    if (native === 'paused') return 'Paused at a completed body boundary.';
    if (native === 'completed') return 'Finished.';
    return `Finished with status ${native || 'unknown'}.`;
  }
  const terminal = value => ['completed', 'operation_failed'].includes(value?.state) &&
    value.process?.status === 'exited' && !value.finishing;
  window.operationOutcome = Object.freeze({sentence, terminal});
})();
