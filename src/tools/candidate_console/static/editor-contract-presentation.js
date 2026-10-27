/* Contract presentation for circuit ports: colour, shape and readable name keyed on
 * the server-sent contract id, plus the legend, refusal reason and protocol-mapping
 * ("adapter") chip. Presentation only: compatibility is always the server's
 * port_inventory choices; nothing here decides whether a connection is allowed. */
(() => {
  'use strict';
  // One row per catalog contract (a unit census binds this table to CONTRACTS and
  // requires every (colour, shape) pair to be distinct). Colours name CSS tokens
  // --contract-<colour> defined for both themes in editor-contract-presentation.css.
  const entries = Object.freeze({
    'interpretation.input': {name: 'Interpretation request', colour: 'interpretation', shape: 'circle'},
    'interpretation.output': {name: 'Interpretation result', colour: 'interpretation', shape: 'square'},
    'literature.input': {name: 'Literature request', colour: 'literature', shape: 'circle'},
    'literature.output': {name: 'Literature result', colour: 'literature', shape: 'square'},
    'proposal.input': {name: 'Proposal request', colour: 'proposal', shape: 'circle'},
    'proposal.output': {name: 'Proposal result', colour: 'proposal', shape: 'square'},
    'implementation.input': {name: 'Implementation request', colour: 'implementation', shape: 'circle'},
    'implementation.output': {name: 'Implementation result', colour: 'implementation', shape: 'square'},
    'validation.input': {name: 'Validation request', colour: 'validation', shape: 'circle'},
    'validation.output': {name: 'Validation result', colour: 'validation', shape: 'square'},
    'tuning.input': {name: 'Tuning request', colour: 'tuning', shape: 'circle'},
    'tuning.output': {name: 'Tuning result', colour: 'tuning', shape: 'square'},
    'native-training.settings': {name: 'Training settings', colour: 'tuning', shape: 'capsule'},
    'storage': {name: 'Storage', colour: 'neutral', shape: 'capsule'},
    'llm-provider': {name: 'LLM provider', colour: 'magenta', shape: 'capsule'},
    'optional.text': {name: 'Text (optional)', colour: 'neutral', shape: 'diamond'},
    'optional.model-id': {name: 'Model id (optional)', colour: 'magenta', shape: 'diamond'},
    'optional.expert-advice': {name: 'Expert advice (optional)', colour: 'tuning', shape: 'diamond'},
    'optional.expert-context': {name: 'Expert context (optional)', colour: 'proposal', shape: 'diamond'},
    'optional.parameter-rules': {name: 'Parameter rules (optional)', colour: 'green', shape: 'diamond'},
    'optional.constraint-context': {name: 'Constraint context (optional)', colour: 'implementation', shape: 'diamond'},
    'optional.task-composition-ref': {name: 'Task composition (optional)', colour: 'literature', shape: 'diamond'},
  });
  const palette = Object.freeze(['interpretation', 'literature', 'proposal', 'implementation', 'validation', 'tuning', 'neutral', 'magenta', 'green']);
  // An id outside the table (a newer server catalog) still gets a stable token.
  function fallback(id) {
    let hash = 0;
    for (const character of id) hash = (hash * 31 + character.codePointAt(0)) >>> 0;
    const words = id.replace(/^optional\./, '').split(/[.-]/).filter(Boolean).join(' ');
    const name = words.charAt(0).toUpperCase() + words.slice(1);
    return id.startsWith('optional.')
      ? {name: `${name} (optional)`, colour: palette[hash % palette.length], shape: 'diamond'}
      : {name, colour: palette[hash % palette.length], shape: 'capsule'};
  }
  const describe = id => ({id, ...(entries[id] || fallback(id))});
  const colourVar = id => `var(--contract-${describe(id).colour})`;
  // Applies the token to a port button or wire path; CSS reads the data attributes.
  function decorate(target, id, required = true) {
    const token = describe(id);
    target.dataset.contractShape = token.shape;
    target.dataset.contractColour = token.colour;
    target.dataset.contractName = token.name;
    target.dataset.contractFill = required ? 'filled' : 'hollow';
    target.style.setProperty('--contract-colour', colourVar(id));
    return token;
  }
  const swatch = (parent, id, required = true) => {
    const mark = document.createElement('span'); mark.className = 'circuit-contract-swatch';
    mark.setAttribute('aria-hidden', 'true'); decorate(mark, id, required); parent.append(mark); return mark;
  };
  const text = (tag, value, parent, className) => {
    const item = document.createElement(tag); item.textContent = value;
    if (className) item.className = className; parent.append(item); return item;
  };
  // Legend of the contracts present in the opened graph (input sockets and results).
  function legend(parent, inventory) {
    const ids = new Set();
    for (const item of inventory) { ids.add(item.socket_contract.id); ids.add(item.node_output_contract.id); }
    const box = document.createElement('details'); box.className = 'circuit-contract-legend';
    text('summary', `Port types (${ids.size})`, box);
    text('p', 'Colour and shape name a contract. A wire can join only an output and an input with the same contract; the server decides which connections are offered. Filled socket: output or required input. Hollow socket: optional input.', box, 'circuit-contract-legend-note');
    const list = text('ul', '', box, 'circuit-contract-legend-list');
    for (const id of [...ids].sort()) {
      const row = text('li', '', list); row.dataset.contract = id;
      swatch(row, id); text('span', describe(id).name, row, 'circuit-contract-legend-name'); text('code', id, row);
    }
    parent.append(box); return box;
  }
  // Short reason for a connection the server does not offer, naming both contracts.
  function refusal(sourceLabel, sourceContract, inputLabel, socketContract) {
    if (!sourceContract || !socketContract) return `Connection refused: the server does not offer ${sourceLabel} for ${inputLabel}.`;
    if (sourceContract === socketContract) return `Connection refused: the server does not offer ${sourceLabel} for ${inputLabel}, although both carry ${socketContract}.`;
    return `Connection refused: ${inputLabel} expects ${socketContract} (${describe(socketContract).name}), but ${sourceLabel} provides ${sourceContract} (${describe(sourceContract).name}).`;
  }
  const sourceLabel = source => !source ? 'unbound' : source.kind === 'external' ? `external:${source.binding}` : `${source.node}.${source.port || 'result'}`;
  // Per-node protocol mapping chip ("adapter"): declared on the consumer node, never a
  // separate node. Expanding it lists source -> argument field mappings from the inventory.
  function adapter(card, nodeId, inventory, expanded, onToggle) {
    const rows = inventory.filter(item => item.node === nodeId);
    const mapping = rows.find(item => item.protocol_mapping)?.protocol_mapping;
    if (!mapping) return null;
    const box = document.createElement('div'); box.className = 'circuit-adapter';
    const chip = text('button', '', box, 'circuit-adapter-chip'); chip.type = 'button';
    chip.id = `circuit-adapter-${nodeId}`; chip.style.setProperty('--contract-colour', colourVar(mapping.output_contract.id));
    swatch(chip, mapping.output_contract.id);
    text('span', `Mapping: ${mapping.id}`, chip, 'circuit-adapter-name');
    const fields = text('div', '', box, 'circuit-adapter-fields'); fields.id = `circuit-adapter-fields-${nodeId}`;
    chip.setAttribute('aria-controls', fields.id);
    const list = text('ul', '', fields);
    for (const row of rows) {
      const line = text('li', '', list); line.dataset.argument = row.argument || '';
      swatch(line, row.socket_contract.id, row.required);
      text('span', `${sourceLabel(row.source)} → ${row.argument || 'request'}`, line, 'circuit-adapter-field');
      text('code', row.socket_contract.id, line);
    }
    text('p', `Native function ${mapping.owner} maps these fields into ${mapping.output_contract.id}. Declared on this node; no extra node is inserted.`, fields, 'circuit-adapter-owner');
    const sync = () => {
      const open = expanded.has(nodeId);
      chip.setAttribute('aria-expanded', String(open)); fields.hidden = !open;
      chip.title = `Protocol ${mapping.id} into ${mapping.output_contract.id}. ${open ? 'Hide' : 'Show'} the field mapping.`;
    };
    chip.addEventListener('click', event => {
      event.stopPropagation();
      if (expanded.has(nodeId)) expanded.delete(nodeId); else expanded.add(nodeId);
      sync(); onToggle();
    });
    sync(); card.append(box); return box;
  }
  window.editorContractPresentation = Object.freeze({describe, decorate, legend, refusal, adapter});
})();
