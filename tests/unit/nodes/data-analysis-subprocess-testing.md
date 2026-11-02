# Data-analysis subprocess fixture allocations

Scope: successful data-analysis integration witnesses with synthetic providers
and real CPU worker processes. `tests/helpers/data_analysis_resources.py` owns
these test-only allocations: 30 seconds per worker and 120 seconds for the
shared `_input` pipeline. They are caller declarations, not framework defaults.

A reference invocation starts separate interface-resolution, parameter-validation,
and execution workers. Python startup, imports, scheduling and filesystem work
consume the same declared budgets as scientific execution. The previous 5-second
worker / 15-second pipeline fixture could expire before the behavior under test;
a controlled 6-second delay before worker startup reproduces that failure.
The successful-pipeline witness retains real subprocesses and evidence checks,
including publication, typed proposer evidence, cleanup, reuse and canonical-input
conflict rejection. Its delayed-start variant adds the delay to all three workers.
A second variant delays the generated-program runner inside the existing sandbox and retains
the generated-program evidence assertions; its old four-second request expires
and triggers a grounding retry because the expected measurement is absent.
The generated case retains the existing enforced-sandbox host prerequisite.

Generated-program fixture requests derive `wall_time_s` from the selected input's
`per_skill_timeout_s`. There is no additional independent 4-second or 10-second
request hiding below that allocation. Historical and workflow-specific inputs
retain their explicit whole-pipeline and per-worker declarations. Sampling-seed
fixtures inherit allocations from `_input` while changing only sampling policy.
Behavioral fixtures retain their 60/120/240-second whole-pipeline envelopes and
scientific trajectories; they share the real-worker allowance.

Deadline/refusal witnesses must declare their own small budgets explicitly.
`test_analysis_deadline_includes_llm_stages_and_refuses_late_report` retains a
15-second total / 5-second worker envelope and a synthetic 16-second late-stage
advance. Production `ExecutionDeadline`, worker termination and generated-program
sandbox enforcement are unchanged; no retry or skip compensates for timing.

These synthetic input changes alter test-only canonical input digests and
budget-bearing rendered prompts. Generated-program resource requests also alter
declaration identities and generation-prompt hashes. Generated code bytes and
production prompt templates, protection/assembly closures, and verifier/rendering
code identities remain unchanged. No supported paper-path configuration changes.

Validation covers the original 18-case issue selection, complete affected test
packages and helper consumers, dedicated deadline-refusal tests, and a startup
witness that fails with the old worker or pipeline allocation. A controlled
startup delay establishes the fixture timing defect; it does not prove every
historical broad-run failure had the same cause or guarantee arbitrary host load.
