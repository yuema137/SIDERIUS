/* "Stop run" for a live candidate operation. The request records operator cancel; only the native receipt says the run stopped. */
(() => {
  'use strict';
  const CONFIRM = 'Stop this run? Work done so far is kept.';
  const KINDS = ['candidate', 'candidate_loop_resume'];
  // prefix selects one mount: `${prefix}-group` (hidden unless running), `${prefix}-button`, `${prefix}-status`.
  function mount(prefix) {
    const $ = name => document.getElementById(`${prefix}-${name}`);
    let id = null, last = null, pending = false, acknowledged = false, error = '';
    function text(status) {
      if (status.native_status === 'cancelled') return 'Run stopped. Work done so far is kept.';
      if (status.cancel_requested || acknowledged) return status.receipt_available ? 'Stop was requested, but the run finished first.' : 'Stopping the run…';
      return pending ? 'Sending Stop…' : error;
    }
    function render(status) {
      if (!status) { id = null; last = null; $('group').hidden = true; $('status').textContent = ''; return; }
      if (status.operation_id !== id) { id = status.operation_id; pending = false; acknowledged = false; error = ''; }
      last = status;
      const running = KINDS.includes(status.kind) && status.state === 'active' && !status.receipt_available;
      $('group').hidden = !running || status.cancel_requested || acknowledged;
      $('button').disabled = pending || !window.consoleSession.connected;
      $('status').textContent = text(status);
    }
    async function stop() {
      const current = id;
      if (!last || pending || acknowledged || !window.consoleSession.connected) return;
      if (!window.confirm(CONFIRM)) return;
      pending = true; error = ''; render(last);
      try {
        await window.consoleSession.request(`operations/${current}/cancel`, {});
        if (current === id) acknowledged = true;
      } catch (failure) {
        if (!failure.stale && current === id) error = 'Stop was not recorded: ' + failure.message + (failure.status ? '' : ' The outcome is unconfirmed; trying again is safe.');
      } finally {
        if (current === id) { pending = false; render(last); }
      }
    }
    $('button').addEventListener('click', () => { void stop(); });
    return Object.freeze({render});
  }
  window.operationStop = Object.freeze({mount});
})();
