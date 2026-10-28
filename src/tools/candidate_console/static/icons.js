/* Icon owner (ui-design-spec.md §3): the vendored Lucide sprite /icons.svg (licence:
 * icons-LICENSE.txt). The sprite is fetched once (connect-src 'self'), parsed as inert SVG
 * and inserted as one hidden <svg>, so every icon is a same-document <use href="#i-NAME">
 * with no inline markup or script. Icons are decorative (aria-hidden); the control that
 * holds one keeps its own text or accessible name. If the sprite cannot load, controls
 * simply show no icon.
 * API: window.consoleIcons.make(name, size = 16) -> <svg>; .decorate(root) prepends an icon
 * to every element with data-icon="NAME" (once). */
(() => {
  'use strict';
  const ns = 'http://www.w3.org/2000/svg';
  function make(name, size = 16) {
    const svg = document.createElementNS(ns, 'svg');
    for (const [key, value] of Object.entries({class: `icon icon-${name}`, width: String(size), height: String(size), viewBox: '0 0 24 24',
      fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
      'aria-hidden': 'true', focusable: 'false'})) svg.setAttribute(key, value);
    const use = document.createElementNS(ns, 'use'); use.setAttribute('href', `#i-${name}`); svg.append(use);
    return svg;
  }
  function decorate(root = document) {
    for (const element of root.querySelectorAll('[data-icon]:not([data-icon-ready])')) {
      element.dataset.iconReady = ''; element.prepend(make(element.dataset.icon, Number(element.dataset.iconSize) || 16));
    }
  }
  async function load() {
    try {
      const response = await fetch('/icons.svg', {cache: 'force-cache', credentials: 'omit'});
      if (!response.ok) return;
      const parsed = new DOMParser().parseFromString(await response.text(), 'image/svg+xml');
      const sprite = document.createElementNS(ns, 'svg');
      sprite.setAttribute('aria-hidden', 'true'); sprite.setAttribute('class', 'icon-sprite');
      // Only <symbol> elements (shapes) are adopted from the parsed file.
      for (const symbol of parsed.querySelectorAll('symbol[id^="i-"]')) sprite.append(document.importNode(symbol, true));
      document.body.prepend(sprite);
    } catch { /* Offline or blocked: controls keep their text labels. */ }
  }
  window.consoleIcons = Object.freeze({make, decorate});
  document.addEventListener('DOMContentLoaded', () => { decorate(); void load(); });
})();
