/* "Stop run" for a live candidate operation. The request records operator cancel; only the native receipt says the run stopped. */
(() => {
  'use strict';
  const CONFIRM = 'Stop this run now? It ends immediately and cannot be undone or resumed, and it produces no candidate result. ' +
    'Files written so far stay in the run folder. A model call already in progress may still be billed by the provider without appearing in the token report.';
  // prefix selects one mount: `${prefix}-group` (hidden unless the server says cancellable), `${prefix}-button`, `${prefix}-status`.
  function mount(prefix) {
    const $ = name => document.getElementById(`${prefix}-${name}`);
    let id = null, last = null, pending = false, acknowledged = false, error = '', stale = false;
    function text(status) {
      if (status.native_status === 'cancelled') return 'Run stopped. Files written so far stay in the run folder; no candidate result is produced.';
      if (status.cancel_requested || acknowledged) return status.receipt_available ? 'Stop was requested, but the run finished first.' : 'Stopping the run…';
      return pending ? 'Sending Stop…' : error;
    }
    function render(status) {
      if (!status) { id = null; last = null; $('group').hidden = true; $('status').textContent = ''; return; }
      if (status.operation_id !== id) { id = status.operation_id; pending = false; acknowledged = false; error = ''; stale = false; }
      last = status;
      const connected = window.consoleSession.connected;
      // The server's `cancellable` is the one authority for offering Stop run.
      $('group').hidden = !status.cancellable || acknowledged;
      $('button').disabled = pending || !connected;
      const observed = text(status);
      // While the server is unreachable this line is the last poll, not current state.
      $('status').textContent = observed && (stale || !connected) ? 'Last observed: ' + observed : observed;
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
    window.consoleSession.subscribe(() => { if (last) render(last); });
    // The page's poll owner reports whether its latest read failed.
    function observation(failed) { if (stale !== failed) { stale = failed; if (last) render(last); } }
    return Object.freeze({render: status => { stale = false; render(status); }, observation});
  }
  window.operationStop = Object.freeze({mount});
})();
