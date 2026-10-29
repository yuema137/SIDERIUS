/* Selected task: browser session state only (no request body or server record carries it).
 * Reads GET /api/tasks after each Connect; exactly one configured task is selected
 * automatically. The choice is remembered per operations store
 * (`siderius.selected-task.v1/<store>`) and dropped when that task is no longer configured.
 * `gated` (connected, list read, nothing selected) closes Workflow and Run; navigation.js
 * presents it. Presentation only: no editor, run or task request depends on it. */
(() => {
  'use strict';
  const session = window.consoleSession;
  const PREFIX = 'siderius.selected-task.v1/';
  let state = 'idle', tasks = [], error = '', selectedId = null, loading = null;
  const key = () => session.operationsStoreId ? PREFIX + session.operationsStoreId : null;
  function remembered() {
    try { return key() ? localStorage.getItem(key()) : null; } catch (_) { return null; }
  }
  function remember(id) {
    try { if (key()) { if (id) localStorage.setItem(key(), id); else localStorage.removeItem(key()); } }
    catch (_) { /* Storage unavailable: the choice stays in this page's memory. */ }
  }
  const publish = () => window.dispatchEvent(new CustomEvent('console-task', {detail: {selectedId, state}}));
  function adopt(list) {
    tasks = list; state = 'ready'; error = '';
    const known = id => !!id && tasks.some(task => task.task_id === id);
    selectedId = known(selectedId) ? selectedId : known(remembered()) ? remembered()
      : tasks.length === 1 ? tasks[0].task_id : null;
    remember(selectedId);
  }
  async function load() {
    if (!session.connected) return;
    const revision = session.revision; loading = revision;
    state = 'loading'; error = ''; publish();
    try {
      const value = await session.request('tasks');
      if (revision !== session.revision) return;
      if (!value || !Array.isArray(value.tasks)) throw new Error('The console sent an unreadable task list.');
      adopt(value.tasks);
    } catch (failure) {
      if (failure.stale || revision !== session.revision) return;
      // A failed read keeps an earlier selection; Retry reads the list again.
      state = 'error'; error = failure.message;
    } finally { if (loading === revision) loading = null; }
    publish();
  }
  function select(id) {
    if (!tasks.some(task => task.task_id === id) || id === selectedId) return;
    selectedId = id; remember(id); publish();
  }
  let seen = null;
  session.subscribe(({connected, revision}) => {
    if (connected && seen !== revision) { seen = revision; void load(); } else publish();
  });
  // The store id may arrive after the list (Connect through an operation link).
  window.addEventListener('console-store', () => {
    if (state !== 'ready') return;
    const previous = selectedId; adopt(tasks);
    if (selectedId !== previous) publish();
  });
  window.consoleTask = Object.freeze({
    select, reload: load,
    get state() { return state; }, get tasks() { return tasks; }, get error() { return error; },
    get selectedId() { return selectedId; },
    get selected() { return tasks.find(task => task.task_id === selectedId) || null; },
    get gated() { return session.connected && ['ready', 'error'].includes(state) && !selectedId; }
  });
})();
