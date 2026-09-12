# src/tools/ci_selection

The selection CLI is `python -m tools.ci_selection`; `manifest.py` declares
ownership/dependency mappings and `resolver.py` derives affected tests from the
changed paths. Unknown impact fails closed to broader validation. Focused tests
are in `tests/unit/tools/ci_selection/test_selection_model.py`.

See [the parent guide](../README.md) for child ownership and the focused validation route.
