/* The one browser wording of the GPU requirement (issue #1136): Run review
 * (reusable-run.js) and the Task tab (task-tab.js) read it from here.
 * Presentation only; core/gpu_requirement.py owns the launch refusal itself. */
(() => {
  'use strict';
  window.consoleCompute = Object.freeze({
    gpuWarning: 'This task does not pass a GPU into the run sandbox; runs that train a model will be refused.',
    // Only a numbered device node passes a GPU; /dev/nvidiactl alone does not.
    gpuDevices: devices => devices.filter(device => /^\/dev\/nvidia\d+$/.test(device))
  });
})();
