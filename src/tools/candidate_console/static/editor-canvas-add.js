/* `+` add-handles on unconnected outputs (canvas-study V5): presentation only.
 * When a card is hovered, focused or selected, an output that feeds no wire shows a `+`,
 * but only if at least one catalog route accepts that output's contract (no dead `+`).
 * It opens a small search of the catalog routes that accept that output's contract
 * (editor-palette.js connectable, the presentation filter of GET /api/editor/node-catalog);
 * choosing one adds the module to the right with that input already connected, as ONE
 * draft edit (editor.js startNode via editorNodePalette.addConnected). The server's node
 * inspection still decides whether the draft is complete; Save checks the exact bytes. */
(() => {
  'use strict';
  const graph = document.getElementById('editor-graph');
  const palette = () => window.editorNodePalette;
  const label = capability => window.editorCapabilityPresentation.label(capability);
  let popover = null, opener = null;
  const element = (tag, text, parent, className) => {
    const value = document.createElement(tag); value.textContent = text;
    if (className) value.className = className;
    if (parent) parent.append(value); return value;
  };
  function close(restore = true) {
    popover?.remove(); popover = null;
    if (restore && opener?.isConnected) opener.focus({preventScroll: true});
    opener = null;
  }
  function open(handle, nodeId, contractId) {
    close(false); opener = handle;
    popover = element('div', '', document.body, 'canvas-add-popover');
    popover.setAttribute('role', 'dialog'); popover.setAttribute('aria-label', `Add a module after ${nodeId}`);
    const search = element('input', '', popover, 'canvas-add-search');
    search.type = 'search'; search.placeholder = 'Search modules that accept this output'; search.setAttribute('aria-label', 'Search modules');
    const list = element('div', '', popover, 'canvas-add-list'); list.setAttribute('role', 'listbox');
    const routes = palette().connectable(contractId);
    const draw = () => {
      list.replaceChildren();
      const query = search.value.trim().toLowerCase();
      const shown = routes.filter(entry => `${label(entry.capability)} ${entry.capability} ${entry.protocol}`.toLowerCase().includes(query));
      if (!shown.length) { element('p', routes.length ? 'No module matches the search.' : 'No module in the catalog accepts this output.', list, 'muted'); return; }
      for (const entry of shown) {
        const option = element('button', '', list, 'canvas-add-option'); option.type = 'button'; option.setAttribute('role', 'option');
        option.dataset.capability = entry.capability; option.dataset.protocol = entry.protocol;
        window.editorCapabilityPresentation.append(option, entry.capability, '', 'canvas-add-heading');
        option.querySelector('.capability-instance')?.remove();
        option.setAttribute('aria-label', `Add ${label(entry.capability)} connected to ${nodeId}`);
        option.addEventListener('click', () => { const added = palette().addConnected(entry, nodeId, contractId); close(!added); });
      }
    };
    search.addEventListener('input', draw);
    popover.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key === 'Enter' && event.target === search) { event.preventDefault(); list.querySelector('.canvas-add-option')?.click(); }
    });
    draw();
    const box = handle.getBoundingClientRect(), width = 280;
    popover.style.left = Math.round(Math.min(box.right + 8, innerWidth - width - 8)) + 'px';
    popover.style.top = Math.round(Math.max(8, Math.min(box.top - 8, innerHeight - 320))) + 'px';
    search.focus();
  }
  function sync() {
    for (const card of graph.querySelectorAll('.circuit-card')) {
      const nodeId = card.dataset.node, output = card.querySelector(`#circuit-output-${CSS.escape(nodeId)}`);
      const connected = !!graph.querySelector(`.circuit-wire-target[data-from="${CSS.escape(nodeId)}"]`);
      let handle = card.querySelector(':scope > .circuit-add-next');
      const wanted = output && output.dataset.contract && !output.disabled && !connected && palette().connectable(output.dataset.contract).length > 0;
      if (!wanted) { handle?.remove(); continue; }
      if (!handle) {
        handle = element('button', '', card, 'circuit-add-next'); handle.type = 'button';
        handle.setAttribute('aria-label', `Add a module after ${nodeId}`); handle.title = 'Add a module that receives this output';
        handle.append(window.consoleIcons?.make('plus', 16) || document.createTextNode('+'));
        handle.addEventListener('click', event => { event.stopPropagation(); open(handle, nodeId, output.dataset.contract); });
      }
      // Level with the output row (CSSOM positioning; the card owns its size).
      handle.style.top = Math.round(output.offsetTop + output.offsetHeight / 2 - 10) + 'px';
    }
  }
  // Cards and wires are re-rendered by editor-circuit.js; re-attach after each change.
  let frame = 0;
  new MutationObserver(() => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; sync(); }); }).observe(graph, {childList: true, subtree: true});
  document.addEventListener('pointerdown', event => { if (popover && !popover.contains(event.target) && !event.target.closest?.('.circuit-add-next')) close(false); });
  window.addEventListener('console-view', () => close(false));
  window.addEventListener('editor-node-catalog', sync);
})();
