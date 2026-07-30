# V19 Launch Protocol — Runtime-Control Settings (IMPLEMENTED, audit-backed)

- **Status**: IMPLEMENTED AND FROZEN (2026-07-29) — the §4 minimal
  split shipped as `2a5a330` (tests `5e787b2`, 14 deterministic
  proofs incl. V18 admission parity at the 60-min boundary); the
  eight-chain serial queue shipped as `c734ae1`
  (`sdsc_submission_scripts/v19_queue_runner.sh`, 13 tests, 8/8 chain
  dry-runs green). The executable launch plan is
  `reports/v19_20260729_2136.md` (on-disk report). LAUNCH REMAINS
  OPERATOR-GATED — nothing has been launched.
- **Scope of this draft**: only the trial/formal admission + watchdog
  settings. The remaining V19 launch configuration (§5) records the
  already-made operator decisions and their non-interaction with the
  watchdog change.

## 1. Audited V18/V18r effective values (source-cited)

| Phase | Admission | Watchdog | Runtime budget | Effective source |
|---|---|---|---|---|
| Trial | **record-only — never rejects** (`operator_budget_seconds=None` for trials: `ml_hyperparameter_tune_agent.py::_runtime_policy_dict`, ~line 1447 — `chosen_time_budget*60 if (not is_trial …) else None`; `decide_admission` with `budget is None` → always "admitted") | deadline = `max(120s floor, Σpredicted × 3.0)` — no budget term (None) | trial wall-time 20 min enforced by the TUNER round budget (`--trial_time_budget_minutes 20`), a separate pre-runtime-control mechanism | launch scripts (`launch_v18_wave1.sh:198-202`, `v18r_queue_runner.sh:75-79`): `--runtime_trial_safety_factor 3.0` |
| Formal | `Σpredicted_known_cost × 2.0 > 7200 s → REJECT` (`session.py::decide_admission:503-556`) ⇒ admits only predicted ≤ 60 min — exactly the `a780186` "tightened to ≤60 min" record | deadline = `max(120s floor, min(7200 s, Σpredicted × 2.0))` (`sandbox_executor.py::_watchdog_deadline_provider:408-438`) | `--formal_time_budget_minutes 120` → `operator_budget_seconds=7200` | launch scripts: `--runtime_formal_safety_factor 2.0` |

Fallbacks and defaults (declared vs configured vs effective):

| Setting | Schema default | Shell default | V18r launch value | When used |
|---|---|---|---|---|
| `runtime_safety_factor` (legacy/shared) | 1.0 (`hyperparam_tuning.py:1445`) | 1.0 (`_chain_common.sh:100`) | **1.5** (explicit) | only when the phase-specific factor is None — inert in V18r (both phase factors set) |
| `runtime_trial_safety_factor` | None (→ fallback) | "" (omit) | **3.0** (explicit; `d8d4f1e` raised 2.0→3.0) | every trial attempt |
| `runtime_formal_safety_factor` | None (→ fallback) | "" (omit) | **2.0** (explicit; `a780186`) | every formal attempt |
| watchdog enabled | False | 0 | **on** (`--runtime_watchdog`) | — |
| watchdog floor | 60 s | 60 s | **120 s** (explicit) | degenerate-estimate guard |

## 2. Audited formulas (code-traced)

- **Resolution** (`_runtime_policy_dict`): `effective = phase_factor if
  set else legacy_factor`; the resolved value is written to
  `RuntimeControlPolicy.safety_factor` — *"enforcement (admission +
  watchdog) reads this field only"* (schema docstring, `session.py:117`).
- **Admission** (`decide_admission`, post-setup + post-phase stages):
  `known_cost = Σ predicted_seconds of components WITH predictions`
  (setup's prediction = its measurement; grows as phases verify);
  reject iff `known_cost × safety_factor > operator_budget_seconds`
  (fail-closed also on verification failure); `budget=None` →
  record-only, always admit. Units: seconds. No clamping. Rejection is
  final (§3 lower-bound rule); an in-subprocess rejection consumes a
  tuner attempt.
- **Watchdog** (`_watchdog_deadline_provider`): `deadline =
  max(floor_seconds, min(operator_budget_seconds?, Σpredicted ×
  safety_factor))`, recomputed live from the observation sidecar (the
  deadline tightens as verification lands predictions); kill = TERM →
  10 s grace → KILL on the process group. Setup and verification time
  are inside the measured components (setup prediction = measurement;
  verification steps ARE the first production steps), so both formulas
  include them via `Σpredicted`.
- **Same factor in both mechanisms: YES — coupled by design** (single
  `safety_factor` per attempt). Trial and formal use the same
  formulas; they differ only through the resolved factor and the
  budget (None for trials).

## 3. Independence audit — HISTORICAL VERDICT: COUPLED (resolved by §4)

- Trial admission vs trial watchdog: same resolved factor, BUT trial
  admission is inert (no budget) ⇒ **trial watchdog 3.5 is achievable
  today** by setting `--runtime_trial_safety_factor 3.5` with no
  admission consequence.
- Formal admission vs formal watchdog: **genuinely coupled.** Setting
  `--runtime_formal_safety_factor 3.5` would set the watchdog margin
  to 3.5 AND change admission from `predicted ≤ 7200/2.0 = 60 min` to
  `predicted ≤ 7200/3.5 ≈ 34.3 min` — a MATERIAL TIGHTENING that
  violates the "admission unchanged from V18" requirement.
- Separate CLI flags for admission vs watchdog: **do not exist.**
- ⇒ **Design conflict (operator plan §5): honoring watchdog=3.5 for
  formals with V18 admission required a minimal configuration split —
  RESOLVED: the split is implemented and tested (§4, `2a5a330` +
  `5e787b2`); the coupled behavior above is preserved as the audit
  record of the PRE-SPLIT state and remains the exact fallback
  behavior when the new flag is omitted.**

## 4. Minimal split — IMPLEMENTED (`2a5a330`, tests `5e787b2`; the
text below is the approved design it implements)

Add an optional watchdog-only factor consumed exclusively by the
deadline provider; omitted → falls back to the effective
`safety_factor` → byte-identical V18 behavior:

- `WatchdogConfig.safety_factor: float | None = None`
  (`core/runtime_control/session.py`) — None → use
  `policy.safety_factor` (current behavior).
- `_watchdog_deadline_provider` (`core/sandbox_executor.py`): use
  `policy.watchdog.safety_factor or policy.safety_factor` in the
  estimate term. Admission code untouched.
- Wiring: `HyperparamTuningInput.runtime_watchdog_safety_factor`
  (schema, default None) → tuner `_runtime_policy_dict` → protocol
  `ml_model_valid_to_ml_model_tune` → `run_one_iteration.py` CLI →
  `_chain_common.sh` flag (+ shell-parity tests).
- Tests: deadline uses the watchdog factor when set / falls back when
  unset; admission provably unaffected by the new field; V18-parity
  (flags omitted ⇒ identical policy dict).

One flag (not per-phase) suffices for the operator's symmetric 3.5
decision; per-phase watchdog factors can be added later if ever
needed.

## 5. Effective V19 runtime values (the §4 split is implemented —
these are the CURRENT launch values, not proposals)

| Setting | V19 value | Note |
|---|---|---|
| Trial admission | unchanged = record-only (no budget) | inherited V18 behavior |
| Formal admission | unchanged = `predicted × 2.0 ≤ 7200 s` (⇒ ≤ 60 min) | `--runtime_formal_safety_factor 2.0` kept |
| Trial watchdog factor | **3.5** | via `--runtime_watchdog_safety_factor` (uniform for both phases) |
| Formal watchdog factor | **3.5** | via `--runtime_watchdog_safety_factor` (§4 split, implemented) |
| Legacy fallback | 1.5 kept (inert) | unchanged |
| Watchdog floor | 120 s | unchanged |

**Hardware scope**: factors are launch-script values (no hostname
auto-config exists). Scoping 3.5 to the 5090 box = putting it in the
5090 launch profile/command only; H100 launch scripts keep their
values unless the operator chooses otherwise. Recommended: encode the
V19 launch command per target box in this protocol when frozen.

## 6. Interaction with the decided V19 launch configuration

Changing ONLY the watchdog factor (via §4) provably does not alter:
admission (untouched code path), VRAM gating (`evaluate_vram_skill`,
independent), HealthGate routing/thresholds (independent config),
scoring, trial/formal scientific budgets (20/120 min flags unchanged),
PR 1 delta thresholds (`--skip_formal_min_delta` /
`--bypass_formal_time_budget_min_delta` unchanged), PR 2 ordering
(`order_strategy=sequential`, ascending file indices per band — an
independent input; note RT2's per-file-build accounting already
handles sequential setup), PR 3 feedback flag (ON per operator
decision; prompt-only), or agent advice. All decided V19 toggles
(PR 1 coupling ON, PR 2 sequential, PR 3 ON, four bands) live on
separate flags audited in their own PRs.

## 7. Stale documentation found (to correct WITH the split PR, not now)

- `_chain_common.sh:101` comment "V18 posture 2.0 (Wave-1A split)" on
  the TRIAL factor — stale: trial went 2.0 → 3.0 (`d8d4f1e`);
  effective V18r trial value is 3.0.
- `run_one_iteration.py` / `run_comparison.py` help text "V18 posture
  2.0" on the trial flag — same staleness.
- Historical wording "safety factor" (design docs, memory notes)
  described the WATCHDOG margin in `running_chain_test.md` ("deadline
  = predicted × safety_factor") while the schema calls it the
  admission multiplier — both are true (coupled field); the a780186
  "admission tightened to ≤60 min" record confirms the operator's
  formal 2.0 was consciously BOTH. No manifest contradiction found:
  launch scripts, schema provenance fields, and design-doc records
  agree on 1.5 / 3.0 / 2.0 / floor 120 / watchdog on.

## 8. Scheduling revision (operator, 2026-07-29 — rev 2)

The rev-1 serial eight-chain schedule was superseded BEFORE LAUNCH (no
V19 run ever started under it) by the pairwise decision: each band's
architecture and loss chains run CONCURRENTLY (exactly two chains, same
band, never cross-band, never more than two), waves in band order
15-19 → 10-14 → 4-9 → 0-3, each wave gated on both prior chains
reaching a terminal queue state. Scientific settings are unchanged.
Rationale (operational priority, not a scientific ranking): 15-19 has
no prior evidence and the highest FCNet target; 10-14 carries the only
prior valid formal for continuity; 4-9 next; 0-3 last per the operator
order. VRAM basis: per-attempt 16 GB admission caps each chain
(min(0.8×physical, budget)); aggregate 2×16 = 32 GB equals the 5090 —
the residual aggregate-OOM risk and its frozen response are recorded in
the launch report §5.1/§11. Queue implementation:
`sdsc_submission_scripts/v19_queue_runner.sh` (pairwise waves,
authoritative per-chain wave state, targeted serial `--only` recovery).

## 9. Gate 0 attempt 1 — FAIL — PRODUCTION PATH (2026-07-29 22:35)

Launched after CI green on PR #149 head `9119f14`. Both chains died in
< 2 min, pre-LLM ($0 API, zero training, zero GPU work):

```text
TypeError: run_workflow() got an unexpected keyword argument
'runtime_watchdog_safety_factor'    (run_one_iteration.py:1500)
```

Missing edge: the §4 split wired the new flag through shell
(`_chain_common.sh:309,507`), CLI + call site
(`run_one_iteration.py:957,1550`), schema (`hyperparam_tuning.py:1481`),
protocol (`ml_model_valid_to_ml_model_tune.py:130,300`) and tuner
(`ml_hyperparameter_tune_agent.py:1461`) — but NOT through
`workflows/model_exploration.py::run_workflow` (signature + the
`local_validated_model(...)` forwarding). Test gap: no test asserted
CLI↔workflow kwarg parity; the pseudo-loop tests call `run_workflow`
without the new kwarg, so all 14 split tests passed.

Fix (2 lines, commit `5d7f30f`): add
`runtime_watchdog_safety_factor: float | None = None` to the
`run_workflow` signature and forward it into
`local_validated_model(...)`. Regression: AST kwarg-parity guard
(`tests/unit/core/test_watchdog_admission_split.py::TestWorkflowKwargParity`)
— demonstrated to report exactly `['runtime_watchdog_safety_factor']`
against the pre-fix signature. Full evidence:
`reports/v19_gate0_20260729_2209.md` §8 (attempt-1 record preserved;
never overwritten by later attempts).

## 10. V19 Launch-Critical Propagation Matrix (audit, 2026-07-29)

Audit standard (operator): every launch-critical value → accepted at
every layer → forwarded without mutation → consumed by the intended
subsystem → recorded consistently in artifacts. A row is PASS only when
a test demonstrates the final consumer and artifact receive the
intended (sentinel) value — name-matching alone proves nothing.

**Layer chain audited** (Gate 0 / formal V19 launch path):

```text
gate_chain_args (v19_gate0_pair_runner.sh — single source of truth)
→ parse_chain_args / build_app_args   (_chain_common.sh)
→ argparse + normalize_args           (run_one_iteration.py)
→ run_workflow(...) call site         (run_one_iteration.py:1500)
→ run_workflow                        (workflows/model_exploration.py)
→ protocol functions                  (agent/schemas/protocols/*)
→ typed inputs (Interpretation/Proposal/HyperparamTuning)
→ final consumers (tuner policy, admission, deadline provider,
   ordering sampler/loader, HealthGate config, renderers)
→ run-invariants lock / manifests / run_config provenance
```

**Generic boundary contracts** (close the attempt-1 class for EVERY
flag, present and future):

| Boundary | Guard | Test |
|---|---|---|
| shell → CLI | every emittable `APP_ARGS` flag accepted by argparse (incl. `--no-*` BooleanOptionalAction forms) | `test_launch_surface_parity.py::TestShellToCli` |
| call site → run_workflow | AST kwarg parity, fails on any future caller/callee gap; no `**kwargs` masking | `test_watchdog_admission_split.py::TestWorkflowKwargParity` |
| run_workflow → protocols | every kwarg of all 5 protocol calls accepted by the protocol signature | `test_launch_surface_parity.py::TestWorkflowToProtocols` |
| protocols → schemas | every schema-constructor kwarg is a declared field/alias — CRITICAL: schemas default to `extra="ignore"`, so a typo would be SILENTLY dropped (worse than attempt 1: no crash) | `test_launch_surface_parity.py::TestProtocolsToSchemas` |

**Value-level propagation** (frozen Gate command → resolved CLI:
`test_gate0_config_propagation.py`, real shell + real argparse + real
normalize_args, both flavors; workflow → typed inputs + lock:
`test_launch_config_propagation_pseudo.py`, real run_workflow with
sentinels, agents mocked at the boundary only).

| # | Setting family | Gate 0 value | Resolved-CLI proof | Consumer-level proof | Artifact proof | Result |
|---|---|---|---|---|---|---|
| 1 | PR 1 coupling flag + deltas (0.0 / 0.5) | ON, 0.0, 0.5 | `test_incumbent_and_feedback` | delta-gate decision logic consumes resolver verbatim, fire/no-fire at exact deltas incl. 0.0-skip and +margin-bypass: `test_delta_gates.py` (20) | manifest `chain_incumbent_used`/`chain_incumbent_source`: `test_chain_incumbent_pseudo.py` A/B/C | PASS |
| 2 | PR 1 incumbent restore (valid-formal decision, trial context-only, invalid excluded) | restore ON | — | `test_chain_incumbent_pseudo.py` (branch A numeric 1.25 → iter-2 tuner input; B null; C flag-off), `test_valid_candidate_selection.py` (7), `test_resume.py` (70) | same + Invariant II local-score isolation | PASS |
| 3 | PR 2 ordering (sequential, 15,16,17,18,19) | sequential, ascending | `test_scope_and_ordering` (typed lists, no sort hazard) | DESCENDING sentinel `[19,18,17,16,15]` reaches tuner input un-re-sorted (`test_launch_config_propagation_pseudo`); sampler/loader visit order proven at the engine (`test_ordering_engine.py` — blocks visited in file order, loader iterates sampler order, non-permutation rejected); tuner formal branch (`test_ordering_formal_branch.py`) | lock `ordering_override_*` = canonical fields (`run_invariants.py:128`); sentinel equality in lock dump | PASS |
| 4 | PR 3 feedback (ON, 3, 8) | ON, 3, 8 | `test_incumbent_and_feedback` | sentinels True/7/11 reach InterpretationInput AND ProposalInput flag AND tuner input; typed history channel (`collapse_fingerprint_history`) restore: `test_resume_fingerprint_history.py`; renderers: PR #145 P3 suites | lock `structured_health_feedback_enabled`/window/max sentinel equality; all-three-lock-sites guard (`test_health_feedback_chain_wiring.py`) | PASS |
| 5 | Runtime factors (1.5 / 3.0 / 2.0 / wd 3.5 / floor 120) | as frozen | `test_runtime_control` | REAL `decide_admission` + REAL `_watchdog_deadline_provider`: `test_watchdog_admission_split.py` (18) — formal 2.0 boundary preserved with/without override, trial record-only, deadlines at 3.5, floor/budget clamps; non-crossing: `test_trial_formal_safety_split.py` | policy provenance carries both factors; tuner policy dict both phases | PASS |
| 6 | Budgets (5 / 30 min; 24 / 24 GB) | as frozen | `test_budgets` | sentinels 7/31/23/25 reach tuner input; budget→policy: `_build_runtime_policy` tests (7200-s formal budget path) | run_config stamps (existing tuner provenance tests) | PASS |
| 7 | Portions (0.02/1.0/0.01 × trial+formal) | as frozen | `test_portions` | sentinels .037/.93/.017/.041/.97/.019 reach tuner input exactly | run_config provenance (existing) | PASS |
| 8 | Scope + HealthGate files (15-19; 15,16,17,18,19) | as frozen | `test_scope_and_ordering` (typed `DataScope`) | tuner input typed scope + monitored list sentinel; enforcement layers: DS suites (constructive/boundary/direct-access), `validate_sample_set` at sandbox | lock `resolved_data_scope` + effective-config sha256; peek-subset validation (`test_run_invariants.py` partial-scope cases) | PASS |
| 9 | Execution controls (iters 2, rounds 2, attempts 3, epochs 1, force-formal ON, cold start) | as frozen | `test_execution_controls` (incl. `force_formal_round is True` default and empty seed_paths) | rounds/epochs sentinels 4/2 reach tuner input; force-formal consumed by tuner round planner (existing force-formal suite) | manifest per-iteration record | PASS |
| 10 | Advice (per-flavor Gate files) | arch/loss Gate advice | `test_advice_resolves_per_flavor` — normalize_args loads the JSON; arch≠loss content; correct flavor phrases; no beat-FCNet | stage-scoped sentinels: interp advice reaches InterpretationInput only; propose advice reaches ProposalInput via the Commit-2d channel (`expert_context` item source="human" + human AgentCard — the legacy `ProposalInput.human_advice` field is intentionally unset); tune advice reaches tuner `human_advice` | advice path stamped in resolved argv provenance; hashes re-verified: gate `f945fa8…`/`5bacafe…`, formal `427a6c62…`/`380c5f5e…` UNCHANGED | PASS |
| 11 | LLM config (openai_tiered_v1.json) | as frozen | `test_strategies_and_configs` | `WorkflowLLMConfig` precedence over `--llm_model` shorthand (`model_exploration.py:2888`); per-role `llm_config.get(...)` at all five agent constructions. KNOWN COSMETIC: shell banner prints the deprecated shorthand default (`gemini-3.1-pro-preview`) — the tiered file governs | resolved argv provenance | PASS (banner-lie documented) |
| 12 | Watchdog switch + floor | ON, 120 s | `test_runtime_control` | deadline provider floor test (`test_floor_remains_active`) | provenance | PASS |
| 13 | Resume/legacy (all locked fields) | — | — | same-policy accepted; changed flag/window/max/scope/enabled/sha rejected NAMING field+values; legacy lock resolves OFF-3-8; enabling over legacy REJECTED (no silent upgrade): `test_run_invariants*.py`; ordering pair canonical → generic drift rejection; corrupted-history restore raises naming iter+model | lock is the artifact | PASS |
| 14 | Pair-runner (Gate) | frozen command | arch/loss diff exactly {workspace, run_name, advice}; all frozen values; forbidden flags absent; every flag parseable | full main-flow scenarios via screen shim: stagger blocks loss on arch failure; both exits preserved; summary on every exit path; wrapper PID self-reported | `gate0_pair_summary.json` schema incl. `loss_launched` | PASS |

**Audit summary**: 14 families / ~45 individual settings audited; **0 new
propagation gaps found** beyond the already-fixed attempt-1 defect
(matrix row 5's missing workflow edge). One intentional-design finding
documented (row 10: proposer advice travels via `expert_context`, not
the legacy field — Commit-2d design, not a gap). One cosmetic finding
re-confirmed (row 11 banner-lie). New guards added so the attempt-1
class cannot recur silently at ANY boundary: 4 generic boundary
contracts + 12 resolved-value tests + 2 sentinel workflow tests +
12 pair-runner tests.

**Fix/guard commits**: `5d7f30f` fix(runtime) workflow propagation +
parity regression; `ea239cb` fix(v19) hardened Gate pair runner +
frozen Gate advice; `a32d6f1` test(v19) propagation contracts + value
sentinels.

**Gate 0 attempt 2 precondition**: CI green on the head carrying the
fix + these guards; workspaces attempt-1-preserved (renamed) + fresh
cold; then the standing relaunch authorization applies.

**Follow-up (operator decision required, before the FORMAL launch)**:
`v19_queue_runner.sh` still launches each wave's pair with the
attempt-1-era pattern (no stagger health check; `screen -ls`-parsed
PID). Recommend porting the Gate runner's hardening (stagger check +
in-session wrapper-PID self-report + marker-grace wait) to the queue
runner as its own PR before the formal V19 launch. Not done in the
audit repair — out of its narrowly-scoped mandate.
