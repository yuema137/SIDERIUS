/* The only Bearer owner: credentials never leave this closure except in headers. */
(() => {
  'use strict';
  let token = '', revision = 0, connected = false;
  const listeners = new Set();
  const publish = () => { for (const listener of listeners) listener({connected, revision}); };
  const status = message => { document.getElementById('access-status').textContent = message; };
  async function request(path, body) {
    const version = revision;
    let response;
    try {
      response = await fetch('/api/' + path, {
        method: body === undefined ? 'GET' : 'POST', cache: 'no-store', credentials: 'omit',
        headers: {Authorization: 'Bearer ' + token, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})
      });
    } catch (error) { if (version !== revision) error.stale = true; throw error; }
    const value = await response.json();
    if (version !== revision) { const error = new Error('Previous connection response ignored.'); error.stale = true; throw error; }
    if (!response.ok) {
      if (response.status === 401) {
        connected = false; revision++; token = ''; publish();
        status('Connection unavailable. Reconnect to confirm observations; pending requests and drafts are retained.');
      }
      const error = new Error(value.error?.message || 'The console refused this request.');
      error.status = response.status; error.code = value.error?.code; error.value = value; throw error;
    }
    return value;
  }
  window.consoleSession = Object.freeze({request, subscribe(listener) { listeners.add(listener); }, get connected() { return connected; }, get revision() { return revision; }});
  document.getElementById('access-form').addEventListener('submit', async event => {
    event.preventDefault();
    token = document.getElementById('token').value.trim(); document.getElementById('token').value = '';
    revision++; const version = revision; connected = false; publish(); status('Connecting…');
    const selected = window.consoleNavigation?.operation;
    try {
      try { await request(selected ? 'operations/' + selected : 'choices'); }
      catch (error) { if (!selected || ![404, 409].includes(error.status)) throw error; }
      if (version !== revision) return;
      connected = true; status('Connected. Observations refresh every 2 seconds while this page is visible.'); publish();
    } catch (error) { if (version === revision && !error.stale) status('Connection failed: ' + error.message); }
  });
})();
