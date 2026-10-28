/* The single owner of capability display names (sentence case, used on canvas cards,
 * palette, inspector, loop, run and result views) and their decorative marks. */
(() => {
  'use strict';
  const svg = 'http://www.w3.org/2000/svg';
  const entries = Object.freeze({
    interpretation: {label: 'Interpret results', role: 'interpretation', paths: [['path', {d: 'M4 4v16h16'}], ['path', {d: 'm7.5 15 3.5-4 3 2.5 4.5-5.5'}], ['circle', {cx: '18.5', cy: '8', r: '1.6'}]]},
    literature: {label: 'Literature review', role: 'literature', paths: [['path', {d: 'M6 3.5h8l4 4V20H6z'}], ['path', {d: 'M14 3.5V8h4M9 12h5M9 15h3'}], ['circle', {cx: '17.5', cy: '16.5', r: '2.5'}], ['path', {d: 'm19.3 18.3 2 2'}]]},
    proposal: {label: 'Propose model', role: 'proposal', paths: [['path', {d: 'M9 18h6M10 21h4'}], ['path', {d: 'M8.5 14.5a7 7 0 1 1 7 0c-.8.6-1.2 1.3-1.3 2h-4.4c-.1-.7-.5-1.4-1.3-2Z'}], ['path', {d: 'M12 2v2M4.9 5l1.4 1.4M19.1 5l-1.4 1.4'}]]},
    implementation: {label: 'Implement', role: 'implementation', paths: [['path', {d: 'm8 7-5 5 5 5M16 7l5 5-5 5M14 5l-4 14'}]]},
    validation: {label: 'Validate', role: 'validation', paths: [['path', {d: 'M12 3 20 6v5c0 5-3.4 8-8 10-4.6-2-8-5-8-10V6z'}], ['path', {d: 'm8.5 12 2.3 2.3 4.8-5'}]]},
    tuning: {label: 'Train & tune', role: 'tuning', paths: [['path', {d: 'M4 6h16M4 12h16M4 18h16'}], ['circle', {cx: '9', cy: '6', r: '2'}], ['circle', {cx: '15', cy: '12', r: '2'}], ['circle', {cx: '7', cy: '18', r: '2'}]]},
  });
  const fallback = Object.freeze({label: 'Capability', role: 'generic', paths: [['circle', {cx: '12', cy: '12', r: '8'}], ['path', {d: 'M12 8v8M8 12h8'}]]});

  function append(parent, capability, instanceId, className) {
    const entry = entries[capability] || fallback;
    const row = document.createElement('span');
    row.className = `capability-heading capability-${entry.role}${className ? ` ${className}` : ''}`;
    row.dataset.capability = capability;
    const icon = document.createElementNS(svg, 'svg');
    icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('aria-hidden', 'true'); icon.setAttribute('focusable', 'false');
    for (const [tag, attributes] of entry.paths) {
      const shape = document.createElementNS(svg, tag);
      for (const [name, value] of Object.entries(attributes)) shape.setAttribute(name, value);
      icon.append(shape);
    }
    row.append(icon);
    const label = document.createElement('span'); label.className = 'capability-name'; label.textContent = entry.label; row.append(label);
    const instance = document.createElement('small'); instance.className = 'capability-instance';
    instance.textContent = instanceId; instance.setAttribute('aria-label', `Instance ${instanceId}`); row.append(instance);
    parent.append(row);
    return entry.label;
  }
  const label = capability => (entries[capability] || fallback).label;
  window.editorCapabilityPresentation = Object.freeze({append, label});
})();
