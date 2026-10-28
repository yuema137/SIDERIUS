/* Settings page: allowlisted choices and folder refs only; the server resolves every path.
 * Save is compare-and-swap on the settings file's sha256 and takes effect after a restart. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const session = () => window.consoleSession;
  const ORIGINS = {server_config: 'Set in console.json', global_settings: 'This page', workspace_layout: 'Workspace folder', not_set: 'Not set'};
  const NAMES = {llm_profile: 'Model profile', advice: 'Advice file', data_root: 'Data folder', preparation_root: 'Preparation folder', candidate_root: 'Candidate folder', reusable_runs_root: 'Workflow runs folder'};
  let view = null, draft = null, loadedRevision = null, busy = false;
  const say = text => { $('settings-status').textContent = text; };
  const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  const element = (tag, text, attributes = {}) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  };

  function choiceList(container, name, cards, selected, noneLabel) {
    container.replaceChildren();
    const options = [{label: noneLabel, ref: null}, ...cards];
    options.forEach((card, index) => {
      const id = `settings-${name}-${index}`;
      const row = element('div', undefined, {class: 'settings-choice'});
      const input = element('input', undefined, {type: 'radio', name: 'settings-' + name, id});
      input.checked = same(card.ref, selected); input.disabled = !view.writable;
      input.addEventListener('change', () => { draft[name] = card.ref; renderPending(); });
      const label = element('label', card.label, {for: id});
      if (card.ref) label.append(element('span', card.ref.source === 'library' ? ' (library)' : ' (console.json allowlist)', {class: 'muted'}));
      row.append(input, label);
      if (card.ref) row.append(...details(card));
      container.append(row);
    });
  }

  // Facts from the server's owners: key names and routes only, never file contents or values.
  function details(card) {
    if (card.problem) return [element('p', 'Unavailable: ' + card.problem, {class: 'muted'})];
    const out = [];
    if (card.required_names) {
      out.push(element('p', card.required_names.length ? 'Needs keys: ' + card.required_names.join(', ') : 'Needs no provider keys.', {class: 'muted'}));
      if (card.routes?.length) {
        const more = element('details'), list = element('ul');
        more.append(element('summary', 'Show routes'));
        for (const route of card.routes) list.append(element('li', `${route.name}: ${route.transport ? `${route.transport.provider} ${route.transport.model_id || ''}`.trim() : route.applicability}`));
        more.append(list); out.push(more);
      }
    }
    if (card.present_keys) {
      out.push(element('p', 'Advice for: ' + (card.present_keys.join(', ') || 'nothing'), {class: 'muted'}));
      if (card.unsupported_keys.length) out.push(element('p', `Workflows cannot use ${card.unsupported_keys.join(', ')} yet; a workflow that references this file will be refused until they can.`));
    }
    return out;
  }

  // Upload moves the file's text from this computer to the server's write-once library.
  async function importFile(kind, input) {
    const file = input.files[0]; input.value = '';
    if (!file || !view?.writable) return;
    // The server refuses request bodies over 256 KiB; measure the JSON body it will receive.
    const body = {kind, label: file.name.replace(/\.json$/i, '').slice(0, 63) || kind, content: await file.text()};
    if (new TextEncoder().encode(JSON.stringify(body)).length > 256 * 1024) { say('Not imported: the file is too large; the console accepts uploads up to about 256 KiB.'); return; }
    say('Importing…');
    try {
      const ref = await session().request('settings/library', body);
      say(`Imported as ${ref.name} in the server library. Select it, then Save.`);
      await load(true);
    } catch (error) { if (!error.stale) say('Not imported: ' + error.message); }
  }

  async function listFolders(rootId, subpath) {
    const query = new URLSearchParams({root_id: rootId, subpath, limit: '200'});
    return session().request('settings/folders?' + query.toString());
  }

  function folderPicker(task) {
    const box = element('div', undefined, {class: 'settings-folder'});
    box.append(element('h3', task.label));
    if (task.data_root_origin === 'server_config') {
      box.append(element('p', 'Set in console.json; not editable here.', {class: 'muted'}));
      return box;
    }
    const selected = draft.data_folders[task.task_id] || null;
    const rootLabel = element('label', 'Data root', {for: 'settings-root-' + task.task_id});
    const root = element('select', undefined, {id: 'settings-root-' + task.task_id});
    root.append(element('option', 'Workspace layout default', {value: ''}));
    for (const card of view.data_roots) root.append(element('option', card.label, {value: card.id}));
    root.value = selected ? selected.root_id : ''; root.disabled = !view.writable;
    const where = element('p', '', {role: 'status'});
    const list = element('ul', undefined, {class: 'settings-folders'});
    let current = selected ? selected.subpath : '';
    const show = () => {
      const chosen = draft.data_folders[task.task_id];
      where.textContent = chosen ? `Selected: ${view.data_roots.find(card => card.id === chosen.root_id)?.label || chosen.root_id} / ${chosen.subpath}` : `Selected: data/${task.task_id} in the workspace (default).`;
    };
    async function browse(path) {
      current = path; list.replaceChildren();
      if (!root.value) { show(); return; }
      try {
        const listing = await listFolders(root.value, path);
        if (path) {
          const up = element('button', '.. (up)', {type: 'button', class: 'secondary'});
          up.addEventListener('click', () => { void browse(path.split('/').slice(0, -1).join('/')); });
          list.append(element('li')); list.lastChild.append(up);
          const use = element('button', `Use ${path}`, {type: 'button'});
          use.disabled = !view.writable;
          use.addEventListener('click', () => { draft.data_folders[task.task_id] = {root_id: root.value, subpath: path}; show(); renderPending(); });
          list.append(element('li')); list.lastChild.append(use);
        }
        for (const entry of listing.entries) {
          const item = element('li');
          if (entry.kind === 'link') item.append(element('span', `${entry.name} (link; not selectable)`, {class: 'muted'}));
          else {
            const open = element('button', entry.name + '/', {type: 'button', class: 'secondary'});
            open.addEventListener('click', () => { void browse(path ? `${path}/${entry.name}` : entry.name); });
            item.append(open);
          }
          list.append(item);
        }
        if (listing.incomplete) list.append(element('li', 'More folders exist than one listing shows.', {class: 'muted'}));
        if (!listing.entries.length) list.append(element('li', 'No subfolders here.', {class: 'muted'}));
      } catch (error) { if (!error.stale) list.append(element('li', 'Folders unavailable: ' + error.message)); }
      show();
    }
    root.addEventListener('change', () => {
      if (!root.value) { delete draft.data_folders[task.task_id]; renderPending(); }
      void browse('');
    });
    box.append(rootLabel, root, where, list);
    show();
    if (root.value) void browse(current.split('/').slice(0, -1).join('/'));
    return box;
  }

  function renderRows() {
    const body = $('settings-rows'); body.replaceChildren();
    for (const row of view.rows) {
      const tr = element('tr');
      for (const text of [row.task_id || 'All tasks', NAMES[row.name] || row.name, ORIGINS[row.origin] || row.origin, row.label, row.effective || '—']) tr.append(element('td', text));
      body.append(tr);
    }
  }

  // One plain sentence per problem, naming a fix that actually works for it.
  function fix(entry) {
    const name = entry.name, data = entry.created_by === 'operator';
    switch (entry.status) {
      case 'missing': return data ? `${name} is missing. Create this folder on the server and put the task's data in it.`
        : `${name} is missing. Run the init command below on the server to create it.`;
      case 'symlink': return `${name} is a link; the console never follows links. Move the link aside and ${data ? 'create a real folder there' : 'run init to create a real folder'}.`;
      case 'not_directory': return `${name} is a file, not a folder. Move it aside and ${data ? 'create the folder' : 'run init'}.`;
      case 'not_owner': return `${name} belongs to another user or others can write to it. Make it yours and run chmod 700 on it; init cannot fix this.`;
      case 'unreadable': return `${name} cannot be read by the console. Check its permissions (chmod 700 on your own folders).`;
      default: return `${name}: ${entry.status}.`;
    }
  }

  function renderWorkspace() {
    const facts = $('settings-workspace'); facts.replaceChildren();
    const problems = $('settings-workspace-problems'); problems.replaceChildren();
    const readiness = view.workspace;
    facts.append(element('dt', 'Workspace'), element('dd', view.workspace_root || 'Not configured (console.json has no workspace_root)'));
    if (readiness) {
      facts.append(element('dt', 'Folders'), element('dd', readiness.ready ? 'All required folders are present.' : 'Some folders need attention.'));
      for (const entry of readiness.entries) {
        if (entry.status === 'present' || entry.created_by === 'writer') continue;
        problems.append(element('li', fix(entry)));
      }
    }
    $('settings-init').hidden = !readiness?.init_command;
    $('settings-init-command').textContent = readiness?.init_command || '';
  }

  function renderPending() {
    const notes = [];
    if (view.restart_required) notes.push('Saved; active after server restart.');
    if (!same(draft, view.pending || empty())) notes.push('Unsaved changes on this page.');
    if (view.restart_required && view.pending) {
      const changed = ['llm_profile', 'advice', 'data_folders'].filter(key => !same(view.pending[key], view.active?.[key]));
      if (changed.length) notes.push('Saved but not yet active: ' + changed.map(key => ({llm_profile: 'model profile', advice: 'advice file', data_folders: 'data folders'})[key]).join(', ') + '.');
    }
    $('settings-pending').textContent = notes.join(' ');
    $('settings-save').disabled = busy || !view.writable || (view.problem && !view.settings_sha256) || same(draft, view.pending || empty());
  }

  const empty = () => ({schema_version: 'siderius.console-global-settings/v1', llm_profile: null, advice: null, data_folders: {}});

  function render() {
    $('settings-host').textContent = `Folders are on the server running the console (${view.host}), not on this computer.`;
    $('settings-form').hidden = !view.enabled;
    draft = JSON.parse(JSON.stringify(view.pending || empty()));
    choiceList($('settings-models'), 'llm_profile', view.llm_profiles, draft.llm_profile, 'Not set (tasks must set llm_config_file)');
    choiceList($('settings-advice'), 'advice', view.advice_files, draft.advice, 'None');
    const data = $('settings-data'); data.replaceChildren();
    if (!view.tasks.length) data.append(element('p', 'No tasks are configured.', {class: 'muted'}));
    for (const task of view.tasks) data.append(folderPicker(task));
    for (const kind of ['llm', 'advice']) $('settings-import-' + kind).disabled = !view.writable;
    renderRows(); renderWorkspace(); renderPending();
    if (view.problem) { say(view.problem); return; }
    say(!view.enabled ? 'Global settings are not enabled in console.json; values below are fixed by the server.'
      : view.writable ? 'Choose values, then Save. Changes take effect after the server restarts.'
        : 'Read-only: console.json does not allow browser changes to global settings.');
  }

  async function load(keepStatus = false) {
    if (!session().connected || busy) return;
    const status = $('settings-status').textContent;
    busy = true; say('Reading settings…');
    try { view = await session().request('settings'); loadedRevision = session().revision; render(); if (keepStatus) say(status); }
    catch (error) { if (!error.stale) say('Settings unavailable: ' + error.message); }
    finally { busy = false; if (view) renderPending(); }
  }

  $('settings-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !view?.writable) return;
    busy = true; renderPending(); say('Saving…');
    try {
      view = await session().request('settings', {expected_sha256: view.settings_sha256, settings: draft}, 'PUT');
      render(); say('Saved; active after server restart.');
    } catch (error) {
      if (error.stale) return;
      say(error.code === 'stale' ? 'Settings changed elsewhere since this page loaded. Reload, then choose again.' : 'Not saved: ' + error.message);
    } finally { busy = false; if (view) renderPending(); }
  });
  $('settings-reload').addEventListener('click', () => { void load(); });
  for (const kind of ['llm', 'advice']) $('settings-import-' + kind).addEventListener('change', event => { void importFile(kind, event.target); });
  const wanted = () => window.consoleNavigation.view === 'settings' && loadedRevision !== session().revision;
  session().subscribe(state => {
    if (!state.connected) { say(view ? 'Not connected. Reconnect to reload settings.' : 'Connect to load settings.'); return; }
    if (wanted()) void load();
  });
  window.addEventListener('console-view', () => { if (session().connected && wanted()) void load(); });
})();
