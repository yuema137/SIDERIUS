/* The one browser wording of the GPU requirement (issue #1136): Run review
 * (reusable-run.js) and the Task tab (task-tab.js) read it from here.
 * Presentation only; core/gpu_requirement.py owns the launch refusal itself. */
(() => {
  'use strict';
  window.consoleCompute = Object.freeze({
    gpuWarning: 'This task does not pass a GPU into the run sandbox; runs that train a model will be refused.',
    // A GPU device node of a core/gpu_devices.py provider passes a GPU (/dev/nvidia<N>,
    // or /dev/dxg under WSL2); /dev/nvidiactl alone does not. Kept equal to the
    // providers by tests/unit/core/test_gpu_devices.py.
    gpuDevices: devices => devices.filter(device => /^\/dev\/(?:nvidia[0-9]+|dxg)$/.test(device))
  });
})();
