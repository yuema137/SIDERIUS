/* Node palette and node add/remove presentation; editor.js owns every document mutation.
 * Addable routes come only from GET /api/editor/node-catalog (the native catalog projection).
 * This module renders that list, proposes an instance id and position, projects a pending
 * node onto the canvas, and offers remove actions; the server reviews every byte. */
(() => {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  // Drag payload is prefixed text/plain: custom MIME types are dropped by some drag
  // implementations (e.g. automated Chromium drags), so the drop would never arrive.
  const PREFIX = 'siderius-capability:';
  let host = null, canvas = null, actions = null, catalog = null, loading = null, state = {enabled: false, pendingNode: null};
  const element = (tag, text, parent, className) => {
    const value = document.createElement(tag); value.textContent = text;
    if (className) value.className = className;
    if (parent) parent.append(value); return value;
  };
  const label = capability => window.editorCapabilityPresentation.label(capability);
  const routeText = entry => entry.protocol ? `from ${entry.protocol}` : 'from an external input';
  const cards = () => [...(canvas?.querySelectorAll('.circuit-card') || [])];
  function instanceId(capability) {
    const taken = new Set(cards().map(card => card.dataset.node));
    let id = capability, n = 1;
    while (taken.has(id)) id = `${capability}${++n}`;
    return id;
  }
  // World (document) coordinates: card._position is the circuit's placed layout.
  function placement(point) {
    const placed = cards().filter(card => card._position);
    if (!placed.length) return {x: 0, y: 0};
    if (!point) return {x: Math.max(...placed.map(card => card._position.x)) + 300, y: Math.min(...placed.map(card => card._position.y))};
    const world = canvas.querySelector('.circuit-world'), box = world.getBoundingClientRect();
    const scale = world.offsetWidth ? box.width / world.offsetWidth : 1, ref = placed[0];
    return {x: Math.round((point.x - box.left) / scale - (ref.offsetLeft - ref._position.x)),
      y: Math.round((point.y - box.top) / scale - (ref.offsetTop - ref._position.y))};
  }
  function add(entry, point = null) {
    if (!state.enabled || !actions) return;
    const {x, y} = placement(point);
    actions.add({node: instanceId(entry.capability), capability: entry.capability, protocol: entry.protocol, x, y});
  }
  function renderList() {
    const list = host.querySelector('.palette-list'); list.replaceChildren();
    if (!catalog) { element('p', loading ? 'Loading capabilities…' : 'Connect to load the capability catalog.', list, 'palette-empty'); return; }
    const query = host.querySelector('.palette-search').value.trim().toLowerCase();
    const groups = new Map();
    catalog.forEach((entry, index) => {
      const text = `${label(entry.capability)} ${entry.capability} ${entry.protocol || 'external'} ${entry.input_contract.id}`.toLowerCase();
      if (query && !text.includes(query)) return;
      if (!groups.has(entry.capability)) groups.set(entry.capability, []);
      groups.get(entry.capability).push([entry, index]);
    });
    if (!groups.size) { element('p', 'No capability matches the search.', list, 'palette-empty'); return; }
    for (const [capability, entries] of groups) {
      const group = element('details', '', list, 'palette-category'); group.open = true; group.dataset.capability = capability;
      element('summary', `${label(capability)} · ${entries.length} route${entries.length === 1 ? '' : 's'}`, group);
      for (const [entry, index] of entries) {
        const button = element('button', `${label(capability)} ${routeText(entry)}`, group, 'palette-entry');
        button.type = 'button'; button.draggable = true; button.dataset.capability = capability; button.dataset.protocol = entry.protocol || '';
        const inputs = entry.arguments.length ? entry.arguments.map(item => `${item.name} (${item.required ? 'required' : 'optional'}, ${item.contract.id})`).join('; ') : `request (${entry.input_contract.id})`;
        button.title = `Add a ${capability} node ${routeText(entry)}. Inputs: ${inputs}. Output: ${entry.output_contract.id}. Click to add, or drag onto the canvas.`;
        button.setAttribute('aria-label', `Add ${label(capability)} ${routeText(entry)}`);
        button.disabled = !state.enabled;
        button.addEventListener('click', () => add(entry));
        button.addEventListener('dragstart', event => { event.dataTransfer.setData('text/plain', PREFIX + index); event.dataTransfer.effectAllowed = 'copy'; });
      }
    }
  }
  async function load() {
    if (catalog || loading || !window.consoleSession?.connected) return;
    const revision = window.consoleSession.revision; loading = revision; renderList();
    try { const value = await window.consoleSession.request('editor/node-catalog'); if (revision === window.consoleSession.revision) catalog = value.entries; }
    catch (error) { if (!error.stale) host.querySelector('.palette-note').textContent = 'Capability catalog unavailable: ' + error.message; }
    finally { if (loading === revision) loading = null; if (host) renderList(); }
  }
  function mount(container, graphElement, callbacks) {
    host = container; canvas = graphElement; actions = callbacks; host.replaceChildren();
    element('h3', 'Add capability', host);
    const search = element('input', '', host, 'palette-search');
    search.type = 'search'; search.placeholder = 'Search capabilities'; search.setAttribute('aria-label', 'Search capabilities');
    search.addEventListener('input', renderList);
    element('div', '', host, 'palette-list');
    const cancel = element('button', 'Cancel new node', host, 'palette-cancel');
    cancel.type = 'button'; cancel.hidden = true; cancel.addEventListener('click', () => actions.cancel());
    element('p', 'Click or drag a capability onto the canvas. A new node stays a local draft until its required inputs are connected and you review and save.', host, 'palette-note').setAttribute('role', 'status');
    canvas.addEventListener('dragover', event => { if (state.enabled && [...event.dataTransfer.types].includes('text/plain')) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } });
    canvas.addEventListener('drop', event => {
      const data = event.dataTransfer.getData('text/plain'), index = data.startsWith(PREFIX) ? data.slice(PREFIX.length) : '';
      if (!state.enabled || index === '' || !catalog?.[Number(index)]) return;
      event.preventDefault(); add(catalog[Number(index)], {x: event.clientX, y: event.clientY});
    });
    window.consoleSession?.subscribe(() => { if (window.consoleSession.connected) void load(); });
    renderList(); void load();
  }
  function setState(next) {
    state = {...state, ...next};
    if (!host) return;
    for (const button of host.querySelectorAll('.palette-entry')) button.disabled = !state.enabled;
    const cancel = host.querySelector('.palette-cancel');
    cancel.hidden = !state.pendingNode; cancel.textContent = state.pendingNode ? `Cancel new node ${state.pendingNode}` : 'Cancel new node';
    if (!catalog) void load();
  }
  // The pending node is drawn from the proposal plus server-projected ports (draft.view.ports).
  function project(draft) {
    const graph = clone(draft.graph), proposal = draft.proposal;
    graph.definition.nodes.push({id: proposal.node, capability: proposal.capability, request: proposal.protocol
      ? {kind: 'protocol', protocol: proposal.protocol, arguments: clone(proposal.arguments)}
      : {kind: 'external', binding: proposal.binding ?? ''}});
    graph.positions = [...(graph.positions || []), {node: proposal.node, x: proposal.x, y: proposal.y}];
    return {graph, inventory: [...clone(draft.inventory), ...clone(draft.view?.ports || [])]};
  }
  // Optimistic local binding; the next node-draft inspection replaces it with server state.
  function bind(draft, argument, source) {
    const proposal = draft.proposal;
    if (argument === null) proposal.binding = source?.kind === 'external' ? source.binding : null;
    else {
      proposal.arguments = proposal.arguments.filter(item => item.name !== argument);
      if (source) proposal.arguments.push({name: argument, source: clone(source)});
    }
    for (const port of draft.view?.ports || []) if (port.argument === argument) { port.source = source ? clone(source) : null; port.bound = !!source; }
    if (draft.view) draft.view.status = 'checking';
  }
  const draftMessage = view => view.status === 'complete'
    ? `New node ${view.proposal.node} is complete. Review the exact Python insertion, then save.`
    : `New node ${view.proposal.node} is a draft (${view.status}): ${view.diagnostics.join(' ')} Connect its inputs on the canvas or in Selection.`;
  function inspectorActions(parent, nodeId, options) {
    const button = element('button', 'Remove capability', parent, 'editor-remove-node');
    button.type = 'button'; button.disabled = !options.enabled;
    button.setAttribute('aria-label', `Remove ${nodeId}`);
    button.title = 'Review shows the exact source removal and refuses while other capabilities still read this one.';
    button.addEventListener('click', () => options.remove([nodeId]));
  }
  let menu = null;
  const closeMenu = () => { menu?.remove(); menu = null; };
  function contextMenu(event, nodeId, remove) {
    event.preventDefault(); closeMenu();
    menu = element('div', '', document.body, 'node-context-menu'); menu.setAttribute('role', 'menu');
    menu.style.left = event.clientX + 'px'; menu.style.top = event.clientY + 'px';
    const item = element('button', `Remove ${nodeId}`, menu); item.type = 'button'; item.setAttribute('role', 'menuitem');
    item.addEventListener('click', () => { closeMenu(); remove([nodeId]); });
    item.focus();
  }
  document.addEventListener('pointerdown', event => { if (menu && !menu.contains(event.target)) closeMenu(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(); });
  window.editorNodePalette = Object.freeze({mount, setState, project, bind, draftMessage, inspectorActions, contextMenu});
})();
