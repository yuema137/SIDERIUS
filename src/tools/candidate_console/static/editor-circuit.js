/* Presentation and ephemeral gestures only; editor.js owns every document mutation. */
(() => {
  'use strict';
  let projection = null, actions = null, host = null, pending = null, drag = null;
  const geometry = window.editorCircuitGeometry;
  const presentation = window.editorCapabilityPresentation;
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
    return projection.options.find(value => value.node === node && value.argument === argument);
  }
  function highlight() {
    if (!host) return;
    for (const input of host.querySelectorAll('[data-input]')) {
      const option = choice(input.dataset.node, input.dataset.argument || null);
      const compatible = pending && option?.choices.some(value => same(value.source, pending));
      input.classList.toggle('compatible', !!compatible);
      input.classList.toggle('incompatible', !!pending && !compatible);
      input.title = pending ? (compatible ? 'Type-compatible source. Click to rebind; review before saving.' : 'This source is not offered for this input by the server.') : 'Select an output socket first.';
    }
    for (const output of host.querySelectorAll('[data-output]')) output.setAttribute('aria-pressed', String(output.dataset.node === pending?.node));
  }
  const point = socket => {
    const rect = socket.querySelector('.circuit-socket').getBoundingClientRect();
    const origin = host.querySelector('.circuit-world').getBoundingClientRect();
    return {x: rect.left + rect.width / 2 - origin.left, y: rect.top + rect.height / 2 - origin.top};
  };
  function draw() {
    if (!host) return;
    const svg = host.querySelector('svg'); svg.replaceChildren();
    const world = host.querySelector('.circuit-world');
    const cards = [...world.querySelectorAll('.circuit-card')], rect = world.getBoundingClientRect();
    const boxes = cards.map(card => { const b = card.getBoundingClientRect(); return {left: b.left - rect.left - 5, right: b.right - rect.left + 5, top: b.top - rect.top - 5, bottom: b.bottom - rect.top + 5}; });
    const occupied = new Set();
    for (const input of world.querySelectorAll('[data-input]')) {
      const option = choice(input.dataset.node, input.dataset.argument || null);
      const node = projection.document.definition.nodes.find(value => value.id === input.dataset.node);
      const source = option?.argument === null ? null : node.request.arguments.find(value => value.name === option?.argument)?.source;
      if (source?.kind !== 'result') continue;
      const output = [...world.querySelectorAll('[data-output]')].find(value => value.dataset.node === source.node);
      if (!output) continue;
      const route = geometry.route(point(output), point(input), boxes, cards.indexOf(output.closest('.circuit-card')), cards.indexOf(input.closest('.circuit-card')), occupied);
      if (!route) { say('Some wires could not be routed around the current cards. Move overlapping cards; the connection list retains every binding.'); continue; }
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', geometry.path(route)); path.classList.add('circuit-wire');
      path.dataset.from = source.node; path.dataset.to = node.id; path.dataset.argument = option.argument;
      svg.append(path);
    }
    highlight();
  }
  function port(parent, node, argument, output) {
    const snapshot = projection;
    const label = output ? 'result' : argument || 'request';
    const button = element('button', label, parent, `circuit-port ${output ? 'circuit-output' : 'circuit-input'}`);
    button.type = 'button'; button.dataset.node = node.id;
    button.setAttribute('aria-label', `${node.id}.${label} ${output ? 'output' : 'input'}`);
    if (output) { button.dataset.output = ''; button.setAttribute('aria-pressed', 'false'); }
    else { button.dataset.input = ''; button.dataset.argument = argument || ''; }
    element('span', '', button, 'circuit-socket');
    button.addEventListener('click', () => {
      if (projection !== snapshot || !projection.enabled) return;
      if (output) { pending = {kind: 'result', node: node.id, port: 'result'}; highlight(); say(`Selected ${node.id}.result. Choose a highlighted input, or press Escape to cancel.`); return; }
      if (!pending) { say('Select a result output socket first. External bindings remain available in the inspector.'); return; }
      const selected = choice(node.id, argument)?.choices.find(value => same(value.source, pending));
      if (!selected) { say('Connection refused: the server does not offer this source for this input.'); return; }
      cancel(); actions.bind(node.id, argument, selected.source);
    });
    return button;
  }
  function render(container, value, callbacks) {
    const focus = container.contains(document.activeElement) ? document.activeElement.id : null;
    host = container; projection = value; actions = callbacks; cancel(false); host.replaceChildren();
    const message = element('p', 'Select a capability to inspect it. Choose an output, then a highlighted input to rebind.', host, 'circuit-message');
    message.setAttribute('role', 'status');
    const viewport = element('div', '', host, 'circuit-viewport'), world = element('div', '', viewport, 'circuit-world');
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('aria-hidden', 'true'); world.append(svg);
    if (!value.document) return;
    const saved = new Map(value.document.positions.map(p => [p.node, p]));
    const cards = [];
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
        if (projection !== value || !projection.enabled || !event.altKey || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
        event.preventDefault(); const position = card._position;
        actions.move(node.id, position.x + (event.key === 'ArrowLeft' ? -20 : event.key === 'ArrowRight' ? 20 : 0), position.y + (event.key === 'ArrowUp' ? -20 : event.key === 'ArrowDown' ? 20 : 0));
      });
      heading.addEventListener('pointerdown', event => {
        if (projection !== value || !projection.enabled || event.button !== 0 || drag) return;
        heading.setPointerCapture(event.pointerId);
        drag = {pointerId: event.pointerId, node: node.id, card, startX: event.clientX, startY: event.clientY, position: {...card._position}, left: card.offsetLeft, top: card.offsetTop};
      });
      heading.addEventListener('pointermove', event => {
        if (projection !== value || !drag || drag.node !== node.id || drag.pointerId !== event.pointerId) return;
        card.style.left = drag.left + event.clientX - drag.startX + 'px'; card.style.top = drag.top + event.clientY - drag.startY + 'px'; draw();
      });
      heading.addEventListener('pointerup', event => {
        if (projection !== value || !drag || drag.node !== node.id || drag.pointerId !== event.pointerId) return;
        const gesture = drag; drag = null;
        const dx = event.clientX - gesture.startX, dy = event.clientY - gesture.startY;
        if (projection.enabled && Math.abs(dx) + Math.abs(dy) > 3) actions.move(node.id, Math.round(gesture.position.x + dx), Math.round(gesture.position.y + dy));
        else { gesture.card.style.left = gesture.left + 'px'; gesture.card.style.top = gesture.top + 'px'; draw(); }
      });
      heading.addEventListener('pointercancel', event => {
        if (projection === value && drag?.node === node.id && drag.pointerId === event.pointerId) { cancel(); say('Node move cancelled.'); }
      });
      const mapping = element('details', '', card, 'circuit-mapping');
      element('summary', 'Mapping details', mapping);
      const mappingList = element('dl', '', mapping, 'circuit-mapping-list');
      element('dt', 'Capability ID', mappingList); element('dd', node.capability, mappingList);
      element('dt', 'Instance ID', mappingList); element('dd', node.id, mappingList);
      if (node.request.kind === 'protocol') { element('dt', 'Protocol', mappingList); element('dd', node.request.protocol, mappingList); }
      for (const option of value.options.filter(item => item.node === node.id)) {
        const input = port(card, node, option.argument, false); input.id = `circuit-input-${node.id}-${option.argument || 'request'}`;
        const source = option.argument === null ? {kind: 'external', binding: node.request.binding} : node.request.arguments.find(item => item.name === option.argument).source;
        element('dt', option.argument || 'Request', mappingList);
        element('dd', source.kind === 'external' ? `external:${source.binding}` : `${source.node}.${source.port}`, mappingList);
      }
      const output = port(card, node, null, true); output.id = `circuit-output-${node.id}`;
      cards.push(card);
    }
    const maxHeight = Math.max(0, ...cards.map(card => card.offsetHeight)) + 90;
    const arranged = geometry.arrange(value.document.definition.nodes, maxHeight);
    for (const card of cards) { const position = saved.get(card.dataset.node) || arranged.get(card.dataset.node); card._position = {x: position.x, y: position.y}; }
    const ox = 60 - Math.min(0, ...cards.map(card => card._position.x)), oy = 60 - Math.min(0, ...cards.map(card => card._position.y));
    for (const card of cards) { card.style.left = card._position.x + ox + 'px'; card.style.top = card._position.y + oy + 'px'; }
    world.style.width = Math.max(700, ...cards.map(card => card.offsetLeft + card.offsetWidth + 80)) + 'px';
    world.style.height = Math.max(300, ...cards.map(card => card.offsetTop + card.offsetHeight + 80)) + 'px';
    setEnabled(value.enabled); draw();
    if (focus) document.getElementById(focus)?.focus({preventScroll: true});
  }
  function setEnabled(enabled) {
    if (!projection || !host) return;
    projection.enabled = enabled;
    for (const port of host.querySelectorAll('.circuit-port')) port.disabled = !enabled;
    for (const heading of host.querySelectorAll('.editor-node')) heading.setAttribute('aria-disabled', String(!enabled));
    if (!enabled) cancel();
  }
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && (pending || drag)) { cancel(); say('Circuit gesture cancelled.'); } });
  document.addEventListener('contextmenu', event => { if (pending && host?.contains(event.target)) { event.preventDefault(); cancel(); say('Connection selection cancelled.'); } });
  document.addEventListener('pointermove', event => {
    if (!pending || !host?.contains(event.target)) return;
    const output = host.querySelector(`#circuit-output-${CSS.escape(pending.node)}`), svg = host.querySelector('svg');
    const origin = host.querySelector('.circuit-world').getBoundingClientRect();
    const start = point(output), end = {x: event.clientX - origin.left, y: event.clientY - origin.top};
    svg.querySelector('.circuit-pending')?.remove();
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.classList.add('circuit-pending');
    path.setAttribute('d', geometry.path([start, {x: (start.x + end.x) / 2, y: start.y}, {x: (start.x + end.x) / 2, y: end.y}, end])); svg.append(path);
  });
  new ResizeObserver(() => { if (projection?.document) draw(); }).observe(document.body);
  window.editorCircuit = Object.freeze({render, setEnabled});
})();
