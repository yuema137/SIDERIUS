/* Named workflow versions: Save name field and read-only history.
 * The server owns the version record beside the source; this module only presents
 * it. Names are display metadata: the saved SHA-256 remains the version identity. */
(() => {
  'use strict';
  const $ = id => document.getElementById(`editor-${id}`);
  const session = window.consoleSession;
  const host = $('history');
  const nameInput = $('version-name');
  let key = '', project = '', listing = null, generation = 0, typed = false;
  const node = (tag, text, parent, className) => {
    const element = document.createElement(tag); element.textContent = text;
    if (className) element.className = className;
    if (parent) parent.append(element); return element;
  };
  const historyStatus = node('p', 'Connect and open a project to see its saved versions.', host);
  historyStatus.id = 'editor-history-status'; historyStatus.setAttribute('role', 'status');
  const list = node('ol', '', host, 'editor-history-list'); list.id = 'editor-history-list';
  const detail = node('section', '', host, 'editor-history-detail'); detail.id = 'editor-history-detail';
  detail.hidden = true; detail.setAttribute('aria-label', 'Selected version (read-only)');
  const short = sha => sha.slice(0, 12);
  const label = row => row.name || (row.origin === 'unrecorded' ? 'Unnamed (current file, not saved here)' : 'Unnamed (observed before a Save)');
  const when = row => row.recorded_at ? new Date(row.recorded_at).toLocaleString() : 'time not recorded';
  nameInput.addEventListener('input', () => { typed = true; });

  // Latest named Save of this exact SHA-256, or null; presentation only.
  function nameFor(sha256) {
    const rows = (listing?.versions || []).filter(row => row.sha256 === sha256 && row.name);
    return rows.length ? rows[rows.length - 1].name : null;
  }
  window.editorVersions = Object.freeze({
    saveName() { return nameInput.value.trim() || null; },
    nameFor,
  });

  function render() {
    list.replaceChildren();
    if (!listing) return;
    historyStatus.textContent = listing.record_present
      ? `Version names are recorded in ${listing.record_path}.`
      : `No version record yet. The first Save creates ${listing.record_path}; the current file is listed as an unnamed version.`;
    for (const row of [...listing.versions].reverse()) {
      const item = node('li', '', list, row.current ? 'current' : '');
      item.dataset.index = String(row.index); item.dataset.sha256 = row.sha256;
      node('strong', label(row), item);
      node('span', ` · ${when(row)} · `, item);
      node('span', short(row.sha256), item, 'mono');
      if (row.current) node('span', ' · Current', item, 'editor-history-current');
      if (!row.bytes_available) node('span', ' · SHA only (no saved copy)', item, 'muted');
      const open = node('button', 'Open read-only', item); open.type = 'button';
      open.addEventListener('click', () => void show(row));
    }
  }

  async function show(row) {
    const version = generation, id = project;
    try {
      const value = await session.request(`editor/${encodeURIComponent(id)}/versions/${row.index}?sha256=${row.sha256}`);
      if (version !== generation) return;
      detail.replaceChildren();
      node('h3', `${label(value.version)} · ${short(value.version.sha256)} (read-only)`, detail);
      const previous = value.previous;
      node('p', !previous ? 'First listed version; nothing to compare.'
        : value.diff === null ? `Diff unavailable: the bytes of ${label(previous)} or this version are not kept. Compare SHA-256 ${short(previous.sha256)} → ${short(value.version.sha256)}.`
          : `Difference from ${label(previous)} (${short(previous.sha256)}):`, detail);
      if (value.diff !== null) node('pre', value.diff || '(No byte changes)', detail).id = 'editor-history-diff';
      const disclosure = node('details', '', detail); node('summary', 'Saved Python source', disclosure);
      node('pre', value.source ?? 'Bytes unavailable; only the SHA-256 is recorded.', disclosure).id = 'editor-history-source';
      detail.hidden = false;
    } catch (error) {
      if (!error.stale && version === generation) {
        historyStatus.textContent = error.message + (error.code === 'conflict' ? '' : ' History unavailable.');
        if (error.code === 'conflict') void load();
      }
    }
  }

  async function load() {
    const version = ++generation, id = project;
    listing = null; detail.hidden = true; render();
    if (!session.connected || !id) { historyStatus.textContent = 'Connect and open a project to see its saved versions.'; return; }
    try {
      const value = await session.request(`editor/${encodeURIComponent(id)}/versions`);
      if (version !== generation) return;
      listing = value;
      if (!typed) nameInput.value = value.next_name;
      nameInput.placeholder = value.next_name;
      render();
    } catch (error) {
      if (!error.stale && version === generation) historyStatus.textContent = error.message + ' Save refuses until the version record is repaired or moved aside.';
    }
  }

  // Reload whenever the saved bytes, project or connection change; a new saved
  // version also resets the name field to the next suggestion.
  window.addEventListener('workflow-editor-state', event => {
    const state = event.detail;
    const next = `${session.revision}|${state.projectId}|${state.savedSha256}`;
    if (next === key) return;
    key = next; project = state.projectId; typed = false;
    void load();
  });
})();
