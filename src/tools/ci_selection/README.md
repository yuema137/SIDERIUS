# src/tools/ci_selection

The selection CLI is `python -m tools.ci_selection`; `manifest.py` declares
ownership/dependency mappings and `resolver.py` derives affected tests from the
changed paths. Unknown impact fails closed to broader validation. Focused tests
are in `tests/unit/tools/ci_selection/test_selection_model.py`.

Changes under `examples/`, `configs/task_composition/`, or
`tests/fixtures/step10_p1/` run the full unit suite.
Tests elsewhere compose these files and fingerprint their contents through
manifests, so Python import analysis alone can miss affected tests. This also
covers task templates, console bundles, composition fixtures and their non-Python
assets.

See [the parent guide](../README.md) for child ownership and the focused validation route.
