# `tools/` — framework developer tooling

**Audience**: framework developers maintaining deterministic checks and
developer-facing utilities.

This package contains importable tooling that supports the checkout, including
CI selection and execution helpers. It is not a task package and does not own
scientific data, generated models or run workspaces.

The maintained operator scripts that launch or inspect runs remain under
[`scripts/`](../../scripts/README.md); workflow behavior belongs to
[`workflows/`](../workflows/README.md). Follow each tool's module documentation
for its inputs and failure behavior.

All paths are derived from the current checkout or supplied explicitly. Tools
must not edit the checkout as a substitute for caller-owned task configuration.

[`workspace_sandbox`](workspace_sandbox/README.md) is an optional operator entry
for isolated orchestration commands. It does not alter existing workflow launches.
