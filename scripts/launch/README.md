# `scripts/launch/`

Maintained chain launcher, shared argument construction, source-authority
probe, and auto-resume inspection. Use an explicit checkout and its own
`.venv`. The launcher verifies that its Python environment imports that checkout
before inspecting run state or starting an iteration.

For an optional fresh foreground chain whose selected settings are checked
again at launch and before every iteration, use the
[native capture walkthrough](../../src/tools/native_chain/README.md).
Ordinary chain execution and automatic resume keep their existing behavior.
