# `scripts/launch/`

Maintained chain launcher, shared argument construction, source-authority
probe, and auto-resume inspection. Use an explicit checkout and its own
`.venv`; #431 probe transport remains outside this infrastructure change.

For an optional fresh foreground chain whose selected settings are checked
again at launch and before every iteration, use the
[native capture walkthrough](../../src/tools/native_chain/README.md).
Ordinary chain execution and automatic resume keep their existing behavior.
