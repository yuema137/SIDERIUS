/* The single owner of capability display names (sentence case, used on canvas cards,
 * palette, inspector, loop, run and result views) and their decorative Lucide icons
 * (ui-design-spec.md §3.3: one icon per capability everywhere). */
(() => {
  'use strict';
  const svg = 'http://www.w3.org/2000/svg';
  const entries = Object.freeze({
    interpretation: {label: 'Interpret results', role: 'interpretation', icon: 'chart-spline'},
    literature: {label: 'Literature review', role: 'literature', icon: 'book-open-text'},
    proposal: {label: 'Propose model', role: 'proposal', icon: 'lightbulb'},
    implementation: {label: 'Implement', role: 'implementation', icon: 'code-xml'},
    validation: {label: 'Validate', role: 'validation', icon: 'shield-check'},
    tuning: {label: 'Train & tune', role: 'tuning', icon: 'sliders-horizontal'},
  });
  const fallback = Object.freeze({label: 'Capability', role: 'generic', icon: 'shapes'});

  function append(parent, capability, instanceId, className) {
    const entry = entries[capability] || fallback;
    const row = document.createElement('span');
    row.className = `capability-heading capability-${entry.role}${className ? ` ${className}` : ''}`;
    row.dataset.capability = capability;
    // Lucide sprite icon (icons.js); an empty decorative <svg> keeps the grid if it is absent.
    row.append(window.consoleIcons ? window.consoleIcons.make(entry.icon, 28) : document.createElementNS(svg, 'svg'));
    const label = document.createElement('span'); label.className = 'capability-name'; label.textContent = entry.label; row.append(label);
    const instance = document.createElement('small'); instance.className = 'capability-instance';
    instance.textContent = instanceId; instance.setAttribute('aria-label', `Instance ${instanceId}`); row.append(instance);
    parent.append(row);
    return entry.label;
  }
  const label = capability => (entries[capability] || fallback).label;
  window.editorCapabilityPresentation = Object.freeze({append, label});
})();
