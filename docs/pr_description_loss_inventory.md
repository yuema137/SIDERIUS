# feat(loss_inventory): enable agent-generated custom loss functions (Checkpoint L)

## Summary

This PR adds a complete end-to-end pipeline for the agent to discover bottlenecks in built-in loss functions, propose novel custom losses grounded in lit-review findings (or operator advice), generate and validate the loss plugin code, register it for cross-iteration reuse, and train under it via the tuner planner. Closes the gap identified at Checkpoint S where 93% of lit-review findings recommended loss-function changes the system could not act on.

## Merge policy

Gate 1 is complete (✅). Gate 2 and Gate 3 are currently running (launched
2026-06-23, HEAD `84a3caf`). This PR is ready to review now:

- If Gate 2/3 pass cleanly → sign-off doc is filled in and this PR merges as-is
- If Gate 2/3 reveal small fixes (e.g. tuner schema validator asymmetry already
  identified in post-run audit) → fixes land as additional commits on this PR
  before merge
- If Gate 2/3 reveal a major architectural gap (e.g. facilitator layer needed) →
  that work opens a separate PR; this PR merges with a note in the sign-off doc
  recording the gap and its planned resolution

Reviewers do not need to wait for Gate 2/3 to review the L1–L6 implementation,
I1–I11 fixes, or test coverage.

## Feature surface (L1–L6)

| Commit group | Adds | Key commits |
|---|---|---|
| **L1** — CapabilityRegistry + loss-plugin loader + sandbox wiring | `agent_generated/_registry.py`, `agent_generated/_loss_loader.py`, `SIDERIUS_LOSS_DIRS` env-var threading | `0a897aa`, `1e5a99d` |
| **L2** — LossConfig "custom" type | Adds `"custom"` to `LossConfig.loss_type` literal + `loss_name` field; extends `get_criterion()` routing | `076710e` |
| **L3** — ProposalOutput/ImplementorIO schema | `CustomLossSpec` on `ProposalOutput`; `LossProvenance` + `loss_dir` on Implementor IO; protocol wiring | `a2ea559`, `b667316`, `8b30294` |
| **L4** — Loss-plugin template + implementor orchestration | Plugin template + 3-stage loss-generation prompts; `_generate_loss()`; dummy-tensor `backward()` validator | `57029ea`, `5292a77` |
| **L5** — Proposer registry awareness | Registry-aware `proposing_stage.md`; node-level `render_available_losses()` + template_vars wiring | `d00bf22`, `36ef617` |
| **L6** — Tuner registry awareness + loss-file propagation | `_register_plugin` now copies the loss plugin file (`dest_loss_dirs`); `PLANNER_PROMPT` gets `{available_losses_block}` + `loss_type="custom"` permission in loss_note branches | `6837020`, `cb5222b` |
| **Checkpoint L hardening** | Phantom Branch B closed at three layers (proposer agent extraction, schema validator, prompt clarification); lit-review-driven advice override | `a421192`, `84a3caf` |

## Issues fixed during Checkpoint L (I1–I11)

Full root-cause analyses with SHAs in `docs/design/enable_loss_inventory.md` § "Issues discovered during Checkpoint L execution (2026-06-22/23)".

- I1 — harness tmpfs exhaustion from `tee` (`b7fb000`)
- I2 — HDF5 cleanup not in try/finally → ~80 GB leak on inference OOM (`a13778a`)
- I3 — formal round had no time budget (`2c9e375`, `a59cd45`)
- I4 — `--ml_lit_review_enabled` not forwarded by bash wrapper (`d96a6e5`)
- I5 — `lit_review_config.yaml` default `enabled: true` silently activated lit-review (`7f29351`)
- I6 — Rule 9 prompt did not forbid Branch B with empty registry (`ac35b07`)
- I7 — implementor did not validate Branch B `loss_name` exists in registry (`ac35b07`)
- I8 — proposer agent silently dropped `custom_loss_spec` from LLM raw output, the L3 regression (`a421192`)
- I9 — tuner planner had no registry awareness, "Bug A" (`cb5222b`)
- I10 — `_register_plugin` did not propagate the loss plugin file, "Bug B" (`6837020`)
- I11 — advice config did not handle concurrent-run registry pollution (`84a3caf`)

## Gate results

| Gate | Status |
|---|---|
| Gate 1 — Real LLM + pseudo training, 3 variants (`expected_value_mse`, `ordinal_ce`, `emd_ordinal`) | ✅ PASSED (2026-06-22) — all three loss plugins compiled, `backward()` check green, `ordinal_ce` self-corrected one `.detach()` hallucination |
| Gate 2 — Real LLM + real training, no lit-review | ✅ **PASSED** (2026-06-24, HEAD `ec03d79`) — iter_001 score `0.5594`, iter_002 score `0.4429`, 3/4 configs trained under custom loss (`expected_value_mse`), iter_002 Branch B reuse via promoted global path |
| Gate 3 — Real LLM + real training + lit-review (full closed loop) | ✅ **PASSED** (2026-06-24, HEAD `ec03d79`) — iter_001 score `0.5134`, iter_002 score `0.8090`, **4/4 configs trained under custom loss**, iter_001 generated lit-review-grounded `spectral_expected_value_mse` citing `arxiv:2512.14078` verbatim, iter_002 Branch B reuse — first end-to-end success of the proof-of-loop |

## Test coverage

- **Workflow units**: 168/168 pass
- **Proposer + schema units**: 553/553 pass (covers new `_validate_branch_b_registry_membership` validator with 5 hand-tested branches)
- **Tuner + bridge + planner-prompt units**: 1054/1054 pass (covers L6b prompt rendering with empty vs populated registry)
- **Implementor units**: existing suites green; Branch B validator covered
- **ruff + ruff format --check + pyright**: clean across all modified Python files

## Out of scope (deferred)

- `siderius capabilities list` CLI — by design (see § Scope in design doc)
- Loss hyperparameter tuning for custom losses (open question 1 in design doc)
- Loss versioning across iterations (open question 2)
- Tuner-side schema-level registry-membership check on `loss_name` (audit identified asymmetry vs proposer; tracked for follow-up; not blocking — runtime path in `_load_custom_loss` does its own check)
