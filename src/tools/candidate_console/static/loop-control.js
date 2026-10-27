/* Authored-loop state and graceful Stop. Only the native receipt in status can say "stopped". */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let request = null, last = null; // request: {id, pending, acknowledged, error}
  const counted = (loop, verb) => loop.attempted_iterations == null
    ? `${verb}; the body count is unavailable.`
    : `${verb} after ${loop.attempted_iterations} of ${loop.final_iteration} bodies.`;
  function describe(status) {
    const loop = status.loop;
    if (status.state === 'operation_failed' && !status.receipt_available) return 'Research loop outcome unavailable: the operation failed without a native receipt.';
    if (!status.receipt_available) {
      const bound = `Research loop: up to ${loop.final_iteration} bodies. The body count is reported by the native receipt at a completed boundary.`;
      return request?.acknowledged
        ? bound + ' Stop requested: the current body completes first, and the final iteration or a native failure may still end the loop. Not yet stopped.'
        : bound;
    }
    if (status.native_status === 'stopped') return counted(loop, 'Research loop stopped at a completed body boundary') + ' No partial body is kept as a result.';
    if (status.native_status === 'completed') return counted(loop, 'Research loop finished') + (request?.acknowledged ? ' The Stop request did not take effect before the final iteration.' : '');
    return counted(loop, `Research loop ended (${status.native_status})`);
  }
  function render(status) {
    last = status;
    const panel = $('loop-control');
    if (!status?.loop) { panel.hidden = true; return; }
    if (request?.id !== status.operation_id) request = {id: status.operation_id, pending: false, acknowledged: false, error: ''};
    panel.hidden = false;
    $('loop-state').textContent = describe(status);
    const running = status.kind === 'candidate' && status.state === 'active' && !status.receipt_available;
    $('loop-stop-group').hidden = !(running && !request.acknowledged);
    $('loop-stop').disabled = request.pending || !window.consoleSession.connected;
    $('loop-stop-status').textContent = request.pending ? 'Submitting Stop request…' : running ? request.error : '';
  }
  async function stop() {
    const current = request;
    if (!last || !current || current.pending || current.acknowledged || !window.consoleSession.connected) return;
    current.pending = true; current.error = ''; render(last);
    try {
      await window.consoleSession.request(`operations/${current.id}/loop-stop`, {});
      current.acknowledged = true;
    } catch (error) {
      if (!error.stale) current.error = 'Stop was not recorded: ' + error.message + (error.status ? '' : ' The outcome is unconfirmed; retrying is safe.');
    } finally {
      current.pending = false;
      if (current === request) render(last);
    }
  }
  $('loop-stop').addEventListener('click', () => { void stop(); });
  window.renderLoopControl = status => {
    if (status === null) { request = null; last = null; $('loop-control').hidden = true; return; }
    render(status);
  };
})();
