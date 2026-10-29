/* Settings (advanced): "Forget this browser's console data" (SEC-4). Removes this
 * origin's console preferences, remembered UUIDs and released run records. Records that
 * may still name an unfinished operation are kept: run intents of other stores or
 * projects (this page cannot check them) and loop-resume request ids (they make a
 * retried Resume replay instead of starting twice). Never offered while the current
 * project's run is active or unconfirmed (the same rule as Forget on Run). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const coordinator = window.reusableIntents;
  const kept = name => name.startsWith('siderius.loop-resume.') ||
    (coordinator.isIntentKey(name) && !['candidate', 'preparation'].some(kind => coordinator.key(kind) === name));
  function names() {
    const result = [];
    try { for (let index = 0; index < localStorage.length; index++) { const name = localStorage.key(index); if (name?.startsWith('siderius.')) result.push(name); } }
    catch (_) { /* Storage unavailable: nothing to forget. */ }
    return result;
  }
  function controls() {
    const button = $('forget-browser-data'), blocked = !coordinator.clearable();
    button.disabled = blocked;
    $('forget-browser-data-status').textContent = blocked
      ? 'Not available while a run of the open project is in progress or unconfirmed.'
      : '';
  }
  $('forget-browser-data').addEventListener('click', () => {
    controls();
    if ($('forget-browser-data').disabled) return;
    const all = names(), keep = all.filter(kept);
    if (!window.confirm(`Forget this browser's console data? Preferences, the remembered operation and finished run records are removed${keep.length ? `; ${keep.length} record${keep.length === 1 ? '' : 's'} that may belong to a still-running operation ${keep.length === 1 ? 'is' : 'are'} kept` : ''}. Nothing on the server changes. The page reloads and asks for the token again.`)) return;
    for (const kind of ['candidate', 'preparation']) {
      const record = (() => { try { return coordinator.read(kind); } catch (_) { return null; } })();
      if (record) coordinator.dismiss(kind, record.value);
    }
    for (const name of all) if (!kept(name)) localStorage.removeItem(name);
    location.reload();
  });
  coordinator.subscribe(controls);
  controls();
})();
