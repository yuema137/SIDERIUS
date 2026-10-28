/* "Your advice to the agents": the first input of the node inspector.
 * Hook: editor.js renderInspector calls render(parent, state, edit) right after the
 * node heading. Field locations come only from GET /api/editor/advice-targets
 * (tools/workflow_authoring/advice_targets.py); editor.js owns the draft document,
 * Review and Save, and records each edit as one undoable draft operation. */
(() => {
  'use strict';
  let targets = null, loading = null, latest = null;
  const element = (tag, text, parent, className) => {
    const value = document.createElement(tag); value.textContent = text;
    if (className) value.className = className;
    if (parent) parent.append(value); return value;
  };
  const container = (document, location) => location === 'preparation_options' ? document.preparation_options
    : document.training_settings ? (document.training_settings.launch || {}) : null;
  function load() {
    if (targets || loading || !window.consoleSession?.connected) return;
    loading = window.consoleSession.request('editor/advice-targets').then(value => {
      targets = value.targets; loading = null;
      if (latest?.section.isConnected) fill(latest);
    }, () => { loading = null; });
  }
  function fill({section, state, edit}) {
    section.replaceChildren();
    const {document, item, inventory, enabled} = state;
    const target = targets?.find(value => value.capability === item.capability);
    if (!targets) { section.hidden = true; load(); return; }
    const values = target ? container(document, target.location) : null;
    if (!target || !values) { section.hidden = true; return; }
    section.hidden = false;
    const id = `editor-advice-${item.id}`;
    const label = element('label', target.label, section, 'advice-label'); label.htmlFor = id;
    const help = element('p', target.help, section, 'advice-help'); help.id = `${id}-help`;
    const input = element('textarea', '', section, 'advice-input');
    input.id = id; input.rows = 4; input.placeholder = target.placeholder; input.disabled = !enabled;
    input.dataset.adviceField = target.field; input.setAttribute('aria-describedby', help.id);
    input.value = values[target.field] ?? '';
    // Under this protocol the agent reads the advice only through its bound socket.
    const socket = target.socket && item.request.kind === 'protocol' && item.request.protocol === target.socket.protocol
      ? inventory.find(entry => entry.node === item.id && entry.argument === target.socket.argument) : null;
    if (socket && !socket.bound) {
      element('p', `This agent reads your advice only when its "${target.socket.argument}" input is connected to an advice input.`, section, 'advice-warning');
    }
    input.addEventListener('input', () => edit(next => {
      if (target.location === 'preparation_options') next.preparation_options[target.field] = input.value === '' ? null : input.value;
      else {
        const launch = (next.training_settings.launch ||= {});
        if (input.value === '') delete launch[target.field]; else launch[target.field] = input.value;
      }
    }, `Edit advice for ${item.id}`));
  }
  /** state: {document, item, inventory, enabled}; edit(mutate(document), label) records one draft edit. */
  function render(parent, state, edit) {
    const section = element('section', '', parent, 'advice-field');
    section.setAttribute('aria-label', 'Your advice to the agents');
    latest = {section, state, edit}; fill(latest);
  }
  /** Select the first canvas module that takes advice and focus its advice field ("Use template"). */
  async function focusFirst() {
    load(); if (loading) await loading;
    const card = targets && [...document.querySelectorAll('#editor-graph .circuit-card')].find(item => targets.some(value => value.capability === item.dataset.capability));
    if (!card) return false;
    const heading = card.querySelector('.editor-node');
    if (heading.getAttribute('aria-pressed') !== 'true') heading.click();
    const input = document.querySelector('#editor-inspector .advice-input');
    input?.scrollIntoView({block: 'nearest'}); input?.focus();
    return !!input;
  }
  window.consoleSession?.subscribe(({connected}) => { if (!connected) { targets = null; loading = null; } });
  window.editorAdvice = Object.freeze({render, focusFirst});
})();
