/* Problems list view only: editor.js owns selection and every document mutation.
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
  const where = item => item.node ? `${item.node}.${item.field || 'request'}` : item.line ? `Source line ${item.line}` : 'Source';
  /** actions: {select(node, field)} for socket problems, {source(line)} otherwise. */
  function render(container, items, actions) {
    container.replaceChildren();
    container.hidden = !items.length;
    if (!items.length) return;
    const heading = node('h2', `${items.length} problem${items.length === 1 ? '' : 's'}`, container);
    heading.id = 'editor-problems-heading';
    node('p', 'Review and Save stay unavailable until these are resolved. Select a problem to go to its field.', container, 'muted');
    const list = node('ul', '', container);
    list.setAttribute('aria-labelledby', heading.id);
    for (const item of items) {
      const entry = node('li', '', list);
      const button = node('button', '', entry, 'editor-problem');
      button.type = 'button'; button.dataset.code = item.code;
      if (item.node) { button.dataset.node = item.node; button.dataset.field = item.field || 'request'; }
      node('strong', where(item), button);
      node('span', ` ${item.message}`, button);
      button.addEventListener('click', () => item.node ? actions.select(item.node, item.field || 'request') : actions.source(item.line || null));
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
