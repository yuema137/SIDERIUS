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
  const INVALID = 'Enter a valid number, or choose default / None.';
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
    if (help.has_schema_default) parts.push(`Schema default: ${show(help.schema_default)}`);
    parts.push(`Native preview: ${show(control.effective)} (updated on review)`);
    return parts.join(' · ');
  }
  /**
   * state: {training, launch(), saved, drafts}; launch() returns the draft's sparse
   * training_settings.launch, saved the loaded source's. actions: {supply(name, value),
   * unset(name, rerender), invalid(name, raw), openSource()}; each records one draft edit.
   */
  function render(parent, state, actions) {
    const {training, saved, drafts} = state;
    const group = node('details', '', parent, 'training-settings'); group.open = true;
    group.id = 'editor-training-settings';
    const summary = node('summary', '', group);
    node('p', 'Epochs are ceilings; native planning resolves epochs. Task-owned rules may further constrain this run.', group);
    node('p', `Preparation output restriction: ${show(training.allowed_output_types)}`, group);
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
        reset.disabled = !changed;
      }
      summary.textContent = `Training settings · ${changedCount} of ${rows.length} changed from default`;
    };
    for (const control of training.controls) {
      const name = control.name, launch = state.launch(), current = stateOf(launch, name);
      const row = node('div', '', group, 'training-field'); row.dataset.trainingField = name;
      const wrapper = node('label', control.label, row);
      const badge = node('span', '', wrapper, 'training-badge'); badge.dataset.trainingBadge = name;
      const modeSelect = node('select', '', wrapper);
      modeSelect.dataset.trainingMode = name;
      for (const [value, title] of [['unset', 'Use native default'], ['supplied', 'Set value'], ...(control.nullable ? [['null', 'None']] : [])]) {
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
      const help = node('small', helpText(control), row, 'field-help'); help.id = `editor-training-help-${name}`;
      input.setAttribute('aria-describedby', help.id); modeSelect.setAttribute('aria-describedby', help.id);
      const reset = node('button', 'Reset to default', row, 'training-reset'); reset.type = 'button';
      reset.dataset.trainingReset = name;
      reset.setAttribute('aria-label', `Reset ${control.label} to the native default`);
      rows.push({name, row, badge, reset});
      const setValue = () => {
        input.setCustomValidity('');
        if (input.type === 'checkbox') actions.supply(name, input.checked);
        else if (input.value.trim() !== '' && Number.isFinite(input.valueAsNumber) && input.checkValidity()) actions.supply(name, input.valueAsNumber);
        else { input.setCustomValidity(INVALID); actions.invalid(name, input.value); }
      };
      modeSelect.addEventListener('change', () => {
        input.disabled = modeSelect.value !== 'supplied'; input.setCustomValidity('');
        if (modeSelect.value === 'unset') actions.unset(name, false);
        else if (modeSelect.value === 'null') actions.supply(name, null);
        else setValue();
        update();
      });
      input.addEventListener('input', () => { setValue(); update(); });
      reset.addEventListener('click', () => actions.unset(name, true));
    }
    update();
    node('p', 'Workflow parameter rules (exact / range / allowed / predicate):', group);
    node('pre', JSON.stringify(state.launch().workflow_parameter_rules ?? null, null, 2), group);
    const advanced = node('button', 'Edit advanced settings and rules in source', group); advanced.type = 'button';
    advanced.addEventListener('click', actions.openSource);
  }
  // Model hyperparameters belong to the task manifest; the editor names the owner only.
  function renderModelOwner(parent, task, binding) {
    const group = node('fieldset', '', parent, 'model-hyperparameters'); group.id = 'editor-model-hyperparameters';
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
    node('p', `This capability ${role} in the research loop: up to ${loop.final_iteration} iterations, ${stops} stop condition${stops === 1 ? '' : 's'}.`, group);
    const button = node('button', 'Edit loop and stop settings', group); button.type = 'button';
    button.addEventListener('click', open);
  }
  window.editorNodeParameters = Object.freeze({training: render, modelOwner: renderModelOwner, loopPointer: renderLoopPointer, helpText});
})();
