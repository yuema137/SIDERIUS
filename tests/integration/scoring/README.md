# tests/integration/scoring

Legacy scoring parity compares the retained scoring route with its historical
reference on synthetic inputs. It catches arithmetic/order drift; no provider,
GPU, or external dataset is required.

## Source and route

`.venv/bin/python -m pytest tests/integration/scoring/test_legacy_parity.py -q`

Owner: `src/execute_tools` scoring/metric modules. See the [integration map](../README.md).
