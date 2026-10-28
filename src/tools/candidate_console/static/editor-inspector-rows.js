/* Inspector input row label (ui-design-spec.md §8.2): "[swatch] Connector name · Required",
 * plus the protocol field name as an advanced-only code chip. Presentation only; the
 * connector name and colour come from editor-contract-presentation.js (server catalog). */
(() => {
  'use strict';
  /** Append and return the <label> that editor.js fills with the source <select>. */
  function label(parent, option, state) {
    const contracts = window.editorContractPresentation, row = document.createElement('label');
    row.className = 'inspector-input';
    const swatch = document.createElement('span'); swatch.className = 'circuit-contract-swatch'; swatch.setAttribute('aria-hidden', 'true');
    contracts.decorate(swatch, option.socket_contract, option.required);
    const name = document.createElement('span'); name.className = 'inspector-input-name';
    name.textContent = `${contracts.describe(option.socket_contract).name} · ${state}`;
    const field = document.createElement('code'); field.className = 'inspector-input-field'; field.dataset.uiFlag = 'advanced';
    field.textContent = option.argument || 'request';
    row.append(swatch, name, field); parent.append(row);
    return row;
  }
  window.editorInspectorRows = Object.freeze({label});
})();
