# P3-L2p Rev 4 — Citation-Reliability Pilot Protocol (DESIGN ONLY)

- **Status**: DRAFT — awaiting operator approval. **No launch from
  this document.** Launch requires an explicit, separate operator
  decision AFTER the production citation fix (PR 3 doc §12 option
  chosen by the operator) and the runner fixes (R-1..R-4) are
  implemented and deterministically validated.
- **Date**: 2026-07-29
- **Parents**: `pr3_l2p_calibration_protocol.md` (rev 2 + §19 + §21
  audit), report §13
  (`reports/pr3_structured_health_feedback_layer2_calibration_2026-07-29.md`).
- **This is NOT a Layer-2 behavioral campaign** and must not be
  interpreted as one. It answers exactly one operational question.

## 1. Question and endpoints

**Primary question**: after the production fix, is citation
reliability high enough to make a valid behavioral calibration
operationally possible?

**Primary endpoint (operational, not behavioral)**:
sample-level terminal `ProposalOutput` success rate.

**Secondary endpoints**: citation-validation failure rate (per attempt
and per sample, by malformed class); retries per sample (causal-stage
and proposing-stage separately); calls and dollars per valid sample;
citation provenance correctness on valid samples (deterministic audit
against fixture ground truth); artifact completeness (incl. the new
`run_status.json`); runner stop-condition enforcement; treatment
isolation and production-pipeline invariants (unchanged from rev 3).

**Explicit non-endpoints**: no efficacy estimation, no C-vs-T
behavioral comparison, no rubric adjudication (deterministic scorer +
citation audit only). Eight samples cannot support behavioral claims
and none will be made.

## 2. Design (smallest useful)

| Item | Value |
|---|---|
| Scenarios | **S1 only** (operator decision 2026-07-29: smallest useful initial design; S2 and any larger run are NOT to be added merely to obtain more samples if this gate fails) |
| Arms | Control (both flags OFF) and Treatment (both ON) — verifies reliability is arm-independent and isolation invariants hold; D arm dropped |
| Repetitions | 2 per arm → **4 samples** (S1_C_1, S1_C_2, S1_T_1, S1_T_2) |
| Nominal calls/sample | S1 = 4 (measured in rev 3: 1 interp + comparison + causal + proposing) |
| Nominal total | 4×4 = **16 calls** |
| Retry allowance | ≤2 additional retry calls per sample (structural and/or post-fix causal-validation retries combined) |
| **Hard call cap** | **24** (16 nominal + 8 retry allowance; worst case may truncate the final sample — R-3 marks it `aborted_incomplete`) |
| Estimated cost | nominal ≈ $3.20, cap-bounded worst ≈ $4.80 (rev-3 measured $0.20/call avg; re-check prices at launch) |
| Model config | frozen as rev 3: openai/gpt-5.5, provider defaults, version pinned from first response, drift = hard stop |
| Fixtures | `p3l2p-fixtures-2` with production vocab seed, hashes re-frozen at launch |
| Execution order (FROZEN) | S1_C_1, S1_T_1, S1_C_2, S1_T_2 — written to `launch_manifest.json` before call 1 |
| Artifacts | `reports/artifacts/pr3_l2p/pilot_rev4_<DATE>/` (per-sample bundle as rev 3 + `run_status.json` + archived launch command) |
| Report | `reports/pr3_citation_reliability_rev4_<DATE>.md` |
| Budget source | remaining Layer-2 allowance ($59.54 of the $80 cap as of 2026-07-29); ledger-enforced per call |

## 3. Pre-registered reliability gate (registered HERE, before any
execution — this document is committed before launch and not amended
mid-run; any mid-run change must be labelled a mid-run protocol
amendment and cannot count as confirmatory)

The gate PASSES only if ALL of:

1. Terminal success rate **≥ 80%** → with n=4 this means **4/4 valid**
   (3/4 = 75% fails the gate; stated explicitly to remove rounding
   discretion).
2. **≥ 1 valid sample in each arm** (C and T) — implied by 4/4, kept
   as an explicit condition in case of a truncated run.
3. **No dominant repeated citation-failure class**: no single
   malformed-id class (as classified in report §13.2) appears in ≥ 2
   samples.
4. **Corrected retry values preserved**: if any sample requires a
   citation-correction retry, the corrected values must appear in the
   final validated `ProposalOutput` (deterministic check against the
   retry response body) — the P-1 fix demonstrably working live.
5. **No provenance corruption**: deterministic citation audit on every
   valid sample matches fixture ground truth under the fixed contract
   (no legal-but-wrong attributions introduced by the fix, e.g. by any
   normalization).
6. **Complete artifacts**: every attempted sample has a full bundle or
   an explicit `aborted_incomplete` marker; `run_status.json` +
   `run_summary.json` written; launch command archived.
7. **Correct runner stop and exit-code behavior**: enforcement path
   proven by the zero-LLM preflight simulation; if a live stop
   triggers, it fires at the first eligible sample boundary; the
   wrapper preserves the process exit status.
8. **Treatment isolation exact**: the C-vs-T proposing-prompt
   difference is exactly the treatment block (rev-3 invariant,
   re-verified per sample).

Gate PASS → campaign re-sizing may be proposed (§5). Gate FAIL → stop;
re-audit; no further LLM spend without a new operator decision.

## 4. Preconditions (ALL required before the launch request)

1. Operator has chosen the production fix option (PR 3 doc §12) and
   the fix is implemented on the branch — stop-and-show rule applies.
2. Deterministic validation green: citation-contract tests (each §13.2
   malformed class rejected with instructive messages), prompt-render
   tests (worked examples present in causal + proposing stages),
   P-1 tests (malformed memo citation corrected within the
   causal-stage retry loop; proposing retry instruction satisfiable).
3. Runner fixes R-1..R-4 implemented with zero-LLM preflight proofs
   (simulated terminal failures trigger the stop at the right sample
   boundary; `run_status.json` outcome enum correct for completed /
   protocol_stop / budget_stop / technical_failure; abort marker
   written on simulated mid-sample cap; wrapper propagates exit
   status).
4. Rev-4 fixture hashes frozen and committed; this protocol committed.
5. Explicit operator launch approval referencing this document.

## 5. Stop conditions (frozen)

- Model-version drift → hard stop before pooling.
- Call cap 56 or dollar precheck → stop; in-flight sample marked.
- Protocol stop: floor-unattainability rule — the §3 gate becomes
  unreachable at the FIRST terminal failure (3/4 = 75% < 80%) → the
  runner stops at that sample boundary automatically (R-1). Remaining
  budget is not spent on samples that cannot change the verdict.
- Any newly discovered production defect → stop, audit-first workflow.
- Operator interrupt at any time.

## 6. After the pilot

- Gate PASS: propose (do not launch) a re-sized behavioral campaign
  using the measured post-fix success rate; the campaign needs its own
  operator authorization (calls + dollars) and remains subject to the
  standing rule against weakening statistical design to fit budget.
- Gate FAIL: verdict stays INCONCLUSIVE; findings feed the next
  audit round; merge options in report §10 unchanged.
- Either way: no P3-L3, no activation, no merge state change from this
  pilot alone.
