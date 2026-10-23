/* Ordinary-file editor: native schemas/catalog stay server-owned. */
(() => {
  'use strict';
  const $ = id => document.getElementById(`editor-${id}`);
  let token = '', project = '', generation = 0, base = null, graph = null;
  let options = [], selected = null, pending = false, sourceDirty = false, mode = 'source', reviewed = null, conflict = null;
  const clone = value => JSON.parse(JSON.stringify(value));
  const status = message => { $('status').textContent = message; };
  const current = (id, version) => project === id && generation === version;
  const node = (tag, text, parent) => {
    const element = document.createElement(tag); element.textContent = text;
    if (parent) parent.append(element); return element;
  };
  function invalidate() {
    generation++; reviewed = null; $('save').disabled = true; $('diff').textContent = '';
    $('pending').textContent = pending ? (mode === 'document' ? 'Pending inspector edits · Review changes to update Python source before editing it.' : 'Pending source edits · not saved') : 'No pending edits.';
  }
  function changed() { pending = true; $('source').disabled = mode === 'document'; invalidate(); }
  async function api(path, body) {
    const response = await fetch(`/api/editor/${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : {'Content-Type': 'application/json'}) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    const value = await response.json();
    if (!response.ok) { const error = new Error(value.error?.message || 'Editor request failed.'); error.value = value; throw error; }
    return value;
  }
  function diagnostic(items = []) { $('diagnostics').textContent = items.map(item => `${item.code}: ${item.message}${item.line ? ` (line ${item.line})` : ''}`).join('\n'); }
  function showConflict(value) {
    conflict = value; reviewed = null; $('save').disabled = true;
    $('conflict').hidden = false; $('rebase').disabled = !value.document;
    $('current').textContent = value.source;
    $('conflict-diff').textContent = 'Current disk file version: ' + value.sha256.slice(0, 12) + '\n--- Current disk source\n+++ Pending proposal\n' + value.source.split('\n').map(line => '- ' + line).join('\n') + '\n' + $('source').value.split('\n').map(line => '+ ' + line).join('\n');
    status('Source changed. Pending proposal preserved; inspect current source before choosing a new base.');
  }
  function adopt(value) {
    base = value; graph = value.document ? clone(value.document) : null; options = value.binding_options;
    $('source').value = value.source; $('source').disabled = !graph; mode = 'source'; sourceDirty = false; pending = false; conflict = null;
    $('conflict').hidden = true; selected = graph?.definition.nodes.some(n => n.id === selected) ? selected : graph?.definition.nodes[0]?.id;
    invalidate(); diagnostic(value.diagnostics); render();
    $('path').textContent = value.source_path;
    $('revision').textContent = 'File version: ' + value.sha256.slice(0, 12);
    $('review').disabled = !graph; $('refresh').disabled = false;
    status(graph ? 'Opened supported declaration. References remain literal.' : 'Unsupported source is read-only. Repair externally, then refresh.');
  }
  function renderGraph() {
    $('graph').replaceChildren(); $('edges').replaceChildren();
    if (!graph) return;
    for (const item of graph.definition.nodes) {
      const button = node('button', '', $('graph')); button.type = 'button'; button.className = 'editor-node';
      button.setAttribute('aria-pressed', String(item.id === selected)); button.dataset.node = item.id;
      node('strong', item.id, button); node('span', item.capability, button);
      button.addEventListener('click', () => { selected = item.id; render(); });
      const bindings = item.request.kind === 'external' ? [{ name: 'request', source: {kind: 'external', binding: item.request.binding} }] : item.request.arguments;
      for (const binding of bindings) {
        const src = binding.source;
        node('li', `${src.kind === 'external' ? `external:${src.binding}` : `${src.node}.${src.port}`} → ${item.id}.${binding.name}`, $('edges'));
      }
    }
  }
  function field(parent, label, value, update) {
    const wrapper = node('label', label, parent), input = document.createElement('input');
    input.value = value; wrapper.append(input);
    input.addEventListener('input', () => { update(input.value); mode = 'document'; changed(); });
  }
  function renderInspector() {
    $('inspector').replaceChildren(); $('references').replaceChildren();
    if (!graph) return;
    const item = graph.definition.nodes.find(n => n.id === selected);
    if (item) {
      node('p', `${item.id} · ${item.capability}`, $('inspector'));
      for (const option of options.filter(entry => entry.node === item.id)) {
        const label = node('label', option.argument || 'Request binding', $('inspector'));
        const select = document.createElement('select'); label.append(select);
        const active = option.argument === null ? {kind: 'external', binding: item.request.binding} : item.request.arguments.find(a => a.name === option.argument).source;
        option.choices.forEach((choice, index) => {
          const el = node('option', choice.label, select); el.value = String(index);
          if (JSON.stringify(choice.source) === JSON.stringify(active)) el.selected = true;
        });
        select.dataset.node = item.id; select.dataset.argument = option.argument || 'request';
        select.addEventListener('change', () => {
          const choice = clone(option.choices[Number(select.value)].source);
          if (option.argument === null) item.request.binding = choice.binding;
          else item.request.arguments.find(a => a.name === option.argument).source = choice;
          mode = 'document'; changed(); status('Binding changed locally. Review validates the graph and updates its connections.');
        });
      }
    }
    for (const key of Object.keys(graph.definition.task)) field($('references'), `task.${key}`, graph.definition.task[key], value => { graph.definition.task[key] = value; });
    for (const external of graph.definition.externals) field($('references'), `external:${external.id}`, external.location, value => { external.location = value; });
  }
  function render() { renderGraph(); renderInspector(); if (sourceDirty) for (const input of document.querySelectorAll('#editor-inspector select, #editor-references input')) input.disabled = true; }
  function resetProjectState() {
    pending = false; sourceDirty = false; mode = 'source';
    base = null; graph = null; conflict = null; reviewed = null; options = []; selected = null;
    $('conflict').hidden = true; $('rebase').disabled = true;
    $('source').value = ''; $('source').disabled = true;
    $('current').textContent = ''; $('conflict-diff').textContent = '';
    $('path').textContent = ''; $('revision').textContent = '';
    $('review').disabled = true; $('refresh').disabled = !project;
    invalidate(); diagnostic(); render(); status('Opening selected project…');
  }
  async function refresh(ask = true) {
    if (pending && ask && !window.confirm('Discard pending edits and refresh from disk?')) return;
    const id = project; invalidate(); const version = generation;
    try { const value = await api(encodeURIComponent(id)); if (current(id, version)) adopt(value); }
    catch (error) { if (current(id, version)) status(error.message + ' Pending state retained.'); }
  }
  $('connect').addEventListener('submit', async event => {
    event.preventDefault(); if (pending && !window.confirm('Discard pending edits after connecting to the selected project?')) return; token = $('token').value; generation++; const version = generation;
    try {
      const choices = await api('projects'); if (generation !== version) return;
      $('project').replaceChildren();
      choices.forEach(choice => { const entry = node('option', choice.project_id, $('project')); entry.value = choice.project_id; });
      $('project').disabled = choices.length === 0; project = choices[0]?.project_id || '';
      resetProjectState();
      if (project) { await refresh(false); } else status('No editor projects configured. Candidate console and monitoring remain available.');
    } catch (error) { if (generation === version) status(error.message); }
  });
  $('project').addEventListener('change', () => {
    if (pending && !window.confirm('Discard pending edits and change project?')) { $('project').value = project; return; }
    project = $('project').value; resetProjectState(); refresh(false);
  });
  $('refresh').addEventListener('click', () => refresh());
  $('source').addEventListener('input', () => { mode = 'source'; sourceDirty = true; changed(); for (const input of document.querySelectorAll('#editor-inspector select, #editor-references input')) input.disabled = true; });
  $('review').addEventListener('click', async () => {
    if (!base?.document) return;
    const id = project, version = generation;
    const proposal = mode === 'document' ? {kind: 'document', document: clone(graph)} : {kind: 'source', source: $('source').value};
    try {
      const value = await api(`${encodeURIComponent(id)}/review`, {expected_sha256: base.sha256, proposal});
      if (!current(id, version)) return;
      $('source').value = value.source; $('source').disabled = false; graph = clone(value.document); mode = 'source'; sourceDirty = false;
      // Choices depend on actual new nodes/externals: refresh projection through
      // the reviewed document using server-derived options returned by review.
      options = value.binding_options; selected = graph.definition.nodes.some(n => n.id === selected) ? selected : graph.definition.nodes[0]?.id;
      reviewed = {source: value.source, sha256: value.sha256, base: base.sha256};
      $('diff').textContent = value.diff || '(No source changes)'; diagnostic(); render(); $('save').disabled = false;
      status('Declaration validated. Inspect the exact Python diff, then save.');
    } catch (error) {
      if (!current(id, version)) return;
      if (error.value?.proposal) { const proposal = error.value.proposal; $('source').value = proposal.source; $('source').disabled = false; graph = clone(proposal.document); options = proposal.binding_options; mode = 'source'; sourceDirty = false; render(); }
      if (error.value?.current) showConflict(error.value.current);
      diagnostic(error.value?.diagnostics); status(error.message);
    }
  });
  $('save').addEventListener('click', async () => {
    if (!reviewed || reviewed.source !== $('source').value) return;
    const id = project, version = generation, exact = {...reviewed};
    $('save').disabled = true;
    try {
      const saved = await api(`${encodeURIComponent(id)}/save`, {source: exact.source, proposal_sha256: exact.sha256, expected_sha256: exact.base});
      if (!current(id, version)) return;
      const value = await api(encodeURIComponent(id)); if (!current(id, version)) return;
      if (value.sha256 !== saved.sha256) { showConflict(value); status('Save completed, then source changed again. Pending reviewed bytes retained.'); return; }
      adopt(value); status(saved.unchanged ? 'Source unchanged; confirmed from disk.' : 'Saved reviewed bytes and reloaded from disk. Recovery copies preserved.');
    } catch (error) {
      if (!current(id, version)) return;
      if (error.value?.current) showConflict(error.value.current);
      status(error.message + ' Save is unconfirmed; pending proposal retained. Refresh to inspect disk.');
      reviewed = null;
    }
  });
  $('discard').addEventListener('click', () => { if (conflict) adopt(conflict); });
  $('rebase').addEventListener('click', () => {
    if (!conflict) return;
    // A form proposal first becomes source via Review; a changed-base review
    // may fail before rendering, so preserve the form graph for re-review.
    base = conflict; conflict = null; $('conflict').hidden = true;
    $('revision').textContent = 'File version: ' + base.sha256.slice(0, 12);
    changed(); status('Current disk source chosen as base. Reconcile your proposal, then review again.');
  });
})();
