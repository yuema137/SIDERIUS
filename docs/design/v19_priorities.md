# V19 Priority Decisions

- **Status**: planning baseline — locked for V19 PR design (operator
  lock, 2026-07-27)
- **Planning lock**: this document defines the approved V19 goals, PR
  ladder, validation standards, progress semantics, and scope
  boundaries. Future implementation details belong in PR-specific
  design documents. Changes to the priority structure, scientific
  framing, validation requirements, or PR scope require an explicit
  operator decision and a documented revision to this file.
  - The lock fixes: the top-level scientific goal; the Phase I/II/
    parallel/III organization; the current PR classifications (unless
    new code evidence exposes a conflict); the validation taxonomy and
    three-layer agent-behavior standard; FCNet as benchmark, not
    implementation template; data ordering as an optimization
    dimension, not a reproduction requirement; genericization as
    bounded and in-passing; merge and production activation as
    separate decisions; the V18r protocol freeze.
  - Allowed without a new operator decision: changing `[ ]` to `[x]`
    when evidence-backed checkpoints complete; adding PR or commit
    numbers; recording approved operator decisions; documenting
    explicit deferrals; correcting factual drift discovered through
    code audit; updating measured FCNet gaps or SIDERIUS results;
    linking newly created PR-specific design documents.
  - Disallowed without explicit operator approval: adding major new
    V19 priorities; reordering the PR ladder; weakening agent-behavior
    validation; replacing empirical validation with prompt inspection;
    changing the scientific success target; turning FCNet
    implementation details into mandatory reproduction goals;
    expanding genericization into a standalone refactor program;
    silently changing blocking-versus-optional PR scope.
  - Content division: this file keeps only the problem and goal link,
    approved scope and non-goals, validation class, preliminary
    validation ideas, blocking checkpoints, progress state, and links
    to the detailed design documents. Code audits, architecture, exact
    interfaces, commit plans, detailed tests, synthetic scenario
    selection, sample-size reasoning, Gate commands, runtime/API-cost
    estimates, stop-and-show evidence, and implementation logs belong
    in each PR's design document. No speculative sample sizes,
    thresholds, or launch commands enter this file before the relevant
    PR audit.
- **Scope**: workflow-adaptation release — the feedback/adaptation agenda
  originally drafted for V18 (carried over after V18 pivoted to the
  split-mode + runtime-control release), plus runtime-control follow-ups
  from the V18r campaign
- **Owner**: TBD
- **Prerequisites** (state audited 2026-07-27): V18r evidence exists
  but the campaign is NOT complete — the four-chain Wave-1 cohort
  (bands 4-9 / 10-14) was externally terminated on 2026-07-25 at
  iterations 6/7/4/4 of 20 (container replacement), leaving 17 closed
  iterations with `run_output` records
  ([`../../reports/v18r_campaign_audit_20260725.md`](../../reports/v18r_campaign_audit_20260725.md));
  bands 15-19 and 0-3 never launched (queue fully pending). PR 4a and
  PR 5 may begin on the 17 closed iterations; full-band coverage (and
  the band 15-19 / 0-3 rows of §1.1) requires the V18r restart after
  the documented restart blockers are fixed. Runtime-control
  observation stores hold V18r production data, though under
  per-iteration roots (audit §6 finding; see O1a in §3)
- **Related**: [`v18_priorities.md`](./v18_priorities.md) (what actually
  shipped in V18 and why these items moved),
  [`runtime_estimation_and_watchdog.md`](./runtime_estimation_and_watchdog.md),
  [`../gates/gate_testing_standard.md`](../gates/gate_testing_standard.md)
  (mandatory reading before designing any real-LLM + real-training
  validation — §4.4),
  GitHub issue #136
- **Frozen protocol note (operator, 2026-07-24)**: none of this changes
  mid-V18r — the running campaign finishes under its committed protocol.

## 1. Goal

**Operator decision (2026-07-27): V19's top-priority goal is to
improve HealthGate-valid formal scores and ultimately produce
band-split scores that exceed the official TIDMAD FCNet result in each
of the four splits (0-3, 4-9, 10-14, 15-19). Every detailed priority in
this document serves that goal.**

**FCNet is the target benchmark, not the implementation template.** No
implementation choice — including the official FCNet training order —
is an objective by itself; such choices are candidate mechanisms or
search dimensions whose value must be demonstrated empirically on
HealthGate-valid formal score (see §1.4).

The prior framing ("can SIDERIUS use structured health and runtime
information to adapt its proposals and workflow decisions?") is retained
as the *mechanism* question — V17 built the health-observation
substrate, V18 pivoted to split-mode + runtime control — but in V19 the
adaptation agenda is subordinate to the score target above.

### 1.1 Quantified targets

The target per band is the FCNet band aggregate: the scoped formal
scalar `log_5.27(Σ_(f,i) per_segment[f,i] / Σ_f |S_f|)` computed over
every segment of the band's files, derived from the committed per-file
linear values in
[`../../reference_data/official_paper_result/fcnet.md`](../../reference_data/official_paper_result/fcnet.md)
(canonical `segment_anchors.json` s_max, 200 segments/file). Raw floors
from `reference_data/raw_baseline/` by the same formula.

| Band | Raw floor | **FCNet target** | Best SIDERIUS valid formal to date | Gap (log units) |
|------|----------:|-----------------:|-----------------------------------:|----------------:|
| 0-3   | −7.5117 | **−4.7030** | never run (V18r queue never launched) | — |
| 4-9   | −0.0735 | **3.1008**  | none valid (best invalid formal −0.9902) | > 4.0 |
| 10-14 | 1.0940  | **6.6810**  | 1.3111 (`v18r_arch_10_14` iter 3, gate-valid) | 5.37 |
| 15-19 | 1.5827  | **6.9836**  | never run (V18r queue never launched) | — |

Comparison rules (DS8 invariant): a claim against a target is only valid
if it is (a) a **formal** score over the full segment set of exactly the
band's files, (b) computed with the canonical anchor map / s_max, and
(c) **HealthGate-valid** under the production policy. Trial scores,
subset/target-mode scores, and gate-invalid scores (V17's 4-5-range
artifacts, the 5.5762667 class-127 phantom family) do not count.

### 1.2 Honest baseline for the gap (auditor notes, 2026-07-27)

- FCNet is a ~323 M-parameter per-band specialist (4 separate
  checkpoints, per-file optimizer re-init). The V18r cohort explored
  ≤ 1.33 M-parameter models at 1 epoch on 10 % of training segments.
  The 5.4-log-unit gap on band 10-14 (≈ 5.27^5.37 ≈ 7,500× linear SNR)
  is therefore a capacity/training-budget gap at least as much as an
  architecture-search gap.
- 15/17 closed V18r iterations produced zero HealthGate-valid trials,
  and V17 produced zero valid formals in 40 iterations. Any path to the
  targets runs through a materially higher valid-round rate first — an
  invalid round cannot beat any target by rule (c).
- Bands 0-3 and 15-19 have no SIDERIUS evidence at all; the V18r
  restart (or a V19 launch) must cover them before band-level claims
  are possible.

### 1.3 Long-term design principle — gradual genericization (operator, 2026-07-27)

**Direction**: reshape SIDERIUS from a TIDMAD-only repo into a generic
framework accommodating different datasets, tasks, and metrics, by
gradually decoupling TIDMAD-specific design (system prompts, scripts,
functions, data plumbing) into pluggable components.

**Mechanism — in-passing refactoring, never a big-bang**: whenever a
module is touched for new development, that PR also refactors the
touched module toward the generic design. No dedicated mega-refactor
PR; the reshaping rides on the normal development ladder. (Precedent
already in this document: §2.9 item 5 extracts the TIDMAD filename
template from the loader while adding ordering strategies.)

Reviewer guardrails (accepted 2026-07-27):

1. **Single written target** — a short genericity-contract doc defines
   the seams ONCE (indexed-dataset contract, task/prompt pack, metric
   interface — extending `configs/task_config.yaml`, the already-declared
   porting entry point). Every in-passing refactor converges to those
   seams; inventing a new abstraction requires updating that doc first.
   Without this, incremental refactors produce divergent half-generic
   layers.
2. **Coupling ledger** — a grep-able inventory of TIDMAD residue
   (`abra_*` filename templates inlined in dataset classes,
   `log_5.27`/`s_max` scoring constants, TIDMAD-worded prompt
   fragments, `tidmad_data_config`, hardcoded 20-file/200-segment
   assumptions), each marked decoupled/remaining, updated in-passing.
   This is the progress meter for the reshaping.
3. **Contract tests, not claims** — each genericized seam gets a unit
   test against a minimal synthetic second-dataset fixture. A seam
   without such a test is not "generic", merely "renamed".
4. **Frozen exceptions** — the TIDMAD metric instance (frozen score
   formula, paper comparability) stays byte-identical; metric
   pluggability adds new metrics beside it. And per the project's
   "fix the bug first" standard, the in-passing refactor lives in its
   own commit within the PR and is skippable for urgent fixes.

PR disposition (operator, 2026-07-27): there is NO standalone docs-only
PR for the contract and ledger — they are folded into PR 2 as its
commit A (see §2.0), because PR 2 is the first work item that genuinely
touches the dataset seam and the smallest useful contract should be
defined where it is first exercised, not speculatively.

### 1.4 Primary scientific framing (operator revision, 2026-07-27)

These statements govern the whole document and every V19 PR:

- the objective is higher **HealthGate-valid formal score**;
- **FCNet is the target benchmark, not the implementation template**;
- sequential ordering is a **candidate optimization dimension**, not a
  required reproduction target;
- genericization is a **bounded in-passing engineering principle**
  (§1.3), never a big-bang;
- **agent behavior must be measured empirically** (§4);
- broad statistical coverage comes primarily from **real-LLM synthetic
  pseudo campaigns** (§4.2 Layer 2);
- end-to-end realism comes from a **small number of bounded real-LLM +
  real-training tests** (§4.2 Layer 3, under `docs/gates/` conventions);
- **no V19 behavioral claim is accepted solely because information
  appears in a prompt**.

## V19 Progress Tracker

Top-level completion state per PR/work item; a box is checked only
when the item is FULLY complete per its §2.0 checklist. Detailed
per-stage checkpoints live inside each PR block in §2.0 (and §3 for
O-items).

**Checkbox discipline**: checkboxes represent evidence-backed
completion. A planning discussion, design intention, prompt change, or
single successful LLM output is not sufficient to mark an
agent-behavior checkpoint complete. Rules:

- `[ ]` means incomplete, unverified, or not yet approved;
- `[x]` means completed with recorded evidence;
- PR merge and production activation are separate checkboxes;
- a deterministic layer may be complete while behavioral validation
  remains incomplete;
- a PR may merge with behavior disabled if only the infrastructure is
  ready;
- exact test results and evidence belong in the PR-specific
  design/implementation documents — update this file when a stage
  completes, but do not turn it into a detailed run log.

**Top-level completion rule**: a top-level PR checkbox is marked `[x]`
only when every blocking requirement for that work item has been
completed with recorded evidence. A code merge alone is not sufficient
when the work item also includes empirical evaluation or behavioral
validation. Optional production activation or default changes remain
separate decisions unless explicitly listed as blocking for that PR.
Concretely: PR 1 may complete even if the secondary per-file table is
explicitly deferred; PR 2's implementation merge precedes empirical
strategy completion; PR 3's deterministic plumbing may merge before
behavioral validation and activation; PR 4b's routing infrastructure
may merge in observe-only mode; PR 6's deterministic stop-policy
implementation may merge while agent-behavior claims remain unmade or
unvalidated; PR 7+ sub-PRs must each satisfy their own behavioral
contracts.

### Phase I — Repair the search substrate

- [x] PR 1 — Chain-level incumbents *(merged 2026-07-28, PR #137
      `6678d19`; coupling flag OFF — P1-ACT activation is a separate
      pending operator decision, tracked in the PR 1 Delivery
      checkpoints and the design doc §0)*
- [ ] PR 2 — Data ordering as an optimization dimension
- [ ] PR 3 — Structured HealthGate feedback propagation

### Phase II — Make feedback alter execution safely

- [ ] PR 4a — Threshold and aggregation study
- [ ] PR 4b — Adaptive routing and fingerprint avoidance
- [ ] PR 6 — Stateful stop policies

### Parallel non-blocking work

- [ ] PR 5 — Metric integrity and score-variant analysis
- [ ] O1a — GPU clock/utilization/contention provenance
- [ ] O2 — Single-chain launcher selector

### Phase III — Workflow evolution

- [ ] PR 7+ — Multi-PR workflow-evolution epic

## 2. Carried-over capability groups (from the V18 draft)

### 2.0 PR ladder — phased organizing view (rev 2, operator revision 2026-07-27)

The capability groups in §2.1–§2.9 are kept below; this subsection is
the organizing layer: phases, PR assignments, per-PR validation class
(taxonomy in §4), and per-PR exit contracts. Rev 2 incorporates the
operator revision request of 2026-07-27: phase organization instead of
a strict rank, PR 0 folded into PR 2, per-PR validation classes, and
removal of the FCNet-reproduction framing from PR 2.

Framing rule for the whole ladder (§1.4): FCNet is the target
benchmark, not the implementation template; implementation choices are
candidate mechanisms whose value must be demonstrated empirically on
HealthGate-valid formal score.

#### Phase I — Repair the search substrate

Three complementary foundations. The implementation ORDER is
operator-fixed (PR 1 → PR 2 → PR 3), but this is an execution order,
NOT a scientific-importance ranking — the three solve different
foundational problems:

- **PR 1** fixes cross-iteration memory and decision-state correctness;
- **PR 2** expands the searchable training-policy space;
- **PR 3** provides the evidence needed to improve the
  HealthGate-valid round rate.

| PR | Title | Sections | Class (§4.1) | Depends on |
|----|-------|----------|--------------|------------|
| **PR 1** | Preserve and use chain-level incumbents | §2.4 | mixed | — |
| **PR 2** | Expose data ordering as a controlled optimization dimension (commit A: minimal indexed-dataset seam + coupling ledger; commit B: ordering implementation) | §2.9 + §1.3 artifacts | deterministic + empirical optimization study | — |
| **PR 3** | Propagate structured HealthGate evidence into downstream agent context | §2.1 | agent-behavior | — |

#### Phase II — Make feedback alter execution safely

| PR | Title | Sections | Class (§4.1) | Depends on |
|----|-------|----------|--------------|------------|
| PR 4a | Threshold & aggregation study | §2.2 (study half) | analysis/policy | PR 3; campaign data (can begin on the 17 closed V18r iterations; full bands preferred) |
| PR 4b | Adaptive routing + collapse-fingerprint avoidance | §2.2 (activation half) | mixed | PR 4a |
| PR 6 | Stateful stop policies | §2.3 | primarily deterministic (mixed if planner-behavior claims are made) | PR 1 (terminal-state/resume contracts) |

#### Parallel non-blocking track

| PR | Title | Sections | Class (§4.1) | Notes |
|----|-------|----------|--------------|-------|
| PR 5 | Metric integrity & score-variant analysis | §2.6 | analysis/policy | parallel research track; does NOT block the ladder unless it discovers a critical flaw HealthGate cannot mitigate |
| O1a | GPU clock/utilization/contention provenance recording ONLY | §3 item 1a | deterministic | recording only, no behavior change; separated from adaptive margins (O1b, §3) which change admission behavior and come after Phase II review |
| O2 | Single-chain launcher selector `--only` | §3 item 2 | deterministic, trivial | can land any time, incl. before the V18r restart |

#### Phase III — Larger workflow evolution

| PR | Title | Sections | Class (§4.1) | Depends on |
|----|-------|----------|--------------|------------|
| PR 7+ | Cross-iteration workflow evolution: meta-planner, run monitor, modular orchestration (multi-PR epic) | §2.5 | agent-behavior heavy | Phases I–II stable |

No dedicated PR: §2.7 forensic backlog (opportunistic), §2.8 DEFER
bookkeeping (table only).

#### PR 0 disposition (folded into PR 2 — operator, 2026-07-27)

There is no standalone genericity-contract PR. PR 2 carries it as two
independently reviewable commits:

```text
PR 2 commit A
Minimal indexed-dataset genericity contract and TIDMAD coupling ledger

PR 2 commit B
Data-ordering implementation against that contract
```

The rider stays narrow and in-passing: define only the seam the PR
requires; update the coupling ledger; add a minimal synthetic
second-dataset contract test; keep the canonical TIDMAD metric and
behavior unchanged; keep the genericization commit independently
reviewable and skippable for urgent fixes. Do not design a large
generic abstraction before a real implementation exercises it.

#### Per-PR exit contracts

Every PR-specific design document must complete the design and
validation template defined below in this subsection: problem
statement; direct relationship to the HealthGate-valid formal score
goal; scope; non-goals; deterministic acceptance criteria;
agent-behavior acceptance criteria (where applicable); synthetic
pseudo evaluation plan; real-LLM + real-training evaluation plan
(where required); estimated validation time and cost (§4.4 budget
table); dependencies; implementation checkpoint; merge decision;
production-activation decision; rollback condition. **An
agent-behavior PR may never exit with only "fields added, prompt
updated, one example looked correct."** The blocks below pin the
non-obvious fields now; the rest is completed in each PR's design doc.

Standard progress-checkpoint template — adapted per PR class; each PR
block below carries its own instantiated checklist, and irrelevant
checkpoints are omitted rather than kept for uniformity (a
deterministic launcher fix needs no agent-behavior validation):

```markdown
- [ ] Code and current behavior audited
- [ ] PR-specific design document approved
- [ ] Scope and non-goals frozen
- [ ] Implementation completed
- [ ] Deterministic validation completed
- [ ] Agent-behavior validation completed, if applicable
- [ ] Validation time, GPU time, and API cost recorded
- [ ] Stop-and-show reviewed
- [ ] PR merged
- [ ] Production activation approved, if separate
- [ ] Post-activation evidence reviewed
```

For every `[x]`, the PR design or implementation log must record the
relevant evidence (commit/PR number; test command; pass/fail counts;
synthetic campaign size; real-training Gate result; cost and runtime;
activation decision; rollback status). Exact test results belong in
the PR-specific documents, not in this priorities file.

**PR 1 — Preserve and use chain-level incumbents (mixed)**

- Problem: `current_run_best_formal_score` is stuck at 0.0 across the
  per-iteration subprocess boundary; no cross-iteration best memory.
- Goal link: formal-decision economics measure against the real
  incumbent, so formal budget concentrates on genuinely better
  candidates.
- **Blocking scope (the PR 1 exit condition) = §2.4.a**: reconstruct
  chain-local best valid formal score; maintain trial incumbent as
  context only; key aggregate incumbents by resolved
  DataScope/run-invariants identity; preserve deterministic resume;
  handle missing incumbent, interrupted iterations, legacy records,
  ties, replayed artifacts, partial campaigns; only valid formal
  incumbents affect formal decision economics.
- **Secondary scope = §2.4.b** (per-file best table): separate commit;
  design = incremental materialization + deterministic rebuild script
  from committed per-round file vectors; **if unexpectedly large,
  explicitly defer the table without blocking the incumbent fix**.
- Deterministic acceptance: exact reconstruction tests over all edge
  cases above; negative tests (invalid/phantom records never become
  incumbents).
- Agent-behavior claim (incumbent context changes the next proposal),
  ONLY if the PR makes it: synthetic control/treatment with several
  incumbent histories, repeated LLM sampling (§4.2 L2), and a small
  real-training confirmation across at least one iteration boundary
  (§4.2 L3). **If the PR does not validate behavioral use, it must
  limit its claim to state correctness and context availability.**
- Rollback (CORRECTED — operator revision 2026-07-27): rollback
  disables the use of the reconstructed incumbent in formal-gate
  decision logic while preserving correct incumbent reconstruction,
  persistence, and provenance. Incumbent reconstruction and recording
  remain enabled; incumbent-driven skip/bypass decisions may be
  disabled by configuration. **The rollback flag must not cause the
  chain incumbent to be replaced by 0.0** — the fixed-0.0 behavior is
  the correctness defect this PR removes, and rolling back to a defect
  would corrupt the decision context again.

##### PR 1 progress checkpoints

*Design and audit*

- [x] Current incumbent-loss path re-audited from code
- [x] Committed-manifest source of truth confirmed
- [x] Scope-key and run-invariants identity design approved
- [x] Legacy, interrupted, replayed, and partial-campaign semantics approved
- [x] Tie-breaking and no-incumbent initialization approved
- [x] Rollback semantics approved without restoring the fixed-0.0 bug

*Blocking deterministic implementation*

- [x] Valid-formal incumbent reconstruction implemented
- [x] Trial incumbent context implemented
- [x] Validity filtering implemented
- [x] Scope-keyed persistence implemented
- [x] Resume and replay behavior implemented
- [x] Formal-gate decision wiring implemented
- [x] Invalid and phantom scores proven unable to become decision incumbents
- [x] Deterministic reconstruction and negative tests passed

*Secondary per-file bookkeeping*

- [x] Incremental per-file table design approved
- [x] Incremental materialization implemented
- [x] Deterministic rebuild script implemented
- [x] Raw-best and valid-best separation verified
- [x] Sampling provenance preserved
- [ ] Historical rebuild tested *(deferred per §2.4.b — rebuild of
      pre-PR-1 historical workspaces is explicitly non-blocking;
      synthetic-workspace rebuild determinism IS tested)*
- n/a — Secondary table explicitly deferred if it threatens the
  blocking scope *(condition never triggered; table shipped in PR 1)*

*Agent-behavior validation — only if behavioral use is claimed
(otherwise mark n/a in the PR design and limit the claims accordingly)*

- n/a — PR 1 makes no behavioral claim (design doc §5); its claims are
  limited to state correctness and context availability. The
  behavioral question (does incumbent context change proposals?)
  remains open for a future validation effort.

*Delivery*

- [x] Validation budget and actual cost recorded
- [x] Stop-and-show approved
- [x] PR merged *(PR #137, merge `6678d19`, 2026-07-28; coupling flag
      still OFF)*
- [ ] Incumbent-driven decision coupling activation approved *(P1-ACT
      — separate operator decision)*
- [ ] Post-activation incumbent behavior reviewed

**PR 2 — Expose data ordering as a controlled optimization dimension
(deterministic + empirical optimization study)**

- Problem: ordering is hardcoded (global shuffle) and therefore
  unavailable as an optimization dimension.
- Goal link: determine whether alternative ordering strategies improve
  HealthGate-valid formal score. The official FCNet sequential-per-file
  procedure is evidence ordering MAY matter — not a reproduction
  target.
- Scope: `order_strategy = "shuffle" | "sequential"`,
  `file_order = list[int] | None`; commit A seam + ledger (above).
- Non-goals: per-file optimizer re-initialization (separate candidate,
  only if later evidence suggests it); eval/scoring order; changing
  the default.
- Success criteria: current global-shuffle behavior remains the
  default and is unchanged; sequential ordering is expressible and
  correctly implemented (verified by inspecting the actual visited
  file/segment sequence against the selected policy); strategy and
  provenance are recorded; runtime, memory, HealthGate-valid rate, and
  score are comparable across strategies under equivalent budgets; the
  better-performing strategy is selected based on evidence; **sequential
  ordering may be rejected or abandoned if it does not improve score**.
- Validation (initial ideas; §4): deterministic — exact file ordering
  (`file_order=[4,6,5]` visits exactly `[4,6,5]`); exact within-file
  behavior; default-shuffle parity; DataScope validation; RT2
  runtime-control compatibility; resume behavior; memory
  measurements. Empirical — controlled comparison of ordering
  strategies under matched budgets on HealthGate-valid rate, score,
  runtime, memory.
- The score comparison is an empirical optimization study, NOT an
  LLM-behavior evaluation — unless the planner is allowed to select
  the ordering and the PR claims it selects appropriately, in which
  case that specific claim is agent-behavior and triggers §4.2/§4.3.
  No superiority claim without score evidence.
- **Merge vs strategy selection (operator revision 2026-07-27)**:
  `ordering implementation merged` is separate from `an ordering
  strategy recommended, planner-selectable, or made the production
  default`. The implementation may merge after deterministic
  correctness, compatibility, runtime-control, memory, and provenance
  checks pass — but **implementation completion does not imply
  sequential superiority**. Strategy promotion requires matched-budget
  empirical evidence covering: HealthGate-valid formal score;
  valid-round rate; wall time; peak host memory; GPU utilization where
  relevant; runtime-prediction accuracy; stability across repeated
  runs. The existing `shuffle` behavior remains the default until
  empirical evidence and operator review support a change; if
  `sequential` does not improve the target metrics, it remains an
  available option but is not promoted.
- **Completion semantics (lock revision, 2026-07-27)**: the PR 2
  ordering implementation may merge after deterministic correctness,
  compatibility, provenance, runtime-control, memory, and
  default-parity validation pass. The top-level PR 2 work item is
  marked complete only after the matched-budget empirical strategy
  evaluation has been reviewed. Strategy recommendation, planner
  exposure, and production-default changes remain separate
  evidence-based decisions. Lifecycle:

  ```text
  ordering capability implemented and deterministically validated
  → implementation may merge
  matched-budget shuffle/sequential evaluation completed
  → empirical evidence reviewed
  strategy recommendation made
  → optional planner exposure may be considered
  operator approval
  → optional production-default change
  all required implementation and empirical work complete
  → top-level PR 2 checkbox may become [x]
  ```

  PR 2 remains ONE top-level roadmap item — do not split into PR 2a/2b
  unless implementation work later demonstrates a real need.

##### PR 2 progress checkpoints

*Design and genericity seam*

- [ ] Current loader and ordering behavior re-audited from code
- [ ] Minimal indexed-dataset contract approved
- [ ] TIDMAD coupling ledger created or updated
- [ ] Synthetic second-dataset fixture designed
- [ ] `shuffle` and `sequential` semantics approved
- [ ] Within-file ordering semantics approved
- [ ] `file_order` validation semantics approved
- [ ] Operator-only versus planner-selectable decision resolved
- [ ] Runtime-control compatibility design approved

*Commit A — bounded genericity work*

- [ ] Minimal indexed-dataset seam implemented
- [ ] TIDMAD path-template coupling extracted where required
- [ ] Coupling ledger updated
- [ ] Second-dataset contract tests passed
- [ ] Canonical TIDMAD metric and current default behavior unchanged

*Commit B — ordering implementation*

- [ ] `order_strategy` schema implemented
- [ ] `file_order` schema and validation implemented
- [ ] Default global-shuffle parity verified
- [ ] Sequential file visitation implemented
- [ ] Exact visited file sequence tests passed
- [ ] Within-file behavior tests passed
- [ ] DataScope boundary tests passed
- [ ] Resume and provenance behavior passed
- [ ] Runtime-control workload and setup accounting updated
- [ ] Memory behavior measured
- [ ] CLI, workflow, tuner, and comparison-script propagation verified

*Empirical strategy evaluation*

- [ ] Matched-budget comparison design approved
- [ ] Validation runtime and cost estimated
- [ ] Small pilot completed
- [ ] `shuffle` comparison runs completed
- [ ] `sequential` comparison runs completed
- [ ] HealthGate-valid rate compared
- [ ] HealthGate-valid formal score compared
- [ ] Runtime and memory compared
- [ ] Prediction-quality impact compared
- [ ] Uncertainty and run-to-run variation reported
- [ ] Strategy recommendation made from evidence

*Delivery and activation*

- [ ] Stop-and-show approved
- [ ] Ordering implementation merged
- [ ] Matched-budget evaluation completed
- [ ] Strategy recommendation reviewed
- [ ] Planner-selectable ordering approved, if applicable
- [ ] Production-default change approved, if applicable
- [ ] Post-activation evidence reviewed
- [ ] Top-level PR 2 complete (implementation + empirical evaluation reviewed)

**PR 3 — Propagate structured HealthGate evidence (agent-behavior)**

- Problem: structured gate signals stop at `ExperimentRecord`; the
  interpreter and proposer see prose only.
- Goal link: raising the HealthGate-valid round rate — the binding
  constraint (15/17 V18r iterations had zero valid trials).
- The PR distinguishes **information delivery** from **behavioral
  use**. Deterministic plumbing (delivery): per-round structured gate
  fields exist in `ModelRunSummary`; legacy records remain compatible;
  interpreter receives the structured evidence and its output preserves
  the relevant collapse fingerprint; proposer receives the interpreted
  structured evidence in the next relevant context; no routing behavior
  changes yet. **Delivery alone does not complete the PR.**
- Behavioral use: all three §4.2 layers mandatory, with a §4.3
  pre-registered contract (control = text-only/no structured collapse
  feedback; treatment = structured gate fields + fingerprint), repeated
  sampling, and the §4.3 metric set. Synthetic coverage spans several
  collapse and non-collapse conditions; the real-training test (L3)
  verifies that REAL HealthGate evidence enters the next agent context
  and produces a meaningful decision change.
- **Completion, merge, and activation semantics (lock revision,
  2026-07-27)**: Layer-1 delivery alone does not complete the
  behavioral objective and does not permit production activation.
  Deterministic plumbing may merge behind a disabled or recording-only
  boundary after its deterministic acceptance criteria pass (§4.5).
  However, the top-level PR 3 work item remains incomplete until
  Layers 2 and 3 have been completed, reviewed, and shown to support
  the claimed behavioral improvement. Lifecycle:

  ```text
  Layer 1 deterministic plumbing validated
  → infrastructure may merge with behavior disabled
  Layer 2 synthetic real-LLM evaluation completed
  → behavioral evidence accumulated under controlled scenarios
  Layer 3 bounded real-LLM + real-training validation completed
  → real-system behavior confirmed
  operator review
  → production activation may be approved
  all required evidence complete
  → top-level PR 3 checkbox may become [x]
  ```

  A merge commit or prompt-plumbing test alone must never mark the
  top-level PR complete.

##### PR 3 progress checkpoints

*Design and behavioral contract*

- [ ] Current gate-information path re-audited from code
- [ ] Structured gate-field schema approved
- [ ] Collapse-fingerprint representation approved
- [ ] Control and treatment conditions defined
- [ ] Superficial-compliance rubric defined
- [ ] Behavioral success and failure metrics defined
- [ ] Relevant Layer-2 scenario subset selected and justified
- [ ] Expected sample size and uncertainty plan defined
- [ ] Validation wall time and API cost estimated
- [ ] Layer-3 Gate design aligned with `docs/gates/`

*Layer 1 — deterministic delivery*

- [ ] Per-round gate fields added to `ModelRunSummary`
- [ ] Legacy records remain compatible
- [ ] Interpreter receives accurate structured evidence
- [ ] Interpreter preserves collapse fingerprints
- [ ] Proposer receives the correct interpreted evidence
- [ ] Stale or unrelated evidence is not substituted
- [ ] Prompt/context snapshots validated
- [ ] No production routing behavior changed

*Layer 2 — true LLM with synthetic pseudo campaign*

- [ ] Small pilot completed
- [ ] Runtime and variance estimate updated
- [ ] Full bounded sample plan approved
- [ ] Control samples completed
- [ ] Treatment samples completed
- [ ] Repeated-collapse scenarios completed
- [ ] Distinct-fingerprint scenarios completed
- [ ] Invalid-high-score scenarios completed
- [ ] Conflicting and near-threshold gate scenarios completed
- [ ] Recovery-after-failure scenarios completed
- [ ] Semantically equivalent repeat proposals evaluated
- [ ] Behavioral metrics aggregated
- [ ] Confidence intervals or uncertainty summary reported
- [ ] Hallucinated or unsupported feedback-use claims categorized

*Layer 3 — true LLM with true training*

- [ ] Relevant Gate documentation reread
- [ ] Minimal real-training scope designed
- [ ] Expected GPU time, wall time, and API cost reported
- [ ] Operator approval obtained
- [ ] Real HealthGate feedback produced
- [ ] Feedback reached the next agent context
- [ ] Meaningful decision change evaluated
- [ ] End-to-end artifacts and provenance validated
- [ ] Real-system limitations reported

*Merge and activation*

- [ ] Deterministic plumbing stop-and-show approved
- [ ] Deterministic plumbing merged (behavior disabled / recording-only)
- [ ] Behavioral validation completed (Layers 2–3 done and reviewed)
- [ ] Production activation approved
- [ ] Rollback path verified
- [ ] Post-activation HealthGate-valid rate reviewed
- [ ] Top-level PR 3 complete (all layers support the claimed behavioral improvement)

**PR 4a — Threshold & aggregation study (analysis/policy)**

- Must produce a **versioned policy proposal with evidence and
  uncertainty**, not exploratory plots. No LLM-behavior claim is
  necessary unless LLM interpretation is part of the analysis.
- Required outputs: empirical gate distributions;
  architecture-family dependence; threshold candidates; aggregation
  comparison (`any_pass`/`all_pass`/numeric); false-positive/
  false-negative (or equivalent) tradeoffs; impact on retention of
  valid formal rounds; a disposition for every gate — activate,
  remain recording-only, or insufficient evidence.

##### PR 4a progress checkpoints

- [ ] Campaign datasets and eligibility rules frozen
- [ ] Gate distributions computed
- [ ] Architecture-family dependence analyzed
- [ ] Threshold candidates evaluated
- [ ] `any_pass`, `all_pass`, and numeric aggregation compared
- [ ] False-positive and false-negative tradeoffs estimated
- [ ] Valid-formal retention impact estimated
- [ ] Missing or insufficient evidence identified
- [ ] Every gate assigned a preliminary disposition
- [ ] Versioned policy proposal written
- [ ] Uncertainty and limitations reported
- [ ] Policy proposal reviewed
- [ ] No behavior change confirmed

**PR 4b — Adaptive routing + fingerprint avoidance (mixed)**

- Deterministic routing logic: exact tests (action resolution,
  severity, persistence).
- Collapse-fingerprint avoidance and proposer adaptation: true-LLM
  pseudo (§4.2 L2) and bounded true-training (§4.2 L3) validation.
- Activation is a separate operator decision with rollback to
  observe-only.

##### PR 4b progress checkpoints

*Deterministic routing*

- [ ] PR 4a policy version selected
- [ ] Routing schema approved
- [ ] Action-resolution tests passed
- [ ] Severity and aggregation tests passed
- [ ] Persistence and resume tests passed
- [ ] Observe-only rollback verified

*Agent behavior*

- [ ] Fingerprint-avoidance behavioral contract defined
- [ ] Relevant synthetic scenario subset selected
- [ ] Layer-2 control/treatment evaluation completed
- [ ] Repeated sampling and uncertainty reported
- [ ] Layer-3 real-training validation approved
- [ ] Layer-3 validation completed
- [ ] Unintended over-avoidance evaluated

*Activation*

- [ ] Merge approved
- [ ] PR merged with behavior disabled or recording-only, if appropriate
- [ ] Production activation separately approved
- [ ] Post-activation routing outcomes reviewed
- [ ] Rollback readiness confirmed

**PR 5 — Metric integrity & score-variant analysis (analysis/policy,
parallel, non-blocking)**

- Runs beside the ladder; escalates only on discovery of a critical
  metric flaw that HealthGate cannot mitigate.
- Validation focuses on offline metric integrity, HealthGate overlap,
  and score comparability; no agent-behavior testing unless the metric
  is surfaced to agents and a behavioral claim is made.

##### PR 5 progress checkpoints

- [ ] Existing metric and HealthGate overlap audited
- [ ] Collapse and phantom families included in the analysis
- [ ] Canonical metric byte-identity confirmed
- [ ] Integrity-gate incremental value evaluated
- [ ] Score-variant candidates defined, if justified
- [ ] Paper comparability impact analyzed
- [ ] Offline experiments completed
- [ ] Governance recommendation written
- [ ] Critical flaw escalation decision made
- [ ] Main V19 ladder remains unblocked unless a critical flaw is confirmed

**PR 6 — Stateful stop policies (primarily deterministic)**

- Counters, reconstruction, terminal states, resume: deterministic
  exact tests (incl. deterministic reconstruction from persisted
  history).
- Any claim that planner behavior improves because of the surfaced
  stop reason is agent-behavior and triggers §4.2/§4.3 — otherwise do
  not make the claim.

##### PR 6 progress checkpoints

- [ ] Stop-policy state model approved
- [ ] `ScoreValidityResult` implemented
- [ ] `RoundHealthClassification` implemented
- [ ] Independent counters implemented
- [ ] OR aggregation implemented
- [ ] Persisted-history reconstruction implemented
- [ ] Resume and replay tests passed
- [ ] `completed_early` terminal-state contracts implemented
- [ ] Monitoring and wrapper compatibility verified
- [ ] Default-disabled behavior verified
- [ ] Synthetic deterministic stop scenarios passed
- [ ] Agent-behavior validation completed only if planner-improvement claims are made
- [ ] Activation policy reviewed
- [ ] PR merged
- [ ] Production activation separately approved

**PR 7+ — Workflow evolution (agent-behavior heavy)**

- Every behavioral claim requires its OWN explicit §4.3 evaluation
  contract, controls, repeated sampling, and bounded Gate-style
  real-system validation. One broad epic-level demonstration must not
  be allowed to validate multiple unrelated claims — no epic-level
  exit without per-claim evidence.

##### PR 7+ epic checkpoints

(no single checklist for the whole epic — each sub-PR uses the
standard agent-behavior checklist)

- [ ] Epic decomposed into independent behavioral claims
- [ ] Each claim assigned its own PR/design document
- [ ] Each claim has a separate evaluation contract
- [ ] Shared infrastructure separated from behavior-changing logic
- [ ] Merge and activation boundaries defined per sub-PR
- [ ] No epic-level behavioral claim accepted from one broad demo

### 2.1 Feedback propagation — REMAINDER  *(→ PR 3)*

Landed in V18: condensed health-validity propagation
(`best_raw_health_validity`, `per_model_raw_best_health_validity`,
HealthGate-valid candidate selection — PR #124).

Remaining:

- **Per-round structured gate fields in `ModelRunSummary`** — per-round
  `is_degenerate`, `failure_reason`, `gate_action`, counterfactual
  production-verdict fields; protocol update in
  `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py` (today
  the protocol carries no gate fields).
- **Interpreter prompt template** — surface the structured collapse
  fields; drop text-only interpretations.
- **Proposer prompt template** — explicit collapse-fingerprint avoidance
  from the propagated fields.

Dependencies: none. Blocks: 2.2 (fingerprints), 2.5 (cross-iteration flow).

**Acceptance strengthening (operator revision 2026-07-27)**: this item
is NOT complete when the fields appear in a schema or prompt. The
claim is that structured HealthGate evidence improves downstream agent
behavior, so the PR must separately demonstrate (a) information
delivery — the deterministic plumbing above — and (b) behavioral use,
via the mandatory three-layer validation of §4.2 with the §4.3
control/treatment contract, repeated sampling, and statistical
reporting. Deterministic plumbing may still merge behind a disabled or
recording-only boundary per §4.5 — but the top-level work item stays
incomplete until behavioral validation concludes. See the PR 3 exit
contract in §2.0.

### 2.2 Adaptation  *(→ PR 4a study / PR 4b activation)*

Unchanged from the V18 draft — none of it landed (V18r still runs the
frozen observe-mode policy):

- **Threshold study** — now with V17 campaign + legacy-V18 + V18r
  evidence: do `min_unique_int8_values=25`, `min_std_mv=1.0`,
  `collapse_threshold=0.95` hold per-architecture? Escalates
  `production_disposition: undetermined` → concrete values.
- **Aggregation-policy search** — `any_pass` vs `all_pass` vs numeric,
  against real campaign data.
- **Adaptive routing** — blocking-style checks route to
  `invalidate_round` / `skip_to_formal` once evidence supports the
  threshold.
- **Cross-iteration collapse-fingerprint avoidance** — proposer seeded
  with prior rounds' fingerprints.

Dependencies: 2.1. V18r produces additional evidence (e.g. the observed
20-unique-int8 near-threshold cases on files 4-9).

### 2.3 Independent stateful stop policies  *(→ PR 6)*

Carried verbatim from the V18 draft (nothing landed; the `gate-exhaustion`
surfacing that exists today is not the typed circuit breaker):

An optional, tuner-scoped circuit breaker evaluates persisted
completed-round observations without changing scorer mathematics or
per-gate routing:

```text
score validity → HealthGate observation → round-health classification
  → independent tuner stop policies → routing decision
```

Candidate policies: repeated model collapse, repeated invalid score —
independent consecutive-round counters, OR aggregation, every blocking
policy recorded. Scorer stays stateless; only the policy layer may
resolve `stop_remaining_rounds`. Streaks are tuner-local (never spanning
workflow iterations, models, or chains); baselines and failed attempts
do not seed counters.

Implementation goals: typed `ScoreValidityResult` (independent of
HealthGate); typed `RoundHealthClassification`
(`healthy`/`collapsed`/`indeterminate`); tuner-level stop-policy
evaluator; OR-aggregated typed routing results; deterministic
reconstruction from persisted history; policy-result persistence and
audit metadata; a successful `completed_early` terminal state
(new tuner/wrapper/resume/monitoring contracts, without weakening
PR #121's partial-campaign protection); default-disabled operational
circuit breaker enabled only after campaign policy review.

### 2.4 Cross-iteration best-score maintenance  *(tracked: issue #136)*  *(→ PR 1 — operator-fixed)*

**Priority 2 (operator, 2026-07-27).** Scope expanded from the original
"formal incumbent" item: maintain BOTH the best trial score and the
best formal score across iterations, plus a per-file best table as
bookkeeping.

**Problem (confirmed live in V18r production, 2026-07-24; see
`reports/v18r_campaign_audit_20260725.md` §15 and issue #136 item 1)**:
the formal-gate reference `current_run_best_formal_score` is fixed at
the schema default 0.0 every iteration because each iteration is a
fresh `run_one_iteration.py` subprocess and `RestoredState` restores
plugins/vocab/proposal but not the best score. Consequently the
skip-formal / bypass-formal deltas measure against a constant, and no
iteration ever knows the chain's actual incumbent.

#### 2.4.a Decision state — chain incumbents (strict)  *(BLOCKING scope — the PR 1 exit condition)*

Committed, chain-local state, reconstructed from committed
prior-iteration manifests (`best_valid_formal_score` is already
persisted there), frozen at iteration start, updated only after a
successful iteration commit, active next iteration:

```text
chain_best_valid_formal_score: float | None   # feeds decision logic
chain_best_valid_formal_record: provenance | None
chain_best_trial_score: float | None          # context/bookkeeping only
chain_best_trial_record: provenance | None
```

- Only the **valid-formal** incumbent may feed decision logic
  (`skip_formal_min_delta` / `bypass_formal_time_budget_min_delta`).
  Eligibility: formal, HealthGate-valid under production policy.
- The **trial** incumbent is read-only context (interpreter/proposer
  visibility); trial scores are small-sample estimates
  (`eval_portion` 0.02–0.2) and must never gate formal economics.
- Loss and architecture chains keep independent incumbents.
- **Scope-keyed (DS8 note 2026-07-23)**: aggregate scalars are only
  comparable within one resolved `data_scope` — key the committed
  state by resolved scope / run-invariants lock identity.
- The design must specify: no-incumbent initialization,
  partial-campaign eligibility, legacy records with missing HealthGate
  metadata, stable tie-breaking, interrupted iterations,
  duplicate/replayed artifacts, `--auto_resume`, equivalence with
  in-process `run_workflow(max_iterations>1)`, and a deterministic
  migration from the fixed `0.0` reference.
- Deliberate design decision: a rising incumbent bar saves formal
  budget but reduces formal sampling — quantify before enabling
  gate-coupling (V18r evidence: the gates never fired anyway because
  no valid trial existed; see audit §15).

#### 2.4.b Bookkeeping — per-file best table (permissive, labeled)  *(SECONDARY scope — separate commit; explicitly deferrable)*

Operator proposal (2026-07-27), accepted with auditor guardrails: a
chain-level table of per-file bests, maintained for future analysis
(not consumed by any decision logic in V19).

Rows: one per (file, phase ∈ {trial, formal}, validity ∈ {raw, valid}).
Columns (provenance is mandatory):

```text
file_index, phase, validity,
best_log_score,            # log_5.27 of the file's linear mean
iteration, round, exp_id, model_type, model_params,
eval_strategy, eval_portion,   # sampling provenance — REQUIRED
gate_summary,                  # which blocking checks passed/failed
timestamp
```

Auditor guardrails (from the 2026-07-27 V17/V18r audit):

1. **Validity labeling is mandatory** — without it the table's bests
   are topped by phantom-family artifacts (the 5.5762667 class-127
   score would be the all-time best on most files). Raw-best and
   valid-best are separate rows, never merged.
2. **Sampling provenance is mandatory** — per-file trial values at
   2–5 % portions swing by whole log units between rounds (observed:
   file 16 at 4.60 vs 2.49 in adjacent V17 rounds). A best without
   its `eval_portion` is uninterpretable.
3. Per-file values ARE cross-scope comparable (unlike aggregates), so
   this table may span scopes — that is its main analytical value
   (e.g. comparing a 10-14 chain against a full-scope run per file).
4. Source of truth remains the per-round `file_vector` in
   `run_output_iter_*.json`; the table is a materialization and must
   be deterministically rebuildable from those records (rebuild
   script doubles as the migration path for existing V17/V18r data).

Design fork RESOLVED (operator revision, 2026-07-27): **incremental
materialization + a deterministic rebuild script from the committed
per-round file vectors** — both, not either. The table is a separate
commit inside PR 1; migration, historical rebuild, or persistence
complexity must not block the strict §2.4.a incumbent fix — if this
half grows unexpectedly large, it is explicitly deferred without
blocking PR 1.

### 2.5 Workflow evolution  *(→ PR 7+ — multi-PR epic, last)*

Unchanged from the V18 draft: bidirectional cross-iteration information
flow (beyond the vocab/previous-proposal restoration that exists);
iteration-level meta-planner; Run Monitor agent; modular orchestration
(multi-week rework).

### 2.6 Metric refinement — REMAINDER  *(→ PR 5 — parallel, non-blocking research track)*

Landed in V18 (modified form): the correlation guard shipped as the
`pearson_dispersion_recording` HealthGate check (M8 §3.4 — dispersion of
per-file pearson, at the gate layer, recording-only), NOT as a
`score_vector`-internal gate.

Remaining: decide whether an in-`score_vector` integrity gate adds
signal beyond the HealthGate check (now answerable with campaign data);
collapse-resistant score formula variants (governance decision —
paper-comparability).

### 2.7 Deferred forensic backlog  *(no dedicated PR — opportunistic)*

- **v15 iter-4/R4 outlier** — the `final_loss=5.03` untrained run that
  produced a 5.5763 phantom. The class-127 fingerprint mechanism is now
  fully documented (`pluggable_health_checks.md` §7.1); the specific
  historical revisit with modern diagnostics has not been done.

### 2.8 Reclassified DEFER-tier items (carried table)  *(bookkeeping — no PR)*

| Item | Prior | V19 disposition |
|------|-------|-----------------|
| Run Monitor agent | D1 | Under 2.5 workflow evolution |
| Bidirectional cross-iteration flow | D2 | Under 2.5 |
| Collapse-resistant score redesign | D3 | Under 2.6 |
| Multi-condition stop gates | D4 | Refined into 2.3 |
| Modular agent orchestration | D5 | Under 2.5 |
| ModelConfig typed Pydantic | D6 | Tech-debt; not V19-blocking |
| Info-source weighting | D7 | Follows 2.2 |

### 2.9 Data-loader ordering strategy — selection vs ordering split  *(→ PR 2 — operator-fixed)*

**Priority 3 (operator, 2026-07-27).** Audit finding (2026-07-27):
SIDERIUS has two data axes but only one is a real, settable concept.

- **Selection** (which files/segments are in play) — exists:
  DataScope + `snapshot`/`anchors`/`target` strategies +
  `train_portion` subsampling, layered and enforced.
- **Ordering** (the sequence in which selected data is visited during
  training) — does NOT exist. The production path
  (`execute_tools/train_engine_sandbox.py::run_experiment_streaming`,
  every trial and formal round) hardcodes: per-epoch subsample →
  concatenate ALL files into one `TIDMADEpochDataset` → global
  uniform shuffle (`DataLoader(shuffle=True)`, line 593). The
  "streaming"/"one file at a time" docstrings (lines 477–481, 881)
  describe a legacy implementation that no longer exists — fix that
  drift as part of this work.

**Requirement**: make ordering an independent, first-class option,
settable everywhere the data loader is invoked (tuner, workflow, chain
CLI, `run_comparison.py`), validated by a Pydantic schema before it
reaches the training subprocess (project rule: no raw LLM/operator
input to execution). Initial strategies:

```text
order_strategy: "shuffle" | "sequential"     (default: "shuffle" —
                                              preserves current behavior)
file_order:     list[int] | None             (sequential only; user-given
                                              file sequence; default None =
                                              sorted ascending file index;
                                              must be ⊆ resolved scope,
                                              no duplicates)
```

Design points to settle in the implementation design doc:

1. **Two-level ordering semantics** — `sequential` fixes the FILE
   visit order; within-file segment order is a separate sub-decision
   (proposed default: shuffle within file — the legacy TIDMAD
   `train.py` semantics are cited as prior art for this choice, not as
   a reproduction requirement). Operator to confirm.
2. **Memory model per strategy** — global `shuffle` requires the
   current full concatenation (or slow random-access HDF5 reads);
   `sequential` permits true one-file-resident streaming (restoring
   the name), cutting peak RAM from `Σ files` to `max(file)`. The
   strategy choice should select the loading implementation
   internally; at the user level only the two options above are
   visible ("clean to set").
3. **Runtime-control compatibility** — RT2 measures epoch-0 dataset
   construction as setup and counts steps from the materialized
   loader (`train_engine_sandbox.py:594-604`); per-file sequential
   construction spreads that cost across the epoch, so the
   verification/prediction model (`workload_resolvers.py`, P/M/A
   records) must learn the per-file-build term. The §12 error ledger
   is the acceptance evidence.
4. **Who may set it** — operator-only flag vs planner-selectable
   (`ExperimentPlan` field with normalization + provenance, like
   DataScope's snapshot normalization). Operator to decide.
5. **Genericity (multi-dataset)** — the ordering layer must depend
   only on an "indexed multi-file dataset" contract
   (`file_index → segment list`, resolvable to a readable file), not
   on TIDMAD naming (`abra_training_{i:04d}.h5` is currently inlined
   in the dataset classes). Porting to another indexed dataset should
   be a `task_config.yaml`-level change, per the project's
   task-agnostic rule. This item is the natural place to extract the
   file-path template out of the loader.
6. **Scope boundary** — training loader only; eval/scoring order is
   score-invariant and stays untouched. `score_vector`, HealthGates,
   and the scoring formula are explicitly out of scope.

Relevance to the §1 goal (REFRAMED — operator revision 2026-07-27):
**data ordering is currently hardcoded and therefore unavailable as an
optimization dimension; this item exposes ordering as a controlled,
comparable search variable so that SIDERIUS can determine empirically
whether alternative ordering strategies improve HealthGate-valid
formal score.** The official FCNet procedure (sequential-per-file) is
useful evidence that ordering MAY matter — V19 is not required to
reproduce or preserve it merely because the baseline used it, and
**strategy selection is governed by HealthGate-valid formal score,
runtime, memory, and resource evidence — not by fidelity to the
baseline procedure**. Sequential ordering may be rejected or abandoned
if it does not improve score. Per-file optimizer re-initialization is
**not a V19 commitment**: it is not added merely because FCNet used
it, and remains only a possible independent future variable if
evidence supports testing it. Success criteria and the controlled
strategy-comparison requirement live in the PR 2 exit contract (§2.0).

Overlap check (per the additive-then-audit process): no overlap with
§2.1–§2.8; touches the same files as 2.4 only at the
tuner-input/chain-CLI plumbing level.

## 3. New runtime-control follow-ups (from the V18r campaign, 2026-07-24)

*(also in issue #136)*

1. **Adaptive runtime margins / drift root-cause** — Wave 1A measured a
   systematic ~1.55–1.6× post-verification slowdown, uniform across a
   50× parameter range (design doc §12 Wave-1A entry). Safety-factor
   record (audited from git history 2026-07-27):
   - HISTORICAL: `43212fe` introduced the trial/formal safety-factor
     split at trial 2.0 (formal remaining on the legacy 1.5 posture);
     `d8d4f1e` raised trial 2.0 → 3.0 (operator decision); `a780186`
     set formal 2.0 (operator decision, clean restart — "posture now:
     trial 3.0 / formal 2.0", with admission simultaneously tightened
     to predicted ≤ 60 min against the 120-min formal budget).
   - CURRENT CONFIGURATION: the V18r launch surfaces
     (`launch_v18_wave1.sh`, `v18r_queue_runner.sh`) pin
     `--runtime_trial_safety_factor 3.0` /
     `--runtime_formal_safety_factor 2.0` (legacy fallback
     `--runtime_safety_factor 1.5`).
   - FUTURE POLICY (O1b, undecided): whether margins become adaptive
     (periodic re-verification or error-ledger-driven per-phase
     factors) is an open design question; candidate numeric values
     belong in the O1b design document, not in this locked baseline.
   **Split (operator revision 2026-07-27):**
   - **O1a — provenance only** (parallel non-blocking track, §2.0;
     deterministic): record GPU clocks/utilization/contention in
     observation provenance to separate sustained-load clock decay
     from neighbor contention. Recording only — no behavior change.
   - **O1b — adaptive margins** (deliberately AFTER Phase II review;
     changes admission behavior): periodic re-verification or
     error-ledger-driven per-phase safety factors instead of fixed
     operator constants, driven by O1a data.

   **O1a progress checkpoints**

   - [ ] Required GPU clock/utilization/contention fields selected
   - [ ] Collection overhead estimated
   - [ ] Recording-only implementation completed
   - [ ] Observation-schema compatibility verified
   - [ ] Missing-sensor degradation verified
   - [ ] Multi-chain provenance validated
   - [ ] No admission or watchdog behavior change confirmed
   - [ ] PR merged
2. **Launcher single-chain selector (O2)** — `launch_v18_wave1.sh {1a|1b}`
   cannot restart one chain of a pair (the Wave-1A loss restart needed a
   hand-mirrored `run_chain.sh` command). Add `--only <run_name>`.

   **O2 progress checkpoints**

   - [ ] Current launcher behavior audited
   - [ ] `--only <run_name>` interface approved
   - [ ] Valid-chain selection implemented
   - [ ] Invalid-chain rejection implemented
   - [ ] Pair-launch default behavior preserved
   - [ ] Dry-run and shell-parity tests passed
   - [ ] Documentation updated
   - [ ] PR merged

## 4. Validation and Evaluation Standard (V19-wide — operator revisions, 2026-07-27)

This standard applies to every PR in §2.0. Governing rule (§1.4): **no
V19 behavioral claim is accepted solely because information appears in
a prompt.**

**Why validation is first-class in this project**: SIDERIUS is an
agent system. The project must not infer behavioral success from
prompt construction, schema wiring, one plausible LLM response, or
qualitative inspection. Agent outputs are stochastic and can contain
superficial compliance, unsupported explanations, inconsistent
reasoning, or hallucinated use of feedback. Any claim that agent
behavior improved must therefore be supported by repeated empirical
evaluation.

**Common false-positive signals** — none of these, alone or together,
proves that a feedback mechanism works:

- the new field appears in the prompt;
- the LLM repeats the field in its explanation;
- one proposal looks different;
- the agent claims it avoided a prior failure;
- one pseudo run succeeds;
- the agent produces a confident but unsupported rationale.

The real question is whether the information produces a **measurable
and repeatable change in decisions**.

**Preliminary-but-actionable boundary**: this section defines the
required validation layers, controls, repetition, uncertainty
reporting, cost estimation, Gate-document dependency, and
operator-approval boundaries. Exact sample sizes, commands,
thresholds, prompts, datasets, and budgets are decided in the design
document of each concrete PR, after the relevant code and evidence
have been audited — they are deliberately NOT fixed here.

### 4.1 Validation taxonomy

All V19 work divides into two validation classes; every PR is labeled
in §2.0 as `deterministic`, `agent-behavior`, `mixed`, or
`analysis/policy`.

**Deterministic functionality** — e.g. chain-incumbent reconstruction;
exact data ordering; state persistence; resume behavior; threshold
routing; typed stop counters; launcher selection; schema validation.
Validated primarily by: unit tests; exact contract tests; negative
tests; deterministic pseudo execution; small integration tests;
targeted real-system checks when environment interaction matters.
Acceptance criteria must be exact and direct — e.g. if
`file_order=[4,6,5]`, the visited file sequence is exactly `[4,6,5]`.

**Agent-behavior functionality** — e.g. whether structured HealthGate
feedback changes the proposer; whether the interpreter preserves the
correct collapse fingerprint; whether the proposer avoids semantically
equivalent failed strategies; whether incumbent context influences the
next proposal appropriately; whether the tuner reacts to feedback
rather than merely repeating it; whether a meta-planner changes
strategy across iterations. These CANNOT be accepted based on prompt
presence, one successful response, or a qualitative demo. A PR must
not claim improved behavior merely because information reached the
prompt; it must show the full chain:

```text
information reached the prompt
→ the agent used it
→ the resulting decision changed in the intended direction
→ the effect is repeatable
```

### 4.2 Three-layer validation for agent behavior

**Layer 1 — Deterministic prompt and context plumbing.** Verify: the
correct fields are present; values are accurate; provenance is
preserved; stale or unrelated fields are not substituted; the
information reaches the correct agent role; the information survives
all protocol transformations; legacy and missing-field behavior is
explicit. This layer proves delivery only — it does not prove
behavioral use.

**Layer 2 — True LLM with synthetic pseudo campaign.** Real production
LLM configuration with controlled pseudo training, pseudo scoring, and
synthetic feedback. This is the primary source of statistical coverage
(cheap and fast relative to real training), so it should cover a
relatively large number of controlled scenarios, including at least:
repeated collapse with one fingerprint; multiple different collapse
fingerprints; invalid score without collapse; conflicting gate
results; near-threshold gate values; a healthy round after repeated
failures; incumbent improvement; no improvement relative to incumbent;
trial improvement without valid formal improvement; repeated proposal
of a semantically equivalent failed strategy; misleading high raw
score with invalid HealthGate evidence; misleading or incomplete
feedback; missing legacy fields. Many of these situations are
difficult, expensive, or unreliable to reproduce with real training —
which is exactly why this layer exists. Because pseudo execution is
relatively inexpensive, use enough scenarios and repeated LLM samples
to characterize stochastic behavior rather than showing a single
example. Purpose: determine whether the agent reliably changes its
behavior under controlled feedback.

**Scenario library, not a mandatory matrix**: the scenarios listed
above form a reusable V19 behavioral-validation library. Each
PR-specific evaluation selects the relevant subset, explains why the
selected cases cover the claimed behavior, and identifies any
important excluded cases. A PR is not required to run every scenario
when many are unrelated to its claim. For example: PR 1 may focus on
incumbent-improvement, no-improvement, invalid-formal incumbent, and
conflicting trial/formal histories; PR 3 focuses heavily on collapse
fingerprints, invalid high scores, conflicting gate evidence, recovery
after collapse, and semantically equivalent repeated proposals; PR 4b
focuses on routing outcomes, repeated fingerprints, near-threshold
results, and inappropriate avoidance; PR 7+ defines separate scenario
subsets for each behavioral claim rather than one giant evaluation for
the whole epic. The selected subset must still provide meaningful
coverage and repeated samples.

**Layer 3 — True LLM with true training.** A small-scale but real
production path: real LLM; real training; real inference/scoring where
relevant; real HealthGate results; real persisted context; real
next-iteration feedback. This layer does NOT reproduce every synthetic
case — its purpose is to verify that the behavior observed in Layer 2
survives contact with the real system.

Layers 2 and 3 are BOTH mandatory for any PR whose success claim
depends on changed LLM behavior.

### 4.3 Behavioral evaluation contract and statistical evidence

A single LLM response is anecdotal evidence, not validation. Every
agent-behavior or mixed PR includes an **initial validation design in
its PR-specific design document**. At the priorities stage, exact
values that cannot yet be justified are NOT invented; instead the
PR design must answer:

- What behavior is expected to change?
- What observable output represents that behavior?
- What would count as superficial compliance?
- What is the control condition?
- What is the treatment condition?
- Which synthetic situations need coverage?
- Which behaviors require real-training confirmation?
- What failure modes should be recorded?
- What evidence would be sufficient for merge?
- What evidence would be required before production activation?
- What result would trigger rollback or redesign?

The quantitative contract then specifies: scenario count; repetitions
per scenario; LLM configuration; sampling settings; control and
treatment groups; success rubric; failure taxonomy; aggregate success
rate; uncertainty reporting; merge threshold; activation threshold.

Reference control/treatment (PR 3): control = proposer receives the
previous text-only / no structured collapse feedback; treatment =
proposer receives the new structured gate fields and explicit collapse
fingerprint. Candidate metrics (finalized during PR 3 design, not
prematurely fixed here): repeated-collapse-fingerprint rate; rate of
semantically equivalent repeated proposals; explicit acknowledgment of
prior failure; material change in architecture/loss/training strategy;
inappropriate avoidance of unrelated/otherwise useful strategies;
next-round HealthGate-valid rate; valid formal score improvement;
**unsupported claims that the feedback was used**.

No universal sample size is prescribed. Choose sample size
considering: expected behavioral variance; cost per LLM call; number
of scenarios; practical effect size; available budget — optionally
after a small pilot that estimates runtime and behavioral variance.

The evaluation must distinguish genuine decision changes from
superficial wording changes. Report confidence intervals or another
appropriate uncertainty summary whenever sample sizes permit. Never
claim an improvement based only on a few favorable examples. Do not
silently reduce repetitions after seeing unfavorable variance — any
change to the planned sample size is documented with rationale.

### 4.4 Validation time, GPU-time, and API-cost budgeting

Every PR design estimates validation cost BEFORE tests are launched,
in a budget table with at least:

```text
validation layer | scenario count | samples per scenario |
expected LLM calls | expected training runs | expected wall time |
expected GPU time | expected API cost | hard upper bound |
approval requirement
```

**Synthetic pseudo campaign budgeting**: comparatively broad coverage
and repeated samples are allowed (no real training cost; many
controlled edge cases; the primary source of statistical power) — but
pseudo campaigns still consume LLM calls, tokens, wall time, and
engineering time, all estimated before launch. Sample counts are
chosen for meaningful coverage, not to maximize calls. If runtime or
variance is uncertain, run a small pilot first:

```text
small pilot → estimate variance and runtime
→ determine required sample count → run the bounded evaluation
```

Never launch a large repeated LLM experiment without first measuring
one or a few representative samples. Each agent-behavior checkpoint
provides: expected duration per sample; expected total duration;
expected number of LLM calls; expected token/API cost; expected GPU
time; concurrency assumptions; a hard upper bound; stop conditions.

**Real LLM + real-training budgeting**: intentionally small. Before
designing or launching: read the relevant documentation under
[`docs/gates/`](../gates/gate_testing_standard.md) and follow the
established Gate 1 / Gate 2 conventions; identify the closest existing
Gate scenario; use the smallest scope that still exercises the claimed
behavior; use limited rounds and iterations; avoid repeating evidence
already established by the synthetic campaign or prior Gates; estimate
GPU time, API cost, and total wall time; define hard stop conditions;
**require operator approval before any launch that combines real LLM
calls with real training**. Real behavioral validation must not turn
into a full campaign unless separately approved — use reduced
portions, small deterministic scopes, and explicit success criteria
wherever they preserve the behavioral signal.

Principle: **synthetic pseudo campaigns for broad scenario coverage
and statistical power; a small number of real-LLM + real-training runs
for end-to-end confirmation.**

### 4.5 Merge versus production activation

For agent-behavior PRs, `implementation merged` and `behavior
activated in production` are SEPARATE decisions. A PR may merge
infrastructure or recording-only support after deterministic (Layer 1)
validation while keeping behavior-changing features disabled.
Production activation additionally requires: the required behavioral
evaluation (Layers 2–3); acceptable uncertainty; operator review;
documented rollback; bounded Gate-style validation. This separation is
especially important for: adaptive routing (PR 4b); fingerprint
avoidance (PR 4b); stop-policy feedback (PR 6); meta-planner behavior
(PR 7+).

## 5. Sequencing hypothesis (superseded record)

**Superseded by the §2.0 PR ladder (2026-07-27)** — kept below as the
original pre-goal reasoning record. Not committed — starting point once
V18r data is in hand:

1. Feedback propagation remainder (2.1) — smallest surface, unblocks 2.2/2.5
2. Chain-wide incumbent (2.4) — contained, high operational value, issue #136
3. Metric refinement remainder (2.6) — parallel; independent
4. Adaptation (2.2) — needs 2.1 + campaign data
5. Runtime-control follow-ups (§3) — parallel; provenance first
6. Independent stop policies (2.3) — after completion/resume design
7. Workflow evolution (2.5) — largest surface, last
8. Forensic backlog (2.7) — throughout

## 6. Related docs

- [`v18_priorities.md`](./v18_priorities.md) — the original draft and
  V18's actual delivery record
- [`v17_priorities.md`](./v17_priorities.md) — the substrate
- [`v17_pregate_threshold_review.md`](./v17_pregate_threshold_review.md)
  — the frozen policy 2.2 reevaluates
- [`runtime_estimation_and_watchdog.md`](./runtime_estimation_and_watchdog.md)
  — runtime-control design (§12 Wave-1A evidence)
- [`../gates/gate_testing_standard.md`](../gates/gate_testing_standard.md)
  — canonical Gate 1/Gate 2 parameters and pass criteria; mandatory
  reading before designing any §4.2 Layer-3 (real-LLM + real-training)
  validation
- [`collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md),
  [`pluggable_health_checks.md`](./pluggable_health_checks.md)
