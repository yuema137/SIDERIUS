/* The only Bearer owner: credentials never leave this closure except in headers. */
(() => {
  'use strict';
  let token = '', revision = 0, connected = false, storeId = null;
  const listeners = new Set();
  let changing = false;
  // Connected pages show one compact line; the token form returns only on request or disconnect.
  function present() {
    const collapsed = connected && !changing;
    for (const id of ['access-heading', 'access-help', 'access-form']) document.getElementById(id).hidden = collapsed;
    document.getElementById('access-connected').hidden = !connected;
    document.getElementById('access-change').hidden = !collapsed;
    document.getElementById('access-section').classList.toggle('access-collapsed', collapsed);
  }
  const publish = () => { if (!connected) changing = false; present(); for (const listener of listeners) listener({connected, revision}); };
  const status = message => { document.getElementById('access-status').textContent = message; };
  // Reachability is separate from authentication: a failed fetch or a proxy 502/503/504
  // keeps the token and drafts, but the header must not claim "Connected." (E-6).
  let reachable = true, probe = null;
  function reach(value) {
    if (value === reachable) return;
    reachable = value;
    document.getElementById('access-section').classList.toggle('access-unreachable', !value);
    if (connected) status(value ? 'Connected.' : 'Server unreachable. Retrying…');
    if (!value && !probe) probe = setInterval(() => {
      if (!connected || document.hidden) return;
      request('choices').catch(() => {});
    }, 5000);
    if (value && probe) { clearInterval(probe); probe = null; }
    window.dispatchEvent(new CustomEvent('console-reachability', {detail: {reachable: value}}));
  }
  // Only JSON bodies are parsed: a proxy or server error page must not surface as a
  // JavaScript parse error (S-3/E-5).
  async function body(response) {
    if (!(response.headers.get('content-type') || '').includes('application/json')) return null;
    try { return await response.json(); } catch (_) { return null; }
  }
  async function request(path, payload, method = payload === undefined ? 'GET' : 'POST') {
    const version = revision;
    let response;
    try {
      response = await fetch('/api/' + path, {
        method, cache: 'no-store', credentials: 'omit',
        headers: {Authorization: 'Bearer ' + token, ...(payload === undefined ? {} : {'Content-Type': 'application/json'})},
        ...(payload === undefined ? {} : {body: JSON.stringify(payload)})
      });
    } catch (error) {
      if (version !== revision) error.stale = true;
      else { reach(false); error.unreachable = true; }
      throw error;
    }
    const value = await body(response);
    if (version !== revision) { const error = new Error('Previous connection response ignored.'); error.stale = true; throw error; }
    const gateway = [502, 503, 504].includes(response.status) && value === null;
    reach(!gateway);
    if (!response.ok) {
      if (response.status === 401) {
        connected = false; revision++; token = ''; publish();
        status('Connection unavailable. Reconnect to confirm observations; pending requests and drafts are retained.');
      }
      const fallback = value === null ? `Server error (${response.status}).` : 'The console refused this request.';
      const error = new Error(value?.error?.message || fallback);
      error.status = response.status; error.code = value?.error?.code; error.value = value;
      if (gateway) error.unreachable = true;
      throw error;
    }
    if (value === null) { const error = new Error('The console sent an unreadable response.'); error.status = response.status; throw error; }
    return value;
  }
  // The one reader of GET /api/choices: {operations_store_id, tasks}.
  async function choices() {
    const value = await request('choices');
    if (!value || typeof value.operations_store_id !== 'string' || !/^[0-9a-f]{32}$/.test(value.operations_store_id) || !Array.isArray(value.tasks)) {
      throw new Error('The console sent unreadable task choices.');
    }
    if (storeId !== value.operations_store_id) {
      storeId = value.operations_store_id;
      window.dispatchEvent(new CustomEvent('console-store', {detail: {operationsStoreId: storeId}}));
    }
    return value;
  }
  window.consoleSession = Object.freeze({request, choices, subscribe(listener) { listeners.add(listener); }, get connected() { return connected; }, get revision() { return revision; }, get reachable() { return reachable; }, get operationsStoreId() { return storeId; }});
  document.getElementById('access-form').addEventListener('submit', async event => {
    event.preventDefault();
    token = document.getElementById('token').value.trim(); document.getElementById('token').value = '';
    revision++; const version = revision; connected = false; publish(); status('Connecting…');
    const selected = window.consoleNavigation?.operation;
    try {
      try { await (selected ? request('operations/' + selected) : choices()); }
      catch (error) { if (!selected || ![404, 409].includes(error.status)) throw error; }
      if (version !== revision) return;
      connected = true; changing = false; status('Connected.'); publish();
    } catch (error) { if (version === revision && !error.stale) status('Connection failed: ' + error.message); }
  });
  document.getElementById('access-change').addEventListener('click', () => {
    changing = true; present(); document.getElementById('token').focus();
  });
  document.getElementById('access-disconnect').addEventListener('click', () => {
    token = ''; revision++; connected = false; storeId = null; publish();
    status('Disconnected. Enter the console token to reconnect; drafts and the selected operation are retained.');
    document.getElementById('token').focus();
  });
  present();
})();
