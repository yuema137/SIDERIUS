/* UI settings: the single owner of view flags that reveal Advanced or developer sections.
 * Loaded in <head> (before styles/body, like theme.js) so the first paint already hides
 * gated sections. A section opts in with `data-ui-flag="advanced"` or `"developer"`; CSS
 * (styles.css) hides it unless the root carries `data-ui-<flag>="on"`. Flags only change
 * what is shown: no request, draft or run state, and a hidden section keeps its state.
 * API: window.uiSettings.isEnabled(flag), .set(flag, enabled), .flags; event
 * `ui-settings-change` {flag, enabled}. Storage: siderius.console.ui.<flag> = "on". */
(() => {
  'use strict';
  const flags = Object.freeze({
    advanced: 'Show advanced tools',
    developer: 'Show developer details',
  });
  const key = flag => 'siderius.console.ui.' + flag;
  const state = {};
  for (const flag of Object.keys(flags)) {
    try { state[flag] = localStorage.getItem(key(flag)) === 'on'; } catch { state[flag] = false; }
  }
  const apply = flag => {
    if (state[flag]) document.documentElement.setAttribute('data-ui-' + flag, 'on');
    else document.documentElement.removeAttribute('data-ui-' + flag);
  };
  for (const flag of Object.keys(flags)) apply(flag);
  function set(flag, enabled) {
    if (!(flag in flags)) throw new Error('Unknown UI flag: ' + flag);
    state[flag] = !!enabled; apply(flag);
    try { if (state[flag]) localStorage.setItem(key(flag), 'on'); else localStorage.removeItem(key(flag)); }
    catch { /* Keep working for this page without persistent storage. */ }
    window.dispatchEvent(new CustomEvent('ui-settings-change', {detail: {flag, enabled: state[flag]}}));
  }
  window.uiSettings = Object.freeze({flags, isEnabled: flag => !!state[flag], set});
  document.addEventListener('DOMContentLoaded', () => {
    // Settings panel: a non-modal disclosure under the header gear button.
    const button = document.getElementById('settings-toggle'), panel = document.getElementById('settings-panel');
    const toggle = open => { panel.hidden = !open; button.setAttribute('aria-expanded', String(open)); };
    button.addEventListener('click', () => toggle(panel.hidden));
    panel.addEventListener('keydown', event => { if (event.key === 'Escape') { toggle(false); button.focus(); } });
    for (const input of panel.querySelectorAll('input[data-ui-setting]')) {
      const flag = input.dataset.uiSetting;
      input.checked = !!state[flag];
      input.addEventListener('change', () => set(flag, input.checked));
    }
  });
})();
