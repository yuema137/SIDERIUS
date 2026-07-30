# V19 Launch Protocol — Runtime-Control Settings (DRAFT, audit-backed)

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

## 3. Independence audit — VERDICT: COUPLED

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
  formals with V18 admission requires a minimal configuration split.**

## 4. Minimal split proposal (NOT implemented — for review)

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

## 5. Proposed V19 runtime values (pending the §4 split for formals)

| Setting | V19 value | Note |
|---|---|---|
| Trial admission | unchanged = record-only (no budget) | inherited V18 behavior |
| Formal admission | unchanged = `predicted × 2.0 ≤ 7200 s` (⇒ ≤ 60 min) | `--runtime_formal_safety_factor 2.0` kept |
| Trial watchdog factor | **3.5** | via the new watchdog-only flag (or, equivalently today, trial factor 3.5 — but the flag keeps semantics uniform) |
| Formal watchdog factor | **3.5** | REQUIRES the §4 split |
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
