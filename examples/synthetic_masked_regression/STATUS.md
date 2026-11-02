# Status — L2

Core deterministic vertical slice implemented: fail-closed composition,
disjoint train/evaluation scopes, continuous model output, semantic masked
objective, source-aligned deliverable persistence, lower-is-better masked MSE,
observational masked MAE, task-owned Health with fixed PASS/FAIL controls, and
the isolated resource worker's task-valid batch boundary with explicit
full-batch acceptance and too-small-scope refusal evidence. The production
training engine completes one bounded CPU optimizer step over the real
``[truth, mask]`` supervision and persists the trained model. A deterministic
production-workflow witness traverses interpret, optional literature review,
propose, implement, validate, and tune with the composed manifest. Lit-review
ON uses an explicit non-default config and passes all four advisor channels;
OFF neither reads its configured path nor invokes the advisor. A record-level conflict control proves
that the lower-is-better masked MSE selects the winner while masked MAE remains
observational. Byte-identical package copies at unrelated checkout roots share
one semantic identity and resume one persisted workspace; a declared-plugin
edit moves the identity and refuses that workspace without modifying its lock.
The interpretation node also runs directly through its public typed contract
with no workflow state and, on the deterministic cold-start path, no LLM call.

The production isolated preflight is also physically qualified on an H100
80GB with matched admitted/refused controls; see
`expected/h100_resource_qualification.json`.

Not claimed: live LLM-agent execution or network literature retrieval by this
example. The workflow witness uses typed deterministic substitutes; real
training, scoring, Health, and GPU execution are covered independently.

`SyntheticMaskedTaskDataPath.validate_health_coverage` proves attempt coverage
for both manifests before composed, Health-enabled trial/formal execution.
It accepts only scopes whose rows belong to the configured evaluation shard
and include at least `MIN_HEALTH_VALID_ROWS` (two) valid rows. Smaller valid
selections, foreign-shard
rows, and `health_gate_files` overrides other than the singleton evaluation
shard are uncovered demand and cause `TaskHealthCoverageError` at the attempt
boundary. Full and sampled scopes follow the same rule. The positive dispersion
floor requires at least two valid predictions because population standard
deviation (`ddof=0`) is always zero for one sample. Coverage still does not
guarantee a passing dispersion verdict. The proof uses
scope metadata; disk/supervision consistency remains a materialization check.
Regression evidence: `tests/unit/examples/test_masked_health_coverage.py`.

## Sampling seed contract (#1169)

Scope and epoch subsampling now raise `core.seeding.MissingRunSeed` when the
caller omits the seed. Explicitly seeded results and fixed generated shard
bytes are unchanged. Editing `_masked_task.py` changes its content hash and
both shipped and modular composition fingerprints, so previous workspace
locks cannot resume against this revision. Archived qualification receipts
retain their original identities; this change claims no new GPU qualification.
Regression: `tests/unit/examples/test_example_sampling_seeds.py`.
