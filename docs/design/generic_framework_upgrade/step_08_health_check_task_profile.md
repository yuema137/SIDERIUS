# Step 08 — HealthGates on declared task-profile inputs — acceptance / decomposition design (parent)

## 0. Status and provenance

**DRAFT rev 1 — for operator review. Nothing is frozen.**

Drafted 2026-08-18 against `master` @ `171078fb` (post-#221), from a fresh
source audit of `execute_tools/health_checks/` (17 modules, 3,207 lines),
`configs/health_checks.yaml`, `execute_tools/deliverable_spec.py`,
`execute_tools/dataset_config.py`, `core/run_invariants.py`, and the firing
site `nodes/ml_hyperparameter_tune_agent/execution.py:923`.

Roadmap authority: `docs/design/siderius_generic_framework_upgrade.md` §8
(the Step-08 module section), §8.4a (Rev-5 obligations, §22.12), §22.8
(orthogonality), §20.7 (dependency map), §15.1 row "§8 HealthGates". This
parent freezes **WHAT + acceptance**; the children freeze **HOW** (§20 of the
Step-07 parent establishes that split and it is reused here). Per the
operator's instruction this revision carries **scope, validation and
methodology per PR only — no per-commit checklists**; those are written into
each child design at its own freeze.

**Ordering note, stated up front.** The frozen sequence is
`Step 07 → D14 → Step 08` (§22.11a / §20.7). D14 has **not started**. This
document may be reviewed and frozen before D14, but Step-08 **implementation
does not begin until D14 has merged**, because 08's Track-B/C L2 evidence
("inapplicable on a *real* non-int8 deliverable") requires an executable
non-TIDMAD deliverable that only D14 can produce. Everything in this design is
therefore split into evidence at **current maturity** (L1,
declaration-backed — available now) and **L2 evidence** (real artifacts —
lands with/after D14). No item in this Step may raise a track's maturity
itself: that is D14's, and Step 08 **must not genericize the data loader "in
passing"** (§20.7, verbatim).

## 1. Final observable Step effect

A task ships its own health-check family. Concretely, after Step 08:

1. **Checks declare the task-profile inputs they need** — the declaration is
   data, not prose: which declared file *group* they peek (§4's
   `health_peek_files` indirection), which *deliverable* facts they require
   (storage dtype / encoding / channel layout / mV scale from the Deliverable
   Contract), and which numeric parameters are thresholds owned by the task.
2. **Applicability is a verdict, not a disguised pass.** A check whose
   declared inputs do not apply to the bound task's deliverable (an
   int8-distribution check against a float32 image tensor) reports
   `inapplicable` **by declaration comparison, before any I/O** — never the
   current `passed=True, reason="not applicable — …"` convention
   (`protocol.py:22-31`), which is indistinguishable from a genuine pass in
   every aggregate.
3. **Generic checks still FIRE and can block** on any task: a dispersion
   check runs on a declared-float deliverable and its verdict has gate
   authority (roadmap fixture 8.4-C).
4. **Per-task thresholds live in the task's health config**; the framework
   owns the runner, gate policy, severity resolution and persistence.
   TIDMAD's six checks (`output_diversity`, `output_std`,
   `amplitude_collapse` blocking; `pearson_dispersion`,
   `spectral_peak_ratio`, `per_file_output_std` recording) become the first
   task-owned family — the golden instances.
5. **D18 is discharged**: a scalar-only metric (no per-sample evidence)
   reaches `HealthCheckContext` as an explicit typed statement, not as a
   fabricated `file_vector=[]` that per-file checks silently iterate zero
   times. (The full "no per-sample evidence" vocabulary is shared with
   Step 12; Step 08 owns the HealthGate-side expression.)

**Unchanged, byte-for-byte:** TIDMAD verdicts on fixture outputs; gate IDs
(records and prompts reference them); the `health_checks_effective.yaml`
sha-pinning MECHANISM; severity resolution
(`SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND > CONTINUE`); the firing
point (tuner round boundaries, never inside `score_vector`).

## 2. Current source census (audited at `171078fb`)

What exists, what is partially landed, and what is coupled — so the children
inherit facts rather than re-deriving them.

### 2.1 Already landed (consume, do not rebuild)

- **The group indirection exists and is in production use.**
  `configs/health_checks.yaml` already says
  `peek_file_indices: task_health_peek`, resolved against
  `DatasetProfile…health_peek_files` (`dataset_config.py:499`; TIDMAD
  declares `[3, 10, 17]` at `:587`), with `anchor_selection_files` a
  **separate** declaration (`:540` validates both). Roadmap fixture 8.4-A's
  "two separate declarations, never one map" is therefore already
  structurally true; 08 must *evidence* it, not build it.
- **Some checks already read the profile**: `spectral_peak_ratio.py:55`
  (sampling frequency), `per_file_output_std.py:126` and
  `pearson_dispersion.py:30` (num_files). Partial migration — the pattern to
  complete, and proof the resolution seam works inside checks.
- **The Deliverable Contract exists** (`execute_tools/deliverable_spec.py`)
  and derives channel-group identity from `DatasetProfile.channels` and the
  storage representation from `.encoding` (`:212-214`). Step 06 froze it as
  a reader seam; 08 is its second consumer (the roadmap's dependency-2).
- **The context is already introspective**: `HealthCheckContext`
  (`schemas.py:113-127`) tells checks to "read what they need" and to skip
  gracefully — the *behavioural* half of applicability exists; the *typed
  verdict* half does not.

### 2.2 The couplings Step 08 removes

- **`_peek.py:93-100` hardcodes the deliverable's shape**: channel
  `channel0001`, int8 storage, the `("timeseries", channel, "timeseries")`
  HDF5 node path. Every peeking check inherits this; it is the single
  load-bearing TIDMAD assumption in the subsystem.
- **`protocol.py` has no applicability step** (rev-6 removed it,
  `:22-31`), so inapplicability is a `passed=True` with prose — invisible
  to aggregation, to records, and to the interpreter.
- **Thresholds are framework config**: `min_unique_int8_values: 25` etc.
  live in the shared `configs/health_checks.yaml` with empirical TIDMAD
  provenance in comments; a second task would have to edit TIDMAD's file.
- **Check identity is flat**: `registry.py` is a global name→skill map with
  no notion of which task owns a family.

### 2.3 The hard boundary (roadmap finding 12a — restated verbatim in effect)

`core/run_invariants.py:475-488` hard-refuses a changed health-config sha
against an existing workspace (remediation = "start a new workspace"). So any
content change to the effective config **must land at a fresh-workspace
boundary between campaigns**. Both children carry this migration note; no
implementation may weaken the lock to ease its own landing.

### 2.4 Firing path (unchanged by 08)

`execution.py:923` (`agent_input.health_gate_enabled`) →
`evaluate_and_persist_health_gates` (`evaluation.py`) →
`runner.get_gates_for_position` → per-check `run(ctx, config)`. Gate actions
and severity resolution are CLAUDE.md-frozen. 08 changes what a check
*declares and receives*, never when or where gates fire.

## 3. Approved scope — **TWO PRs** (`08a` → `08b`)

Two capabilities, two blast radii, in dependency order. Not one PR: the
schema/protocol surface (every check touched, verdict vocabulary extended)
and the config-ownership surface (YAML layout, registry, task family) fail
differently, are reviewed differently, and 08b consumes 08a's contract.
Not three: the "generic checks fire on non-int8" obligation (8.4-C) is an
**evidence obligation on both PRs**, not a third capability — splitting it
out would create a PR whose only content is tests (see
`project_step02_decomposition_cautions`: split by capability, never by
concept).

```text
08a  Check input contract + applicability verdicts
       what a check DECLARES, what it RECEIVES, how it says "not for this task"
08b  Task-owned health config + the TIDMAD six as the first task family
       who OWNS the thresholds and the family; D18's scalar-only statement
```

### 3.1 PR 08a — check input contract + applicability

**Scope.**

- Extend the check protocol so every check **declares** its required inputs
  as typed data: the deliverable facts it needs (storage dtype / encoding /
  channel layout / scale), the declared file group it peeks, and the
  numeric-parameter names it treats as task thresholds. One declaration
  authority; the runner and records read the same object.
- Add the **`inapplicable` verdict** to the result vocabulary: produced by
  declaration comparison (check's requirements vs the bound task's
  `DatasetProfile` + Deliverable Contract) **before any file I/O**; carried
  distinctly in `HealthCheckResult`, gate evaluation, persisted records and
  any aggregate a prompt renders. An inapplicable check never blocks and is
  never counted as a pass.
- Route the peek layer through the Deliverable Contract: channel identity,
  storage dtype and the HDF5 node path come from `deliverable_spec` /
  `DatasetProfile.encoding`, replacing `_peek.py`'s literals. TIDMAD resolves
  to byte-identical reads.
- Complete the partial profile migration inside the six checks (the
  remaining hardcoded facts join the pattern
  `spectral_peak_ratio.py:55` already uses).

**Non-goals.** No YAML layout change; no registry/ownership change; no new
checks; no prompt-visible content change beyond the additive verdict field;
no data-loader work (D14's).

**Methodology.** Declaration-first: write the input-declaration schema and
the applicability comparison as pure functions over
(`DatasetProfile`, `DeliverableSpec`, check declaration) — unit-ownable,
no I/O. Then thread them through `protocol.py` / `schemas.py` /
`runner.py` with the existing checks migrated one at a time, each proving
TIDMAD verdict identity on the committed fixtures before the next.
`_peek.py` is rewritten as a *reader of the contract* with the old
signatures preserved as thin delegates. The rev-6 "no `is_applicable`"
decision is superseded deliberately and the protocol docstring says so with
this design cited — the simplification it bought (every check yields a
definite verdict) is kept, because `inapplicable` IS a definite verdict.

**Validation.**

- **TIDMAD parity (Stage A):** the six checks produce byte-identical
  `HealthCheckResult`s on the existing committed fixtures; the effective
  config sha is unchanged by 08a (declarations live in code, not YAML).
- **Atomic contrasts (Stage B, current maturity):**
  - 8.4-B *encoding declaration only*: a declared-float deliverable makes
    the int8-family checks `inapplicable` — asserted on the verdict, with
    a spy proving **no file was opened**.
  - 8.4-C *generic-check firing only*: a dispersion check on the same
    declared-float deliverable **fires and can fail** — the negative
    control that inapplicability is not a blanket exemption.
  - Tracks B/C at L1: Pets and DAVIS *declarations* drive the same
    comparison functions; the int8 family reports `inapplicable` with a
    reason naming the mismatched declaration axis. **No real deliverable is
    read** (none exists before D14).
- **Reachability:** production gate evaluation at the tuner round boundary
  consumes the declaration path — a recording double proves
  `evaluate_and_persist_health_gates` routes through the applicability
  comparison, so it cannot be a parallel unused seam.
- **L2 (post-D14, recorded as a deferred obligation on this PR):** the same
  8.4-B assertion re-run against a *real* Track-B/C deliverable artifact.

**Test-layer ownership (per the #221 permanent rule).**
UNIT: the declaration schema; the applicability comparison (pure);
contract-routed peek arithmetic; verdict transport into records; the atomic
8.4-B/C fixtures. GATE 1: none (no LLM-facing change; the additive record
field is hidden from prompts unless 08b says otherwise). GATE 2: one bounded
run at the final executable head proving gates still fire and persist on a
real TIDMAD round with the new path (posture from
`docs/gates/gate_testing_standard.md` at the child's freeze). CI IMPACT:
`execute_tools/health_checks/*` → `tests/unit/execute_tools/health_checks/`
(+ the always-on guards) under the #221 selector; `agent/schemas` hub rules
apply if any record schema moves.

### 3.2 PR 08b — task-owned health config + the first task family

**Scope.**

- Move per-task thresholds and the family roster into **task health
  config**: the task declares *which* checks run and *with what
  parameters*; the framework YAML keeps gate POLICY (roles, actions,
  severity, cadence). TIDMAD's six, with their current empirical thresholds
  and provenance comments, become the first task family — values unchanged.
- Registry gains family/ownership identity without breaking the flat
  name→skill lookup (existing IDs stable; records and prompts reference
  them).
- **D18**: `HealthCheckContext` receives an explicit typed statement when
  the bound metric supplies no per-sample evidence, replacing the silent
  `file_vector=[]` bridge; per-file checks consume it as `inapplicable`
  (08a's verdict) rather than iterating an empty list into a hollow pass.
- The effective-config materialization (`health_checks_effective.yaml`)
  composes framework policy + task family into the same single pinned
  artifact — **mechanism untouched**, content composition new.

**Non-goals.** No new check implementations; no change to gate actions or
severity; no phantom-fingerprint/byte-identity machinery from the stale
`collapse_detection_framework_generic.md` (explicitly not resurrected,
roadmap §8.5); no Track-B/C check *families* beyond declarations (their real
families are meaningful only at/after D14).

**Methodology.** Config-shape first: define the task-health-config schema
and its composition into the effective artifact, with TIDMAD's composed
output proven byte-identical (or, if key ordering must change,
semantically-identical with the sha delta called out — see the migration
note). Then move ownership file-by-file with the effective artifact diffed
at each step. D18 lands last, as a consumer of both 08a's verdict and the
new context statement. The fresh-workspace boundary (§2.3) is stated in the
child design AND in the operator-facing runbook note before merge.

**Validation.**

- **TIDMAD parity:** composed effective config semantically identical;
  verdicts identical on fixtures; gate IDs stable; run-invariants lock
  behaviour demonstrated (a changed sha against an existing workspace is
  REFUSED — asserted, since it is the safety boundary this PR leans on).
- **Atomic contrast 8.4-A** *(group semantics only)*: TIDMAD-shaped outputs
  with peek files resolved from a **different** declared health-peek set
  than the anchor-selection set — two declarations observably independent.
- **Tracks B/C at L1:** each pack carries a declared task health config
  whose family excludes the int8 checks; composing it yields an effective
  artifact in which those checks are absent-or-inapplicable **by
  declaration**, and a generic check is present.
- **D18:** a scalar-only `MetricSpec` produces the typed no-per-sample
  statement; each per-file check reports `inapplicable` naming it; nothing
  renders a hollow pass. Negative control: a per-file metric still feeds
  `file_vector` unchanged.
- **L2 (post-D14 obligation):** one real Track-B or C round evaluated
  through a composed non-TIDMAD family.

**Test-layer ownership.** UNIT: config schema + composition; ownership
resolution; D18 statement + consumption; 8.4-A fixture. GATE 1: none unless
the child chooses to surface family identity in a prompt (then the PB-delta
rules from 07b apply and Gate 1 is re-dispositioned at the child's freeze).
GATE 2: REQUIRED, one bounded run — this PR changes what production
composes and pins at startup, which is lifecycle. CI IMPACT: adds
`configs/` + task-pack health files as literal-path test inputs (the #221
selector already routes doc/config inputs by read-edges).

## 4. Explicit non-goals (Step level)

- **No data-loader genericization** — D14 owns `storage → sample → tensor`.
- **No maturity inflation**: Pets/DAVIS stay at their current pack maturity;
  every L2 item is an explicit deferred obligation, not a hidden dependency.
- **No sha-pin mechanism change**; no weakening of the run-invariants lock.
- **No scoreability/diagnosis/metric entanglement** (§22.8): HealthGate
  stays a validity/pathology channel. A check never reads the metric's
  verdict; the metric never reads a gate's.
- **No prompt redesign**: any prompt-visible change is limited to additive,
  authority-rendered content and is dispositioned at the child freeze.

## 5. Compatibility surfaces (Step level)

| surface | guarantee |
|---|---|
| TIDMAD verdicts on committed fixtures | byte-identical across both PRs |
| gate IDs | stable (records + prompts reference them) |
| `health_checks_effective.yaml` sha mechanism | untouched; content change lands only at a fresh-workspace boundary (§2.3) |
| severity resolution / gate actions | frozen (CLAUDE.md) |
| firing point | tuner round boundaries only |
| `score_vector` | never returns health data (frozen invariant) |

## 6. Gate disposition (to be confirmed against `gate_testing_standard.md` at each child freeze)

| | Gate 1 | Gate 2 |
|---|---|---|
| 08a | not required (no LLM-facing change) | required, bounded once at the final executable head |
| 08b | not required unless a prompt delta is chosen | required, bounded once (startup composition + pinning is lifecycle) |

Both Gate-2 runs are cold-start per the operator rule, posture quoted from
the standard at freeze time, and — per #221's model — their assertion lines
are written into the child design *before* implementation so the runs are
discriminative rather than ceremonial.

## 7. Stop conditions (Step level)

Stop and return to the operator if: TIDMAD fixture parity cannot be held
byte-identical where §5 promises it · the applicability comparison would
need information neither `DatasetProfile` nor the Deliverable Contract
declares (that is a missing declaration, i.e. Step-02/06 scope, not a reason
to peek) · the effective-config composition cannot preserve the pinning
mechanism · D18's statement would require changing `score_vector`'s frozen
2-tuple · any change would move a frozen prompt byte outside an approved
delta · Track B/C L1 evidence would require a real deliverable (that is D14
leaking in).

## 8. Open questions for the operator (this review)

1. **PR count** — is the 2-PR split (contract/applicability · ownership/
   family) accepted, with 8.4-C as a shared evidence obligation rather than
   a third PR?
2. **Sequencing confirmation** — freeze this parent now but hold both child
   designs until D14 merges, or also write 08a's child design pre-D14 (its
   L1 scope is genuinely D14-independent)?
3. **`inapplicable` in prompts** — should the interpreter/planner ever see
   inapplicability (a per-task capability statement), or is it
   record/operator-only until Step 09 consumes diagnosis-adjacent evidence?
   Default in this draft: record-only, hidden from prompts.
4. **Effective-config sha under 08b** — composition may change the sha even
   with identical semantics. Accept "semantically identical + fresh-workspace
   boundary" as the compatibility statement where byte-identity is
   impossible, per §2.3?
