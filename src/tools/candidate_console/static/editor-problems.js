/* Problems popover view only (page-bar chip, spec §9): editor.js owns selection and every document mutation.
 * Items are the server's diagnostics: located draft problems (DraftProblem: code,
 * node, field, message) and source diagnostics (SourceDiagnostic: code, message,
 * line, field_path). The browser never derives a problem of its own. */
(() => {
  'use strict';
  const node = (tag, text, parent, className) => {
    const element = document.createElement(tag); element.textContent = text;
    if (className) element.className = className;
    parent.append(element); return element;
  };
  const cssId = value => String(value).replace(/[^A-Za-z0-9_-]/g, '\\$&');
  // One plain sentence per problem (spec §9): "Propose model: Results analysis is not connected".
  // actions.describe(node, field) -> {module, connector} from the open graph and the server inventory.
  function sentence(item, actions) {
    if (!item.node) return `Python source${item.line ? ` line ${item.line}` : ''}: ${item.message}`;
    const {module, connector} = actions.describe?.(item.node, item.field || 'request') || {};
    const who = module || item.node;
    if (item.code === 'required_unbound' && connector) return `${who}: ${connector} is not connected`;
    return `${who}: ${item.message}`;
  }
  /** actions: {select(node, field)} for socket problems, {source(line)} otherwise, {describe}. */
  function render(container, items, actions) {
    container.replaceChildren();
    container.hidden = !items.length;
    if (!items.length) { container.classList.remove('open'); return; }
    const heading = node('h2', `${items.length} problem${items.length === 1 ? '' : 's'} to fix before saving`, container);
    heading.id = 'editor-problems-heading';
    const list = node('ul', '', container);
    list.setAttribute('aria-labelledby', heading.id);
    for (const item of items) {
      const entry = node('li', '', list);
      const button = node('button', '', entry, 'editor-problem');
      button.type = 'button'; button.dataset.code = item.code;
      if (item.node) { button.dataset.node = item.node; button.dataset.field = item.field || 'request'; }
      button.append(window.consoleIcons?.make('circle-alert', 16) || '');
      node('span', sentence(item, actions), button, 'editor-problem-text');
      // The raw located diagnostic stays available as advanced detail.
      // Server messages may already start with their location ("build.output: …"): say it once.
      const where = item.node ? `${item.node}.${item.field || 'request'}` : item.line ? `line ${item.line}` : 'source';
      const message = item.message.startsWith(`${where}: `) ? item.message.slice(where.length + 2) : item.message;
      const raw = node('code', `${where} · ${message}`, button, 'editor-problem-raw');
      raw.dataset.uiFlag = 'advanced';
      button.addEventListener('click', () => {
        container.classList.remove('open');
        if (item.node) actions.select(item.node, item.field || 'request'); else actions.source(item.line || null);
      });
    }
  }
  /** Move focus to the inspector control of one socket, and mark its canvas port. */
  function focusField(nodeId, field) {
    const control = document.querySelector(`#editor-inspector select[data-node="${cssId(nodeId)}"][data-argument="${cssId(field)}"]`);
    const port = document.getElementById(`circuit-input-${nodeId}-${field}`);
    for (const element of document.querySelectorAll('.problem-focus')) element.classList.remove('problem-focus');
    for (const element of [control, port]) element?.classList.add('problem-focus');
    port?.closest('details.circuit-optional')?.setAttribute('open', '');
    port?.scrollIntoView({block: 'nearest', inline: 'nearest'});
    control?.scrollIntoView({block: 'nearest'});
    control?.focus();
    return !!control;
  }
  /** Open Advanced source and place the caret at a one-based line. */
  function focusSource(line) {
    const advanced = document.getElementById('editor-advanced'), source = document.getElementById('editor-source');
    if (advanced) advanced.open = true;
    if (!source) return;
    if (line) {
      const lines = source.value.split('\n'), offset = lines.slice(0, line - 1).reduce((sum, text) => sum + text.length + 1, 0);
      source.setSelectionRange(offset, offset + (lines[line - 1]?.length || 0));
    }
    source.focus();
  }
  window.editorProblems = Object.freeze({render, focusField, focusSource});
})();
