# tests/integration/execute_tools

These tests cover execute-tools checkpoint boundaries: subprocess profile
transport, a tiny module-local synthetic-HDF5 CPU training route, and an
optional CUDA-only checkpoint-memory measurement. No shared pytest option
selects scientific data or a task-specific executor.

## Source and route

`.venv/bin/python -m pytest tests/integration/execute_tools/test_inference_checkpoint_memory.py -q`

Owner: `src/execute_tools/`; inspect each module marker before invoking a
subprocess or CUDA route. See the [integration map](../README.md).
