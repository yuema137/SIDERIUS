/* The only Bearer owner: credentials never leave this closure except in headers. */
(() => {
  'use strict';
  let token = '', revision = 0, connected = false;
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
  async function request(path, body, method = body === undefined ? 'GET' : 'POST') {
    const version = revision;
    let response;
    try {
      response = await fetch('/api/' + path, {
        method, cache: 'no-store', credentials: 'omit',
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
  // Downloads need the bearer header too, so a plain link cannot carry them; return a Blob.
  async function download(path) {
    const version = revision;
    const response = await fetch('/api/' + path, {cache: 'no-store', credentials: 'omit', headers: {Authorization: 'Bearer ' + token}});
    if (version !== revision) { const error = new Error('Previous connection response ignored.'); error.stale = true; throw error; }
    if (!response.ok) {
      const value = await response.json().catch(() => ({}));
      const error = new Error(value.error?.message || 'The console refused this download.'); error.status = response.status; throw error;
    }
    return response.blob();
  }
  window.consoleSession = Object.freeze({request, download, subscribe(listener) { listeners.add(listener); }, get connected() { return connected; }, get revision() { return revision; }});
  document.getElementById('access-form').addEventListener('submit', async event => {
    event.preventDefault();
    token = document.getElementById('token').value.trim(); document.getElementById('token').value = '';
    revision++; const version = revision; connected = false; publish(); status('Connecting…');
    const selected = window.consoleNavigation?.operation;
    try {
      try { await request(selected ? 'operations/' + selected : 'choices'); }
      catch (error) { if (!selected || ![404, 409].includes(error.status)) throw error; }
      if (version !== revision) return;
      connected = true; changing = false; status('Connected.'); publish();
    } catch (error) { if (version === revision && !error.stale) status('Connection failed: ' + error.message); }
  });
  document.getElementById('access-change').addEventListener('click', () => {
    changing = true; present(); document.getElementById('token').focus();
  });
  document.getElementById('access-disconnect').addEventListener('click', () => {
    token = ''; revision++; connected = false; publish();
    status('Disconnected. Enter the console token to reconnect; drafts and the selected operation are retained.');
    document.getElementById('token').focus();
  });
  present();
})();
