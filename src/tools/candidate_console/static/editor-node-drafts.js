/* Pending palette nodes and new external inputs of the unified draft (no DOM).
 *
 * Any number of nodes and inputs can be pending at once, beside moves, inspector,
 * loop and binding edits. editor.js keeps them in the draft (fields `nodes`,
 * `externals`, see editor-draft.js) and this module only projects them for display
 * and edits the pending lists. The server stays the authority: POST
 * /api/editor/{project}/nodes-draft returns the ports of the whole projected graph
 * (choices include pending results and new inputs) and the draft status; Review
 * reviews the same typed `node_drafts` proposal (workflow_authoring.models).
 */
(() => {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  const active = state => (state.nodes?.length || 0) + (state.externals?.length || 0) > 0;
  // Server inspection depends on requests and inputs, not on layout: moving a card never re-inspects.
  const key = state => window.editorDraft.canonical({
    nodes: (state.nodes || []).map(({x, y, ...rest}) => rest), externals: state.externals || [], bindings: state.bindings,
    externalsSaved: state.document?.definition.externals || [], requests: (state.document?.definition.nodes || []).map(node => node.request)});
  const sourceOf = (item, argument) => argument === null
    ? (item.binding ? {kind: 'external', binding: item.binding} : null)
    : clone(item.arguments.find(value => value.name === argument)?.source ?? null);
  const instance = item => ({id: item.node, capability: item.capability, request: item.protocol
    ? {kind: 'protocol', protocol: item.protocol, arguments: clone(item.arguments)}
    : {kind: 'external', binding: item.binding ?? ''}});

  /** Display graph and port inventory: the edited document plus pending nodes and inputs.
   * `view` is the newest server inspection (possibly of an older key): its ports are reused
   * for nodes still present; sources always come from the current draft. */
  function project(state, view) {
    if (!active(state)) return {graph: state.document, inventory: window.editorDraft.inventory(state)};
    const graph = clone(state.document);
    graph.definition.externals = [...graph.definition.externals, ...clone(state.externals)];
    for (const item of state.nodes) {
      graph.definition.nodes.push(instance(item));
      graph.positions = [...(graph.positions || []), {node: item.node, x: item.x, y: item.y}];
    }
    const present = new Set(graph.definition.nodes.map(node => node.id));
    const ports = (view?.ports || state.anchor.inventory || []).filter(port => present.has(port.node));
    const inventory = window.editorDraft.inventory({...state, anchor: {...state.anchor, inventory: ports}});
    const pending = new Map(state.nodes.map(item => [item.node, item]));
    for (const port of inventory) {
      const item = pending.get(port.node);
      if (item) { port.source = sourceOf(item, port.argument); port.bound = port.source !== null; }
    }
    return {graph, inventory};
  }
  /** Pending nodes after connecting (source) or disconnecting (null) one of their sockets. */
  function bind(nodes, nodeId, argument, source) {
    return clone(nodes).map(item => {
      if (item.node !== nodeId) return item;
      if (argument === null) item.binding = source?.kind === 'external' ? source.binding : null;
      else {
        item.arguments = item.arguments.filter(value => value.name !== argument);
        if (source) item.arguments.push({name: argument, source: clone(source)});
      }
      return item;
    });
  }
  /** Drop pending nodes; sockets that read them are disconnected (pending) or return to
   * their saved source (binding patches). `disconnected` lists them for the status line. */
  function cancel(state, ids) {
    const reads = source => source?.kind === 'result' && ids.includes(source.node), disconnected = [];
    const nodes = clone(state.nodes).filter(item => !ids.includes(item.node)).map(item => {
      for (const value of item.arguments) if (reads(value.source)) disconnected.push(`${item.node}.${value.name}`);
      return {...item, arguments: item.arguments.filter(value => !reads(value.source))};
    });
    const bindings = clone(state.bindings).filter(patch => {
      if (reads(patch.source)) disconnected.push(`${patch.node}.${patch.argument ?? 'request'}`);
      return !reads(patch.source);
    });
    return {nodes, bindings, disconnected};
  }
  /** Layout entries a move should record. The circuit reports every card (pinning auto-placed
   * ones); when only pending cards moved, pinning saved cards would edit the saved document
   * and turn a byte-preserving insertion into a canonical re-render, so only they are kept. */
  function moves(state, layout) {
    const pending = new Map((state.nodes || []).map(item => [item.node, item]));
    const saved = new Map((state.document?.positions || []).map(item => [item.node, item]));
    const differs = (entry, from) => !!from && (from.x !== entry.x || from.y !== entry.y);
    const movedPending = layout.filter(entry => differs(entry, pending.get(entry.node)));
    const movedSaved = layout.some(entry => !pending.has(entry.node) && differs(entry, saved.get(entry.node)));
    return movedPending.length && !movedSaved ? movedPending : layout;
  }
  const plural = (word, items) => items.length ? `${word}${items.length > 1 ? 's' : ''} ${items.join(', ')}` : '';
  // "node a", "nodes a, b and input s": pending-line and undo-label text.
  const summary = state => [plural('node', (state.nodes || []).map(item => item.node)),
    plural('input', (state.externals || []).map(item => item.id))].filter(Boolean).join(' and ');
  const message = view => view.status === 'complete'
    ? 'New nodes and inputs are complete. Review the exact Python change, then save.'
    : `Draft ${view.status}: ${view.diagnostics.join(' ')} Connect the red inputs on the canvas or in Selection; Review stays blocked until then.`;

  window.editorNodeDrafts = Object.freeze({active, key, project, bind, cancel, moves, summary, message});
})();
