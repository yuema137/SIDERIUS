# tests/integration/execute_tools

These tests cover execute-tools checkpoint boundaries: real subprocess profile
transport and a CUDA-only checkpoint-memory measurement. The transport tests
use tiny synthetic HDF5; memory and training routes are skipped/opt-in by
their markers and never imply a normal CI run.

## Source and route

`.venv/bin/python -m pytest tests/integration/execute_tools/test_inference_checkpoint_memory.py -q`

Owner: `src/execute_tools/`; inspect each module marker before invoking a
subprocess, CUDA, or real-training route. See the [integration map](../README.md).
