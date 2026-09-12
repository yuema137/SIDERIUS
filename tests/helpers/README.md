# tests/helpers

Recording doubles and deterministic builders support composed workflow and
pseudo-data tests; changes must be checked through their consuming suites.

## Focused route

`.venv/bin/python -m pytest tests/helpers/test_recording_fakes.py -q`

This protects the recording/replay contract; see the [tests index](../README.md).
