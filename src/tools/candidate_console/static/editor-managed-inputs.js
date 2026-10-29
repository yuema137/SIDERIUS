/* Framework-supplied inputs of a new module (operator rule 2026-10-28): presentation only.
 * The server lists, per open document, the inputs candidate preparation generates itself
 * (SourceView/ReviewView `managed_roles`, from candidate_prepare.resolution): per-node
 * storage, native training settings and a managed proposal request. A module added by any
 * route gets those bindings exactly as the shipped examples declare them:
 *   ManagedCandidateBinding(id="<node>_store", contract="storage"),
 *   ManagedCandidateBinding(id="training", contract="native-training.settings"),
 *   ManagedCandidateBinding(id="initial", contract="proposal.input")
 * (a taken id falls back to "<node>_<suffix>" / a numbered id). v1 sources have no roles. */
(() => {
  'use strict';
  const NAMES = {'storage': node => [`${node}_store`], 'native-training.settings': node => ['training', `${node}_training`],
    'proposal.input': node => ['initial', `${node}_initial`]};
  /** {item, externals}: `item` (a PendingNode) with its managed inputs bound, the new bindings. */
  function provide(item, entry, roles, taken) {
    const next = {...item, arguments: [...(item.arguments || [])]}, externals = [], used = new Set(taken);
    const name = contract => {
      const options = (NAMES[contract] || (node => [`${node}_${contract.replace(/[^a-z0-9]+/gi, '_')}`]))(next.node);
      let id = options.find(value => !used.has(value)) || options.at(-1), n = 1;
      const first = id; while (used.has(id)) id = `${first}${++n}`;
      used.add(id); return id;
    };
    const add = contract => { const id = name(contract); externals.push({id, contract, kind: 'managed_candidate'}); return id; };
    if (!entry?.protocol) {
      if (entry && !next.binding && roles.some(role => role.argument === null && role.contract === entry.input_contract.id)) next.binding = add(entry.input_contract.id);
      return {item: next, externals};
    }
    for (const argument of entry.arguments) {
      if (!argument.required || next.arguments.some(value => value.name === argument.name)) continue;
      if (!roles.some(role => role.argument === argument.name && role.contract === argument.contract.id)) continue;
      next.arguments.push({name: argument.name, source: {kind: 'external', binding: add(argument.contract.id)}});
    }
    return {item: next, externals};
  }
  window.editorManagedInputs = Object.freeze({provide});
})();
