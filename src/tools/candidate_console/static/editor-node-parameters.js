/* Per-node parameter groups, view only: editor.js owns the draft document, Review and Save.
 * Values, defaults and help come from the server's TrainingInspector projection. */
(() => {
  'use strict';
  const node = (tag, text, parent, className) => {
    const element = document.createElement(tag); element.textContent = text;
    if (className) element.className = className;
    parent.append(element); return element;
  };
  const show = value => JSON.stringify(value);
  const INVALID = 'Enter a number, or choose Default.';
  // Collapsed by default (spec §8.1); an author who opened it keeps it open across re-renders.
  let trainingOpen = false;
  const stateOf = (launch, name) => !Object.hasOwn(launch, name) ? 'unset' : launch[name] === null ? 'null' : 'supplied';
  // Help lists only what the native schema declares; absent metadata is not shown.
  function helpText(control) {
    const help = control.help || {}, parts = [];
    if (help.description) parts.push(help.description);
    if (help.unit) parts.push(`Unit: ${help.unit}`);
    const bounds = [
      help.minimum !== null && help.minimum !== undefined ? `≥ ${help.minimum}` : null,
      help.exclusive_minimum !== null && help.exclusive_minimum !== undefined ? `> ${help.exclusive_minimum}` : null,
      help.maximum !== null && help.maximum !== undefined ? `≤ ${help.maximum}` : null,
      help.exclusive_maximum !== null && help.exclusive_maximum !== undefined ? `< ${help.exclusive_maximum}` : null,
    ].filter(Boolean);
    if (bounds.length) parts.push(`Range: ${bounds.join(', ')}`);
    return parts.join(' · ');
  }
  // Schema default and native preview are advanced detail (tour #9): raw JSON values.
  function nativeText(control) {
    const help = control.help || {};
    return `${help.has_schema_default ? `Schema default: ${show(help.schema_default)} · ` : ''}Native preview: ${show(control.effective)} (updated on review)`;
  }
  /**
   * state: {training, launch(), saved, drafts}; launch() returns the draft's sparse
   * training_settings.launch, saved the loaded source's. actions: {supply(name, value),
   * unset(name, rerender), invalid(name, raw), openSource()}; each records one draft edit.
   */
  // Required run-policy choices (L-1b): plain labels from the server projection; unset is
  // shown as a problem on the field, and the Run page's review refuses it.
  function renderPolicy(parent, state, actions) {
    const choices = state.training.policy || [];
    if (!choices.length) return;
    const group = node('fieldset', '', parent, 'training-policy'); group.id = 'editor-training-policy';
    node('legend', 'Run policy (required)', group);
    for (const control of choices) {
      const row = node('div', '', group, 'training-choice'); row.dataset.trainingChoiceField = control.name;
      const label = node('label', control.label, row);
      const select = node('select', '', label); select.dataset.trainingChoice = control.name;
      node('option', 'Choose…', select).value = '';
      for (const option of control.options) node('option', option.label, select).value = option.value;
      const current = state.launch()[control.name];
      select.value = control.options.some(option => option.value === current) ? current : '';
      const problem = node('small', '', row, 'field-error'); problem.id = `editor-training-choice-error-${control.name}`; problem.setAttribute('role', 'status');
      const help = node('small', control.explanation, row, 'field-help'); help.id = `editor-training-choice-help-${control.name}`;
      select.setAttribute('aria-describedby', `${problem.id} ${help.id}`);
      const mark = () => {
        const missing = control.required && !select.value;
        row.dataset.problem = String(missing); select.setAttribute('aria-invalid', String(missing));
        problem.textContent = missing ? 'Required: choose one. A run cannot start without it.' : '';
      };
      select.addEventListener('change', () => {
        if (select.value) actions.supply(control.name, select.value); else actions.unset(control.name, false);
        mark();
      });
      mark();
    }
  }
  function render(parent, state, actions) {
    const {training, saved, drafts} = state;
    renderPolicy(parent, state, actions);
    const group = node('details', '', parent, 'training-settings'); group.open = trainingOpen;
    group.id = 'editor-training-settings';
    group.addEventListener('toggle', () => { trainingOpen = group.open; });
    const summary = node('summary', '', group);
    node('p', 'Trial rounds are quick screening runs on planner-sized samples. Each iteration ends with a Formal round, which by default retrains its best trial setup on the operator-fixed sample set and scores it on the full evaluation split. Only Formal scores are comparable across candidates, and the run keeps the best valid Formal score.', group, 'muted').id = 'editor-training-trial-formal-help';
    for (const text of ['Epochs are ceilings; native planning resolves epochs. Task-owned rules may further constrain this run.',
      `Preparation output restriction: ${show(training.allowed_output_types)}`]) node('p', text, group, 'muted').dataset.uiFlag = 'advanced';
    const rows = [];
    // Badges, counts and Reset follow every edit without re-rendering (focus stays put).
    const update = () => {
      const launch = state.launch();
      let changedCount = 0;
      for (const {name, row, badge, reset} of rows) {
        const current = stateOf(launch, name), draft = drafts.has(name);
        const changed = current !== 'unset' || draft;
        const unsaved = draft || current !== stateOf(saved, name) || (current === 'supplied' && launch[name] !== saved[name]);
        if (changed) changedCount++;
        row.dataset.modified = String(changed); row.dataset.unsaved = String(unsaved);
        badge.textContent = unsaved ? 'Changed, not saved' : changed ? 'Modified' : 'Default';
        // Reset is a small icon shown only when there is something to reset (spec §8.2).
        reset.disabled = !changed; reset.hidden = !changed;
      }
      summary.textContent = `Training settings · ${changedCount} of ${rows.length} changed`;
    };
    for (const control of training.controls) {
      const name = control.name, launch = state.launch(), current = stateOf(launch, name);
      const row = node('div', '', group, 'training-field'); row.dataset.trainingField = name;
      const wrapper = node('label', control.label, row);
      const badge = node('span', '', wrapper, 'training-badge'); badge.dataset.trainingBadge = name;
      const modeSelect = node('select', '', wrapper);
      modeSelect.dataset.trainingMode = name;
      for (const [value, title] of [['unset', 'Default'], ['supplied', 'Set value'], ...(control.nullable ? [['null', 'None']] : [])]) {
        node('option', title, modeSelect).value = value;
      }
      modeSelect.value = current;
      const input = node('input', '', wrapper); input.dataset.training = name;
      input.type = control.kind === 'boolean' ? 'checkbox' : 'number';
      if (input.type === 'number') input.step = control.kind === 'integer' ? '1' : 'any';
      const value = current === 'supplied' ? launch[name] : control.effective;
      if (input.type === 'checkbox') input.checked = value === true; else input.value = value ?? '';
      if (drafts.has(name)) { modeSelect.value = 'supplied'; input.value = drafts.get(name); input.setCustomValidity(INVALID); }
      input.disabled = modeSelect.value !== 'supplied';
      // Validation sits under its own control (spec §8.2), not only in the page status.
      const error = node('small', '', row, 'field-error'); error.id = `editor-training-error-${name}`; error.setAttribute('role', 'status');
      const help = node('small', helpText(control), row, 'field-help'); help.id = `editor-training-help-${name}`;
      const native = node('span', `${help.textContent ? ' · ' : ''}${nativeText(control)}`, help); native.dataset.uiFlag = 'advanced';
      input.setAttribute('aria-describedby', help.id); modeSelect.setAttribute('aria-describedby', help.id);
      const reset = node('button', '', row, 'training-reset secondary icon-button'); reset.type = 'button';
      reset.append(window.consoleIcons?.make('rotate-ccw', 16) || ''); node('span', 'Reset to default', reset, 'sr-only'); reset.title = 'Reset to default';
      reset.dataset.trainingReset = name;
      reset.setAttribute('aria-label', `Reset ${control.label} to the native default`);
      rows.push({name, row, badge, reset});
      const invalid = on => { error.textContent = on ? INVALID : ''; input.setAttribute('aria-invalid', String(on)); };
      if (drafts.has(name)) invalid(true);
      const setValue = () => {
        input.setCustomValidity(''); invalid(false);
        if (input.type === 'checkbox') actions.supply(name, input.checked);
        else if (input.value.trim() !== '' && Number.isFinite(input.valueAsNumber) && input.checkValidity()) actions.supply(name, input.valueAsNumber);
        else { input.setCustomValidity(INVALID); invalid(true); actions.invalid(name, input.value); }
      };
      modeSelect.addEventListener('change', () => {
        input.disabled = modeSelect.value !== 'supplied'; input.setCustomValidity(''); invalid(false);
        if (modeSelect.value === 'unset') actions.unset(name, false);
        else if (modeSelect.value === 'null') actions.supply(name, null);
        else setValue();
        update();
      });
      input.addEventListener('input', () => { setValue(); update(); });
      reset.addEventListener('click', () => actions.unset(name, true));
    }
    update();
    const rules = node('div', '', group, 'training-rules'); rules.dataset.uiFlag = 'advanced';
    node('p', 'Workflow parameter rules (exact / range / allowed / predicate):', rules);
    node('pre', JSON.stringify(state.launch().workflow_parameter_rules ?? null, null, 2), rules);
    const advanced = node('button', 'Edit advanced settings and rules in source', rules, 'secondary'); advanced.type = 'button';
    advanced.addEventListener('click', actions.openSource);
  }
  // Model hyperparameters belong to the task manifest; the editor names the owner only.
  function renderModelOwner(parent, task, binding) {
    const group = node('fieldset', '', parent, 'model-hyperparameters'); group.id = 'editor-model-hyperparameters';
    group.dataset.uiFlag = 'advanced'; // task-manifest detail: Settings › Show advanced tools
    node('legend', 'Model hyperparameters (read-only)', group);
    node('p', 'Model hyperparameters are owned by the task manifest, not by this workflow. Edit them in the task package.', group);
    const list = node('dl', '', group);
    node('dt', 'Task manifest', list); node('dd', task.manifest, list, 'mono').id = 'editor-model-owner';
    if (binding) { node('dt', 'Task package', list); node('dd', `${binding.package_id} @ ${binding.revision}`, list, 'mono'); }
  }
  // Loop and stop settings are workflow-level (AuthoredLoop); a loop endpoint points there.
  function renderLoopPointer(parent, loop, nodeId, open) {
    const group = node('fieldset', '', parent, 'node-loop-settings'); group.id = 'editor-node-loop-settings';
    node('legend', 'Loop and stop settings', group);
    const role = loop.feedback.source.node === nodeId ? 'feeds results back' : 'receives feedback';
    const stops = loop.stop_conditions?.length || 0;
    node('p', `This module ${role} in the research loop: up to ${loop.final_iteration} iterations, ${stops} stop condition${stops === 1 ? '' : 's'}.`, group);
    const button = node('button', 'Edit loop and stop settings', group, 'secondary'); button.type = 'button';
    button.addEventListener('click', open);
  }
  window.editorNodeParameters = Object.freeze({training: render, modelOwner: renderModelOwner, loopPointer: renderLoopPointer, helpText});
})();
