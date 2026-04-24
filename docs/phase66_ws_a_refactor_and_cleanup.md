# Phase 6.6 — WS-A Refactor & Cleanup (Follow-up)

**Status:** Scoped, paused. Unblocked post-WS-B.
**Author:** SIDERIUS core
**Date:** 2026-04-23 (split from parent).
**Parent:** `docs/phase66_deterministic_vram_and_hardening.md` — WS-A delivered the verified physical VRAM engine (Evidence Gate PASS at ±0.04% training / ±0.01% inference). This follow-up finishes the structural refactor + dead-code purge that was strategically deferred to prioritise the WS-B (Implementor/Proposer Hardening) transition. PR #1.1.
**Scope:** 5 items — A.6, A.7, A.9, A.15, A.16. None change the predicted numbers. All are architectural tidying + the PR ship event.
**Branch:** Resumes on `feat/deterministic-vram` after WS-B merges; ships as a single PR at A.16.

---

## 1. Inheritance

This doc does **not** re-state parent material. All of the following are load-bearing and must be re-read before starting work:

| Inherited from parent | Location | Why it still governs |
|---|---|---|
| **Design Principles 1–5** | §2 | No new principles; refactor operates under the existing ones (especially #2 no-model-name-branches and #5 no device literals). |
| **Architecture target** (5-file `evaluate_vram_skill/` layout) | §3.1 | A.6/A.7 complete the move of composition logic out of `wrapper.py` into the per-phase estimators named in §3.1. |
| **Wrapper return-dict contract** | §3.7 + `test_wrapper_contract.py` | Refactor MUST NOT change the return-dict shape. 19 contract tests pin it. |
| **Guardrail suite** | §5.4 + `tests/unit/guardrails/` | `_PENDING_CLEANUP` xfails convert to PASS automatically as A.6/A.7/A.9 land. No new guardrail added here. |
| **Evidence Gate** | §5.2 + Appendix A.2 | Cleanup is structural; the ±0.04% / ±0.01% residuals must be unchanged after A.6+A.7. Regression: re-run `docs/phase66_telemetry/evidence_gate_dynamic_depth_simple.py`; bytes must match Appendix A.2. |
| **File inventory (Appendix B)** | Appendix B | Authoritative list of files touched across the full phase. |

---

## 2. Scope

### A.6 — Extract `_compose_training_peak` into `training_skill/estimator.py`

**Current.** Training peak is composed inline in `agent/skills/evaluate_vram_skill/wrapper.py::_compose_training_peak` (saved_bytes + input + output + params + training_overhead + cuda_context + cudnn_backward). This "fat wrapper" shape was chosen in A.8 to unblock the A.14 Evidence Gate without pre-committing to an estimator-layer signature.

**Target.** `agent/skills/training_skill/estimator.py::estimate_peak_bytes` calls `probe_activation_footprint(mode="training")` + `phase_overhead_bytes(params, mode="training", optimizer=...)` + the two calibrated constants from `overhead.py`. The wrapper imports from the estimator instead of composing locally. `estimate_wall_time_seconds` is untouched.

**Invariants.** Appendix A.2 training residual stays at −0.04%. Guardrail `training_estimator` xfail → PASS.

### A.7 — Extract `_compose_inference_peak` into `inference_skill/estimator.py`

Symmetric to A.6. Current `_compose_inference_peak` (input + max(output_bytes, forward_output_bytes_max) + params + cuda_context) moves to `agent/skills/inference_skill/estimator.py::estimate_peak_bytes`. Wall-time untouched.

**Subtlety — the resolver needs more than an int.** The wrapper's `resolve_inference_batch` consults `forward_output_bytes_max` during its descending batch sweep. The refactored estimator must either (a) return a small frozen dataclass exposing both the peak and the `forward_output_bytes_max`, or (b) split into two functions. Decision deferred to implementation time — the right shape becomes clearer after A.6 lands.

**Invariants.** Appendix A.2 inference residual stays at −0.01%. Guardrail `inference_estimator` xfail → PASS.

### A.9 — Delete `core/inference_defaults.py`

The tuner passes `inference_batch` explicitly (A.11). The `inference_batch_for(model_type)` fallback in `sandbox_executor.execute_inference` is dead code in the production path — kept only to let intermediate-stage tests not break during the A.7 landing window.

**Order of operations:**
1. Delete `_INFERENCE_BATCH_SIZES` + `inference_batch_for` + `is_inference_batch_registered` + `assert_inference_batch_registered` from `core/inference_defaults.py`. Delete the file if nothing else remains.
2. In `sandbox_executor.execute_inference`: remove the import + the `None` fallback branch. `inference_batch=None` becomes a `ValueError` (fail-fast — Principle 2 for callers).
3. Update `tests/unit/core/test_sandbox_executor.py::TestExecuteInferenceBatch`: the "None falls back" case converts to "None raises ValueError". Three of the four existing tests survive verbatim.
4. Guardrail `inference_defaults` xfail auto-converts to PASS — `_iter_target_files` yields nothing for a missing file.

### A.15 — Mark `docs/resource_estimator_implement.md` superseded

One-line edit per affected section: `**Superseded by docs/phase66_deterministic_vram_and_hardening.md (2026-04-22)**` at section top. Scope per parent §1.1 supersede clause: §10.5, §10.14 Commits 2/3/5/K.2.5–8 (VRAM analytical formulas + inference-batch table). `estimate_wall_time_seconds` sections stay live — not touched by Phase 6.6.

Defer until A.6/A.7 land so the supersede note can reference the final estimator shape.

### A.16 — Self-review + open PR #1

After A.6/A.7/A.9/A.15 land, self-review the full `feat/deterministic-vram` branch against parent §6 PR #1 Reviewer checklist:
- Evidence Gate passes with logged numbers. ✅ (already done, Appendix A.2)
- Guardrail tests pass. ✅ (post-A.6/A.7/A.9 the three xfails convert to PASS)
- Return-dict schema is backward-compatible (only additive). Verify against `test_wrapper_contract.py`.
- `sandbox_executor.execute_inference` no longer reads `inference_defaults`. Verify A.9.

Open PR #1 as one cohesive WS-A story.

---

## 3. Sequencing gate

Work on A.6 must not begin until:
1. WS-B (parent §4, B.1–B.8) has merged to `master`.
2. Any estimator-layer design refinements surfaced during WS-B (e.g. a new named overhead term, a new probe hook) are reviewed and folded into §2 above.

This sequencing exists because fat-wrapper composition works — the Evidence Gate already proves it — and WS-B may surface one more design input that's cleaner to fold in before the estimator layer crystallises, rather than after.

---

## 4. Checklist

**Legend:** `[~]` = scoped, paused · `[ ]` = not started · `[x]` = landed.

- [~] A.6 Extract `_compose_training_peak` → `training_skill/estimator.py::estimate_peak_bytes`. Wall-time untouched. Evidence-gate invariant: training residual stays at −0.04%.
- [~] A.7 Extract `_compose_inference_peak` → `inference_skill/estimator.py::estimate_peak_bytes`. Wall-time untouched. Evidence-gate invariant: inference residual stays at −0.01%. Decide int vs dataclass return shape at implementation time.
- [~] A.9 Delete `core/inference_defaults.py` + sandbox `None` fallback path. Fail-fast on missing `inference_batch` kwarg.
- [~] A.15 Mark `docs/resource_estimator_implement.md` superseded per parent §1.1 scope clause.
- [~] A.16 Self-review + open PR #1 (full WS-A — landed work + this cleanup).

---

## 5. Invariants under refactor

The cleanup MUST NOT:
- Change Appendix A.2 numbers (regression check: re-run evidence gate after A.6 + A.7; training must land at 0.8228 GB, inference at 0.4211 GB — byte-exact).
- Introduce any model-name string (parent §5.4 guardrail).
- Introduce any device literal (parent §5.1 guardrail).
- Modify `estimate_wall_time_seconds` in either estimator.
- Change the wrapper's return-dict shape (parent §3.7 contract pinned by `test_wrapper_contract.py`; 19 tests).
- Change the `[Hardware]` log-line regime classifier (PHYSICAL / BUDGET / PHYSICAL VETO — pinned by `test_vram_budget_gb_cannot_exceed_physical_cap` and the two sibling tests).
