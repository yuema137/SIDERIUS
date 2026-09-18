# Artifact handoffs and concurrent calls

The caller may branch, repeat, overlap or stop calls. SIDERIUS does not provide a
new scheduler through this documentation. Independence of input evidence does
not establish independence of filesystem writes or GPU allocations.

Before overlapping calls, inspect each guide's output paths. Assign disjoint
call-owned workspaces and run names, and disjoint generated model, loss and test
paths where the API exposes them. A shared `workspace` with different names is
not sufficient when both calls write a shared cache, registry or generated
library. Import-time plugin registration and process environment changes are
also shared in a Python process. Separate processes isolate that state only;
they do not partition shared filesystem paths, VRAM, time, or permissions.

`core.generated_library.bind_generated_library_to_workspace(workspace)` binds
process environment and descendant discovery to a workspace. Call it before
registry-bearing imports in a fresh invocation process. It is not a context
manager and does not implement a lock. Do not race two calls that mutate one
library or publish into one mutable registry; any shared publication must use
the existing supported owner and be sequenced around those writes. This is a
resource conflict constraint, not a preference for a research workflow.

Local `StorageConfig` supplies the explicit persistence destination. Postgres
storage and `database_*` handoff protocols are placeholders at the reference
revision. Do not infer a supported channel from their schema presence.

Use the actual typed returned output as the source of a handoff. For recovery,
the caller may read its own persisted output, validate it using that output's
native class and then apply the existing typed protocol. A node's record file
is persistence, not an invitation for a peer node to scan it or discover a
"latest" result by filename. Preserve candidate IDs, composition fingerprints,
source artifact identities and output contracts. Do not repurpose the same
candidate identity for a different model because its display name is equal.

Explicitly record which completed output(s) supplied each new request. For
fan-in, use the existing evidence projections and compatible typed inputs from
[the handoff map](handoffs.md). Do not average metric scalars, overwrite Health
labels or join independently selected records to fabricate a winner. The
unchanged task evaluator owns ranking, scoreability and final eligibility.

Failed, partial and degraded outputs remain evidence with those statuses.
`ValidatorOutput.passed` gates the documented validated-model handoff; a schema
validating successfully does not prove the candidate passed its checks.
Retain the candidate material required by the common task even when an internal
tool defaults to cleanup. An incompatible retention route is a setup problem;
it does not relax the baseline final-delivery contract.
