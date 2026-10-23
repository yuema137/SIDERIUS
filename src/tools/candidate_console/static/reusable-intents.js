/* Advisory two-record coordination; the native operation store serializes effects. */
(() => {
  'use strict';
  const keys = {
    candidate: 'siderius.reusable-candidate.v1',
    preparation: 'siderius.reusable-preparation.v1'
  };
  const evidence = new Map();
  const listeners = new Set();
  const uuid = value => typeof value === 'string' &&
    /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value);
  const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);

  function read(kind) {
    const bytes = localStorage.getItem(keys[kind]);
    if (bytes === null) return null;
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
    return {bytes, value};
  }

  function notify() {
    for (const listener of listeners) listener();
  }

  function same(kind, value) {
    try {
      return read(kind)?.bytes === JSON.stringify(value);
    } catch (_) {
      return false;
    }
  }

  function eligible() {
    try {
      return Object.keys(keys).every(kind => {
        const record = read(kind);
        return !record || evidence.get(record.bytes)?.released === true;
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
    localStorage.setItem(keys[kind], bytes);
    if (read(kind)?.bytes !== bytes) throw Error('Intent storage did not retain exact bytes');
    notify();
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
    evidence.set(JSON.stringify(value), {released, dismissible: released || initialRefusal});
    notify();
    return true;
  }

  function dismissible(kind, value) {
    return same(kind, value) && evidence.get(JSON.stringify(value))?.dismissible === true;
  }

  function dismiss(kind, value) {
    if (!dismissible(kind, value)) throw Error('Intent identity or release evidence changed');
    localStorage.removeItem(keys[kind]);
    if (localStorage.getItem(keys[kind]) !== null) throw Error('Intent removal not confirmed');
    evidence.delete(JSON.stringify(value));
    notify();
  }

  window.reusableIntents = Object.freeze({
    read, same, eligible, save, observe, dismiss, dismissible,
    subscribe(listener) { listeners.add(listener); }
  });
  window.addEventListener('storage', event => {
    if (event.key === null || Object.values(keys).includes(event.key)) {
      evidence.clear();
      notify();
    }
  });
})();
