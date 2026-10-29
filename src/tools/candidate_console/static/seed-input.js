/* Optional run-seed input (issue #983). Blank means SIDERIUS generates one at launch.
 * The server validates the range again; this only keeps a typo from becoming a request. */
(() => {
  'use strict';
  const MAX = Number.MAX_SAFE_INTEGER; // 2**53 - 1, the run-seed upper bound.
  // Returns {ok, value}: value is undefined for blank, else an exact integer.
  function parse(text) {
    const raw = String(text ?? '').trim();
    if (!raw) return {ok: true, value: undefined};
    const value = Number(raw);
    return /^\d+$/.test(raw) && Number.isSafeInteger(value) && value <= MAX ? {ok: true, value} : {ok: false};
  }
  const message = `Seed must be blank or a whole number from 0 to ${MAX}.`;
  window.consoleSeed = Object.freeze({parse, message});
})();
