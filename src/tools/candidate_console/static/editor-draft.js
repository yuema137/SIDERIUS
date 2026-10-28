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
 *   nodes        pending palette nodes: PendingNode fields ({node, capability, protocol,
 *                binding, arguments, x, y}); any number, beside every other edit
 *   externals    new external inputs (ExternalBinding / ManagedCandidateBinding JSON)
 *                that pending or saved sockets may read (editor-node-drafts.js)
 *   removed      ids of saved nodes deleted in the draft; their readers are disconnected
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
  const identity = state => canonical({document: state.document, bindings: state.bindings, source: state.anchor.source,
    nodes: state.nodes || [], externals: state.externals || [], removed: state.removed || []});
  const sameTarget = (patch, node, argument) => patch.node === node && patch.argument === argument;

  const withoutText = state => { const {sourceText, ...rest} = state; return rest; };

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
      // A returned state may carry `sourceText` (typed Source text a Discard dropped); the
      // caller restores it as dirty text. History states themselves never keep it.
      undo() {
        const entry = undoStack.pop(); if (!entry) return null;
        push(redoStack, {state: current, label: entry.label}); current = withoutText(entry.state); coalescing = null;
        return {state: clone(entry.state), label: entry.label};
      },
      redo() {
        const entry = redoStack.pop(); if (!entry) return null;
        push(undoStack, {state: current, label: entry.label}); current = withoutText(entry.state); coalescing = null;
        return {state: clone(entry.state), label: entry.label};
      },
      /** Restore the loaded state (never a disk re-read). A dirty discard, including dirty
       * Source text passed as `sourceText`, is itself undoable. */
      discard(sourceText = null) {
        const typed = typeof sourceText === 'string';
        if (typed || identity(current) !== identity(baseline)) {
          push(undoStack, {state: typed ? {...current, sourceText} : current, label: typed ? 'Discard changes and typed source' : 'Discard changes'});
          redoStack.length = 0;
        }
        current = clone(baseline); coalescing = null; return clone(current);
      },
      /** The author chose a newer disk version as base: Discard restores `loaded`, and history
       * restarts there, because older states would rebuild proposals on the superseded source.
       * `state` (edits re-applied onto `loaded`, see `reapply`) becomes one undoable step. */
      rebase(loaded, state, label) {
        baseline = clone(loaded); current = clone(loaded); coalescing = null;
        undoStack.length = 0; redoStack.length = 0;
        if (state) this.record(state, label);
      }
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
    // Pending nodes/inputs (NodeDraftsProposal): targeted insertions on the anchor, unless
    // other edits travel with them (`document` when edited, binding patches).
    // Deleted saved nodes (`removed`) travel in the same typed proposal.
    if (state.nodes?.length || state.externals?.length || state.removed?.length) {
      const edited = canonical(state.document) !== canonical(state.anchor.document);
      return {kind: 'node_drafts', source: state.anchor.source, nodes: clone(state.nodes || []), externals: clone(state.externals || []),
        document: edited ? clone(state.document) : null, bindings: clone(state.bindings), removed: clone(state.removed || [])};
    }
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

  // Array elements merge by their identity field when every side has a unique one.
  const arrayKey = lists => ['id', 'node', 'name'].find(key => lists.every(list => Array.isArray(list) &&
    list.every(item => item && typeof item === 'object' && typeof item[key] === 'string') &&
    new Set(list.map(item => item[key])).size === list.length));
  const isRecord = value => !!value && typeof value === 'object' && !Array.isArray(value);
  /** Three-way merge: `ours` changes relative to `ancestor` applied onto `theirs`. Where both
   * sides changed one value differently, ours wins and the path is reported in `conflicts`. */
  function merge(ancestor, ours, theirs, path, conflicts) {
    const [a, o, t] = [ancestor, ours, theirs].map(canonical);
    if (o === a || o === t) return clone(theirs);
    if (t === a) return clone(ours);
    if ([ancestor, ours, theirs].every(isRecord)) {
      const result = {};
      for (const key of new Set([...Object.keys(theirs), ...Object.keys(ours)])) {
        const value = merge(ancestor[key], ours[key], theirs[key], [...path, key], conflicts);
        if (value !== undefined) result[key] = value;
      }
      return result;
    }
    const key = arrayKey([ancestor, ours, theirs]);
    if (key) {
      const [byA, byO, byT] = [ancestor, ours, theirs].map(list => new Map(list.map(item => [item[key], item])));
      const result = [];
      for (const id of new Set([...byT.keys(), ...byO.keys()])) {
        const value = merge(byA.get(id), byO.get(id), byT.get(id), [...path, id], conflicts);
        if (value !== undefined) result.push(value);
      }
      return result;
    }
    conflicts.push(path.join('.') || '(document)'); return clone(ours);
  }
  /** Re-apply the structured edits of `state` (made against `ancestorDocument`) onto the
   * newer `loaded` projection. Binding patches are not re-applied (Rebase refuses them). */
  function reapply(ancestorDocument, state, loaded) {
    const conflicts = [];
    const document = merge(ancestorDocument, state.document, loaded.document, [], conflicts);
    return {state: {...clone(loaded), document}, conflicts};
  }

  /** Undo/Redo/Discard buttons (secondary: Save stays the one primary action), dirty badge, page-title mark and keyboard shortcuts. */
  function mount({header, actions, undo, redo, discard, active}) {
    const button = (id, text) => {
      const element = document.createElement('button');
      element.id = id; element.type = 'button'; element.className = 'secondary'; element.textContent = text; element.disabled = true;
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
      // Red-team A-4: an open modal or popover owns the keyboard; the canvas behind it does not change.
      if (document.querySelector('dialog[open]') || (event.target instanceof Element && event.target.closest('[role="dialog"], [popover]'))) return;
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

  window.editorDraft = Object.freeze({create, inventory, withBinding, proposal, reapply, canonical, mount});
})();
