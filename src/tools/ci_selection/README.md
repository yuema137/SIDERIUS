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

Changes under `src/agent/prompt_templates/` also run the full unit suite. For
example, the proposal loader computes a stage's filename at runtime, so import
analysis cannot link every template file to the tests that render it. Running the
full suite costs more time but keeps those tests and the packaging checks covered.
The manifest also declares the resource directories scanned by the packaging
check, so changes to nested node Markdown and other packaged assets select it.

See [the parent guide](../README.md) for child ownership and the focused validation route.
