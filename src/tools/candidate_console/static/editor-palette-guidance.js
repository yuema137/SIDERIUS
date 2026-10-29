/* Node palette guidance (presentation only): entry cards, the hover/focus popover,
 * stage headings, the start guide and canvas port highlighting. Every relation shown
 * comes from GET /api/editor/node-catalog (entries plus its `guide`: stage order,
 * description, connects_from/to, the build chain and context feeders, and each
 * argument's `produced_by`). Nothing here decides whether a connection is allowed:
 * the canvas highlight marks ports whose server contract id equals one the entry
 * declares, and binding still goes through the server's port_inventory choices.
 * Contract type names, colour and shape come from editor-contract-presentation.js
 * (the browser side of the server name owner, workflows/definition/contract_names.py);
 * `contract.kind`, when present, names an input's origin. */
(() => {
  'use strict';
  // Display names from editor-capability-presentation.js (their single owner).
  const capabilityLabel = name => window.editorCapabilityPresentation.label(name);
  const contracts = () => window.editorContractPresentation;
  const element = (tag, text, parent, className) => {
    const value = document.createElement(tag); value.textContent = text;
    if (className) value.className = className;
    if (parent) parent.append(value); return value;
  };
  const list = names => names.map(capabilityLabel).join(', ');
  const routeText = entry => entry.protocol ? `Fed by ${list(sources(entry)) || entry.protocol}` : 'Starts from an external input';
  const sources = entry => [...new Set(entry.arguments.flatMap(item => item.produced_by))];
  // One name owner: editor-contract-presentation.js learns the server name from the object.
  const typeName = contract => contracts().describe(contract).name;
  // Origin of an input: the server's contract kind when present, else produced_by.
  const origin = (contract, producedBy) => producedBy.length ? `from ${list(producedBy)}`
    : contract.kind === 'setting' ? 'setting' : 'external input';
  const guideFor = (guide, capability) => guide?.capabilities.find(item => item.capability === capability) || null;

  function swatch(parent, id, required = true) {
    const mark = element('span', '', parent, 'circuit-contract-swatch');
    mark.setAttribute('aria-hidden', 'true'); contracts().decorate(mark, id, required); return mark;
  }
  // Contract names never encode direction: an arrow does ("→ name" is received,
  // "name →" is sent), with "receives"/"sends" as the accessible text.
  function chip(parent, text, id, required, direction) {
    const value = element('span', '', parent, `palette-chip palette-chip-${direction}`);
    value.dataset.contract = id; value.dataset.direction = direction;
    value.setAttribute('aria-label', `${direction} ${text}${required ? '' : ' (optional)'}`);
    if (direction === 'receives') element('span', '→', value, 'palette-arrow').setAttribute('aria-hidden', 'true');
    swatch(value, id, required); element('span', text, value).setAttribute('aria-hidden', 'true');
    if (direction === 'sends') element('span', '→', value, 'palette-arrow').setAttribute('aria-hidden', 'true');
    return value;
  }
  // One addable route row inside an expanded capability: route + typed socket chips.
  function card(button, entry) {
    element('span', routeText(entry), button, 'palette-entry-route');
    const chips = element('span', '', button, 'palette-chips');
    const inputs = entry.arguments.filter(item => item.required);
    if (!entry.protocol) chip(chips, typeName(entry.input_contract), entry.input_contract.id, true, 'receives');
    for (const item of inputs) chip(chips, typeName(item.contract), item.contract.id, true, 'receives');
    const optional = entry.arguments.length - inputs.length;
    if (optional) element('span', `+${optional} optional`, chips, 'palette-chip palette-chip-more');
    chip(chips, typeName(entry.output_contract), entry.output_contract.id, true, 'sends');
  }
  // Icon + display title on one line (ellipsis; full title as tooltip).
  function titled(parent, capability, className) {
    window.editorCapabilityPresentation.append(parent, capability, '', className);
    parent.querySelector('.capability-instance')?.remove();
    parent.querySelector('.capability-name').title = capabilityLabel(capability);
  }
  // Collapsed row (summary): icon | title | marker | step | chevron, one uniform line.
  // The Start here / Optional context badge is a small marker (accessible text and
  // tooltip) here, and a full line in the expanded details.
  function heading(summary, capability, guide, count) {
    titled(summary, capability, 'palette-row-heading');
    const info = guideFor(guide, capability);
    const tag = badge(guide, capability);
    if (tag) {
      const marker = element('span', '', summary, 'palette-badge'); marker.dataset.badge = tag; marker.title = tag;
      element('span', tag, marker, 'palette-visually-hidden');
    }
    if (info) element('span', String(info.stage + 1), summary, 'palette-step').setAttribute('aria-label', `Step ${info.stage + 1}`);
    summary.setAttribute('aria-label', `${capabilityLabel(capability)}${info ? `, step ${info.stage + 1}` : ''}${tag ? `, ${tag}` : ''}, ${count} route${count === 1 ? '' : 's'}`);
  }
  function details(parent, capability, guide, entries) {
    const info = guideFor(guide, capability);
    const box = element('div', '', parent, 'palette-details');
    const tag = badge(guide, capability);
    if (tag) element('p', tag === 'Start here' ? 'Start here: add this first.' : 'Optional context: feeds the chain when you want it.', box, 'palette-details-badge').dataset.badge = tag;
    if (info) element('p', info.description, box, 'palette-details-description');
    const output = entries[0]?.output_contract;
    if (output) {
      const row = element('p', '', box, 'palette-details-output');
      element('span', 'Sends: ', row, 'palette-details-label');
      chip(row, typeName(output), output.id, true, 'sends');
    }
    if (info) {
      element('p', `Connects from: ${info.connects_from.length ? list(info.connects_from) : 'external inputs only'}`, box, 'palette-details-from');
      element('p', `Connects to: ${info.connects_to.length ? list(info.connects_to) : 'nothing (final step)'}`, box, 'palette-details-to');
    }
    element('p', 'Add one of these routes (click, Enter or drag):', box, 'palette-details-label');
    return box;
  }

  // Popover: one shared role=tooltip element, shown on hover and on keyboard focus.
  let popover = null, owner = null, hideTimer = 0;
  function ensurePopover() {
    if (popover) return popover;
    popover = element('div', '', document.body, 'palette-popover'); popover.id = 'palette-popover';
    popover.setAttribute('role', 'tooltip'); popover.hidden = true;
    popover.addEventListener('pointerenter', () => clearTimeout(hideTimer));
    popover.addEventListener('pointerleave', () => hide());
    return popover;
  }
  function inputLine(parent, name, contract, required, producedBy) {
    const row = element('li', '', parent); row.dataset.argument = name;
    element('span', '→', row, 'palette-arrow').setAttribute('aria-hidden', 'true');
    swatch(row, contract.id, required);
    element('strong', name, row);
    element('span', ` · ${typeName(contract)} · ${required ? 'required' : 'optional'} · `, row);
    element('span', origin(contract, producedBy), row, producedBy.length ? 'palette-from-module' : 'palette-from-external');
  }
  function fill(entry, guide) {
    const box = ensurePopover(); box.replaceChildren();
    const info = guideFor(guide, entry.capability);
    titled(box, entry.capability, 'palette-popover-heading');
    element('p', info?.description || '', box, 'palette-popover-description');
    element('p', entry.protocol ? `Request route: ${entry.protocol}. ${routeText(entry)}.` : 'Request route: external. Its whole request is one external input (a binding).', box, 'palette-popover-route');
    element('h4', 'Receives', box);
    const inputs = element('ul', '', box, 'palette-popover-inputs');
    if (!entry.protocol) inputLine(inputs, 'request', entry.input_contract, true, []);
    for (const item of entry.arguments) inputLine(inputs, item.name, item.contract, item.required, item.produced_by);
    element('h4', 'Sends', box);
    const output = element('p', '', box, 'palette-popover-output');
    swatch(output, entry.output_contract.id);
    element('span', typeName(entry.output_contract), output);
    element('span', '→', output, 'palette-arrow').setAttribute('aria-hidden', 'true');
    const from = info?.connects_from || [], to = info?.connects_to || [];
    element('p', `Connects from: ${from.length ? list(from) : 'no other capability (external inputs only)'}`, box, 'palette-popover-from');
    element('p', `Connects to: ${to.length ? list(to) : 'no other capability (final step)'}`, box, 'palette-popover-to');
    element('p', 'Click or press Enter to add; or drag onto the canvas.', box, 'palette-popover-hint');
  }
  function place(anchor) {
    const box = popover, rect = anchor.getBoundingClientRect(), gap = 8;
    box.style.maxHeight = `${window.innerHeight - 16}px`;
    const width = box.offsetWidth, height = box.offsetHeight;
    let left = rect.right + gap, top = rect.top;
    if (left + width > window.innerWidth - gap) { left = Math.max(gap, Math.min(rect.left, window.innerWidth - width - gap)); top = rect.bottom + gap; }
    if (top + height > window.innerHeight - gap) top = Math.max(gap, window.innerHeight - height - gap);
    box.style.left = `${left}px`; box.style.top = `${top}px`;
  }
  function show(anchor, entry, guide, canvas) {
    clearTimeout(hideTimer); fill(entry, guide); owner = anchor;
    popover.hidden = false; place(anchor); highlight(canvas, entry);
  }
  function hide(canvas = null, immediate = true) {
    const run = () => { if (popover) popover.hidden = true; owner = null; clear(canvas); };
    clearTimeout(hideTimer);
    if (immediate) run(); else hideTimer = setTimeout(run, 150);
  }
  // Wires one palette entry to the popover and the canvas highlight.
  function attach(button, entry, guide, canvas) {
    ensurePopover(); button.setAttribute('aria-describedby', 'palette-popover');
    button.addEventListener('pointerenter', () => show(button, entry, guide, canvas));
    button.addEventListener('pointerleave', () => hide(canvas, false));
    button.addEventListener('focus', () => show(button, entry, guide, canvas));
    button.addEventListener('blur', () => hide(canvas));
    button.addEventListener('dragstart', () => { if (popover) popover.hidden = true; });
    button.addEventListener('click', () => hide(canvas));
  }
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && owner) hide(); });

  // Canvas ports already present that this entry could read from or feed into.
  let lit = [];
  function clear() { for (const port of lit) port.classList.remove('palette-compatible'); lit = []; }
  function highlight(canvas, entry) {
    clear();
    if (!canvas) return;
    const reads = new Set(entry.arguments.filter(item => item.produced_by.length).map(item => item.contract.id));
    for (const port of canvas.querySelectorAll('.circuit-port[data-contract]')) {
      const output = port.hasAttribute('data-output');
      if (output ? reads.has(port.dataset.contract) : port.dataset.contract === entry.output_contract.id) {
        port.classList.add('palette-compatible'); lit.push(port);
      }
    }
  }

  // Start guide: the build chain and context feeders, both server-derived.
  // Start guide: one sentence (build chain) plus a "How it works" disclosure.
  function startGuide(box, guide, empty) {
    box.replaceChildren();
    if (!guide?.chain.length) return false;
    const [first, ...rest] = guide.chain.map(capabilityLabel);
    element('p', `${empty ? 'The canvas is empty. ' : ''}Start with ${first}${rest.length ? `, then add ${rest.join(' → ')}` : ''}.`, box, 'palette-guide-lead');
    const more = element('details', '', box, 'palette-guide-more');
    element('summary', 'How it works', more);
    if (guide.context.length) element('p', `${list(guide.context)} add${guide.context.length === 1 ? 's' : ''} optional context that feeds the chain.`, more);
    element('p', 'Expand a capability to see what it receives, what it sends and what it connects to. Hover or focus a route for a preview; click, press Enter or drag it onto the canvas to add it.', more);
    return true;
  }
  function badge(guide, capability) {
    if (guide?.chain[0] === capability) return 'Start here';
    if (guide?.context.includes(capability)) return 'Optional context';
    return '';
  }
  // Group order: guide stage order; capabilities absent from the guide keep catalog order.
  function order(guide, capabilities) {
    const rank = name => guideFor(guide, name)?.stage ?? Number.MAX_SAFE_INTEGER;
    return [...capabilities].sort((a, b) => rank(a) - rank(b));
  }
  window.editorPaletteGuidance = Object.freeze({card, heading, details, attach, hide, startGuide, order, guideFor});
})();
