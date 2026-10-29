/* Research-loop view only: editor.js owns the draft document, Review and Save. */
(() => {
  'use strict';
  const node = (tag, text, parent) => {
    const element = document.createElement(tag); element.textContent = text; parent.append(element); return element;
  };
  const label = capability => window.editorCapabilityPresentation.label(capability);
  const capabilityOf = (state, id) => state.nodes.find(item => item.id === id)?.capability;
  const control = (element, unavailable = false) => {
    element.dataset.loopControl = ''; if (unavailable) element.dataset.loopUnavailable = ''; return element;
  };
  // Each section renders one facet of a declared loop into its own fieldset.
  // Later loop facets (for example stop conditions) are appended to this list;
  // existing sections, the add/remove actions and editor.js stay unchanged.
  const sections = [
    function iterationLimit(parent, state, actions) {
      const group = node('fieldset', '', parent); node('legend', 'Iteration limit', group);
      const wrapper = node('label', 'Final iteration ', group);
      const input = control(node('input', '', wrapper));
      input.id = 'editor-loop-final-iteration'; input.type = 'number'; input.min = '1'; input.step = '1'; input.required = true;
      const draft = state.drafts.get('final_iteration');
      input.value = draft ?? String(state.loop.final_iteration);
      if (draft !== undefined) input.setCustomValidity('Enter a whole number of at least 1.');
      input.addEventListener('input', () => actions.limit(input));
      node('small', 'The loop runs at most this many complete workflow bodies.', group);
    },
    function feedback(parent, state) {
      const group = node('fieldset', '', parent); node('legend', 'Feedback', group);
      const edge = state.loop.feedback, source = edge.source.node;
      const text = node('p', `${label(capabilityOf(state, source))} ${source} → ${label(capabilityOf(state, edge.target))} ${edge.target}`, group);
      text.id = 'editor-loop-feedback';
      const details = node('details', '', group); node('summary', 'Feedback contract', details);
      node('p', `Protocol: ${edge.protocol} · History: ${edge.history}`, details);
      node('p', 'Feedback endpoints are edited in Source.', details);
    },
    stopConditions,
  ];
  // Stop conditions: the declaration (AuthoredLoop.stop_conditions) and Review are
  // authoritative; these checks only keep obviously incomplete values out of Review.
  const STOP_KINDS = Object.freeze({
    metric_threshold: {title: 'Metric threshold', add: 'Add metric threshold', initial: () => ({kind: 'metric_threshold', metric_id: '', threshold: 0}), drafts: {metric_id: '', threshold: ''}},
    no_improvement: {title: 'No improvement', add: 'Add no-improvement stop', initial: () => ({kind: 'no_improvement', completed_bodies: 1}), drafts: {}},
  });
  const STOP_FIELDS = Object.freeze({
    metric_id: {hint: 'Enter the task metric id exactly as declared (no surrounding spaces).',
      parse: input => input.value !== '' && input.value.trim() === input.value ? input.value : undefined},
    threshold: {hint: 'Enter a finite number.',
      parse: input => input.value.trim() !== '' && Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : undefined},
    completed_bodies: {hint: 'Enter a whole number of at least 1, below the final iteration.',
      parse: input => input.value.trim() !== '' && Number.isInteger(input.valueAsNumber) && input.valueAsNumber >= 1 ? input.valueAsNumber : undefined},
  });
  const draftKey = (kind, field) => `stop.${kind}.${field}`;
  const forgetDrafts = (drafts, kind) => { for (const key of [...drafts.keys()]) if (key.startsWith(`stop.${kind}.`)) drafts.delete(key); };
  function stopField(row, condition, field, label, state, actions) {
    const wrapper = node('label', label + ' ', row);
    const input = control(node('input', '', wrapper));
    input.id = `editor-loop-stop-${field.replaceAll('_', '-')}`; input.required = true;
    if (field === 'metric_id') { input.type = 'text'; input.placeholder = 'for example accuracy'; input.spellcheck = false; }
    else { input.type = 'number'; input.step = field === 'threshold' ? 'any' : '1'; if (field === 'completed_bodies') input.min = '1'; }
    const key = draftKey(condition.kind, field), draft = state.drafts.get(key);
    input.value = draft ?? String(condition[field]);
    if (draft !== undefined) input.setCustomValidity(STOP_FIELDS[field].hint);
    input.addEventListener('input', () => actions.edit(loop => {
      const target = loop.stop_conditions?.find(item => item.kind === condition.kind);
      if (!target) return;
      const value = STOP_FIELDS[field].parse(input);
      input.setCustomValidity(value === undefined ? STOP_FIELDS[field].hint : '');
      if (value === undefined) state.drafts.set(key, input.value);
      else { target[field] = value; state.drafts.delete(key); }
    }, STOP_FIELDS[field].parse(input) === undefined
      ? `Incomplete stop conditions are not reviewed. ${STOP_FIELDS[field].hint}`
      : 'Stop condition changed locally. Review and save to update the source.'));
  }
  function stopConditions(parent, state, actions) {
    const group = node('fieldset', '', parent); group.id = 'editor-loop-stop-conditions'; node('legend', 'Stop conditions', group);
    const conditions = state.loop.stop_conditions || [];
    node('p', conditions.length
      ? 'The loop completes early when any condition below is met after a completed body (checked in this order). The iteration limit still applies.'
      : 'None. The loop runs until its iteration limit.', group);
    for (const condition of conditions) {
      const row = node('div', '', group); row.className = 'editor-loop-stop'; row.dataset.stopKind = condition.kind;
      node('strong', STOP_KINDS[condition.kind]?.title ?? condition.kind, row);
      if (condition.kind === 'metric_threshold') {
        stopField(row, condition, 'metric_id', 'Metric id', state, actions);
        stopField(row, condition, 'threshold', 'Threshold', state, actions);
        node('small', 'Stops once the best valid Formal score is at least as good as the threshold. "Better" follows the task metric declaration; the metric id must equal the task metric or the run fails.', row);
      } else if (condition.kind === 'no_improvement') {
        stopField(row, condition, 'completed_bodies', 'Completed bodies', state, actions);
        node('small', 'Stops after this many consecutive completed bodies leave the best valid Formal score unimproved. Must be below the final iteration.', row);
      }
      const remove = control(node('button', 'Remove', row));
      remove.type = 'button'; remove.id = `editor-loop-remove-${condition.kind.replaceAll('_', '-')}`;
      remove.addEventListener('click', () => actions.edit(loop => {
        loop.stop_conditions = (loop.stop_conditions || []).filter(item => item.kind !== condition.kind);
        if (!loop.stop_conditions.length) delete loop.stop_conditions;
        forgetDrafts(state.drafts, condition.kind);
      }, `${STOP_KINDS[condition.kind]?.title ?? condition.kind} stop removed locally. Review and save to update the source.`, true));
    }
    // At most one condition per kind; judge-based stopping is not offered.
    for (const [kind, spec] of Object.entries(STOP_KINDS)) {
      if (conditions.some(item => item.kind === kind)) continue;
      const add = control(node('button', spec.add, group));
      add.type = 'button'; add.id = `editor-loop-add-${kind.replaceAll('_', '-')}`;
      add.addEventListener('click', () => actions.edit(loop => {
        if ((loop.stop_conditions || []).some(item => item.kind === kind)) return;
        loop.stop_conditions = [...(loop.stop_conditions || []), spec.initial()];
        for (const [field, value] of Object.entries(spec.drafts)) state.drafts.set(draftKey(kind, field), value);
      }, `${spec.title} stop added locally. Complete its fields, then review and save to update the source.`, true));
    }
  }
  function render(parent, state, actions) {
    parent.replaceChildren();
    node('h2', 'Research loop', parent);
    if (!state.loop) {
      node('p', 'No research loop declared. Each launch runs the workflow body once.', parent).id = 'editor-loop-absent';
      const add = control(node('button', 'Add research loop', parent), !state.template);
      add.type = 'button'; add.id = 'editor-loop-add';
      add.addEventListener('click', actions.add);
      if (!state.template) node('p', `Adding a loop here requires exactly one ${label('tuning')} node and one ${label('interpretation')} node. Declare other feedback in Source.`, parent);
      setEnabled(parent, state.enabled);
      return;
    }
    // A deleted feedback module leaves the loop pointing at nothing: say so, and offer only
    // Remove (Undo brings the module back). The problems list carries the same problem.
    const present = new Set(state.nodes.map(item => item.id)), edge = state.loop.feedback;
    if (!present.has(edge.source.node) || !present.has(edge.target)) {
      const broken = node('p', 'The research loop feeds back between deleted modules. Undo the delete, or remove the research loop.', parent);
      broken.id = 'editor-loop-broken'; broken.className = 'field-problem-text';
    } else for (const section of sections) section(parent, state, actions);
    if (state.profile !== 'native-interpretation-candidate/v1') {
      node('p', 'Only the native interpretation execution profile runs a research loop; preparation or launch admission refuses this declaration otherwise.', parent).className = 'muted';
    }
    const remove = control(node('button', 'Remove research loop', parent));
    remove.type = 'button'; remove.id = 'editor-loop-remove';
    remove.addEventListener('click', actions.remove);
    setEnabled(parent, state.enabled);
  }
  function setEnabled(parent, enabled) {
    for (const element of parent.querySelectorAll('[data-loop-control]')) {
      element.disabled = !enabled || element.dataset.loopUnavailable !== undefined;
    }
  }
  const refusalHint = 'Stop conditions need a non-empty metric id, a finite threshold, at most one condition per kind, and no-improvement bodies below the final iteration.';
  window.editorLoopControls = Object.freeze({render, setEnabled, refusalHint});
})();
