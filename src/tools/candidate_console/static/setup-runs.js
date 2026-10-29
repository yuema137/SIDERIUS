/* Run page: "Runs of this setup" from GET /api/operations?project_id=<setup> (the store's
 * own attribution, newest first). Presentation only; selecting a run opens Monitor. It
 * reads when Run opens or the open setup changes, and on Refresh. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const session = window.consoleSession;
  let listedFor = null, sequence = 0;
  const say = text => { $('setup-runs-status').textContent = text; };
  const when = value => { const time = new Date(value); return Number.isNaN(time.getTime()) ? String(value) : time.toLocaleString(); };
  function render(operations) {
    const list = $('setup-runs-list'); list.replaceChildren();
    for (const item of operations) {
      const id = String(item.operation_id || '').toLowerCase();
      if (!window.consoleNavigation.isOperationId(id)) continue;
      const entry = document.createElement('li'), link = document.createElement('a'), meta = document.createElement('span');
      link.href = '#monitor/' + id; link.className = 'operation-link';
      link.textContent = [item.run_name || item.kind, when(item.admitted_at)].join(' · ');
      link.title = `Operation UUID ${id} · admitted ${item.admitted_at}`;
      meta.className = 'muted operation-meta';
      meta.textContent = window.operationOutcome?.sentence(item) || item.state;
      entry.append(link, meta); list.append(entry);
    }
  }
  async function load(force = false) {
    const setup = window.experimentSetups?.current, key = setup ? `${session.revision}/${setup.id}` : null;
    $('setup-runs').hidden = !setup;
    if (!setup || !session.connected || (!force && listedFor === key)) return;
    // A newer read (another setup, Refresh) replaces an in-flight one; only the newest renders.
    const mine = ++sequence;
    $('setup-runs-refresh').disabled = true; say('Reading the runs of this setup…'); render([]);
    try {
      const value = await session.request(`operations?limit=50&project_id=${encodeURIComponent(setup.id)}`);
      if (mine !== sequence || window.experimentSetups?.current?.id !== setup.id) return;
      if (!Array.isArray(value?.operations)) throw new Error('unexpected list response');
      listedFor = key; render(value.operations);
      const count = value.operations.length;
      // The store scan has a limit: never claim a complete history it did not examine.
      const notes = [count ? `${count} run${count === 1 ? '' : 's'} of this setup, most recent first.`
        : value.incomplete ? 'No runs found; older runs may be missing.' : 'No runs of this setup yet.'];
      if (value.incomplete && count) notes.push('The store holds more records than one listing examines, so older runs may be missing; open them by UUID in Monitor.');
      if (value.unreadable) notes.push(`${value.unreadable} record${value.unreadable === 1 ? '' : 's'} could not be verified and ${value.unreadable === 1 ? 'is' : 'are'} not listed.`);
      say(notes.join(' '));
    } catch (error) {
      if (!error.stale && mine === sequence) { listedFor = null; say(`The runs of this setup could not be read: ${error.message}. Use Refresh to try again.`); }
    } finally { if (mine === sequence) $('setup-runs-refresh').disabled = !session.connected; }
  }
  const onRun = () => window.consoleNavigation?.view === 'run';
  window.addEventListener('experiment-setup', () => { if (onRun()) void load(); });
  window.addEventListener('console-view', event => { if (event.detail.view === 'run') void load(true); });
  $('setup-runs-refresh').addEventListener('click', () => void load(true));
})();
