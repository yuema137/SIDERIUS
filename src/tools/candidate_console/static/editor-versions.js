/* Named workflow versions: Save name field, history and "Restore this version as a draft".
 * The server owns the version record beside the source; this module only presents
 * it. Names are display metadata: the saved SHA-256 remains the version identity.
 * - The name field refuses, as it is typed, invisible characters (the same Unicode
 *   categories SaveRequest.version_name refuses) and a name already in the loaded history.
 *   No other naming rule; the server still decides.
 * - Restore hands an older version's bytes to the ordinary check (window.workflowEditor
 *   .restoreVersion); nothing is written until the author saves.
 * - History is a beginner surface (red-team A-3); SHA-256 and the record path are advanced. */
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
  // A file the console never saved is never called a saved version (red-team A-6/A-7).
  const label = row => row.name || (row.origin === 'unrecorded' ? 'Current file (not saved in the console yet)' : 'Earlier file (before a console save)');
  const advanced = (tag, text, parent, className) => { const element = node(tag, text, parent, className); element.dataset.uiFlag = 'advanced'; return element; };
  // Unicode categories Cc, Cf, Cs, Co, Cn, Zl, Zp (workflow_authoring.models._INVISIBLE_CATEGORIES).
  const INVISIBLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}]/u;
  const problemText = node('p', '', null, 'field-problem-text'); problemText.id = 'editor-version-problem';
  problemText.setAttribute('role', 'alert'); problemText.hidden = true;
  nameInput.after(problemText);
  function nameProblem() {
    const name = nameInput.value.trim();
    if (!name) return null;
    if (INVISIBLE.test(name)) return 'This name contains an invisible character; type it again without it.';
    if ((listing?.versions || []).some(row => row.name === name)) return `"${name}" is already used by another version; choose a different name.`;
    return null;
  }
  function checkName() {
    const problem = nameProblem();
    problemText.textContent = problem || ''; problemText.hidden = !problem;
    nameInput.setAttribute('aria-invalid', String(!!problem));
    window.dispatchEvent(new CustomEvent('editor-version-name'));
  }
  const when = row => row.recorded_at ? new Date(row.recorded_at).toLocaleString() : 'time not recorded';
  nameInput.addEventListener('input', () => { typed = true; checkName(); });

  // Latest named Save of this exact SHA-256, or null; presentation only.
  function nameFor(sha256) {
    const rows = (listing?.versions || []).filter(row => row.sha256 === sha256 && row.name);
    return rows.length ? rows[rows.length - 1].name : null;
  }
  // Whether a console Save recorded these exact bytes (presentation only).
  const recorded = sha256 => (listing?.versions || []).some(row => row.sha256 === sha256 && row.origin === 'saved');
  window.editorVersions = Object.freeze({
    saveName() { return nameInput.value.trim() || null; },
    nameProblem,
    nameFor,
    recorded,
    get loaded() { return !!listing; },
  });

  function render() {
    list.replaceChildren();
    if (!listing) return;
    historyStatus.replaceChildren(listing.record_present
      ? 'Each Save adds a version here. Open one to see what changed, or restore it as unsaved changes.'
      : 'No saved versions yet. Your first Save starts this history.');
    advanced('span', ` Record file: ${listing.record_path}`, historyStatus, 'mono');
    for (const row of [...listing.versions].reverse()) {
      const item = node('li', '', list, row.current ? 'current' : '');
      item.dataset.index = String(row.index); item.dataset.sha256 = row.sha256;
      node('strong', label(row), item);
      node('span', ` · ${when(row)}`, item);
      advanced('span', ` · ${short(row.sha256)}`, item, 'mono');
      if (row.current) node('span', ' · Current', item, 'editor-history-current');
      if (!row.bytes_available) node('span', ' · content not kept', item, 'muted');
      const open = node('button', 'View', item, 'secondary'); open.type = 'button';
      open.setAttribute('aria-label', `View ${label(row)}`);
      open.addEventListener('click', () => void show(row));
    }
  }

  async function show(row) {
    const version = generation, id = project;
    try {
      const value = await session.request(`editor/${encodeURIComponent(id)}/versions/${row.index}?sha256=${row.sha256}`);
      if (version !== generation) return;
      detail.replaceChildren();
      const heading = node('h3', `${label(value.version)} (read-only)`, detail);
      advanced('span', ` · ${short(value.version.sha256)}`, heading, 'mono');
      // Restore: these bytes become an ordinary checked proposal; nothing is written.
      if (value.source !== null && !value.version.current) {
        const restore = node('button', 'Restore this version as a draft', detail, 'secondary'); restore.type = 'button';
        restore.id = 'editor-history-restore';
        restore.addEventListener('click', async () => {
          if (version !== generation) return;
          restore.disabled = true;
          try { if (await window.workflowEditor.restoreVersion(value.source, label(value.version))) detail.hidden = true; }
          finally { restore.disabled = false; }
        });
      }
      const previous = value.previous;
      node('p', !previous ? 'The first version; nothing to compare.'
        : value.diff === null ? `The content of ${label(previous)} or of this version is not kept, so the changes cannot be shown.`
          : `Changes since ${label(previous)}:`, detail);
      if (value.diff !== null) {
        const changes = node('details', '', detail); node('summary', 'Show the changes', changes);
        node('pre', value.diff || '(No changes)', changes).id = 'editor-history-diff';
      }
      const disclosure = advanced('details', '', detail); node('summary', 'Saved Python source', disclosure);
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
      render(); checkName();
      window.dispatchEvent(new CustomEvent('editor-versions'));
    } catch (error) {
      if (!error.stale && version === generation) historyStatus.textContent = `History unavailable: ${window.editorSaveOutcome.sentence(error.message)} Saving is refused until the version record is repaired or moved aside.`;
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
