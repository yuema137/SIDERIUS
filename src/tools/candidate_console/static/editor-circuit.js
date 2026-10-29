/* Presentation and ephemeral gestures only; editor.js owns every document mutation. */
(() => {
  'use strict';
  let projection = null, actions = null, host = null, pending = null, drag = null, selectedWire = null, connecting = false
  // A mouse press never focuses a card (pointerdown preventDefault), and selecting re-renders:
  // the clicked heading is focused after that render so Delete and Alt+arrows act on it.
  let refocus = null;
  // View-only state (zoom, scroll, expanded optional inputs). It is
  // kept per opened graph and never reaches a document, so viewing never changes source.
  let view = {key: null, scale: 1, fitPending: false, scroll: null, expanded: new Set(), adapters: new Set()};
  const CARD_GAP = {x: 135, y: 90};
  // Fit to view never goes below this zoom (text stays >= ~9px at the 12px label size); larger
  // graphs scroll inside the viewport. Manual zoom out still reaches 40%.
  const FIT_MIN = 0.75;
  // Empty space kept around the cards when Fit frames the graph (document pixels).
  const FIT_PAD = 40;
  const geometry = window.editorCircuitGeometry;
  const presentation = window.editorCapabilityPresentation;
  const contracts = window.editorContractPresentation;
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const element = (tag, text, parent, className) => {
    const value = document.createElement(tag); value.textContent = text;
    if (className) value.className = className;
    parent.append(value); return value;
  };
  const wireLayer = () => host.querySelector('.circuit-world > svg');
  // While a canvas gesture runs, nothing on the page is text-selectable (user-select: none).
  const gesture = on => { document.body.classList.toggle('circuit-gesture', on); if (!on) getSelection()?.removeAllRanges(); };
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
  const refusal = (source, node, argument) => contracts.refusal(capabilityOf(source.node),
    projection.inventory.find(value => value.node === source.node)?.node_output_contract.id,
    'this input', choice(node, argument)?.socket_contract.id);
  // A refused drop is explained where it happened (tour #7, spec K10): one sentence under the
  // input; it goes away with the next gesture or render.
  function anchorNote(port, text) {
    host.querySelector('.circuit-anchor-note')?.remove();
    const card = port.closest('.circuit-card'), note = element('p', text, host.querySelector('.circuit-world'), 'circuit-walk-note circuit-anchor-note');
    note.setAttribute('role', 'status');
    note.style.left = card.offsetLeft + 'px'; note.style.width = card.offsetWidth + 'px';
    note.style.top = card.offsetTop + port.offsetTop + port.offsetHeight + 4 + 'px';
  }
  // `source` is the pending output, or a hovered output for a preview without selecting it.
  function highlight(source = pending) {
    if (!host) return;
    for (const input of host.querySelectorAll('[data-input]')) {
      const option = choice(input.dataset.node, input.dataset.argument || null);
      const compatible = source && option?.choices.some(value => same(value.source, source));
      input.classList.toggle('compatible', !!compatible);
      input.classList.toggle('incompatible', !!source && !compatible);
      if (source && !compatible) input.dataset.refusal = refusal(source, input.dataset.node, option?.argument); else delete input.dataset.refusal;
    }
    for (const output of host.querySelectorAll('[data-output]')) output.setAttribute('aria-pressed', String(output.dataset.node === pending?.node));
    for (const group of host.querySelectorAll('.circuit-optional')) {
      const compatible = [...group.querySelectorAll('[data-input]')].filter(input => input.classList.contains('compatible')).length;
      const summary = group.querySelector('summary');
      summary.classList.toggle('compatible', compatible > 0);
      summary.dataset.compatible = String(compatible);
    }
    const disconnect = host.querySelector('.circuit-disconnect');
    if (disconnect) { disconnect.hidden = !selectedWire; disconnect.disabled = !projection.enabled || projection.allowBindingChange === false; }
    for (const target of host.querySelectorAll('.circuit-wire-target')) {
      const selected = same(selectedWire, wireKey(target));
      target.setAttribute('aria-pressed', String(selected));
      [...host.querySelectorAll('.circuit-wire')].find(path => same(wireKey(path), wireKey(target)))?.classList.toggle('selected', selected);
    }
  }
  // Wires are read aloud in plain words ("Propose model sends Model plan to Implement") and
  // join the Tab order only with advanced tools on (E-7); beginners select one with the mouse.
  const wireLabel = (from, to, contract) => `${capabilityOf(from)} sends ${contract ? contracts.describe(contract).name : 'its result'} to ${capabilityOf(to)}`;
  const wireTabIndex = enabled => enabled && window.uiSettings?.isEnabled('advanced') ? '0' : '-1';
  const wireKey = target => ({from: target.dataset.from, to: target.dataset.to, argument: target.dataset.argument || null});
  function selectWire(target) {
    if (!projection?.enabled) return;
    selectedWire = wireKey(target);
    target.focus({preventScroll: true}); highlight();
    say(`Selected: ${target.getAttribute('aria-label')}. Disconnect it with the button or Delete.`);
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
    note.textContent = outside.length
      ? `${outside.length} of ${cards.length} modules are partly outside the view. Scroll the canvas or use Fit to view.`
      : `All ${cards.length} modules are in view.`;
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
  // Fit the whole graph into the canvas: the union of every card's box plus FIT_PAD on each side,
  // scrolled to that box's origin (view only; never below the legibility floor FIT_MIN).
  function fit() {
    const viewport = host?.querySelector('.circuit-viewport');
    if (!viewport || !viewport.clientWidth || !projection?.document) return;
    view.fitPending = false;
    sizeWorld();
    const boxes = [...host.querySelectorAll('.circuit-world .circuit-card')].map(card => cardBox(card));
    const union = boxes.length ? {
      left: Math.min(...boxes.map(box => box.left)) - FIT_PAD, top: Math.min(...boxes.map(box => box.top)) - FIT_PAD,
      right: Math.max(...boxes.map(box => box.right)) + FIT_PAD, bottom: Math.max(...boxes.map(box => box.bottom)) + FIT_PAD,
    } : {left: 0, top: 0, right: 0, bottom: 0};
    const origin = {x: Math.max(0, union.left), y: Math.max(0, union.top)};
    const content = {width: union.right - origin.x, height: union.bottom - origin.y};
    const max = parseFloat(getComputedStyle(viewport).maxHeight);
    const available = {width: viewport.clientWidth - 2, height: (Number.isFinite(max) ? max : viewport.clientHeight) - 2};
    const scale = geometry.fitScale(content, available, FIT_MIN);
    applyScale(scale);
    viewport.scrollLeft = origin.x * scale; viewport.scrollTop = origin.y * scale; updateVisibility();
  }
  function draw() {
    if (!host) return;
    // The wire layer is the world's own <svg>; toolbar buttons also hold (icon) svgs.
    const svg = wireLayer(); svg.replaceChildren();
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
      if (!route) { say('Some wires could not be drawn around overlapping cards. Tidy up, or move the cards apart.'); continue; }
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', geometry.path(route)); path.classList.add('circuit-wire');
      if (output.dataset.contract) contracts.decorate(path, output.dataset.contract);
      path.dataset.from = source.node; path.dataset.to = input.dataset.node; path.dataset.argument = option.argument;
      svg.append(path);
      const target = document.createElementNS(svg.namespaceURI, 'path');
      target.setAttribute('d', geometry.path(route)); target.classList.add('circuit-wire-target');
      target.dataset.from = source.node; target.dataset.to = input.dataset.node; target.dataset.argument = option.argument;
      target.setAttribute('tabindex', wireTabIndex(projection.enabled)); target.setAttribute('role', 'button'); target.setAttribute('aria-pressed', 'false');
      target.setAttribute('aria-label', wireLabel(source.node, input.dataset.node, option.socket_contract));
      target.addEventListener('focus', () => path.classList.add('focused'));
      target.addEventListener('blur', () => path.classList.remove('focused'));
      target.addEventListener('click', event => { event.stopPropagation(); selectWire(target); });
      target.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); selectWire(target); }
        else if (['Delete', 'Backspace'].includes(event.key) && same(selectedWire, wireKey(target))) { event.preventDefault(); event.stopPropagation(); disconnectSelectedWire(); }
      });
      svg.append(target);
    }
    drawFeedback(svg, world);
    highlight(); updateVisibility();
  }
  // The research loop's feedback wire (tour #18): dashed, from the feedback module's output
  // over the top of the cards back to the target module. Display only; the loop panel edits it.
  function drawFeedback(svg, world) {
    const loop = projection?.document?.definition.loop;
    const output = loop && world.querySelector(`#circuit-output-${CSS.escape(loop.feedback.source.node)}`);
    const target = loop && world.querySelector(`.circuit-card[data-node="${CSS.escape(loop.feedback.target)}"] > .editor-node`);
    if (!output || !target) return;
    const start = point(output), box = target.getBoundingClientRect(), end = toWorld(box.left, box.top + box.height / 2);
    const top = Math.max(8, Math.min(...[...world.querySelectorAll('.circuit-card')].map(card => card.offsetTop)) - 28);
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', geometry.path([start, {x: start.x + 20, y: start.y}, {x: start.x + 20, y: top}, {x: end.x - 20, y: top}, {x: end.x - 20, y: end.y}, end]));
    path.classList.add('circuit-feedback'); path.dataset.from = loop.feedback.source.node; path.dataset.to = loop.feedback.target;
    path.setAttribute('aria-label', `Research loop: ${capabilityOf(loop.feedback.source.node)} feeds back to ${capabilityOf(loop.feedback.target)}`);
    svg.prepend(path);
  }
  // "Check the workflow": the token walk (editor-circuit-walk.js) over what this canvas shows.
  function checkLoop() {
    if (!projection?.document || !host) return;
    const walk = window.editorCircuitWalk, value = walk.plan(projection.document, projection.inventory);
    void walk.run(host, value, {say, module: capabilityOf,
      connector: option => contracts.describe(option.socket_contract).name});
  }
  // "Connects with" for the socket tooltip: capability names of the server-offered sources
  // (an input) or of the inputs that offer this result (an output). Server data only.
  const capabilityOf = id => presentation.label(projection.document?.definition.nodes.find(item => item.id === id)?.capability);
  function connectsWith(nodeId, metadata) {
    const names = metadata
      ? metadata.choices.map(choice => choice.source.kind === 'result' ? capabilityOf(choice.source.node) : 'an external input')
      : projection.inventory.filter(item => item.choices.some(choice => choice.source.kind === 'result' && choice.source.node === nodeId)).map(item => capabilityOf(item.node));
    return [...new Set(names)].join(', ');
  }
  function port(parent, node, argument, output, metadata = null) {
    const snapshot = projection;
    // The visible label is the connector (schema) name; field names live in the advanced Mapping details.
    const button = element('button', '', parent, `circuit-port ${output ? 'circuit-output' : 'circuit-input'}`);
    button.type = 'button'; button.dataset.node = node.id; button.dataset.tip = 'port';
    const contract = metadata ? metadata.socket_contract : projection.inventory.find(value => value.node === node.id)?.node_output_contract;
    button.dataset.tipConnects = connectsWith(node.id, metadata);
    if (contract) {
      element('span', contracts.describe(contract).name, button, 'circuit-port-contract').setAttribute('aria-hidden', 'true');
      button.dataset.contract = contract.id;
      contracts.decorate(button, contract, metadata ? metadata.required : true);
    }
    if (metadata) {
      const state = metadata.bound ? (metadata.required ? 'Required' : 'Optional') : `${metadata.required ? 'Required' : 'Optional'} · Not connected`;
      element('span', state, button, `circuit-port-requirement${metadata.bound ? '' : ' circuit-port-unbound-label'}`);
      button.setAttribute('aria-label', `${state.replace(' · ', ', ')}.`);
      button.classList.toggle('is-unbound', !metadata.bound);
      button.dataset.required = String(metadata.required);
    } else button.setAttribute('aria-label', 'Output.');
    if (output) { button.dataset.output = ''; button.setAttribute('aria-pressed', 'false'); }
    else { button.dataset.input = ''; button.dataset.argument = argument || ''; }
    if (button.dataset.contract) contracts.direction(button, button.dataset.contract, output);
    element('span', '', button, 'circuit-socket');
    button.addEventListener('click', () => {
      if (projection !== snapshot || !projection.enabled) return;
      if (!projection.allowBindingChange) { say('Review/save or discard the current edits before changing a connection.'); return; }
      if (output) { host.querySelector('.circuit-anchor-note')?.remove(); pending = {kind: 'result', node: node.id, port: 'result'}; highlight(); say(`Selected the output of ${capabilityOf(node.id)}. Choose a highlighted input, or press Escape to cancel.`); return; }
      if (!pending) { say('Choose an output first (the socket on the right side of a module).'); return; }
      const selected = choice(node.id, argument)?.choices.find(value => same(value.source, pending));
      if (!selected) { const reason = refusal(pending, node.id, argument); say(reason); anchorNote(button, reason); return; }
      cancel(); actions.bind(node.id, argument, selected.source);
    });
    if (output) {
      // Hover previews compatible inputs; pressing starts a drag that drops on an input.
      const preview = {kind: 'result', node: node.id, port: 'result'};
      button.addEventListener('pointerenter', () => { if (!pending && projection === snapshot && projection.enabled) highlight(preview); });
      button.addEventListener('pointerleave', () => { if (!pending && projection === snapshot) highlight(); });
      // preventDefault: a wire drag never starts a text selection (which would turn into a
      // native drag of the selection and cancel the pointer gesture).
      button.addEventListener('pointerdown', event => { if (event.button === 0) { event.preventDefault(); gesture(true); connecting = true; button.click(); } });
    }
    return button;
  }
  const button = (parent, text, id, onClick, icon = null) => {
    // Canvas controls are secondary (tour #15): Save stays the page's one primary action.
    const value = element('button', text, parent, 'circuit-view-button secondary'); value.type = 'button'; value.id = id;
    if (icon && window.consoleIcons) value.prepend(window.consoleIcons.make(icon));
    value.addEventListener('click', onClick); return value;
  };
  // Icon-only canvas control (canvas-study V2): the name is the accessible label and a
  // visually hidden text; the shared tooltip shows it on hover/focus.
  const iconButton = (parent, label, id, onClick, icon) => {
    const value = button(parent, '', id, onClick, icon);
    value.classList.add('icon-button'); value.setAttribute('aria-label', label); value.dataset.tipLabel = label;
    element('span', label, value, 'sr-only'); return value;
  };
  // Pipeline position of a module (Literature/Interpret -> Propose -> Implement -> Validate -> Train & tune).
  const STAGES = ['literature', 'interpretation', 'proposal', 'implementation', 'validation', 'tuning'];
  const stageOf = id => { const index = STAGES.indexOf(projection.document.definition.nodes.find(node => node.id === id)?.capability); return index < 0 ? STAGES.length : index; };
  // Tidy up (the one layout tool, red-team A-1): one undoable layout edit (editor.js move) on
  // the 16px grid; the view refits.
  function tidyUp() {
    if (!projection?.document || !projection.enabled || projection.allowMove === false) return;
    const cards = [...host.querySelectorAll('.circuit-card')];
    const size = {width: Math.max(0, ...cards.map(card => card.offsetWidth)), height: Math.max(0, ...cards.map(card => card.offsetHeight))};
    const placed = geometry.tidy(projection.document.definition.nodes, size, undefined, undefined, stageOf);
    view.fitPending = true; view.scroll = null;
    actions.move([...placed].map(([node, position]) => ({node, ...position})), 'Tidy up layout');
  }
  function toolbar(parent, value) {
    const bar = element('div', '', parent, 'circuit-toolbar');
    bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', 'Canvas view');
    iconButton(bar, 'Zoom out', 'circuit-zoom-out', () => applyScale(Math.max(0.4, Math.round((view.scale - 0.1) * 10) / 10)), 'zoom-out');
    const zoom = element('span', `${Math.round(view.scale * 100)} %`, bar, 'circuit-zoom'); zoom.setAttribute('aria-label', 'Canvas zoom');
    iconButton(bar, 'Zoom in', 'circuit-zoom-in', () => applyScale(Math.min(1, Math.round((view.scale + 0.1) * 10) / 10)), 'zoom-in');
    iconButton(bar, 'Actual size', 'circuit-zoom-reset', () => applyScale(1), 'maximize');
    iconButton(bar, 'Fit to view', 'circuit-fit', fit, 'scan');
    const check = iconButton(bar, 'Check the workflow', 'circuit-check', checkLoop, 'repeat-2');
    check.disabled = !value.document;
    const tidy = iconButton(bar, 'Tidy up', 'circuit-tidy', tidyUp, 'layout-grid');
    tidy.disabled = !value.document || !value.enabled || value.allowMove === false;
    const note = element('p', '', parent, 'circuit-view-note'); note.setAttribute('aria-live', 'polite');
  }
  function render(container, value, callbacks) {
    const focus = refocus || (container.contains(document.activeElement) ? document.activeElement.id : null); refocus = null;
    const key = `${value.viewKey ?? ''}|${(value.document?.definition.nodes || []).map(node => node.id).join(',')}`;
    const previous = container.querySelector('.circuit-viewport');
    if (view.key !== key) view = {key, scale: 1, fitPending: true, scroll: null, expanded: new Set(), adapters: new Set()};
    else if (previous && !view.fitPending) view.scroll = {left: previous.scrollLeft, top: previous.scrollTop};
    window.editorCircuitWalk?.stop();
    host = container; projection = value; actions = callbacks; cancel(false); selectedWire = null; host.replaceChildren();
    const message = element('p', 'Select a module to see its inputs. Drag from an output to a highlighted input to connect them.', host, 'circuit-message');
    message.setAttribute('role', 'status');
    toolbar(host, value);
    if (value.document) contracts.legend(host, value.inventory);
    const disconnect = element('button', 'Disconnect selected connection', host, 'circuit-disconnect');
    disconnect.type = 'button'; disconnect.hidden = true; disconnect.addEventListener('click', disconnectSelectedWire);
    const viewport = element('div', '', host, 'circuit-viewport'), sizer = element('div', '', viewport, 'circuit-sizer');
    viewport.id = 'circuit-viewport'; viewport.tabIndex = -1; viewport.setAttribute('aria-label', 'Workflow canvas');
    const world = element('div', '', sizer, 'circuit-world');
    viewport.addEventListener('scroll', updateVisibility, {passive: true});
    viewObserver.disconnect(); viewObserver.observe(viewport);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('role', 'group'); svg.setAttribute('aria-label', 'Workflow connections'); world.append(svg);
    if (!value.document) return;
    const saved = new Map(value.document.positions.map(p => [p.node, p]));
    const cards = [];
    // A move persists every displayed position, so later sources never mix stored and fallback layouts.
    const layout = (moved, x, y) => cards.map(card => card.dataset.node === moved ? {node: moved, x, y} : {node: card.dataset.node, ...card._position});
    const move = positions => actions.move(positions);
    for (const node of value.document.definition.nodes) {
      const card = element('article', '', world, 'circuit-card'); card.dataset.node = node.id; card.dataset.capability = node.capability;
      const heading = element('button', '', card, 'editor-node');
      heading.type = 'button'; heading.dataset.node = node.id; heading.id = `circuit-node-${node.id}`;
      const capabilityLabel = presentation.append(heading, node.capability, node.id);
      heading.setAttribute('aria-label', `${capabilityLabel}, instance ${node.id}`);
      const role = [...heading.querySelector('.capability-heading').classList].find(name => name.startsWith('capability-') && name !== 'capability-heading');
      if (role) card.classList.add(role);
      heading.setAttribute('aria-pressed', String(node.id === value.selected));
      heading.addEventListener('click', () => {
        if (projection !== value || !projection.selectable) return;
        refocus = heading.id; actions.select(node.id);
        if (refocus) { refocus = null; heading.focus({preventScroll: true}); }
      });
      heading.addEventListener('contextmenu', event => { if (projection === value && projection.enabled && !pending && actions.menu) { actions.select(node.id); actions.menu(node.id, event); } });
      heading.addEventListener('keydown', event => {
        // Node removal is proposed by editor.js (Review shows the exact change before Save).
        if (projection === value && projection.enabled && ['Delete', 'Backspace'].includes(event.key) && actions.remove) { event.preventDefault(); actions.remove([node.id]); return; }
        if (projection !== value || !projection.enabled || projection.allowMove === false || !event.altKey || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
        event.preventDefault(); const position = card._position;
        move(layout(node.id, position.x + (event.key === 'ArrowLeft' ? -20 : event.key === 'ArrowRight' ? 20 : 0), position.y + (event.key === 'ArrowUp' ? -20 : event.key === 'ArrowDown' ? 20 : 0)));
      });
      heading.addEventListener('pointerdown', event => {
        if (projection !== value || !projection.enabled || projection.allowMove === false || event.button !== 0 || drag) return;
        event.preventDefault(); gesture(true); heading.setPointerCapture(event.pointerId);
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
        if (projection === value && drag?.node === node.id && drag.pointerId === event.pointerId) { cancel(); say('Move cancelled.'); }
      });
      // Server inventory marks required sockets; an unbound one flags the whole card.
      const missing = value.inventory.filter(item => item.node === node.id && item.required && !item.bound).length;
      card.classList.toggle('has-required-unbound', missing > 0);
      // §8.3 / operator rule: the socket itself carries the red light; the card only a small count.
      if (missing) {
        const badge = element('span', String(missing), card, 'circuit-problem-badge'); badge.dataset.node = node.id;
        badge.setAttribute('aria-label', `${missing} required input${missing === 1 ? '' : 's'} not connected`); badge.setAttribute('role', 'img');
      }
      // Advanced detail (ui-settings.js): hidden for beginners, so a flag change re-renders.
      const mapping = element('details', '', card, 'circuit-mapping'); mapping.dataset.uiFlag = 'advanced';
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
      // Required inputs and optional inputs fed by a wire always show; every other optional
      // input (not connected, or fed by an external input) folds into one "+N optional" row.
      const folded = options.filter(option => !option.required && option.source?.kind !== 'result' && !option.framework_supplied);
      let group = null;
      if (folded.length) {
        group = document.createElement('details'); group.className = 'circuit-optional'; group.dataset.node = node.id;
        const summary = element('summary', `+${folded.length} optional`, group);
        summary.id = `circuit-optional-${node.id}`;
        group.open = view.expanded.has(node.id);
        group.addEventListener('toggle', () => {
          if (group.open) view.expanded.add(node.id); else view.expanded.delete(node.id);
          if (projection === value) draw();
        });
      }
      for (const option of options) {
        // Framework-supplied inputs (managed storage, …) get no socket; Mapping details list them.
        if (!option.framework_supplied) {
          const input = port(folded.includes(option) ? group : card, node, option.argument, false, option); input.id = `circuit-input-${node.id}-${option.argument || 'request'}`;
        }
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
    const placed = geometry.place(value.document.definition.nodes, saved, size, CARD_GAP);
    for (const card of cards) card._position = placed.get(card.dataset.node);
    const ox = 60 - Math.min(0, ...cards.map(card => card._position.x)), oy = 60 - Math.min(0, ...cards.map(card => card._position.y));
    for (const card of cards) { card.style.left = card._position.x + ox + 'px'; card.style.top = card._position.y + oy + 'px'; }
    world.style.transform = view.scale === 1 ? '' : `scale(${view.scale})`;
    sizeWorld();
    setEnabled(value.enabled, value.selectable ?? value.enabled); draw();
    if (view.fitPending) fit();
    else if (view.scroll) { viewport.scrollLeft = view.scroll.left; viewport.scrollTop = view.scroll.top; }
    updateVisibility();
    const overlapping = geometry.overlaps(cards.map(card => cardBox(card)));
    if (overlapping.length) {
      const names = overlapping.map(([a, b]) => `${capabilityOf(cards[a].dataset.node)} and ${capabilityOf(cards[b].dataset.node)}`).join('; ');
      say(`Some cards overlap (${names}). Tidy up arranges them in columns; Undo puts them back.`);
    }
    if (focus) document.getElementById(focus)?.focus({preventScroll: true});
  }
  // Selecting a capability is navigation, not an edit: invalid inspector drafts block edits
  // (enabled) but must not trap the author on one node (selectable).
  function setEnabled(enabled, selectable = enabled) {
    if (!projection || !host) return;
    projection.enabled = enabled; projection.selectable = selectable;
    for (const port of host.querySelectorAll('.circuit-port')) port.disabled = !enabled;
    const disconnect = host.querySelector('.circuit-disconnect'); if (disconnect) disconnect.disabled = !enabled || projection.allowBindingChange === false;
    for (const target of host.querySelectorAll('.circuit-wire-target')) {
      target.setAttribute('aria-disabled', String(!enabled)); target.setAttribute('tabindex', wireTabIndex(enabled));
    }
    for (const heading of host.querySelectorAll('.editor-node')) heading.setAttribute('aria-disabled', String(!selectable));
    const tidy = host.querySelector('#circuit-tidy'); if (tidy) tidy.disabled = !enabled || !projection.document || projection.allowMove === false;
    if (!enabled) { cancel(); selectedWire = null; highlight(); }
  }
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (pending || drag) { cancel(); say('Cancelled.'); }
    if (selectedWire) { selectedWire = null; highlight(); say('Connection deselected.'); }
    host?.querySelector('.circuit-anchor-note')?.remove();
  });
  // Drag-to-connect: a press on an output released over an input clicks that input.
  document.addEventListener('pointerup', event => {
    if (document.body.classList.contains('circuit-gesture')) gesture(false);
    if (!connecting) return;
    connecting = false;
    if (!pending || !host) return;
    // The input whose own box holds the release point; a highlighted (compatible) one wins
    // over a neighbour whose label might reach into it at small zoom.
    const holding = [...host.querySelectorAll('[data-input]')].filter(element => {
      const box = element.getBoundingClientRect();
      return element.getClientRects().length && event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom;
    });
    const input = holding.find(element => element.classList.contains('compatible')) || holding[0] ||
      document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-input]');
    if (!input || !host.contains(input)) return;
    input.click();
    // The release ends the drag: the browser's own click that follows (on the common ancestor
    // of press and release) must not act on the canvas again.
    const swallow = click => { click.stopPropagation(); click.preventDefault(); };
    document.addEventListener('click', swallow, {capture: true, once: true});
    setTimeout(() => document.removeEventListener('click', swallow, {capture: true}), 0);
  });
  document.addEventListener('pointercancel', () => { if (document.body.classList.contains('circuit-gesture')) gesture(false); });
  document.addEventListener('contextmenu', event => { if (pending && host?.contains(event.target)) { event.preventDefault(); cancel(); say('Cancelled.'); } });
  document.addEventListener('pointermove', event => {
    if (!pending || !host?.contains(event.target)) return;
    const output = host.querySelector(`#circuit-output-${CSS.escape(pending.node)}`), svg = wireLayer();
    const start = point(output), end = toWorld(event.clientX, event.clientY);
    svg.querySelector('.circuit-pending')?.remove();
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.classList.add('circuit-pending');
    path.setAttribute('d', geometry.path([start, {x: (start.x + end.x) / 2, y: start.y}, {x: (start.x + end.x) / 2, y: end.y}, end])); svg.append(path);
  });
  new ResizeObserver(() => { if (projection?.document) draw(); }).observe(document.body);
  // Settings flags change card content (mapping details, chips): re-place the cards.
  window.addEventListener('ui-settings-change', () => { if (host && projection) render(host, projection, actions); });
  // A canvas rendered while hidden (zero width) fits once it is first laid out.
  const viewObserver = new ResizeObserver(() => {
    if (!projection?.document) return;
    if (view.fitPending) fit(); else updateVisibility();
  });
  // "Skip to canvas" (index.html): the selected module, else the first, else the canvas itself.
  function focusCanvas() {
    const target = host?.querySelector('.editor-node[aria-pressed="true"]') || host?.querySelector('.editor-node') || host?.querySelector('.circuit-viewport');
    target?.focus(); return !!target;
  }
  window.editorCircuit = Object.freeze({render, setEnabled, focusCanvas});
})();
