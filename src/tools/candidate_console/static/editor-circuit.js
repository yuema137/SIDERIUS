/* Presentation and ephemeral gestures only; editor.js owns every document mutation. */
(() => {
  'use strict';
  let projection = null, actions = null, host = null, pending = null, drag = null, selectedWire = null, connecting = false;
  // View-only state (zoom, scroll, arranged view, expanded optional inputs). It is
  // kept per opened graph and never reaches a document, so viewing never changes source.
  let view = {key: null, scale: 1, fitPending: false, arranged: false, scroll: null, expanded: new Set(), adapters: new Set()};
  const CARD_GAP = {x: 135, y: 90};
  const geometry = window.editorCircuitGeometry;
  const presentation = window.editorCapabilityPresentation;
  const contracts = window.editorContractPresentation;
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const element = (tag, text, parent, className) => {
    const value = document.createElement(tag); value.textContent = text;
    if (className) value.className = className;
    parent.append(value); return value;
  };
  const say = text => { if (host) host.querySelector('.circuit-message').textContent = text; };
  function cancel(redraw = true) {
    const moved = drag;
    if (moved) { moved.card.style.left = moved.left + 'px'; moved.card.style.top = moved.top + 'px'; }
    pending = null; drag = null;
    host?.querySelector('.circuit-pending')?.remove(); highlight();
    if (moved && redraw) draw();
  }
  function choice(node, argument) {
    return projection.inventory.find(value => value.node === node && value.argument === argument);
  }
  // Refusal reason naming both server-sent contracts (presentation only).
  const refusal = (source, node, argument) => contracts.refusal(`${source.node}.result`,
    projection.inventory.find(value => value.node === source.node)?.node_output_contract.id,
    `${node}.${argument || 'request'}`, choice(node, argument)?.socket_contract.id);
  // `source` is the pending output, or a hovered output for a preview without selecting it.
  function highlight(source = pending) {
    if (!host) return;
    for (const input of host.querySelectorAll('[data-input]')) {
      const option = choice(input.dataset.node, input.dataset.argument || null);
      const compatible = source && option?.choices.some(value => same(value.source, source));
      input.classList.toggle('compatible', !!compatible);
      input.classList.toggle('incompatible', !!source && !compatible);
      input.title = source ? (compatible ? 'Type-compatible source. Click to rebind; review before saving.' : refusal(source, input.dataset.node, option?.argument)) : 'Select an output socket first.';
    }
    for (const output of host.querySelectorAll('[data-output]')) output.setAttribute('aria-pressed', String(output.dataset.node === pending?.node));
    for (const group of host.querySelectorAll('.circuit-optional')) {
      const compatible = [...group.querySelectorAll('[data-input]')].filter(input => input.classList.contains('compatible')).length;
      const summary = group.querySelector('summary');
      summary.classList.toggle('compatible', compatible > 0);
      summary.title = compatible ? `${compatible} compatible optional input${compatible === 1 ? '' : 's'}; expand to connect.` : '';
    }
    const disconnect = host.querySelector('.circuit-disconnect');
    if (disconnect) { disconnect.hidden = !selectedWire; disconnect.disabled = !projection.enabled || projection.allowBindingChange === false; }
    for (const target of host.querySelectorAll('.circuit-wire-target')) {
      const selected = same(selectedWire, wireKey(target));
      target.setAttribute('aria-pressed', String(selected));
      [...host.querySelectorAll('.circuit-wire')].find(path => same(wireKey(path), wireKey(target)))?.classList.toggle('selected', selected);
    }
  }
  const wireKey = target => ({from: target.dataset.from, to: target.dataset.to, argument: target.dataset.argument || null});
  function selectWire(target) {
    if (!projection?.enabled) return;
    selectedWire = wireKey(target);
    target.focus({preventScroll: true}); highlight();
    say(`Selected connection ${selectedWire.from}.result to ${selectedWire.to}.${selectedWire.argument}. Disconnect it with the button or Delete.`);
  }
  function disconnectSelectedWire() {
    if (!projection?.enabled || projection.allowBindingChange === false || !selectedWire) return;
    const target = {...selectedWire};
    selectedWire = null; highlight();
    actions.disconnect(target.to, target.argument);
  }
  // Screen pixels to world (document-layout) pixels under the view zoom.
  const toWorld = (clientX, clientY) => {
    const origin = host.querySelector('.circuit-world').getBoundingClientRect();
    return {x: (clientX - origin.left) / view.scale, y: (clientY - origin.top) / view.scale};
  };
  const point = socket => {
    const rect = socket.querySelector('.circuit-socket').getBoundingClientRect();
    return toWorld(rect.left + rect.width / 2, rect.top + rect.height / 2);
  };
  // Layout offsets are unaffected by the zoom transform, so boxes stay in world pixels.
  const cardBox = (card, margin = 0) => ({left: card.offsetLeft - margin, right: card.offsetLeft + card.offsetWidth + margin,
    top: card.offsetTop - margin, bottom: card.offsetTop + card.offsetHeight + margin});
  function sizeWorld() {
    const world = host.querySelector('.circuit-world'), sizer = host.querySelector('.circuit-sizer');
    const cards = [...world.querySelectorAll('.circuit-card')];
    const size = {width: Math.max(0, ...cards.map(card => card.offsetLeft + card.offsetWidth + 80)),
      height: Math.max(0, ...cards.map(card => card.offsetTop + card.offsetHeight + 80))};
    world.style.width = size.width + 'px'; world.style.height = size.height + 'px';
    sizer.style.width = size.width * view.scale + 'px'; sizer.style.height = size.height * view.scale + 'px';
    return size;
  }
  function updateVisibility() {
    const viewport = host?.querySelector('.circuit-viewport'), note = host?.querySelector('.circuit-view-note');
    if (!viewport || !note) return;
    const frame = viewport.getBoundingClientRect();
    const inner = {left: frame.left + viewport.clientLeft, top: frame.top + viewport.clientTop};
    inner.right = inner.left + viewport.clientWidth; inner.bottom = inner.top + viewport.clientHeight;
    const cards = [...viewport.querySelectorAll('.circuit-card')];
    const outside = cards.filter(card => {
      const box = card.getBoundingClientRect();
      return box.left < inner.left - 1 || box.right > inner.right + 1 || box.top < inner.top - 1 || box.bottom > inner.bottom + 1;
    });
    viewport.dataset.outsideCards = String(outside.length);
    const zoom = host.querySelector('.circuit-zoom'); if (zoom) zoom.textContent = `${Math.round(view.scale * 100)} %`;
    note.textContent = (outside.length
      ? `${outside.length} of ${cards.length} capabilities are partly outside the view. Scroll the canvas or use Fit to view.`
      : `All ${cards.length} capabilities are in view.`) +
      (view.arranged ? ' Arranged view: display only; the saved positions are unchanged.' : '');
    // Edge shadows mark each side that still has content to scroll to.
    const shadows = [];
    if (viewport.scrollLeft > 1) shadows.push('inset 14px 0 12px -12px var(--edge)');
    if (viewport.scrollLeft + viewport.clientWidth < viewport.scrollWidth - 1) shadows.push('inset -14px 0 12px -12px var(--edge)');
    if (viewport.scrollTop > 1) shadows.push('inset 0 14px 12px -12px var(--edge)');
    if (viewport.scrollTop + viewport.clientHeight < viewport.scrollHeight - 1) shadows.push('inset 0 -14px 12px -12px var(--edge)');
    viewport.style.boxShadow = shadows.join(', ');
  }
  function applyScale(scale) {
    view.scale = scale;
    const world = host.querySelector('.circuit-world');
    world.style.transform = scale === 1 ? '' : `scale(${scale})`;
    sizeWorld(); updateVisibility();
  }
  // Fit the whole graph into the canvas (view only; never below the legibility floor).
  function fit() {
    const viewport = host?.querySelector('.circuit-viewport');
    if (!viewport || !viewport.clientWidth || !projection?.document) return;
    view.fitPending = false;
    const content = sizeWorld(), max = parseFloat(getComputedStyle(viewport).maxHeight);
    const available = {width: viewport.clientWidth - 2, height: (Number.isFinite(max) ? max : viewport.clientHeight) - 2};
    applyScale(geometry.fitScale(content, available));
    viewport.scrollLeft = 0; viewport.scrollTop = 0; updateVisibility();
  }
  function draw() {
    if (!host) return;
    const svg = host.querySelector('svg'); svg.replaceChildren();
    const world = host.querySelector('.circuit-world');
    sizeWorld();
    const cards = [...world.querySelectorAll('.circuit-card')];
    const boxes = cards.map(card => cardBox(card, 5));
    const occupied = new Set();
    for (const input of world.querySelectorAll('[data-input]')) {
      const option = choice(input.dataset.node, input.dataset.argument || null);
      const source = option?.source;
      if (source?.kind !== 'result') continue;
      const output = [...world.querySelectorAll('[data-output]')].find(value => value.dataset.node === source.node);
      if (!output) continue;
      const route = geometry.route(point(output), point(input), boxes, cards.indexOf(output.closest('.circuit-card')), cards.indexOf(input.closest('.circuit-card')), occupied);
      if (!route) { say('Some wires could not be routed around overlapping or crowded cards. Use Arrange view (display only) or Fit to view, or move cards; the connection list retains every binding.'); continue; }
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', geometry.path(route)); path.classList.add('circuit-wire');
      if (output.dataset.contract) contracts.decorate(path, output.dataset.contract);
      path.dataset.from = source.node; path.dataset.to = input.dataset.node; path.dataset.argument = option.argument;
      svg.append(path);
      const target = document.createElementNS(svg.namespaceURI, 'path');
      target.setAttribute('d', geometry.path(route)); target.classList.add('circuit-wire-target');
      target.dataset.from = source.node; target.dataset.to = input.dataset.node; target.dataset.argument = option.argument;
      target.setAttribute('tabindex', '0'); target.setAttribute('role', 'button'); target.setAttribute('aria-pressed', 'false');
      target.setAttribute('aria-label', `Connection ${source.node}.result to ${input.dataset.node}.${option.argument}`);
      target.addEventListener('focus', () => path.classList.add('focused'));
      target.addEventListener('blur', () => path.classList.remove('focused'));
      target.addEventListener('click', event => { event.stopPropagation(); selectWire(target); });
      target.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); selectWire(target); }
        else if (['Delete', 'Backspace'].includes(event.key) && same(selectedWire, wireKey(target))) { event.preventDefault(); event.stopPropagation(); disconnectSelectedWire(); }
      });
      svg.append(target);
    }
    highlight(); updateVisibility();
  }
  function port(parent, node, argument, output, metadata = null) {
    const snapshot = projection;
    const label = output ? 'result' : argument || 'request';
    const button = element('button', label, parent, `circuit-port ${output ? 'circuit-output' : 'circuit-input'}`);
    button.type = 'button'; button.dataset.node = node.id;
    if (metadata) {
      const state = metadata.bound ? 'bound' : metadata.required ? 'required, unbound' : 'optional, unbound';
      const contract = metadata.socket_contract;
      const mapping = metadata.protocol_mapping ? `; mapped by ${metadata.protocol_mapping.owner} (${metadata.protocol_mapping.id}) to ${metadata.protocol_mapping.output_contract.id}` : '';
      const offered = metadata.choices.length ? metadata.choices.map(value => `${value.label} [${value.contract.id}]`).join('; ') : 'no connections offered by the server';
      const detail = `${node.id}.${label} input; ${state}; contract ${contract.id}: ${contract.native_type}${mapping}; server-offered connections: ${offered}`;
      button.title = detail;
      button.setAttribute('aria-label', detail);
      element('span', detail, button, 'circuit-port-tooltip').setAttribute('role', 'tooltip');
      const type = element('span', contracts.describe(contract.id).name, button, 'circuit-port-contract');
      type.setAttribute('aria-hidden', 'true');
      element('span', metadata.bound ? (metadata.required ? 'required' : 'optional') : `${metadata.required ? 'Required' : 'Optional'} · unbound`, button,
        `circuit-port-requirement${metadata.bound ? '' : ' circuit-port-unbound-label'}`);
      button.classList.toggle('is-unbound', !metadata.bound);
      button.dataset.contract = contract.id;
      button.dataset.required = String(metadata.required);
      contracts.decorate(button, contract.id, metadata.required);
    } else {
      const contract = projection.inventory.find(value => value.node === node.id)?.node_output_contract;
      const detail = `${node.id}.result output${contract ? `; contract ${contract.id}: ${contract.native_type}` : ''}`;
      button.title = detail;
      button.setAttribute('aria-label', detail);
      element('span', detail, button, 'circuit-port-tooltip').setAttribute('role', 'tooltip');
      if (contract) {
        const type = element('span', contracts.describe(contract.id).name, button, 'circuit-port-contract');
        type.setAttribute('aria-hidden', 'true');
        button.dataset.contract = contract.id;
        contracts.decorate(button, contract.id);
      }
    }
    if (output) { button.dataset.output = ''; button.setAttribute('aria-pressed', 'false'); }
    else { button.dataset.input = ''; button.dataset.argument = argument || ''; }
    element('span', '', button, 'circuit-socket');
    button.addEventListener('click', () => {
      if (projection !== snapshot || !projection.enabled) return;
      if (!projection.allowBindingChange) { say('Review/save or discard the current edits before changing a connection.'); return; }
      if (output) { pending = {kind: 'result', node: node.id, port: 'result'}; highlight(); say(`Selected ${node.id}.result. Choose a highlighted input, or press Escape to cancel.`); return; }
      if (!pending) { say('Select a result output socket first. External bindings remain available in the inspector.'); return; }
      const selected = choice(node.id, argument)?.choices.find(value => same(value.source, pending));
      if (!selected) { say(refusal(pending, node.id, argument)); return; }
      cancel(); actions.bind(node.id, argument, selected.source);
    });
    if (output) {
      // Hover previews compatible inputs; pressing starts a drag that drops on an input.
      const preview = {kind: 'result', node: node.id, port: 'result'};
      button.addEventListener('pointerenter', () => { if (!pending && projection === snapshot && projection.enabled) highlight(preview); });
      button.addEventListener('pointerleave', () => { if (!pending && projection === snapshot) highlight(); });
      button.addEventListener('pointerdown', event => { if (event.button === 0) { connecting = true; button.click(); } });
    }
    return button;
  }
  const button = (parent, text, id, onClick) => {
    const value = element('button', text, parent, 'circuit-view-button'); value.type = 'button'; value.id = id;
    value.addEventListener('click', onClick); return value;
  };
  // Re-render the current projection after a view-only change (arranged view).
  const rerender = () => { if (host && projection) render(host, projection, actions); };
  function toolbar(parent, value) {
    const bar = element('div', '', parent, 'circuit-toolbar');
    bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', 'Canvas view');
    button(bar, 'Fit to view', 'circuit-fit', fit).title = 'Scale the view so every capability is visible. Saved positions are unchanged.';
    button(bar, '−', 'circuit-zoom-out', () => applyScale(Math.max(0.4, Math.round((view.scale - 0.1) * 10) / 10))).setAttribute('aria-label', 'Zoom out');
    const zoom = element('span', `${Math.round(view.scale * 100)} %`, bar, 'circuit-zoom'); zoom.setAttribute('aria-label', 'Canvas zoom');
    button(bar, '+', 'circuit-zoom-in', () => applyScale(Math.min(1, Math.round((view.scale + 0.1) * 10) / 10))).setAttribute('aria-label', 'Zoom in');
    button(bar, 'Actual size', 'circuit-zoom-reset', () => applyScale(1));
    const arrange = button(bar, view.arranged ? 'Show saved layout' : 'Arrange view', 'circuit-arrange', () => {
      view.arranged = !view.arranged; view.fitPending = true; view.scroll = null; rerender();
    });
    arrange.setAttribute('aria-pressed', String(view.arranged));
    arrange.title = 'Display a non-overlapping layout derived from the connections. Display only: saved positions change only if you then move a card, review and save.';
    arrange.disabled = !value.document;
    const note = element('p', '', parent, 'circuit-view-note'); note.setAttribute('aria-live', 'polite');
  }
  function render(container, value, callbacks) {
    const focus = container.contains(document.activeElement) ? document.activeElement.id : null;
    const key = `${value.viewKey ?? ''}|${(value.document?.definition.nodes || []).map(node => node.id).join(',')}`;
    const previous = container.querySelector('.circuit-viewport');
    if (view.key !== key) view = {key, scale: 1, fitPending: true, arranged: false, scroll: null, expanded: new Set(), adapters: new Set()};
    else if (previous && !view.fitPending) view.scroll = {left: previous.scrollLeft, top: previous.scrollTop};
    host = container; projection = value; actions = callbacks; cancel(false); selectedWire = null; host.replaceChildren();
    const message = element('p', 'Select a capability to inspect it. Choose an output, then a highlighted input to rebind.', host, 'circuit-message');
    message.setAttribute('role', 'status');
    toolbar(host, value);
    if (value.document) contracts.legend(host, value.inventory);
    const disconnect = element('button', 'Disconnect selected connection', host, 'circuit-disconnect');
    disconnect.type = 'button'; disconnect.hidden = true; disconnect.addEventListener('click', disconnectSelectedWire);
    const viewport = element('div', '', host, 'circuit-viewport'), sizer = element('div', '', viewport, 'circuit-sizer');
    const world = element('div', '', sizer, 'circuit-world');
    viewport.addEventListener('scroll', updateVisibility, {passive: true});
    viewObserver.disconnect(); viewObserver.observe(viewport);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('role', 'group'); svg.setAttribute('aria-label', 'Workflow connections'); world.append(svg);
    if (!value.document) return;
    const saved = new Map(value.document.positions.map(p => [p.node, p]));
    const cards = [];
    // A move persists every displayed position, so later sources never mix stored and fallback layouts.
    // Moving a card in the arranged view adopts the displayed layout as an ordinary local edit.
    const layout = (moved, x, y) => cards.map(card => card.dataset.node === moved ? {node: moved, x, y} : {node: card.dataset.node, ...card._position});
    const move = positions => { view.arranged = false; actions.move(positions); };
    for (const node of value.document.definition.nodes) {
      const card = element('article', '', world, 'circuit-card'); card.dataset.node = node.id; card.dataset.capability = node.capability;
      const heading = element('button', '', card, 'editor-node');
      heading.type = 'button'; heading.dataset.node = node.id; heading.id = `circuit-node-${node.id}`;
      const capabilityLabel = presentation.append(heading, node.capability, node.id);
      heading.setAttribute('aria-label', `${capabilityLabel}, instance ${node.id}`);
      const role = [...heading.querySelector('.capability-heading').classList].find(name => name.startsWith('capability-') && name !== 'capability-heading');
      if (role) card.classList.add(role);
      heading.setAttribute('aria-pressed', String(node.id === value.selected));
      heading.addEventListener('click', () => { if (projection === value && projection.enabled) actions.select(node.id); });
      heading.addEventListener('keydown', event => {
        if (projection !== value || !projection.enabled || projection.allowMove === false || !event.altKey || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
        event.preventDefault(); const position = card._position;
        move(layout(node.id, position.x + (event.key === 'ArrowLeft' ? -20 : event.key === 'ArrowRight' ? 20 : 0), position.y + (event.key === 'ArrowUp' ? -20 : event.key === 'ArrowDown' ? 20 : 0)));
      });
      heading.addEventListener('pointerdown', event => {
        if (projection !== value || !projection.enabled || projection.allowMove === false || event.button !== 0 || drag) return;
        heading.setPointerCapture(event.pointerId);
        drag = {pointerId: event.pointerId, node: node.id, card, startX: event.clientX, startY: event.clientY, position: {...card._position}, left: card.offsetLeft, top: card.offsetTop};
      });
      heading.addEventListener('pointermove', event => {
        if (projection !== value || !drag || drag.node !== node.id || drag.pointerId !== event.pointerId) return;
        card.style.left = drag.left + (event.clientX - drag.startX) / view.scale + 'px'; card.style.top = drag.top + (event.clientY - drag.startY) / view.scale + 'px'; draw();
      });
      heading.addEventListener('pointerup', event => {
        if (projection !== value || !drag || drag.node !== node.id || drag.pointerId !== event.pointerId) return;
        const gesture = drag; drag = null;
        const dx = event.clientX - gesture.startX, dy = event.clientY - gesture.startY;
        if (projection.enabled && Math.abs(dx) + Math.abs(dy) > 3) move(layout(node.id, Math.round(gesture.position.x + dx / view.scale), Math.round(gesture.position.y + dy / view.scale)));
        else { gesture.card.style.left = gesture.left + 'px'; gesture.card.style.top = gesture.top + 'px'; draw(); }
      });
      heading.addEventListener('pointercancel', event => {
        if (projection === value && drag?.node === node.id && drag.pointerId === event.pointerId) { cancel(); say('Node move cancelled.'); }
      });
      const mapping = element('details', '', card, 'circuit-mapping');
      mapping.addEventListener('toggle', draw);
      element('summary', 'Mapping details', mapping);
      const mappingList = element('dl', '', mapping, 'circuit-mapping-list');
      element('dt', 'Capability ID', mappingList); element('dd', node.capability, mappingList);
      element('dt', 'Instance ID', mappingList); element('dd', node.id, mappingList);
      if (node.request.kind === 'protocol') { element('dt', 'Protocol', mappingList); element('dd', node.request.protocol, mappingList); }
      const protocolMapping = value.inventory.find(item => item.node === node.id)?.protocol_mapping;
      if (protocolMapping) {
        element('dt', 'Protocol owner', mappingList); element('dd', protocolMapping.owner, mappingList);
        element('dt', 'Mapped input contract', mappingList); element('dd', protocolMapping.output_contract.id, mappingList);
      }
      const options = value.inventory.filter(item => item.node === node.id);
      // Required and bound inputs always show; optional unbound ones fold into one expandable row.
      const folded = options.filter(option => !option.required && !option.bound);
      let group = null;
      if (folded.length) {
        group = document.createElement('details'); group.className = 'circuit-optional'; group.dataset.node = node.id;
        const summary = element('summary', `${folded.length} optional input${folded.length === 1 ? '' : 's'}`, group);
        summary.id = `circuit-optional-${node.id}`;
        group.open = view.expanded.has(node.id);
        group.addEventListener('toggle', () => {
          if (group.open) view.expanded.add(node.id); else view.expanded.delete(node.id);
          if (projection === value) draw();
        });
      }
      for (const option of options) {
        const input = port(folded.includes(option) ? group : card, node, option.argument, false, option); input.id = `circuit-input-${node.id}-${option.argument || 'request'}`;
        element('dt', option.argument || 'Request', mappingList);
        element('dd', option.source ? (option.source.kind === 'external' ? `external:${option.source.binding}` : `${option.source.node}.${option.source.port}`) : 'unbound', mappingList);
      }
      if (group) card.append(group);
      const output = port(card, node, null, true); output.id = `circuit-output-${node.id}`;
      // Below the output row: port tooltips open upward and never cover the chip.
      contracts.adapter(card, node.id, value.inventory, view.adapters, () => { if (projection === value) draw(); });
      cards.push(card);
    }
    // Card size comes from the rendered cards (editor.css owns it), never a copied constant.
    const size = {width: Math.max(0, ...cards.map(card => card.offsetWidth)), height: Math.max(0, ...cards.map(card => card.offsetHeight))};
    // The arranged view uses the same placement with no stored positions: display only.
    const placed = geometry.place(value.document.definition.nodes, view.arranged ? new Map() : saved, size, CARD_GAP);
    for (const card of cards) card._position = placed.get(card.dataset.node);
    const ox = 60 - Math.min(0, ...cards.map(card => card._position.x)), oy = 60 - Math.min(0, ...cards.map(card => card._position.y));
    for (const card of cards) { card.style.left = card._position.x + ox + 'px'; card.style.top = card._position.y + oy + 'px'; }
    world.style.transform = view.scale === 1 ? '' : `scale(${view.scale})`;
    sizeWorld();
    setEnabled(value.enabled); draw();
    if (view.fitPending) fit();
    else if (view.scroll) { viewport.scrollLeft = view.scroll.left; viewport.scrollTop = view.scroll.top; }
    updateVisibility();
    const overlapping = geometry.overlaps(cards.map(card => cardBox(card)));
    if (!view.arranged && overlapping.length) {
      const names = overlapping.map(([a, b]) => `${cards[a].dataset.node} and ${cards[b].dataset.node}`).join('; ');
      say(`Saved card positions overlap (${names}). Arrange view shows a non-overlapping layout without changing the saved source; moving a card there adopts that layout as a reviewable edit.`);
    }
    if (focus) document.getElementById(focus)?.focus({preventScroll: true});
  }
  function setEnabled(enabled) {
    if (!projection || !host) return;
    projection.enabled = enabled;
    for (const port of host.querySelectorAll('.circuit-port')) port.disabled = !enabled;
    const disconnect = host.querySelector('.circuit-disconnect'); if (disconnect) disconnect.disabled = !enabled || projection.allowBindingChange === false;
    for (const target of host.querySelectorAll('.circuit-wire-target')) {
      target.setAttribute('aria-disabled', String(!enabled)); target.setAttribute('tabindex', enabled ? '0' : '-1');
    }
    for (const heading of host.querySelectorAll('.editor-node')) heading.setAttribute('aria-disabled', String(!enabled));
    if (!enabled) { cancel(); selectedWire = null; highlight(); }
  }
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (pending || drag) { cancel(); say('Circuit gesture cancelled.'); }
    if (selectedWire) { selectedWire = null; highlight(); say('Wire selection cancelled.'); }
  });
  // Drag-to-connect: a press on an output released over an input clicks that input.
  document.addEventListener('pointerup', event => {
    if (!connecting) return;
    connecting = false;
    const input = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-input]');
    if (pending && input && host?.contains(input)) input.click();
  });
  document.addEventListener('contextmenu', event => { if (pending && host?.contains(event.target)) { event.preventDefault(); cancel(); say('Connection selection cancelled.'); } });
  document.addEventListener('pointermove', event => {
    if (!pending || !host?.contains(event.target)) return;
    const output = host.querySelector(`#circuit-output-${CSS.escape(pending.node)}`), svg = host.querySelector('svg');
    const start = point(output), end = toWorld(event.clientX, event.clientY);
    svg.querySelector('.circuit-pending')?.remove();
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.classList.add('circuit-pending');
    path.setAttribute('d', geometry.path([start, {x: (start.x + end.x) / 2, y: start.y}, {x: (start.x + end.x) / 2, y: end.y}, end])); svg.append(path);
  });
  new ResizeObserver(() => { if (projection?.document) draw(); }).observe(document.body);
  // A canvas rendered while hidden (zero width) fits once it is first laid out.
  const viewObserver = new ResizeObserver(() => {
    if (!projection?.document) return;
    if (view.fitPending) fit(); else updateVisibility();
  });
  window.editorCircuit = Object.freeze({render, setEnabled});
})();
