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
  ];
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
    for (const section of sections) section(parent, state, actions);
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
  window.editorLoopControls = Object.freeze({render, setEnabled});
})();
