/* Display-only number formatting. Stored and transported values are never changed;
 * callers keep the exact value available (title/tooltip) whenever the display differs. */
(() => {
  'use strict';
  // Up to four decimals for ordinary magnitudes; four significant digits for tiny or
  // huge values, where fixed decimals would hide the value entirely.
  function format(value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || Number.isInteger(value)) return String(value);
    const size = Math.abs(value);
    if (size < 1e-3 || size >= 1e9) return String(Number(value.toPrecision(4)));
    return String(Number(value.toFixed(4)));
  }
  const exact = value => String(value);
  window.consoleNumbers = Object.freeze({format, exact, differs: value => format(value) !== exact(value)});
})();
