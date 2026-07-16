# M7 — Loss-Implementor Contract Fix — Execution Plan

- **Status**: draft
- **Scope**: **generic** (framework bug fix)
- **Owner**: TBD
- **Created**: 2026-07-16
- **Last Updated**: 2026-07-16
- **Parent design**: none (this is a bug fix, not a designed feature) — but see [`docs/design/collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md) §7 for the phantom-filter pattern from which the fix draws inspiration
- **Tracks**: issue #112, [`v17_priorities.md`](./v17_priorities.md) MUST-fix **M7**

## 1. Purpose

M7 fixes the loss-implementor contract violation discovered during
PR #101 Gate 2 execution (2026-07-15): the proposer emits a
`custom_loss_name` but the implementor is not invoked (or its output
is not visible at training time), so every training subprocess aborts
with:

> `ValueError: Custom loss 'X' not found in LOSS_REGISTRY or agent_generated/losses/. Run the implementor first to generate the loss plugin`

This is a **bug fix**, not a designed feature — the exact fix shape
depends on the root cause investigation in §3.1-3.2 below. This doc
is the executable roadmap for the investigation + fix + validation.

## 2. Preconditions

- [ ] PR #114 merged (design docs on master, status `active`) — **DONE** as of `e1244ea`
- [ ] Access to the PR #101 Gate 2 failure workspace preserved for
      forensic reference (or ability to reproduce)
- [ ] Reproducer confirmed: running Gate 2 WITHOUT
      `advice/workflow/gate2_smoke_advice.json` (allowing custom loss
      proposals) reliably reproduces the ValueError. Record the exact
      command that reproduces:
      ```bash
      bash sdsc_submission_scripts/run_chain.sh \
          --mode lilab \
          --workspace /tmp/m7_repro_$(date +%s) \
          --run_name m7_repro \
          --num_iterations 1 \
          --max_rounds 2 \
          --max_epochs 1 \
          --trial_portion 0.02 \
          --train_portion 0.02 \
          --eval_portion 0.02 \
          --trial_time_budget_minutes 5 \
          --no-force_formal_round \
          --formal_time_budget_minutes 30 \
          --llm_config llm_configs/openai_tiered_v1.json \
          --seed_paths \
              /home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
              /home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
      ```
- [ ] Baseline test count captured (for Gate G4)

## 3. Execution checklist

### 3.1 Investigation — trace the proposer → implementor → training subprocess handoff path

- [ ] Identify where the proposer emits `custom_loss_name` in the
      `ProposalOutput` schema (`agent/schemas/proposal.py`) — capture
      the field name and its Pydantic validator
- [ ] Identify where the implementor is (or is not) invoked in
      response — trace through `workflows/model_exploration.py` and
      `nodes/ml_model_implementor/`
- [ ] Identify where the training subprocess is launched — trace to
      `nodes/ml_hyperparameter_tune_agent/` and `execute_tools/`
- [ ] Report the exact root cause **verbatim** before proposing a fix
      (paste code snippets, no summarisation). Answer:
  - Does the workflow call the implementor for the loss plugin? Where?
  - If yes, why is the plugin missing at training time? (path issue?
    subprocess env? capability registry pointing at wrong dir?)
  - If no, is this by design (planned optional path) or a bug in the
    workflow's proposer-to-implementor edge?
- [ ] Cross-reference with the earlier session note in
      [`v17_priorities.md`](./v17_priorities.md) MUST-fix **M7** (root-
      cause hypothesis: capability index advertises losses whose file
      paths point to old run-workspaces, not to `agent_generated/losses/`)
      — confirm or refute

### 3.2 Design decision point

Based on §3.1 findings, choose ONE:

- [ ] **Option A**: auto-invoke — the workflow always calls the loss
      implementor whenever the proposer emits a `custom_loss_name`
      that is not already in the runtime `LOSS_REGISTRY`. Fix goes in
      `workflows/model_exploration.py`.
- [ ] **Option B**: forbid — the proposer is prevented from proposing
      a `custom_loss_name` that references an unimplemented loss.
      Modify `ProposalOutput` Pydantic validator (proposal.py) to
      raise if `custom_loss_name is set AND not in known LOSS_REGISTRY`,
      forcing the LLM to re-plan.
- [ ] **Option C**: hybrid — validate at proposal time (Option B) AND
      auto-fallback to invoke the implementor if the validation fails
      but the loss is well-defined per its spec.

Record the chosen option + rationale in this section before
proceeding to §3.3.

### 3.3 Implement the chosen fix

Skeleton per option (fill in after §3.2 decision):

**If Option A**:
- [ ] In `workflows/model_exploration.py`, add a step between proposer
      and tuner: `if proposal.custom_loss_name not in loss_registry:
      invoke_implementor(proposal.custom_loss_spec)`
- [ ] Ensure the implementor's output plugin file is placed under
      `agent_generated/losses/` (not a run-workspace path)
- [ ] Update capability index (`agent_generated/_capability_index.json`)
      to point at the new plugin

**If Option B**:
- [ ] Add `_validate_loss_name_in_registry` model_validator to
      `ProposalOutput` in `agent/schemas/proposal.py` — reject
      `custom_loss_name` that isn't in the registry passed via
      Pydantic context
- [ ] Wire the context from the proposer node
      (`nodes/ml_model_proposal_agent/`)

**If Option C**:
- [ ] Both of the above, plus fallback logic in the workflow

### 3.4 Unit tests

Create `tests/unit/nodes/ml_model_implementor/test_loss_contract_m7.py` (Option A/C)
or `tests/unit/agent/schemas/test_proposal_loss_validator_m7.py` (Option B/C). Required cases:

- [ ] `test_proposal_with_registered_loss_passes` — proposal referencing an already-registered loss name passes without issue
- [ ] `test_proposal_with_new_loss_name_and_spec_triggers_implementor` (Option A/C) — asserts the implementor is invoked
- [ ] `test_proposal_with_new_loss_name_without_spec_rejected` (Option B/C) — validator raises with actionable message
- [ ] `test_implementor_output_lands_in_global_loss_dir` (Option A/C) — plugin file appears under `agent_generated/losses/`, not a workspace path
- [ ] Regression: `test_existing_proposals_still_valid` — a corpus of proposals from prior chain runs still passes validation

### 3.5 Integration test

- [ ] Create `tests/integration/workflows/test_m7_loss_implementor_end_to_end.py`:
  - Run a mini chain where the proposer proposes a NEW custom loss
    (with a well-formed `custom_loss_spec`)
  - Assert EITHER (Option A/C): the implementor generates the plugin
    before training and the training subprocess does NOT hit the
    "Custom loss not found" error
  - OR (Option B): the proposal is rejected before the training
    subprocess launches, with a clear failure_reason that names the
    missing loss

## 4. Validation gates

### Gate G1 — After §3.3 (fix implemented)

Run the specific reproducer from §2:

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/m7_verify_$(date +%s) \
    --run_name m7_verify \
    --num_iterations 1 \
    --max_rounds 2 \
    --max_epochs 1 \
    --trial_portion 0.02 \
    --train_portion 0.02 \
    --eval_portion 0.02 \
    --trial_time_budget_minutes 5 \
    --no-force_formal_round \
    --formal_time_budget_minutes 30 \
    --llm_config llm_configs/openai_tiered_v1.json \
    --seed_paths \
        /home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
        /home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
```

Verify the ValueError is gone (chain either completes rounds
successfully or fails cleanly on a DIFFERENT reason — e.g. the
proposal is rejected before training launches).

### Gate G2 — After §3.4 (unit tests)

```bash
python -m pytest tests/unit/nodes/ml_model_implementor/ tests/unit/agent/schemas/ -k m7 -v
```
Expected: all M7-tagged tests pass.

### Gate G3 — After §3.5 (integration test)

```bash
python -m pytest tests/integration/workflows/test_m7_loss_implementor_end_to_end.py -v
```
Expected: all tests pass.

### Gate G4 — Full regression

```bash
python -m pytest tests/unit/ tests/integration/ -q
```
Expected: no new failures vs the master baseline captured in §2.

### Gate G5 — Real-run validation (mandatory before marking Done)

Re-run Gate 2 **WITHOUT** the `gate2_smoke_advice.json` constraint
(i.e., allow custom losses in the proposer):

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/m7_gate2_$(date +%s) \
    --run_name m7_gate2 \
    --num_iterations 2 \
    --max_rounds 2 \
    --max_proposal_attempts 3 \
    --max_epochs 1 \
    --trial_portion 0.02 \
    --train_portion 0.02 \
    --eval_portion 0.02 \
    --trial_time_budget_minutes 5 \
    --no-force_formal_round \
    --formal_time_budget_minutes 30 \
    --llm_config llm_configs/openai_tiered_v1.json \
    --seed_paths \
        /home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
        /home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
```

Assert:

- [ ] The chain does NOT hit the error `ValueError: Custom loss 'X' not found in LOSS_REGISTRY or agent_generated/losses/` at any point
- [ ] Chain exits 0 with either successful rounds OR cleanly rejected proposals (no framework crashes)
- [ ] The five original Gate 2 pass criteria (see [`docs/gates/gate_testing_standard.md`](../gates/gate_testing_standard.md)) still hold

**Anti-hallucination check**: paste into the M7 completion note:
(a) the exact `ValueError` message that would have appeared before the fix (quoted verbatim from the pre-fix Gate 2 log), (b) confirmation from the actual post-fix log that this exact string does NOT appear — via a `grep -c "Custom loss" <log>` count of 0 or by explicitly showing the absence.

## 5. Definition of Done

- [ ] All checklist items in §3 marked `[x]`
- [ ] All 5 validation gates pass with evidence recorded
- [ ] PR opened, CI green, merged to master
- [ ] Issue **#112** closed with reference to the merge commit SHA
- [ ] `docs/design/v17_priorities.md` M7 row updated to note the
      closing PR / commit
- [ ] `advice/workflow/gate2_smoke_advice.json` retirement candidate
      identified (per its `_meta.lifecycle` field). Either delete it
      or update the `lifecycle` note to reflect resolution
- [ ] Consider whether the fix satisfies the intent of open-question
      note in `docs/design/tidmad_collapse_advice_and_forensics.md`
      §4.4 (row about custom losses) — update that table if the failure
      mode is now precluded by the fix

## 6. Open questions / risks

- Depending on the Option (A/B/C) chosen in §3.2, the fix scope varies
  significantly. Option A adds a runtime step; Option B adds only a
  schema validator. Prefer the smallest fix that eliminates the bug.
- The user-facing failure message in Option B must be actionable —
  the LLM proposer must be able to recover on re-plan. Consider
  what pattern of failure_reason best steers the LLM (test empirically
  with a small chain).
- Concurrency: if two chains run in parallel and both propose the same
  new custom loss, Option A may race on the plugin file write. Assess
  whether locking or atomic-rename is needed.
- The capability index update (`agent_generated/_capability_index.json`)
  is currently the workflow's responsibility. Confirm the update
  happens transactionally with the plugin file write, or add an
  idempotency guard.

## 7. Related docs

- **Priorities**: [`docs/design/v17_priorities.md`](./v17_priorities.md) MUST-fix **M7**
- **Advice workaround**: `advice/workflow/gate2_smoke_advice.json` — the current bypass, to be retired after this fix
- **Sibling execution plans**:
  - [`m1_file_vector_dedup_execution_plan.md`](./m1_file_vector_dedup_execution_plan.md) — orthogonal detection work; unblocked by M7 for realistic chain runs
  - [`m4_phantom_score_table_execution_plan.md`](./m4_phantom_score_table_execution_plan.md) — orthogonal; benefits from M7 for cataloguing phantoms in unrestricted chains
- **Related HealthGate framework**: [`pluggable_health_checks.md`](./pluggable_health_checks.md) — the framework this fix restores full utility for
- **Design pattern inspiration**: [`collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md) §7 — bad-vs-good example of config-injected vs hardcoded task specificity (M7's Option B echoes this pattern for loss registration)
