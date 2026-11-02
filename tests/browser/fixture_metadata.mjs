/** Startup protocol shared with fixture_metadata.py; ordinary stdout is never metadata. */
import {createInterface} from 'node:readline';

const marker = 'SIDERIUS_BROWSER_METADATA ';

/** @param {import('node:child_process').ChildProcess & {stdout: import('node:stream').Readable}} child
 * @param {{timeoutMs?: number}} options
 * @returns {Promise<Record<string, any>>}
 */
export function waitForMetadata(child, {timeoutMs = 30000} = {}) {
  return new Promise((resolve, reject) => {
    const lines = createInterface({input: child.stdout});
    const timer = setTimeout(() => finish(new Error('Fixture metadata startup timeout')), timeoutMs);
    function finish(error, metadata) {
      clearTimeout(timer);
      lines.removeAllListeners();
      lines.close();
      child.off('error', onError);
      child.off('close', onClose);
      // Keep draining logs so a live server cannot block on a full stdout pipe.
      child.stdout.resume();
      if (error) reject(error);
      else resolve(metadata);
    }
    function onError() { finish(new Error('Fixture failed to start')); }
    function onClose(code, signal) { finish(new Error(`Fixture closed before metadata (${code ?? signal})`)); }
    function onLine(line) {
      if (!line.startsWith(marker)) return;
      let metadata;
      try { metadata = JSON.parse(line.slice(marker.length)); }
      catch { finish(new Error('Fixture emitted malformed metadata JSON')); return; }
      if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
        finish(new Error('Fixture metadata must be an object')); return;
      }
      finish(null, metadata);
    }
    lines.on('line', onLine);
    lines.once('close', () => finish(new Error('Fixture stdout ended before metadata')));
    child.once('error', onError);
    child.once('close', onClose);
    if (child.exitCode !== null || child.signalCode !== null) onClose(child.exitCode, child.signalCode);
  });
}
