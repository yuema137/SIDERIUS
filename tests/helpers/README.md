# tests/helpers

Recording doubles and deterministic builders support composed workflow and
pseudo-data tests; changes must be checked through their consuming suites.

## Focused route

`.venv/bin/python -m pytest tests/helpers/test_recording_fakes.py -q`

This protects the recording/replay contract; see the [tests index](../README.md).

The [inference startup helper](inference_startup.py) builds checkpoint-bound
startup requests for CPU-only tests. Callers can choose a clock and budgets
separately, so they can test elapsed time without sleeping. Its consumers are
checked with:

```bash
.venv/bin/python -m pytest tests/unit/core/ tests/helpers/ -q
```

Run from the repository root using this checkout's development environment.
Success means valid receipts are accepted and late acknowledgments are refused;
no GPU training or live provider is involved.
