/* Advisory two-record coordination; the native operation store serializes effects.
 * Records are keyed by (operations store id, project): an intent for another store or
 * project never blocks this one and is never checked against the wrong store (R-3). */
(() => {
  'use strict';
  const kinds = ['candidate', 'preparation'];
  const legacy = kind => `siderius.reusable-${kind}.v1`;
  const prefix = kind => `siderius.reusable-${kind}.v2/`;
  // Page-local evidence per exact record bytes; never persisted.
  const evidence = new Map();
  const listeners = new Set();
  let store = null, project = null;
  const uuid = value => typeof value === 'string' &&
    /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value);
  const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);

  function key(kind) {
    return store && project ? `${prefix(kind)}${store}/${encodeURIComponent(project)}` : null;
  }

  function parse(kind, bytes) {
    const value = JSON.parse(bytes);
    const payload = value.payload;
    if (value.version !== 1 || value.origin !== location.origin ||
        typeof value.project !== 'string' || !payload?.selection) {
      throw Error('Invalid retained intent');
    }
    if (kind === 'candidate') {
      const preparation = payload.selection.preparation;
      if (!uuid(payload.candidate_operation_id) ||
          !digest(payload.expected_request_digest) ||
          typeof preparation?.envelope !== 'string' ||
          !digest(preparation.expected_receipt_sha256)) {
        throw Error('Invalid candidate intent');
      }
    } else {
      const selection = payload.selection;
      if (!uuid(selection.preparation_operation_id) || !uuid(selection.run_id) ||
          !digest(selection.expected_source_sha256) ||
          typeof selection.task_id !== 'string' || typeof selection.run_name !== 'string' ||
          !digest(payload.expectation?.request_digest) || !payload.expectation?.observations) {
        throw Error('Invalid preparation intent');
      }
    }
    return value;
  }

  function read(kind) {
    const name = key(kind);
    if (!name) return null;
    const bytes = localStorage.getItem(name);
    if (bytes === null) return null;
    const value = parse(kind, bytes);
    if (value.project !== project) throw Error('Retained intent names another project');
    return {bytes, value};
  }

  function notify() {
    for (const listener of listeners) listener();
  }

  // A pre-store (v1, per-origin) record moves under the current store and its own project
  // once; it is then checked against this store like any other record.
  function adoptLegacy() {
    for (const kind of kinds) {
      const name = key(kind);
      try {
        const bytes = localStorage.getItem(legacy(kind));
        if (bytes === null || localStorage.getItem(name) !== null) continue;
        if (parse(kind, bytes).project !== project) continue;
        localStorage.setItem(name, bytes);
        if (localStorage.getItem(name) === bytes) localStorage.removeItem(legacy(kind));
      } catch (_) { /* Unreadable legacy bytes stay where they are. */ }
    }
  }

  function setContext(next) {
    const changed = next.store !== store || next.project !== project;
    store = next.store; project = next.project;
    if (!changed) return;
    if (key('preparation')) adoptLegacy();
    // After the other workflow-editor-state listeners: subscribers must not observe a
    // new context while their own editor snapshot is still the previous project's.
    queueMicrotask(notify);
  }

  function same(kind, value) {
    try {
      return read(kind)?.bytes === JSON.stringify(value);
    } catch (_) {
      return false;
    }
  }

  const entry = bytes => evidence.get(bytes) || {released: false, refused: false, dispatched: false, unknown: false};
  function update(value, change) {
    const bytes = JSON.stringify(value);
    evidence.set(bytes, {...entry(bytes), ...change});
    notify();
  }

  function eligible() {
    if (!key('preparation')) return false;
    try {
      return kinds.every(kind => {
        const record = read(kind);
        return !record || entry(record.bytes).released === true;
      });
    } catch (_) {
      return false;
    }
  }

  function save(kind, value) {
    if (!eligible() || read(kind)) {
      throw Error('An operation intent already exists or remains unresolved');
    }
    const bytes = JSON.stringify(value);
    localStorage.setItem(key(kind), bytes);
    if (read(kind)?.bytes !== bytes) throw Error('Intent storage did not retain exact bytes');
    notify();
  }

  // Called immediately before every POST of this exact record; any earlier "unknown"
  // observation no longer proves absence once a new dispatch may be in flight.
  function dispatching(kind, value) {
    if (same(kind, value)) update(value, {dispatched: true, unknown: false});
  }

  function observe(kind, value, status, initialRefusal = false) {
    if (!same(kind, value)) return false;
    const payload = value.payload;
    const expectedId = kind === 'candidate'
      ? payload.candidate_operation_id : payload.selection.preparation_operation_id;
    const expectedDigest = kind === 'candidate'
      ? payload.expected_request_digest : payload.expectation.request_digest;
    const expectedKind = kind === 'candidate' ? 'candidate' : 'prepare_reusable';
    if (status && (status.operation_id !== expectedId ||
        status.request_digest !== expectedDigest || status.kind !== expectedKind)) {
      return false;
    }
    const spawnFailed = status?.state === 'operation_failed' && status.reason === 'spawn_failed';
    const terminalExited = ['completed', 'operation_failed'].includes(status?.state) &&
      status.process?.status === 'exited';
    const released = !status?.finishing && (spawnFailed || terminalExited);
    update(value, {released, refused: initialRefusal, unknown: false});
    return true;
  }

  // The server read this store and holds no such operation. Forgetting is allowed only
  // when this page dispatched the record before that read (Retry before Forget).
  function observeUnknown(kind, value) {
    if (!same(kind, value)) return false;
    const current = entry(JSON.stringify(value));
    update(value, {released: false, unknown: current.dispatched});
    return true;
  }

  function state(kind, value) {
    const current = same(kind, value) ? entry(JSON.stringify(value)) : null;
    return current ? {...current, forgettable: current.unknown === true} : null;
  }

  function dismissible(kind, value) {
    const current = state(kind, value);
    return !!current && (current.released || current.refused || current.forgettable);
  }

  function dismiss(kind, value) {
    if (!dismissible(kind, value)) throw Error('Intent identity or release evidence changed');
    const name = key(kind);
    localStorage.removeItem(name);
    if (localStorage.getItem(name) !== null) throw Error('Intent removal not confirmed');
    evidence.delete(JSON.stringify(value));
    notify();
  }

  // Whether every retained record of the current store and project may be cleared now.
  function clearable() {
    try {
      return kinds.every(kind => {
        const record = read(kind);
        return !record || dismissible(kind, record.value);
      });
    } catch (_) {
      return false;
    }
  }

  // Storage keys of records this page cannot release (other stores/projects, legacy).
  function isIntentKey(name) {
    return kinds.some(kind => name === legacy(kind) || name.startsWith(prefix(kind)));
  }

  window.reusableIntents = Object.freeze({
    read, same, eligible, save, observe, observeUnknown, dispatching, dismiss, dismissible,
    state, key, clearable, isIntentKey,
    get context() { return {store, project}; },
    subscribe(listener) { listeners.add(listener); }
  });
  window.addEventListener('storage', event => {
    if (event.key === null || isIntentKey(event.key)) {
      evidence.clear();
      notify();
    }
  });
  let editorProject = window.workflowEditor?.state?.projectId || null;
  const sync = () => setContext({store: window.consoleSession?.operationsStoreId || store, project: editorProject});
  window.addEventListener('workflow-editor-state', event => { editorProject = event.detail?.projectId || null; sync(); });
  window.addEventListener('console-store', sync);
  sync();
})();
