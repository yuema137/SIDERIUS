/* "Check the loop" walk-through (operator UX decision 2026-10-28), presentation only.
 *
 * On demand a token travels the drawn wires in execution order (sources first), then the
 * research loop's feedback wire. At the first break it stops: that socket gets a soft red
 * halo (CSS .walk-break, never larger than the card) and a short anchored explanation. With
 * prefers-reduced-motion the token never moves; the halo and explanation show at once.
 *
 * The walk reads only what the canvas already shows: the server port inventory (bound,
 * required, framework_supplied, source) and the declared loop. It derives no compatibility
 * or validity of its own; the problems list and Save stay the authority.
 *
 * API: window.editorCircuitWalk.plan(document, inventory) -> {steps, failure}
 *      window.editorCircuitWalk.run(host, plan, labels) -> Promise<'complete' | 'break' | 'stopped'>
 *      window.editorCircuitWalk.stop()
 * The viewport carries data-walk-state = running | complete | break while a result shows. */
(() => {
  'use strict';
  const SPEED = 700, MIN_MS = 220, MAX_MS = 900; // px/s and per-wire bounds
  let active = null;

  // Execution order: a node after every node whose result it reads; ties keep canvas order.
  function order(nodes) {
    const ids = nodes.map(node => node.id), placed = [], remaining = new Set(ids);
    const parents = node => node.request?.kind === 'protocol'
      ? node.request.arguments.filter(item => item.source?.kind === 'result').map(item => item.source.node) : [];
    while (remaining.size) {
      const ready = nodes.filter(node => remaining.has(node.id) && parents(node).every(id => !remaining.has(id)));
      const next = ready.length ? ready : [nodes.find(node => remaining.has(node.id))];
      for (const node of next) { placed.push(node); remaining.delete(node.id); }
    }
    return placed;
  }
  /** Steps the token takes and the first break (null when every connection holds). */
  function plan(document, inventory) {
    const nodes = document?.definition.nodes || [], steps = [];
    if (!nodes.length) return {steps, failure: {kind: 'empty'}};
    const present = new Set(nodes.map(node => node.id));
    for (const node of order(nodes)) {
      for (const option of inventory.filter(item => item.node === node.id && !item.framework_supplied)) {
        if (option.source?.kind === 'result' && present.has(option.source.node)) steps.push({kind: 'wire', from: option.source.node, to: node.id, argument: option.argument});
        else if (option.required && !option.bound) return {steps, failure: {kind: 'socket', node: node.id, argument: option.argument, option}};
      }
    }
    const loop = document.definition.loop;
    if (loop) {
      const {source, target} = loop.feedback;
      if (!present.has(source.node) || !present.has(target)) return {steps, failure: {kind: 'loop', node: present.has(source.node) ? source.node : null}};
      steps.push({kind: 'feedback', from: source.node, to: target});
    }
    return {steps, failure: null};
  }
  const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const cssId = value => CSS.escape(String(value));
  function pathOf(host, step) {
    if (step.kind === 'feedback') return host.querySelector('.circuit-feedback');
    return host.querySelector(`.circuit-wire[data-from="${cssId(step.from)}"][data-to="${cssId(step.to)}"][data-argument="${cssId(step.argument ?? '')}"]`);
  }
  // One wire: the token (an HTML dot in the world, so wire redraws never remove it) follows
  // the drawn path; a redraw replaces the path, so it is looked up again when detached.
  // Resolves false when the walk was stopped.
  function travel(host, step, token, ticket) {
    let path = pathOf(host, step);
    if (!path) return Promise.resolve(true);
    const length = path.getTotalLength(), duration = Math.min(MAX_MS, Math.max(MIN_MS, length / SPEED * 1000));
    return new Promise(done => {
      const started = performance.now();
      const frame = now => {
        if (active !== ticket) { done(false); return; }
        if (!path.isConnected) path = pathOf(host, step);
        if (!path) { done(true); return; }
        const t = Math.min(1, (now - started) / duration), eased = t < .5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
        const point = path.getPointAtLength(eased * path.getTotalLength());
        token.style.left = point.x + 'px'; token.style.top = point.y + 'px';
        if (t < 1) requestAnimationFrame(frame); else done(true);
      };
      requestAnimationFrame(frame);
    });
  }
  // The break: halo on the socket (or the loop's output socket), and one anchored sentence.
  function showBreak(host, failure, labels) {
    const world = host.querySelector('.circuit-world');
    let port = null, text;
    if (failure.kind === 'socket') {
      port = host.querySelector(`#${cssId(`circuit-input-${failure.node}-${failure.argument || 'request'}`)}`);
      text = `${labels.module(failure.node)} can't start: ${labels.connector(failure.option)} is not connected.`;
    } else if (failure.kind === 'loop') {
      port = failure.node ? host.querySelector(`#${cssId(`circuit-output-${failure.node}`)}`) : null;
      text = 'The research loop feeds back to a deleted module. Undo the delete, or remove the loop.';
    } else text = 'Add at least one module, then check again.';
    if (port) {
      port.classList.add('walk-break');
      port.closest('details.circuit-optional')?.setAttribute('open', '');
      port.scrollIntoView({block: 'nearest', inline: 'nearest'});
      const card = port.closest('.circuit-card');
      const note = document.createElement('p');
      note.className = 'circuit-walk-note'; note.id = 'circuit-walk-note'; note.textContent = text; note.setAttribute('role', 'status');
      note.style.left = card.offsetLeft + 'px'; note.style.top = card.offsetTop + card.offsetHeight + 8 + 'px'; note.style.width = card.offsetWidth + 'px';
      world.append(note);
      port.setAttribute('aria-describedby', note.id);
    }
    return text;
  }
  function stop() {
    if (!active) return;
    const {host} = active; active = null;
    host.querySelector('.circuit-walk-token')?.remove();
    for (const port of host.querySelectorAll('.walk-break')) { port.classList.remove('walk-break'); port.removeAttribute('aria-describedby'); }
    host.querySelector('.circuit-walk-note')?.remove();
    delete host.querySelector('.circuit-viewport')?.dataset.walkState;
  }
  /** labels: {module(nodeId), connector(option), say(text)}. */
  async function run(host, value, labels) {
    stop();
    const ticket = {host}; active = ticket;
    const viewport = host.querySelector('.circuit-viewport');
    viewport.dataset.walkState = 'running';
    if (!reduced() && value.steps.length) {
      labels.say('Checking the loop: following every connection in order…');
      const token = document.createElement('span');
      token.className = 'circuit-walk-token'; token.setAttribute('aria-hidden', 'true');
      host.querySelector('.circuit-world').append(token);
      for (const step of value.steps) if (!(await travel(host, step, token, ticket))) return 'stopped';
      token.remove();
    }
    if (active !== ticket) return 'stopped';
    if (value.failure) { viewport.dataset.walkState = 'break'; labels.say(showBreak(host, value.failure, labels)); return 'break'; }
    viewport.dataset.walkState = 'complete';
    labels.say(value.steps.some(step => step.kind === 'feedback') ? 'The loop is complete: every required input is connected and the feedback returns.' : 'Every required input is connected.');
    return 'complete';
  }
  window.editorCircuitWalk = Object.freeze({plan, run, stop, order});
})();
