/* Save outcome wording and the conflict card's line diff (red-team S-2..S-5).
 * Pure presentation: editor.js owns every request, the draft and the conflict state.
 * - failure(error): one plain sentence per save refusal. A 4xx reply means the server
 *   refused before writing (workflow_authoring.service); anything else (5xx, an
 *   unreadable reply, no reply) leaves the outcome unknown, and editor.js re-reads the
 *   file to find out instead of guessing.
 * - lineDiff(before, after): a unified diff with three context lines, never a dump of
 *   both files. */
(() => {
  'use strict';
  const sentence = text => {
    const value = String(text || '').trim().replace(/[.;:,]+$/, '');
    return value ? value[0].toUpperCase() + value.slice(1) + '.' : '';
  };
  // Refusals whose own server message is not yet a plain sentence for this step.
  const PLAIN = {
    busy: 'Not saved: another save of this workflow is in progress. Try again in a moment.',
    validation: 'Not saved: the server refused the request (check the version name).',
    proposal: 'Not saved: the checked file changed before saving. Press Save to check it again.'
  };
  /** {known: true, message} when nothing was written; {known: false, reason} otherwise. */
  function failure(error) {
    const status = Number(error?.status) || 0;
    if (status >= 400 && status < 500) {
      if (status === 401) return {known: true, message: 'Not saved: the connection was lost. Reconnect, then save again.'};
      const plain = PLAIN[error.code];
      if (plain) return {known: true, message: plain};
      const text = sentence(error.message);
      return {known: true, message: /^not saved\b/i.test(text) ? text : `Not saved. ${text}`};
    }
    const reason = status >= 500 ? `The server failed (error ${status})`
      : error instanceof SyntaxError ? 'The server sent an unreadable reply'
      : 'The console did not answer';
    return {known: false, reason};
  }

  /** Unified diff of two texts (three context lines); identical texts give ''. */
  function lineDiff(before, after, labels = ['saved version', 'on disk now']) {
    const a = before.split('\n'), b = after.split('\n');
    let start = 0;
    while (start < a.length && start < b.length && a[start] === b[start]) start++;
    let endA = a.length, endB = b.length;
    while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA--; endB--; }
    if (start === endA && start === endB) return '';
    // Longest common subsequence of the changed middle; a very large middle is one replacement.
    const n = endA - start, m = endB - start, ops = [];
    for (let i = 0; i < start; i++) ops.push([' ', a[i]]);
    if (n * m <= 4e6) {
      const table = new Uint32Array((n + 1) * (m + 1)), at = (i, j) => i * (m + 1) + j;
      for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) {
        table[at(i, j)] = a[start + i] === b[start + j] ? table[at(i + 1, j + 1)] + 1 : Math.max(table[at(i + 1, j)], table[at(i, j + 1)]);
      }
      let i = 0, j = 0;
      while (i < n || j < m) {
        if (i < n && j < m && a[start + i] === b[start + j]) { ops.push([' ', a[start + i]]); i++; j++; }
        else if (j < m && (i === n || table[at(i, j + 1)] >= table[at(i + 1, j)])) { ops.push(['+', b[start + j]]); j++; }
        else { ops.push(['-', a[start + i]]); i++; }
      }
    } else {
      for (let i = start; i < endA; i++) ops.push(['-', a[i]]);
      for (let j = start; j < endB; j++) ops.push(['+', b[j]]);
    }
    for (let i = endA; i < a.length; i++) ops.push([' ', a[i]]);
    // Hunks: changed lines plus up to three unchanged lines around them.
    const keep = ops.map(() => false);
    ops.forEach(([kind], index) => { if (kind !== ' ') for (let k = Math.max(0, index - 3); k <= Math.min(ops.length - 1, index + 3); k++) keep[k] = true; });
    const out = [`--- ${labels[0]}`, `+++ ${labels[1]}`];
    let lineA = 1, lineB = 1, index = 0;
    while (index < ops.length) {
      if (!keep[index]) { if (ops[index][0] !== '+') lineA++; if (ops[index][0] !== '-') lineB++; index++; continue; }
      const hunk = [], fromA = lineA, fromB = lineB;
      while (index < ops.length && keep[index]) {
        const [kind, text] = ops[index]; hunk.push(kind + ' ' + text);
        if (kind !== '+') lineA++; if (kind !== '-') lineB++; index++;
      }
      out.push(`@@ -${fromA},${lineA - fromA} +${fromB},${lineB - fromB} @@`, ...hunk);
    }
    return out.join('\n');
  }

  window.editorSaveOutcome = Object.freeze({failure, lineDiff, sentence});
})();
