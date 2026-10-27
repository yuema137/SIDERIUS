/* Task-control view only: editor.js owns drafts, requests and acceptance. */
(() => {
  'use strict';
  const node = (tag, text, parent) => {
    const element = document.createElement(tag); element.textContent = text; parent.append(element); return element;
  };
  const identity = (parent, label, binding, summary = true) => {
    if (summary) node('p', label + ': ' + (binding ? `${binding.package_id} · ${binding.revision}` : 'Legacy / unbound'), parent);
    if (!binding) return;
    const details = node('details', '', parent); node('summary', label + ' technical identity', details);
    node('p', `Data path: ${binding.task_data_path_id}`, details);
    node('p', `Fingerprint: ${binding.semantic_fingerprint}`, details);
  };
  const GUIDE = 'https://github.com/Galileo-Sandbox/SIDERIUS/blob/master/src/tools/candidate_console/README.md#bind-a-task-version';
  // The panel always states which task package/version the workflow uses (never an empty box).
  function usage(parent, state) {
    const binding = state.savedBinding;
    const text = !state.connected && !state.projectOpen ? 'Connect to see which task package and version this workflow uses.'
      : !state.projectOpen ? 'Open a project to see which task package and version its workflow uses.'
        : binding ? `This workflow uses task package ${binding.package_id}, version ${binding.revision}.`
          : 'This workflow is not bound to a task package version; its task references are used as written (legacy / unbound). Ordinary editing remains available.';
    const line = node('p', text, parent); line.id = 'editor-task-state';
    if (binding) identity(parent, 'Saved task', binding, false);
  }
  // Shown instead of the version selector when the console offers no configured versions.
  function unavailable(parent, state) {
    const why = node('p', '', parent); why.id = 'editor-task-unavailable';
    if (!state.connected) { why.textContent = 'Connect to load the configured task versions.'; return; }
    if (!Array.isArray(state.choices)) { why.textContent = 'Configured task versions are not loaded. Use Refresh task choices to load them.'; return; }
    why.textContent = 'No task versions are configured for this console, so there is nothing to switch to. A version is offered here when a configured task declares task_revision in the console configuration. See ';
    const link = node('a', 'Bind a task version', why); link.href = GUIDE; link.target = '_blank'; link.rel = 'noopener noreferrer';
    why.append(document.createTextNode(' (src/tools/candidate_console/README.md).'));
  }
  window.editorTaskControls = Object.freeze({render(parent, state, actions) {
    const focusId = parent.contains(document.activeElement) ? document.activeElement.id : null;
    try {
      parent.replaceChildren();
      node('h2', 'Task package and version', parent);
      usage(parent, state);
      if (state.choices?.length) {
        const label = node('label', 'Configured task version ', parent), select = node('select', '', label);
        select.id = 'editor-task-choice';
        node('option', 'Select a configured task version', select).value = '';
        for (const choice of state.choices) {
          const option = node('option', `${choice.binding.package_id} · ${choice.binding.revision} (${choice.choice_id})`, select);
          option.value = choice.choice_id;
        }
        select.value = state.selection?.selected_choice_id || '';
        select.disabled = !state.connected || state.saving;
        select.addEventListener('change', () => actions.select(select.value));
        if (state.selection) identity(parent, 'Selected task', state.selection.expected_task_binding);
        if (state.matching.length === 1 && !state.selection) {
          const use = node('button', "Use saved task's configured choice", parent); use.type = 'button';
          use.id = 'editor-task-use-saved'; use.disabled = !state.connected || state.saving;
          use.addEventListener('click', () => actions.select(state.matching[0].choice_id));
        }
        const update = node('button', 'Update workflow references', parent); update.type = 'button';
        update.id = 'editor-task-update'; update.disabled = !state.canUpdate;
        update.addEventListener('click', actions.update);
      } else unavailable(parent, state);
      const message = node('p', state.message, parent); message.id = 'editor-task-message'; message.setAttribute('role', 'status');
      const retry = node('button', 'Refresh task choices', parent); retry.type = 'button';
      retry.id = 'editor-task-refresh';
      retry.disabled = !state.connected || state.saving; retry.addEventListener('click', actions.refresh);
      if (!state.review) return;
      const review = state.review;
      node('h3', 'Task reference review', parent);
      identity(parent, 'Target task', review.target_binding);
      node('p', review.save_supported ? 'Task checks passed. You can save this reference after reviewing the findings. Run preparation is still required before launch.' : `Task review is blocked. Native task check: ${review.observation.result.outcome}. Inspect the findings before changing your draft.`, parent);
      const findings = node('ol', '', parent); findings.id = 'editor-task-findings';
      for (const finding of review.findings) {
        const item = node('li', `${{retained: 'Retained', requires_review: 'Review required', blocked: 'Blocked'}[finding.state]}: ${finding.message}`, findings);
        const details = node('details', '', item); node('summary', 'Technical finding', details);
        node('p', `${finding.code} · ${finding.reference}`, details);
      }
      if (!review.save_supported || review.findings.some(item => item.state === 'blocked')) {
        node('p', 'This reference cannot be saved. Keep your draft and resolve the blocked findings. Unsupported interfaces or workflow mappings require a separate update.', parent); return;
      }
      const check = (id, text, checked, callback) => {
        const label = node('label', '', parent), input = node('input', '', label); input.type = 'checkbox'; input.id = id;
        label.className = 'editor-task-acknowledgement';
        input.checked = checked; input.disabled = !state.connected || state.saving;
        label.append(document.createTextNode(text)); input.addEventListener('change', () => callback(input.checked));
      };
      if (review.current_observation?.result.candidate_check) {
        const details = node('details', '', parent); node('summary', 'Task declaration details', details);
        node('pre', JSON.stringify({previous: review.current_observation.result, target: review.observation.result}, null, 2), details);
      }
      check('editor-task-acknowledge', ' I reviewed every finding above and the exact Python diff.', state.acknowledged, actions.acknowledge);
      if (review.findings.some(item => item.code === 'current_snapshot_adoption')) check('editor-task-adopt', ' Adopt the currently observed snapshot; no historical task identity is claimed.', state.adopted, actions.adopt);
    } finally {
      if (focusId) (document.getElementById(focusId) || document.getElementById('editor-task-choice'))?.focus({preventScroll: true});
    }
  }});
})();
