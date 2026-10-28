/* Contract presentation for circuit ports: colour and shape keyed on the server-sent
 * contract id, plus the legend, refusal reason and protocol-mapping ("adapter") chip.
 * Names, descriptions and kinds are NOT owned here: they arrive on every server
 * contract object (`name`, `description`, `kind`) from the single server owner
 * src/workflows/definition/contract_names.py. A name names the schema only; direction
 * is shown by the socket arrow (`direction`). Presentation only: compatibility is
 * always the server's port_inventory choices; nothing here decides a connection. */
(() => {
  'use strict';
  // One row per catalog contract (a unit census binds this table to CONTRACTS and
  // requires every (colour, shape) pair to be distinct). Colours name CSS tokens
  // --contract-<colour> defined for both themes in editor-contract-presentation.css.
  const entries = Object.freeze({
    'interpretation.input': {colour: 'interpretation', shape: 'circle'},
    'interpretation.output': {colour: 'interpretation', shape: 'square'},
    'literature.input': {colour: 'literature', shape: 'circle'},
    'literature.output': {colour: 'literature', shape: 'square'},
    'proposal.input': {colour: 'proposal', shape: 'circle'},
    'proposal.output': {colour: 'proposal', shape: 'square'},
    'implementation.input': {colour: 'implementation', shape: 'circle'},
    'implementation.output': {colour: 'implementation', shape: 'square'},
    'validation.input': {colour: 'validation', shape: 'circle'},
    'validation.output': {colour: 'validation', shape: 'square'},
    'tuning.input': {colour: 'tuning', shape: 'circle'},
    'tuning.output': {colour: 'tuning', shape: 'square'},
    'native-training.settings': {colour: 'tuning', shape: 'capsule'},
    'storage': {colour: 'neutral', shape: 'capsule'},
    'llm-provider': {colour: 'magenta', shape: 'capsule'},
    'optional.text': {colour: 'neutral', shape: 'diamond'},
    'optional.model-id': {colour: 'magenta', shape: 'diamond'},
    'optional.expert-advice': {colour: 'tuning', shape: 'diamond'},
    'optional.expert-context': {colour: 'proposal', shape: 'diamond'},
    'optional.parameter-rules': {colour: 'green', shape: 'diamond'},
    'optional.constraint-context': {colour: 'implementation', shape: 'diamond'},
    'optional.task-composition-ref': {colour: 'literature', shape: 'diamond'},
  });
  const palette = Object.freeze(['interpretation', 'literature', 'proposal', 'implementation', 'validation', 'tuning', 'neutral', 'magenta', 'green']);
  // Server-sent presentation, learned from every contract object the server projects
  // (ports, choices, catalog, mapping). Ids are the identity; names are display only.
  const learned = new Map();
  function learn(contract) {
    if (contract && typeof contract === 'object' && contract.id && contract.name) {
      learned.set(contract.id, {name: contract.name, description: contract.description || '', kind: contract.kind || ''});
    }
    return contract && typeof contract === 'object' ? contract.id : contract;
  }
  // An id outside the table (a newer server catalog) still gets a stable token; an id
  // the server has not named yet shows id-derived words until its object arrives.
  function fallback(id) {
    let hash = 0;
    for (const character of id) hash = (hash * 31 + character.codePointAt(0)) >>> 0;
    return {colour: palette[hash % palette.length], shape: id.startsWith('optional.') ? 'diamond' : 'capsule'};
  }
  const unnamed = id => {
    const words = id.replace(/^optional\./, '').split(/[.-]/).filter(Boolean).join(' ');
    return {name: words.charAt(0).toUpperCase() + words.slice(1), description: '', kind: ''};
  };
  // Accepts a server contract object (preferred) or a contract id.
  const describe = contract => {
    const id = learn(contract);
    return {id, ...(learned.get(id) || unnamed(id)), ...(entries[id] || fallback(id))};
  };
  const colourVar = contract => `var(--contract-${describe(contract).colour})`;
  // Applies the token to a port button or wire path; CSS reads the data attributes.
  function decorate(target, contract, required = true) {
    const token = describe(contract);
    target.dataset.contractShape = token.shape;
    target.dataset.contractColour = token.colour;
    target.dataset.contractName = token.name;
    target.dataset.contractFill = required ? 'filled' : 'hollow';
    target.style.setProperty('--contract-colour', colourVar(contract));
    return token;
  }
  const swatch = (parent, contract, required = true) => {
    const mark = document.createElement('span'); mark.className = 'circuit-contract-swatch';
    mark.setAttribute('aria-hidden', 'true'); decorate(mark, contract, required); parent.append(mark); return mark;
  };
  const text = (tag, value, parent, className) => {
    const item = document.createElement(tag); item.textContent = value;
    if (className) item.className = className; parent.append(item); return item;
  };
  // Direction mark on a canvas socket: an incoming arrow before an input's label, an
  // outgoing arrow after an output's. Names never encode direction; the accessible
  // name and tooltip state "receives <name>" or "sends <name>".
  function direction(port, contract, sends) {
    const word = sends ? 'sends' : 'receives';
    const mark = document.createElement('span');
    mark.className = 'circuit-port-direction'; mark.textContent = '→'; mark.setAttribute('aria-hidden', 'true');
    if (sends) port.append(mark); else port.prepend(mark);
    port.dataset.contractDirection = word;
    const phrase = `${word.charAt(0).toUpperCase() + word.slice(1)} ${describe(contract).name}`;
    // Accessible name only: no `title` (spec §6.2); the socket tooltip is editor-circuit-tooltip.js.
    const current = port.getAttribute('aria-label');
    port.setAttribute('aria-label', current ? `${phrase}. ${current}` : phrase);
    return word;
  }
  // Legend of the contracts present in the opened graph (input sockets and results).
  function legend(parent, inventory) {
    const ids = new Set();
    for (const item of inventory) { ids.add(learn(item.socket_contract)); ids.add(learn(item.node_output_contract)); }
    const box = document.createElement('details'); box.className = 'circuit-contract-legend';
    text('summary', `Port types (${ids.size})`, box);
    // Opened, the legend is a popover above its bottom-left chip (spec K14): it never pushes the canvas.
    const pop = text('div', '', box, 'circuit-contract-legend-popover');
    const note = text('p', 'Colour, shape and name identify the data type (schema) a socket carries; the same type has the same name everywhere. A wire can join only an output and an input with the same contract; the server decides which connections are offered. Filled socket: output or required input. Hollow socket: optional input. ', pop, 'circuit-contract-legend-note');
    // Direction key inline in the note, so the open legend stays as short as before.
    const key = text('span', '', note, 'circuit-contract-legend-direction');
    text('span', '→', key, 'circuit-port-direction').setAttribute('aria-hidden', 'true');
    text('span', ' before a label: the module receives that type; ', key);
    text('span', '→', key, 'circuit-port-direction').setAttribute('aria-hidden', 'true');
    text('span', ' after a label: the module sends it.', key);
    const list = text('ul', '', pop, 'circuit-contract-legend-list');
    for (const id of [...ids].sort()) {
      const row = text('li', '', list); row.dataset.contract = id;
      // The description is the row tooltip: rows stay one compact line each.
      const token = describe(id); row.title = token.description;
      swatch(row, id); text('span', token.name, row, 'circuit-contract-legend-name');
      text('code', id, row).dataset.uiFlag = 'advanced'; // raw id: Settings › Show advanced tools
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
    learn(mapping.output_contract);
    const box = document.createElement('div'); box.className = 'circuit-adapter'; box.dataset.uiFlag = 'advanced';
    const chip = text('button', '', box, 'circuit-adapter-chip'); chip.type = 'button';
    chip.id = `circuit-adapter-${nodeId}`; chip.style.setProperty('--contract-colour', colourVar(mapping.output_contract.id));
    swatch(chip, mapping.output_contract.id);
    text('span', `Mapping: ${mapping.id}`, chip, 'circuit-adapter-name');
    const fields = text('div', '', box, 'circuit-adapter-fields'); fields.id = `circuit-adapter-fields-${nodeId}`;
    chip.setAttribute('aria-controls', fields.id);
    const list = text('ul', '', fields);
    for (const row of rows) {
      const line = text('li', '', list); line.dataset.argument = row.argument || '';
      swatch(line, row.socket_contract, row.required);
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
  window.editorContractPresentation = Object.freeze({describe, decorate, direction, legend, refusal, adapter, learn});
})();
