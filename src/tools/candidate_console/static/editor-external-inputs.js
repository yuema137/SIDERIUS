/* Inspector help and "Create external input" form for one unbound input socket.
 *
 * GET /api/editor/external-inputs (workflow_authoring.external_inputs) owns which
 * contracts can be declared as external inputs, their one-line explanation and
 * whether a reusable (schema 2) workflow may leave them to candidate preparation
 * ("managed"). No location is ever prefilled: the author types the project-relative
 * JSON file path; the example is only a placeholder. editor.js records the result.
 */
(() => {
  'use strict';
  const IDENTIFIER = /^[a-zA-Z][a-zA-Z0-9_-]*$/;
  let catalog = null, loading = false, onReady = null;
  const element = (tag, text, parent, className) => {
    const value = document.createElement(tag); value.textContent = text;
    if (className) value.className = className;
    if (parent) parent.append(value); return value;
  };
  async function load(ready) {
    if (catalog) return; onReady = ready;
    if (loading || !window.consoleSession?.connected) return;
    loading = true;
    try {
      const value = await window.consoleSession.request('editor/external-inputs');
      catalog = new Map(value.entries.map(entry => [entry.contract.id, entry]));
      onReady?.(); onReady = null;
    } catch { /* the inspector keeps the existing-input select; a later render retries */ }
    finally { loading = false; }
  }
  function suggestion(base, taken) {
    let id = base.replace(/[^a-zA-Z0-9_-]/g, '_').replace(/^[^a-zA-Z]+/, '') || 'input', n = 1;
    const first = id; while (taken.has(id)) id = `${first}${++n}`;
    return id;
  }
  /** Explanation line plus a collapsed creation form under an unbound socket.
   * context: {option, nodeId, reusable, taken (Set of external ids), enabled, ready}. */
  function render(parent, context, create) {
    const {option, nodeId} = context;
    if (!catalog) { void load(context.ready); return; }
    const entry = catalog.get(option.socket_contract.id);
    if (!entry || option.bound) return;
    const socket = `${nodeId}.${option.argument || 'request'}`;
    const id = suggestion(`${nodeId}_${option.argument || 'input'}`, context.taken);
    const choose = option.choices.some(choice => choice.source.kind === 'external') ? 'Choose an existing input above, or create one.' : 'No input of this kind exists yet: create one.';
    const help = element('p', `${option.socket_contract.id}: ${entry.summary} ${choose}`, parent, 'external-input-help');
    help.dataset.socket = socket;
    const form = element('details', '', parent, 'external-input-create'); form.dataset.socket = socket;
    element('summary', 'Create external input…', form);
    const field = (label, input) => { const wrapper = element('label', label, form); wrapper.append(input); return input; };
    const name = field('Input id', Object.assign(document.createElement('input'), {value: id, name: 'external-id'}));
    const managed = entry.managed && context.reusable;
    const mode = managed ? field('Value', document.createElement('select')) : null;
    if (mode) {
      element('option', 'Managed by the run (preparation supplies it)', mode).value = 'managed';
      element('option', 'A JSON file in the project', mode).value = 'file';
      mode.name = 'external-mode';
    }
    const location = field('File path (relative to the project folder)', Object.assign(document.createElement('input'),
      {name: 'external-location', placeholder: `e.g. inputs/${id}.json`}));
    element('p', `The file holds a ${entry.contract.native_type} value as JSON. Nothing is read until a run is prepared.`, form, 'external-input-note');
    const error = element('p', '', form, 'external-input-error'); error.setAttribute('role', 'status');
    const sync = () => { location.parentElement.hidden = mode?.value === 'managed'; };
    mode?.addEventListener('change', sync); sync();
    const button = element('button', 'Create and connect', form); button.type = 'button';
    for (const input of [name, location, button, ...(mode ? [mode] : [])]) input.disabled = !context.enabled;
    button.addEventListener('click', () => {
      const value = name.value.trim(), path = location.value.trim(), isManaged = mode?.value === 'managed';
      if (!IDENTIFIER.test(value)) { error.textContent = 'Use a letter first, then letters, digits, _ or -.'; return; }
      if (context.taken.has(value)) { error.textContent = `An input named ${value} already exists; choose it above or pick another id.`; return; }
      if (!isManaged && !path) { error.textContent = 'Enter the project-relative path of the JSON file.'; return; }
      create(isManaged ? {id: value, contract: entry.contract.id, kind: 'managed_candidate'}
        : {id: value, contract: entry.contract.id, location: path}, nodeId, option.argument);
    });
  }
  window.editorExternalInputs = Object.freeze({render});
})();
