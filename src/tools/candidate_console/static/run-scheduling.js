/* Optional host resources and parallel nodes for one run (B3-4c). Nothing is prefilled
 * or guessed: an empty panel reads as "run as before". The values are sent with the
 * review, which binds them into the reviewed digest; the launch carries the reviewed
 * selection only, so a later edit here needs a new review. */
(() => {
  'use strict';
  const $ = id => document.getElementById('scheduling-' + id);
  const KINDS = [
    ['proposal', 'Proposal'], ['implementation', 'Implementation'], ['validation', 'Validation'],
    ['literature', 'Literature review'], ['interpretation', 'Interpretation'], ['tuning', 'Training (tuning)'],
  ];
  const listeners = [];
  function cell(child) { const td = document.createElement('td'); td.append(child); return td; }
  function input(kind, field, type, label) {
    const el = document.createElement('input');
    el.type = type; el.id = `scheduling-${kind}-${field}`; el.setAttribute('aria-label', label);
    if (type === 'number') { el.min = field === 'cpus' ? '1' : '0'; el.step = field === 'cpus' ? '1' : 'any'; }
    return el;
  }
  function build() {
    const body = $('parallel').querySelector('tbody');
    body.replaceChildren(...KINDS.map(([kind, label]) => {
      const row = document.createElement('tr'); row.dataset.kind = kind;
      const name = document.createElement('th'); name.scope = 'row'; name.textContent = label;
      row.append(name,
        cell(input(kind, 'on', 'checkbox', `${label}: run in parallel`)),
        cell(input(kind, 'gpu', 'checkbox', `${label}: uses a GPU`)),
        cell(input(kind, 'vram', 'number', `${label}: GPU memory in GiB`)),
        cell(input(kind, 'memory', 'number', `${label}: host memory in GiB`)),
        cell(input(kind, 'cpus', 'number', `${label}: CPU slots`)));
      return row;
    }));
  }
  const number = el => (el.value.trim() === '' ? null : Number(el.value));
  const positive = value => value !== null && Number.isFinite(value) && value > 0;
  const whole = value => positive(value) && Number.isInteger(value);
  function readResources() {
    if (!$('declare').checked) return {value: null};
    const gpu = $('gpu').value, vram = number($('vram')), memory = number($('memory')), cpus = number($('cpus'));
    if (gpu === '') return {error: 'Choose whether the run uses a GPU.'};
    if (!positive(memory)) return {error: 'Enter the run\'s host memory in GiB.'};
    if (!whole(cpus)) return {error: 'Enter the run\'s CPU slots as a whole number.'};
    const value = {gpu_count: Number(gpu), host_memory_gib: memory, cpu_slots: cpus, time_budgeted: $('timed').checked};
    if (gpu === '1') {
      if (!positive(vram)) return {error: 'Enter the run\'s GPU memory in GiB.'};
      Object.assign(value, {vram_gib: vram, vram_source: 'configured_cap'});
    } else if (vram !== null) return {error: 'GPU memory applies only to a run that uses a GPU.'};
    return {value};
  }
  function readParallel() {
    const capabilities = {};
    for (const [kind, label] of KINDS) {
      const field = name => document.getElementById(`scheduling-${kind}-${name}`);
      if (!field('on').checked) continue;
      const gpu = field('gpu').checked, vram = number(field('vram')), memory = number(field('memory')), cpus = number(field('cpus'));
      if (!positive(memory)) return {error: `${label}: enter host memory in GiB.`};
      if (!whole(cpus)) return {error: `${label}: enter CPU slots as a whole number.`};
      if (gpu && !positive(vram)) return {error: `${label}: enter GPU memory in GiB.`};
      if (!gpu && vram !== null) return {error: `${label}: GPU memory applies only to a node kind that uses a GPU.`};
      capabilities[kind] = gpu ? {gpu, vram_gib: vram, host_memory_gib: memory, cpu_slots: cpus}
        : {gpu, host_memory_gib: memory, cpu_slots: cpus};
    }
    return {value: Object.keys(capabilities).length ? {capabilities} : null};
  }
  // Shown only when the console shares a host ledger: without one, the backend has no
  // budget to reserve or schedule against and refuses these fields at review.
  const available = () => window.consoleSession?.hostLedger === true;
  function reflect() {
    document.getElementById('scheduling').hidden = !available();
    $('unavailable').hidden = available();
  }
  /** The fields to add to a review selection, or an error to show instead of reviewing. */
  function read() {
    if (!available()) return {value: {}};
    const resources = readResources(); if (resources.error) return resources;
    const parallel = readParallel(); if (parallel.error) return parallel;
    const value = {};
    if (resources.value) value.resources = resources.value;
    if (parallel.value) value.parallel = parallel.value;
    return {value};
  }
  /** One plain line for the reviewed values a review echoed back. */
  function describe(selection) {
    const parts = [];
    const resources = selection?.resources;
    if (resources) {
      const gpu = resources.gpu_count ? `one GPU with ${resources.vram_gib} GiB` : 'no GPU';
      parts.push(`Reserves ${gpu}, ${resources.host_memory_gib} GiB host memory and ${resources.cpu_slots} CPU slot${resources.cpu_slots === 1 ? '' : 's'}${resources.time_budgeted ? '; uses a training time budget' : ''}.`);
    }
    const kinds = Object.keys(selection?.parallel?.capabilities || {});
    if (kinds.length) parts.push(`Runs these node kinds in parallel: ${kinds.join(', ')}.`);
    return parts.length ? parts.join(' ') : 'Runs one node at a time, without a host reservation.';
  }
  function show(problem) { $('problem').textContent = problem || ''; }
  function changed(callback) { listeners.push(callback); }
  document.addEventListener('DOMContentLoaded', () => {
    build(); reflect();
    document.getElementById('scheduling').addEventListener('input', () => { show(''); listeners.forEach(callback => callback()); });
    window.addEventListener('console-host-ledger', () => { reflect(); listeners.forEach(callback => callback()); });
  });
  window.runScheduling = Object.freeze({read, describe, show, changed});
})();
