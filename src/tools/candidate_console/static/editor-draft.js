/* Unified workflow-editor draft: one browser-local history of structured edits.
 *
 * Wiring, disconnection, layout moves, inspector and research-loop edits all
 * become states of one draft with one dirty flag, undo/redo and Discard. The
 * server stays the authority for compatibility, validation and rendering: this
 * module only records states, projects binding patches over the server-derived
 * port inventory, and selects one of the existing typed review proposals.
 *
 * DraftState (plain JSON; the history clones on every boundary):
 *   document     authored workflow document being edited (positions, inspector,
 *                loop); binding changes are NOT applied here
 *   bindings     [{node, argument, source|null}] patches relative to anchor.inventory
 *   anchor       {source, document, inventory}: the last server projection the
 *                draft starts from (loaded source, or a reviewed source/task/node edit)
 *   node         null, or one pending palette node: AddNodeProposal fields without
 *                `source` ({node, capability, protocol, binding, arguments, x, y});
 *                it is added on top of an unedited anchor (document equals
 *                anchor.document, no binding patches), so it is reviewed alone
 *   training, loopTemplate   server presentation values for the anchor (not compared)
 */
(() => {
  'use strict';
  const HISTORY_LIMIT = 200;
  const clone = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  // Key-order independent JSON: removing and re-adding a key is not a change.
  function canonical(value) {
    if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
    if (value && typeof value === 'object') {
      return '{' + Object.keys(value).filter(key => value[key] !== undefined).sort()
        .map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
    }
    return JSON.stringify(value ?? null);
  }
  // Identity of the authored proposal; presentation values never make a draft dirty.
  const identity = state => canonical({document: state.document, bindings: state.bindings, source: state.anchor.source, node: state.node ?? null});
  const sameTarget = (patch, node, argument) => patch.node === node && patch.argument === argument;

  /** History over DraftState values. `loaded` is the state Discard restores. */
  function create(loaded) {
    let baseline = clone(loaded), current = clone(loaded), coalescing = null;
    const undoStack = [], redoStack = [];
    const push = (stack, entry) => { stack.push(entry); if (stack.length > HISTORY_LIMIT) stack.shift(); };
    return Object.freeze({
      get dirty() { return identity(current) !== identity(baseline); },
      get canUndo() { return undoStack.length > 0; },
      get canRedo() { return redoStack.length > 0; },
      get undoLabel() { return undoStack.at(-1)?.label ?? null; },
      get redoLabel() { return redoStack.at(-1)?.label ?? null; },
      /** Record one operation; consecutive operations with the same coalesce key form one undo step. */
      record(state, label, coalesce = null) {
        if (identity(state) === identity(current)) { current = clone(state); return false; }
        if (coalesce !== null && coalesce === coalescing && undoStack.length) {
          undoStack.at(-1).label = label;
          // A coalesced edit typed back to its starting value leaves no empty undo step.
          if (identity(undoStack.at(-1).state) === identity(state)) { undoStack.pop(); coalescing = null; }
        } else {
          push(undoStack, {state: current, label}); coalescing = coalesce;
        }
        redoStack.length = 0; current = clone(state); return true;
      },
      undo() {
        const entry = undoStack.pop(); if (!entry) return null;
        push(redoStack, {state: current, label: entry.label}); current = entry.state; coalescing = null;
        return {state: clone(current), label: entry.label};
      },
      redo() {
        const entry = redoStack.pop(); if (!entry) return null;
        push(undoStack, {state: current, label: entry.label}); current = entry.state; coalescing = null;
        return {state: clone(current), label: entry.label};
      },
      /** Restore the loaded state (never a disk re-read); a dirty discard is itself undoable. */
      discard() {
        if (identity(current) !== identity(baseline)) { push(undoStack, {state: current, label: 'Discard changes'}); redoStack.length = 0; }
        current = clone(baseline); coalescing = null; return clone(current);
      },
      /** The author chose a newer disk version as base: Discard now restores that version. */
      rebase(loaded) { baseline = clone(loaded); coalescing = null; }
    });
  }

  /** Server inventory of the anchor with this draft's binding patches projected onto it. */
  function inventory(state) {
    const projected = clone(state.anchor.inventory || []);
    for (const option of projected) {
      const patch = state.bindings.find(value => sameTarget(value, option.node, option.argument));
      if (!patch) continue;
      option.source = clone(patch.source); option.bound = patch.source !== null;
    }
    return projected;
  }

  /** New patch list after one connect (source) or disconnect (null); a return to the anchor drops the patch. */
  function withBinding(bindings, anchorInventory, node, argument, source) {
    const next = clone(bindings), index = next.findIndex(value => sameTarget(value, node, argument));
    const anchored = anchorInventory.find(value => sameTarget(value, node, argument))?.source ?? null;
    if (canonical(anchored) === canonical(source)) { if (index >= 0) next.splice(index, 1); return next; }
    const patch = {node, argument, source: clone(source)};
    if (index >= 0) next[index] = patch; else next.push(patch);
    return next;
  }

  const withoutLoop = document => { const copy = clone(document); delete copy.definition.loop; return canonical(copy); };
  /** The existing typed review proposal for this draft (server models in workflow_authoring.models). */
  function proposal(state) {
    // A pending node is a byte-preserving source insertion on the anchor (AddNodeProposal).
    if (state.node) return {kind: 'add_node', source: state.anchor.source, ...clone(state.node)};
    if (state.bindings.length) {
      // The server inspects patches over this edited document, so layout and inspector edits travel with them.
      return {kind: 'draft', draft: {base_document: clone(state.document), bindings: clone(state.bindings)}};
    }
    const anchor = state.anchor.document;
    if (withoutLoop(state.document) !== withoutLoop(anchor)) return {kind: 'document', document: clone(state.document)};
    // Loop-only edits keep every other authored byte of the anchor source.
    if (canonical(state.document.definition.loop) !== canonical(anchor.definition.loop)) {
      return {kind: 'loop', source: state.anchor.source, loop: clone(state.document.definition.loop ?? null)};
    }
    return {kind: 'source', source: state.anchor.source};
  }

  /** Undo/Redo/Discard buttons, dirty badge, page-title mark and keyboard shortcuts. */
  function mount({header, actions, undo, redo, discard, active}) {
    const button = (id, text) => {
      const element = document.createElement('button');
      element.id = id; element.type = 'button'; element.textContent = text; element.disabled = true;
      actions.append(element); return element;
    };
    const undoButton = button('editor-undo', 'Undo'), redoButton = button('editor-redo', 'Redo');
    const discardButton = button('editor-discard-draft', 'Discard changes');
    undoButton.setAttribute('aria-keyshortcuts', 'Control+Z');
    redoButton.setAttribute('aria-keyshortcuts', 'Control+Shift+Z Control+Y');
    undoButton.addEventListener('click', undo); redoButton.addEventListener('click', redo);
    discardButton.addEventListener('click', discard);
    const badge = document.createElement('span');
    badge.id = 'editor-dirty'; badge.className = 'editor-dirty'; badge.textContent = 'Unsaved changes'; badge.hidden = true;
    header.append(badge);
    let dirty = false;
    const MARK = '* ';
    const title = () => {
      const plain = document.title.startsWith(MARK) ? document.title.slice(MARK.length) : document.title;
      document.title = dirty ? MARK + plain : plain;
    };
    // Navigation rewrites the title on every view change; reapply the mark afterwards.
    window.addEventListener('console-view', title);
    document.addEventListener('keydown', event => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || !active()) return;
      const key = event.key.toLowerCase();
      if (key !== 'z' && key !== 'y') return;
      // Text controls keep their native text undo; their edits are already draft operations.
      if (event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
      event.preventDefault();
      if (key === 'y' || event.shiftKey) redo(); else undo();
    });
    return Object.freeze({
      render(value) {
        dirty = value.dirty; badge.hidden = !dirty; title();
        undoButton.disabled = !value.canUndo; redoButton.disabled = !value.canRedo; discardButton.disabled = !value.canDiscard;
        undoButton.title = value.canUndo ? `Undo: ${value.undoLabel}` : 'Nothing to undo';
        redoButton.title = value.canRedo ? `Redo: ${value.redoLabel}` : 'Nothing to redo';
      }
    });
  }

  window.editorDraft = Object.freeze({create, inventory, withBinding, proposal, canonical, mount});
})();
