/* Read-only list of this console's admitted operations. Selecting one only changes the
 * route; Status and logs (app.js) owns reading it. The list loads when Monitor opens,
 * on explicit Refresh, and every 10 s while Monitor is visible and a listed operation
 * has not finished (M-4). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const session = () => window.consoleSession;
  const KINDS = {
    prepare: 'Preparation', prepare_reusable: 'Workflow preparation', candidate: 'Candidate run',
    candidate_loop_resume: 'Resumed research loop', native_chain: 'Native chain', native_chain_resume: 'Resumed native chain',
  };
  const REFRESH_MS = 10000;
  let loading = false, operations = [], listedRevision = null;
  const say = text => { if ($('operations-status').textContent !== text) $('operations-status').textContent = text; };
  // One local time format everywhere; the exact ISO value stays on hover.
  function when(value) {
    const time = new Date(value);
    return Number.isNaN(time.getTime()) ? String(value) : time.toLocaleString();
  }
  const unfinished = () => operations.some(item => !['completed', 'operation_failed'].includes(item.state));
  function progress(loop) {
    if (!loop) return '';
    const bodies = window.operationOutcome.plural(loop.final_iteration, 'body', 'bodies');
    return loop.attempted_iterations == null ? `loop up to ${bodies}` : `${loop.attempted_iterations} of ${bodies}`;
  }
  function markCurrent() {
    const selected = (window.consoleNavigation?.operation || '').toLowerCase();
    for (const link of $('operations-list').querySelectorAll('a[data-operation]')) {
      if (link.dataset.operation === selected) link.setAttribute('aria-current', 'true'); else link.removeAttribute('aria-current');
    }
  }
  function render() {
    const list = $('operations-list');
    list.replaceChildren();
    for (const item of operations) {
      const id = String(item.operation_id || '').toLowerCase();
      if (!window.consoleNavigation.isOperationId(id)) continue;
      const entry = document.createElement('li'), link = document.createElement('a'), meta = document.createElement('span');
      link.href = '#monitor/' + id; link.dataset.operation = id; link.className = 'operation-link';
      const name = [item.project_id, item.run_name].filter(Boolean).join(' · ');
      // Run name plus start time tells entries apart even when names repeat.
      link.textContent = [name || KINDS[item.kind] || item.kind, when(item.admitted_at)].join(' · ');
      meta.className = 'muted operation-meta';
      meta.textContent = [KINDS[item.kind] || item.kind, window.operationOutcome.sentence(item), progress(item.loop), item.seed].filter(Boolean).join(' · ');
      link.title = `Operation UUID ${id} · admitted ${item.admitted_at}`;
      entry.append(link, meta); list.append(entry);
    }
    markCurrent();
  }
  async function load() {
    if (!session().connected || loading) return;
    loading = true; $('operations-refresh').disabled = true; say('Reading operations…');
    try {
      const value = await session().request('operations?limit=50');
      if (!Array.isArray(value?.operations)) throw new Error('unexpected list response');
      operations = value.operations; listedRevision = session().revision; render();
      const notes = [operations.length ? `${operations.length} operation${operations.length === 1 ? '' : 's'}, most recent first.` : 'No operations have been admitted by this console yet.'];
      if (value.unreadable) notes.push(`${value.unreadable} record${value.unreadable === 1 ? '' : 's'} could not be verified and ${value.unreadable === 1 ? 'is' : 'are'} not listed.`);
      if (value.incomplete) notes.push('The store holds more records than one listing examines; open others by UUID.');
      notes.push('Listed at ' + new Date().toLocaleTimeString() + (unfinished() ? '; refreshes while a listed operation is running.' : '.'));
      say(notes.join(' '));
      // Next step for unverifiable records, advanced view only.
      $('operations-unreadable').hidden = !value.unreadable;
    } catch (error) {
      if (!error.stale) say('Operation list unavailable: ' + error.message + '. Operations can still be opened by UUID.');
    } finally {
      loading = false; $('operations-refresh').disabled = !session().connected;
    }
  }
  // Monitor lists once per connection on any of its routes, so a connected page never
  // shows the disconnected hint; entering the bare route again re-reads, Refresh on demand.
  const wanted = () => window.consoleNavigation.view === 'monitor' &&
    (listedRevision !== session().revision || (!window.consoleNavigation.operation && !$('route-status').textContent));
  session().subscribe(state => {
    $('operations-refresh').disabled = !state.connected || loading;
    if (!state.connected) { if (operations.length) say('Not connected. The last listed operations are retained; reconnect to refresh.'); else say('Connect to list operations.'); return; }
    if (wanted()) void load();
  });
  window.addEventListener('console-view', event => {
    markCurrent();
    if (event.detail.valid && session().connected && wanted()) void load();
  });
  $('operations-refresh').addEventListener('click', () => { void load(); });
  setInterval(() => {
    if (!session().connected || document.hidden || window.consoleNavigation?.view !== 'monitor' || !unfinished()) return;
    void load();
  }, REFRESH_MS);
})();
