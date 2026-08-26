# OFFICIAL ARXIV CAMPAIGN — GOLDEN NOTEBOOK

**The single tracked notebook shared between the campaign-planning agent (tmux
`official-arxiv-run-31`) and the RTX 5090 Supervisor.**

There is exactly ONE golden notebook. Do not create a competing second one. If
you are a fresh agent or recovering from context compaction: **read this file
first.** It is the context-compaction recovery authority. The chat transcript is
not durable memory.

| artifact | path | role |
|---|---|---|
| campaign plan | `docs/campaign/official_campaign_plan.md` | human-readable Parts 1–8 protocol |
| decision ledger | `docs/campaign/official_campaign_decisions.yaml` | machine-readable frozen decisions |
| **golden notebook** | **this file** | current state + append-only decision/evidence history |

---

## A. CURRENT STATE

*Updated 2026-08-26.*

| field | value |
|---|---|
| campaign plan | `docs/campaign/official_campaign_plan.md` — 3,715 lines |
| decision ledger | `docs/campaign/official_campaign_decisions.yaml` — 161 entries, YAML-valid, no dangling refs |
| plan / ledger tracking | **TRACKED** as of `0914f5b8` on branch `campaign/official-arxiv-campaign-plan` (pushed). F-GOV-1 CLOSED. Content hash not yet frozen — the plan is still being corrected per §A.1. |
| master / release SHA | **`dce0ba42`** (#318 merged). Prior: `f310a264` (origin/master, per Supervisor 2026-08-26 — #320 Lane F2 campaign-portion authority merged; #321 `d74785bb` before it). **`f310a264` is the POST-FIX baseline: every runtime witness must be taken at or after it.** Tag `v0.1.0-rc.1` on `6b123947`. |
| Parts 1–8 | **all OPERATOR-FROZEN** (see §B) |
| ledger status counts | 104 FROZEN · 32 PENDING_AUDIT · 10 PENDING_IMPLEMENTATION · 5 PENDING_OPERATOR_DECISION · 3 PENDING_TESTPOD_QUALIFICATION · 2 PROVISIONALLY_FROZEN |
| post-plan adversarial scan | **NOT STARTED** — Scans A–I |
| standalone package | **NOT STARTED** |
| testpod state | not rehearsed; H100 qualification is issue #314, BLOCKED on `v0.1.0-rc.N` |
| release readiness | Supervisor-owned; not ready |

### A.1 Immediate next actions (directive §2, before any scanning)

1. ~~`num_iterations` 10 → 20~~ — **DONE.** `D-BUD-2` corrected; plan §19.2.
2. ~~FCNet+2 reference-scope confirmation~~ — **DONE, returns a blocker.**
   `A2-FCNET`; plan §19.2a. The rule stays PENDING until four per-band FCNet
   reference scores exist.
3. **Parts 1–8 consistency pass** over the fourteen stale-pattern classes named
   in directive §2 — **NEXT.**
4. Then Scans A–I.

### A.2 Open `PENDING_OPERATOR_DECISION` (5, all inherited — none from Part 8)

| id | item |
|---|---|
| `Q-LIT-1` | literature-review enabled state for the formal campaign |
| `Q-ISO-1` | `--baseline_isolation` disposition (I1/I2/I3/I4) |
| `F-LLM-2` | timeout/connection retry divergence from the frozen policy |
| `D-TOPOLOGY-1` | formal arm topology — blocked on `Q-LIT-1` + `Q-ISO-1` |
| `A6-2` | champion granularity — likely already answered by §19.9's per-band freeze; needs closure |

### A.3 Known release-side state (pushed by Supervisor — do not poll GitHub)

| item | state |
|---|---|
| `origin/master` | `d74785bb` (#321 repaired RED master) |
| PR #320 | **MERGED → `f310a264`.** Lane F2 campaign-portion authority; implements `D-BUD-7`/`D-BUD-8` |
| PR #322 | **this lane's campaign-authority tracking branch**, docs-only. **HEAD of the Supervisor's merge queue** `#322 → #315 → #319 → Lane E group 3`; only the head re-runs CI |
| PR #318 | **MERGED → `dce0ba42`** |
| PR #319 | Lane D execution→narrative provenance; base stale, lane unresponsive |
| PR #315 | Lane C failure honesty (branch `fix/failure-honesty-exit-status`) |
| Lane B | HELD on operator authorization; owns the F-Q4-2 fix |
| `F-BYPASS-WD-1` | this lane's `P7-C` gap, **CONFIRMED and ROUTED to Lane F2** with the frozen 120/200 values and the both-surfaces requirement. Not closed. |
| `F-H100-WD-1` | **watchdog DISABLED on every H100 path** — see §C. Supervisor-owned, blocked on Q5. |
| **F-Q4-2** | **BLOCKS every composed trial/formal run.** Witnessed 5/5 attempts, zero records. `--task_eval_scope_ref` has ZERO production emitters, so the explicit-leg companion flag is emitted unconditionally while the explicit leg never activates. Blocks any composed-task campaign capability. |
| testpod H100 | dual-concurrency diagnostic running. `H100_CORESIDENCY_FACTOR` for the frozen **dual_coresident** topology has **never been measured** — the existing probe measures FOUR bands, the wrong topology. |

### A.4 Issue queue / Supervisor handoffs

**None sent yet.** 10 `PENDING_IMPLEMENTATION` ledger entries plus 32
`PENDING_AUDIT` items are candidates; they must be classified per directive §4
and routed per §5 before any is treated as a Supervisor obligation.

---

## B. FROZEN PARTS 1–8 — index

| part | area | plan § | status |
|---|---|---|---|
| 1 | Treatment definition | §5 | FROZEN |
| 2 | LLM configuration + execution concurrency | §9, §9A–9F | FROZEN |
| 3 | Randomness / seeds / ordering | §10 | FROZEN |
| 4 | Task & data semantics | §16 | FROZEN except eval-portion execution semantics |
| 5 | Agent action space | §17 | FROZEN |
| — | Evaluation lifecycle + observables | §18 | `D-EVAL-1` PROVISIONALLY_FROZEN |
| 6 | Budget | §19 | FROZEN (P6/P7-A…D closed) |
| 7 | Scoring, validity, observables, selection | §20A | FROZEN |
| 8 | Failure / retry / resume / restart | §20B | FROZEN |

Cross-cutting frozen authorities: pod naming (§1) · control plane (§2) ·
no-implicit-defaults principle (§3) · fix-environment-not-outcome (§4).

---

## C. APPEND-ONLY DECISION / EVIDENCE HISTORY

Never erase. Mark `SUPERSEDED BY …` / `CORRECTED BY …` rather than rewriting.
This notebook summarises; raw logs belong in their own evidence files.

---

### 2026-08-26 — Notebook created; standing directive received

**Source.** Operator, tmux `official-arxiv-run-31`.

**Finding.** No golden notebook existed. The Supervisor's own record
(`project_arxiv_autonomous_release_program`) specifies "a single tracked
Markdown under the existing campaign-planning docs area" — created here.

**Decision.** This file is the one notebook. Full directive verbatim in §D.

**Disposition.** Recorded. Directive §2 work is the immediate next action
(§A.1).

---

### 2026-08-26 — Parts 1–8 frozen (summary; detail in the plan)

Recorded across a sequence of operator rulings. Load-bearing audited facts that
future work **must not re-derive or re-break**:

* **Trial portions are advisory, not enforced.** The tuner reads `plan.*` for
  trial rounds; `grep agent_input.{trial,train,eval}_portion` over the tuner
  node returns **NONE**. Schema fallback is `0.02 / 0.1 / 0.02`. `--plan_overrides`
  exists only on the standalone CLI and no launcher passes it. → `A4-1`.
* **Evaluation is `eval_portion` alone** — not composed with `train_portion` or
  `trial_portion`. Training is `trial_portion × train_portion`.
* **`is_trial` run-level is never mutated**; only round-level `plan.is_trial`
  flips. §16.5 matches the code exactly.
* **`TrainingHistory.observations` is `{}` in all 169 real occurrences across
  165 artifact files**, zero producers, zero consumers. → `R-OBS-1`, blocking
  v0.1.0.
* **HealthGates fire on only one of three scoring routes** — the gate block is
  nested inside `ScoringRoute.ANCHOR_NORMALIZED`. TIDMAD un-composed is safe.
* **TIDMAD blocking gates ship `any_pass`** (lenient across files). Operator
  froze `all_pass`. → `D-SCORE-3`.
* **`best_denoising_score` / `best_valid_denoising_score` mix trial and formal
  pools**; the interpreter ranks on them. Formal-only twins exist unused. → G1,
  `D-SCORE-5`.
* **Cross-band aggregation authority does not exist**, and `scoring_utils.py` §3
  names "mean of per-band log scores" and "mean of per-band linear means
  (e.g. 4/6/5/5)" as invalid — 4/6/5/5 is exactly this campaign's band
  partition. The valid construction is ONE `score_vector` call over scope
  0..19, with a working precedent at
  `scripts/score_tidmad_official_banded.py:627`.
* **Under the current H100 band-fleet path there is no wall-clock bound** —
  `runtime_profiles.yaml` has one row (`rtx_5090/single`), no launcher passes
  time budgets, and the posture declares `four_way_coresident` with no watchdog
  flags → uncalibrated → OFF. Scoring was never watchdog-wrapped in any
  configuration.
* **An API failure consumes a scientific attempt** in both the proposal loop and
  the tuner. The vocabulary to classify it correctly exists and is never applied
  to the LLM channel. → `D-BUD-14`, `A8-1`.
* **`formal_eval_portion` is not in `RunInvariants._CANONICAL`** — two
  iterations at different formal eval scopes fold into one incumbent with no
  refusal. Part 6 changes that value, making the gap reachable. → `A8-7`.

---

## D. STANDING OPERATOR DIRECTIVE — VERBATIM

*Received 2026-08-26. Recorded exactly as issued. This is the operative mandate
through final campaign readiness.*

```text
STANDING OPERATOR DIRECTIVE
OFFICIAL ARXIV CAMPAIGN PLANNING / AUDIT / PACKAGING AGENT

You are the dedicated official-campaign planning authority running in:

    tmux:
        official-arxiv-run-31

This message establishes your standing operating mandate through final campaign
readiness.

Persist these rules in tracked project documentation so they survive context
compaction.

Do not rely on this chat transcript as durable memory.

You are NOT a second release Supervisor.

The 5090 Supervisor remains the release / implementation / merge / H100
qualification authority.

You own campaign semantics, audit, issue discovery, standalone packaging, and
campaign-level evidence organization.

======================================================================
0. STANDING OPERATOR AUTHORIZATION
======================================================================

Proceed autonomously.

Do NOT stop for routine operator permission while:

    completing campaign documentation;
    reconciling Parts 1-8;
    launching read-only/adversarial subagents;
    correcting internal inconsistencies;
    deep-auditing v19/v20/current behavior;
    discovering missing features;
    writing issues;
    reporting blockers to Supervisor;
    updating campaign artifacts;
    designing the standalone campaign folder;
    implementing campaign-owned packaging/configuration;
    improving gold advice;
    strengthening blind isolation;
    reviewing testpod rehearsal evidence;
    revising campaign setup in response to verified implementation facts.

Stop only for a genuinely MATERIAL scientific/campaign ambiguity that cannot be
resolved from:

    frozen operator decisions
    existing campaign authorities
    source truth
    v19/v20 historical evidence
    mechanically verified runtime semantics.

Do not ask the operator questions simply because implementation work remains.

Implementation gaps belong to Supervisor routing.

The target is:

    campaign plan complete
    all campaign-required framework capabilities implemented
    standalone official campaign package complete
    testpod end-to-end rehearsal passed
    H100 campaign assumptions qualified
    v0.1.0 released by Supervisor
    package ready for goldpod + blindpod formal run.

======================================================================
1. DURABLE MEMORY / GOLDEN NOTEBOOK
======================================================================

Use the existing canonical campaign plan and machine-readable decision ledger.

In addition, maintain exactly ONE tracked Markdown GOLDEN NOTEBOOK shared with
the Supervisor.

If a suitable notebook already exists, reuse it.

Do not create a competing second notebook.

The notebook must survive context compaction and agent replacement.

Maintain:

A. CURRENT STATE at top

    campaign plan version/hash
    current master/release SHA
    frozen Parts 1-8 status
    unresolved findings
    issue queue
    Supervisor handoffs
    testpod state
    standalone-package state
    release readiness.

B. APPEND-ONLY DECISION / EVIDENCE HISTORY

For every meaningful discovery or change record:

    date/time
    source/audit
    finding
    evidence
    affected frozen policy
    root cause
    decision
    rationale
    alternatives rejected
    issue/owner
    implementation status
    adversarial review
    test evidence
    final disposition.

Never erase history.

Use:

    SUPERSEDED BY ...
    CORRECTED BY ...

rather than rewriting past decisions as if they never existed.

The notebook must summarize; raw logs belong in their own evidence files.

======================================================================
2. FINALIZE PARTS 1-8 FIRST
======================================================================

Complete the canonical Parts 1-8 plan.

Resolve already-authorized corrections, including the latest outer-iteration
policy.

The campaign maximum outer horizon is:

    num_iterations = 20 per band

subject to the frozen success-based band-local early-stop policy once its exact
FCNet-reference scope is mechanically confirmed in the targeted audit.

Do not preserve stale num_iterations=10 merely because v19/v20 used it.

Before declaring the plan ready for post-plan scanning, run a consistency pass
over all frozen decisions.

Search for:

    duplicate authorities;
    stale PENDING_OPERATOR_DECISION entries already resolved;
    contradictory Part 4/6/7/8 semantics;
    trial/formal scope mismatch;
    inconsistent budget values;
    wrong iteration count;
    wrong watchdog ceiling;
    stale any_pass TIDMAD HealthGate policy;
    stale skip/bypass defaults;
    stale treatment definitions;
    old four-way formal topology language;
    old champion aggregation language;
    scalar averaging language;
    old dynamic/static observable misunderstanding;
    old infrastructure-failure accounting;
    old restart/resume semantics.

Correct the plan autonomously when the operator has already ruled.

Do not reopen frozen policy merely because old code differs.

======================================================================
3. AFTER PLAN STABILIZATION — LAUNCH A SUBAGENT SCANNING PROGRAM
======================================================================

Once Parts 1-8 are internally consistent enough to audit as one system, launch
multiple focused independent subagents.

Do not use one omnibus reviewer.

Use overlapping but distinct failure-class ownership.

At minimum cover:

----------------------------------------------------------------------
SCAN A — PLAN CONSISTENCY / AUTHORITY
----------------------------------------------------------------------

Check every behaviorally relevant campaign field:

    where declared
    where resolved
    where consumed
    where persisted
    where resumed
    where reported.

Look for:

    declared-but-unconsumed;
    consumed-but-unprovenanced;
    defaults overriding frozen intent;
    duplicated authorities;
    stale aliases;
    config fields with no runtime effect.

----------------------------------------------------------------------
SCAN B — V19/V20 HISTORICAL FAILURE ARCHAEOLOGY
----------------------------------------------------------------------

Use v19/v20 history to identify:

    old bugs;
    workarounds;
    previously observed scientific failures;
    runtime/watchdog incidents;
    incumbent/resume problems;
    false-success behavior;
    resource-accounting gaps;
    HealthGate weaknesses;
    scheduler issues;
    intervention/restart problems.

Then ask whether any historical failure class remains reachable under the new
campaign.

Do not restore old behavior merely because it existed historically.

----------------------------------------------------------------------
SCAN C — TRIAL / FORMAL / ITERATION STATE MACHINE
----------------------------------------------------------------------

Audit:

    trial winner
    formal incumbent
    mixed-scope fields
    skip formal
    bypass formal
    normal 120-min formal ceiling
    bypass 200-min ceiling
    -inf cold start
    max outer iterations = 20
    band-local success early stop
    FCNet +2 target
    invalid-score exclusion
    cumulative formal best
    resume.

Build adversarial state traces.

----------------------------------------------------------------------
SCAN D — METRIC / HEALTH / VALIDITY
----------------------------------------------------------------------

Audit:

    stabilized Golden Metric authority;
    HealthGate independence;
    all required TIDMAD blocking gates;
    all_pass per-file semantics;
    calibrated thresholds unchanged;
    static secondary metrics;
    dynamic observations;
    ranking separation;
    composed/strict score pooling;
    final 100% measurement.

Ensure no average of four pre-aggregated band scores exists.

----------------------------------------------------------------------
SCAN E — OBSERVABLES / INTERPRETATION
----------------------------------------------------------------------

Verify the two independent axes:

    acquisition:
        dynamic / static

    role:
        ranking
        diagnostic
        interpretation
        search_feedback
        reporting.

Verify real producers, persistence, and LLM consumers.

Specifically ensure real validation-loss trajectory reaches intended downstream
consumers if required by the frozen plan.

----------------------------------------------------------------------
SCAN F — FAILURE / RETRY / RESUME / TRANSACTIONAL SUCCESS
----------------------------------------------------------------------

Audit all Part-8 semantics:

    scientific vs infrastructure failure;
    clean same-attempt retry;
    no scientific budget consumption on infra failure;
    no mid-training resume;
    resource-exhaustion classification;
    exact resume invariants;
    partial vs success;
    final-evaluation retry;
    band-local terminal failure;
    campaign-wide invalidation;
    operator intervention provenance.

----------------------------------------------------------------------
SCAN G — GOLD / BLIND TREATMENT ISOLATION
----------------------------------------------------------------------

Audit:

    exact treatment artifacts;
    hashes;
    rendered proposer contexts;
    TIDMAD prior isolation;
    literature-review path;
    baseline isolation;
    workspace contamination;
    seed paths;
    research memory;
    historical run records;
    package paths;
    environment variables.

Gold positive audit.

Blind negative leak audit.

----------------------------------------------------------------------
SCAN H — GENERICITY / ANTI-GAMING
----------------------------------------------------------------------

Search for:

    TIDMAD literals in generic code;
    metric-name branching;
    FCNet special cases;
    hard-coded file scopes;
    duplicate profile/config systems;
    self-referential tests;
    vacuous scanners;
    missing-file-set census;
    alias/shadow bypasses;
    fixture-only producers;
    TIDMAD fallback gate roster in composed tasks;
    hidden defaults;
    god-file growth.

----------------------------------------------------------------------
SCAN I — STANDALONE REPRODUCIBILITY
----------------------------------------------------------------------

Assume the campaign folder will be copied to a clean H100 machine.

Ask:

    What hidden local state would make it fail or change behavior?

Audit:

    environment
    relative paths
    untracked files
    repo-root assumptions
    data paths
    generated configs
    treatment files
    profile files
    release SHA
    CLI defaults
    runtime profiles
    output paths
    final-evaluation namespace.

======================================================================
4. AUTONOMOUS FINDING RESOLUTION
======================================================================

For each finding, first decide:

    Is this a campaign-design ambiguity?
    Is this a production implementation gap?
    Is this stale documentation?
    Is this historical debt not blocking arXiv?
    Is this a release blocker?
    Is this an ICLR-only issue?

If the frozen operator policy already determines the answer:

    update the plan/docs autonomously.

If the issue is implementation:

    do NOT silently redesign around missing code.

Create/deduplicate a concrete issue and report it to Supervisor.

Each issue handoff must contain:

    concise title
    severity
    arXiv/v0.1.0 blocking status
    campaign blocking status
    exact frozen policy violated
    exact source evidence
    producer→consumer gap
    smallest generic repair boundary
    prohibited shortcuts
    required adversarial/negative witness
    affected campaign artifacts
    invalidation consequences.

Avoid duplicate issues if Supervisor already has a ledger item/PR.

======================================================================
5. SUPERVISOR HANDOFF PROTOCOL
======================================================================

Supervisor is aware that you exist in:

    tmux official-arxiv-run-31.

When you discover implementation work:

    write it into the shared notebook/issue ledger;
    send Supervisor a compact structured handoff.

Do NOT implement core framework fixes independently unless Supervisor explicitly
routes that write set to you.

Supervisor owns:

    implementation lane assignment
    PR coordination
    merge order
    CI/base freshness
    release state.

After Supervisor reports a fix merged:

    independently verify that the frozen campaign requirement is now actually
    satisfied.

Do not close an issue merely because a PR exists.

Require:

    current-source verification
    producer→consumer verification
    appropriate adversarial witness
    correct provenance
    no new genericity regression.

Then mark:

    VERIFIED_CLOSED

and update the campaign plan/notebook.

======================================================================
6. GOLDPOD ADVICE — MAKE IT STRONG BUT NOT NARROW
======================================================================

Treat the Gold advice artifact as a serious scientific deliverable.

It must be:

    detailed
    useful
    evidence-grounded
    broad enough to preserve agent creativity.

Its purpose is NOT to tell the proposer one answer.

It should help the proposer understand:

    what has already been tried;
    what failed and why;
    what succeeded and why;
    which scientific/ML dimensions appear promising;
    what resource envelope is available;
    what kinds of architectures/losses remain unexplored;
    what failure modes to avoid;
    how to use the available budget productively.

Encourage both:

EXPLOITATION

    improve strong existing candidates;
    refine known good ideas;
    improve FCNet-like / baseline-inspired ideas if that is productive;
    combine prior successful ingredients;
    fix known weaknesses.

EXPLORATION

    materially different architectures;
    new losses;
    architecture+loss combinations;
    multiscale/long-context strategies;
    alternative regression architectures;
    more expressive models;
    broader training strategies;
    novel but task-compatible approaches.

Size guidance:

    use the available resource envelope productively;
    larger models within the practical budget are welcome;
    do not artificially remain tiny merely because old trials were constrained;
    prefer as much useful capacity as the resource/watchdog budget can honestly
    support.

But do NOT turn:

    "larger is allowed"

into:

    "always choose the largest model."

And do NOT over-prescribe:

    one architecture
    one loss
    one optimizer
    one schedule
    one training recipe.

A conservative incremental improvement is a legitimate strategy.

A very different approach is also legitimate.

The agent should decide.

Respect the already-frozen treatment exclusion:

    no forbidden pretrained official baseline weights/checkpoints;
    no executable baseline implementation as treatment;
    no exact reconstructable baseline recipe if excluded;
    no hidden TIDMAD information outside the explicit treatment channel.

The advice should be rich prior knowledge, not a solved implementation.

Produce immutable/versioned artifacts with hashes.

All four gold bands receive byte-identical treatment artifacts.

======================================================================
7. BLINDPOD ISOLATION
======================================================================

The blind arm must remain:

    cold execution state
    no TIDMAD treatment seed
    no official baseline prior
    no treatment artifact
    no hidden baseline/research-memory contamination.

General symmetric scientific literature capability may remain available only
within the frozen Part-2 rules.

Perform adversarial negative searches against:

    unique advice phrases
    artifact hashes
    baseline values
    paths
    prior run identifiers
    research memory
    prompts
    rendered contexts
    workspace files
    seed paths.

Do not declare blind isolation merely from config omission.

Prove the effective rendered/consumed context.

======================================================================
8. BUILD THE STANDALONE OFFICIAL CAMPAIGN FOLDER
======================================================================

After all required implementation issues are VERIFIED_CLOSED, build the official
campaign into a standalone self-contained folder.

Reuse existing campaign/config/package conventions if available.

Do not create another configuration framework.

The folder must be sufficient for a clean operator/testpod run without relying
on tribal knowledge.

Include or mechanically reference, as appropriate:

    README / runbook
    exact release authority
    campaign manifest
    machine-readable frozen decisions
    gold treatment artifacts
    blind explicit-disable authority
    LLM config
    data/sample authority
    band definitions
    seed hierarchy
    treatment hashes
    metric config
    HealthGate config
    observable declarations
    budgets
    watchdog/runtime authorities
    trial/formal portions
    20-iteration maximum
    FCNet+2 success-stop authority
    skip/bypass parameters
    normal/bypass ceilings
    failure/retry/resume semantics
    scheduler topology
    output structure
    final evaluation structure
    composed/strict finalization
    provenance/checksum manifest
    validation scripts
    testpod rehearsal command(s).

Every behaviorally relevant value must be explicit.

No silent mutable defaults.

No local shell variables that determine scientific semantics without appearing
in the manifest.

No untracked generated file may be required.

======================================================================
9. CAMPAIGN PACKAGE SELF-AUDIT
======================================================================

Before reporting the package ready, launch fresh subagents against it.

Give at least one reviewer:

    the standalone folder
    frozen campaign contract

but NOT the historical finding list.

Ask it to adversarially find:

    hidden default
    stale path
    treatment leak
    runtime ambiguity
    missing dependency
    impossible restart
    non-reproducible file
    incorrect authority
    cross-arm asymmetry
    invalid aggregation
    premature feedback
    campaign-science logic embedded in framework code.

Use anti-vacuity tests.

Example:

    if a scanner claims blind does not contain advice,
    plant a unique advice sentinel and prove it turns RED.

======================================================================
10. HANDOFF PACKAGE TO SUPERVISOR FOR TESTPOD
======================================================================

When ready, report:

    STANDALONE_CAMPAIGN_PACKAGE_READY_FOR_TESTPOD

to Supervisor.

Provide:

    path
    campaign-plan hash
    manifest hash
    release requirement
    gold advice hashes
    blind-isolation evidence
    expected testpod data path
    expected environment
    exact bounded rehearsal command
    expected output/evidence
    known non-blocking limitations.

Supervisor owns transfer to testpod.

Do not independently create a second divergent testpod copy.

After transfer, verify transferred hashes with Supervisor.

======================================================================
11. TESTPOD REHEARSAL COLLABORATION
======================================================================

Collaborate with Supervisor on bounded testpod rehearsal.

The goal is analogous to a real SIDERIUS Gate-2 lifecycle witness:

    real framework path
    real LLM where needed
    real training
    real inference
    real scoring
    real HealthGate
    real observables
    real persistence/resume

with minimum semantic compute.

Do not judge rehearsal on model quality.

Analyze failures deeply.

When a failure is:

    campaign packaging bug
        -> fix autonomously in your owned package

    generic framework defect
        -> issue to Supervisor

    H100 calibration/runtime issue
        -> Supervisor/testpod coordinator owns measurement;
           you update campaign hardware-derived authority once qualified

    scientific policy ambiguity
        -> only then return to operator if truly not determined by the frozen
           plan.

Iterate until the full campaign lifecycle works.

======================================================================
12. H100 HARDWARE-DERIVED VALUES
======================================================================

Do not assume 5090 values transfer.

Work with Supervisor evidence to finalize hardware-derived authorities such as:

    dual_coresident admission
    36-GB/band feasibility
    runtime factors
    validation cost
    inference cost
    watchdog phase coverage
    normal/bypass execution deadlines
    concurrency effects.

Do not invent H100 factors in planning docs before evidence exists.

Use:

    HARDWARE_DERIVED
    PENDING_HARDWARE_EVIDENCE

until qualified.

When evidence arrives, update the canonical manifest exactly once.

======================================================================
13. CONTINUOUS ADVERSARIAL REVIEW
======================================================================

Do not wait until the end.

After every material campaign-package change:

    re-run the relevant cheapest discriminative checks.

After a cluster of changes:

    launch an independent adversarial reviewer.

Pay special attention to:

    gold/blind symmetry
    advice leakage
    trial/formal scope
    HealthGate validity
    mixed score pools
    iteration early stop
    final-evaluation isolation
    composed/strict scoring
    resume
    hidden defaults.

Do not game tests to the current implementation.

Tests should encode frozen semantics.

======================================================================
14. AUTONOMOUS COMPLETION LOOP
======================================================================

Operate continuously:

    finalize plan
        ->
    adversarial scan
        ->
    discover issue
        ->
    classify
        ->
    hand implementation issue to Supervisor
        ->
    continue scanning independent areas
        ->
    Supervisor fixes/merges
        ->
    independently verify closure
        ->
    update notebook
        ->
    build standalone package
        ->
    fresh package audit
        ->
    Supervisor copies to testpod
        ->
    bounded rehearsal
        ->
    diagnose
        ->
    issue/fix/retest
        ->
    H100 calibration
        ->
    final package freeze
        ->
    Supervisor releases v0.1.0
        ->
    verify gold/blind launch-readiness.

Do not stop merely because you are waiting on one Supervisor issue.

Continue independent work.

Do not repeatedly ask the operator for permission.

======================================================================
15. TERMINAL CONDITION
======================================================================

Your work is complete only when all of the following are true:

    Parts 1-8 canonical plan frozen and internally consistent;

    post-plan adversarial scan complete;

    all arXiv/v0.1.0 campaign-required implementation gaps VERIFIED_CLOSED;

    all ICLR-only issues recorded but not allowed to block arXiv;

    gold advice complete, detailed, broad, immutable and hashed;

    blind isolation proven;

    standalone campaign package complete and self-contained;

    package passes fresh adversarial audit;

    testpod bounded end-to-end rehearsal passes;

    H100 hardware-derived authorities qualified;

    final package hash frozen;

    Supervisor reports exact qualified v0.1.0 release;

    goldpod and blindpod run manifests are ready.

Then report:

    OFFICIAL_CAMPAIGN_PLANNING_COMPLETE
    V0_1_0_VERIFIED
    READY_FOR_GOLDPOD
    READY_FOR_BLINDPOD

with the exact:

    release tag/SHA
    campaign package hash
    campaign-plan hash
    gold treatment hashes
    blind isolation evidence
    remaining ICLR-only/non-blocking issues.

Until then:

    continue autonomously.
```

---

## E. DIVISION OF AUTHORITY (reconciled with the Supervisor's own record)

| this lane — campaign planning (`official-arxiv-run-31`) | RTX 5090 Supervisor |
|---|---|
| Parts 1–8 campaign plan | release-train authority |
| machine-readable decision ledger | implementation routing |
| post-plan adversarial audit | framework remediation |
| standalone campaign package | PR ownership and sequencing |
| gold advice design | adversarial implementation review |
| blind isolation design | CI / merge authority |
| this golden notebook | H100 / testpod qualification |
| campaign-level evidence organisation | runtime / watchdog / calibration closure |
| | **v0.1.0 release** |

**This lane must not become a second release Supervisor.** Coordinate through
tracked artifacts, never ephemeral chat.

---

### 2026-08-26 — F-GOV-1: the campaign authority was untracked — **CLOSED**

**Source.** Release Supervisor, mechanically verified (`git ls-files
'docs/campaign/*'` → empty), then re-verified here before acting.

**Finding.** `official_campaign_plan.md` and `official_campaign_decisions.yaml`
were never gitignored — simply never added to the index. Every frozen operator
ruling existed on one machine's disk: invisible to other lanes, lost on a fresh
clone, unreferenceable by SHA, uncitable from any PR. The operator has
repeatedly directed lanes to "the canonical tracked authority", and it was not
tracked.

**Root cause.** The artifacts were authored across a long planning session on a
fix branch (`fix/failure-honesty-exit-status`, Lane C / PR #315) and never
staged, because landing 380 KB of campaign docs onto an unrelated fix PR would
have polluted it. The correct branch was never created.

**Decision.** Created `campaign/official-arxiv-campaign-plan` from fresh
`origin/master` (`d74785bb`), committed all three artifacts as `0914f5b8`, and
pushed. Docs only — no production code, test or config touched.

**Alternatives rejected.** (a) Committing onto `fix/failure-honesty-exit-status`
— would pollute PR #315's review surface with an unrelated 8,947-line docs
diff. (b) Splitting the 193 KB ledger — it is a single machine-readable
authority with cross-references validated as one document; splitting creates
exactly the competing-ledger risk the directive prohibits. (c) Leaving it
untracked pending operator direction — the standing directive already requires
tracked project documentation.

**Owner.** This lane (campaign artifacts are its write set).

**Disposition.** **CLOSED.** Merge routing belongs to the Supervisor.

---

### 2026-08-26 — Trial portions become live: a MEASURED-vs-COMPUTED audit

**Source.** Release Supervisor, ahead of PR #320 landing.

**Finding.** Typed launch portions did not previously govern trial execution —
the values were dead in transit and trial rounds ran whatever the planner chose,
about `0.02`. After #320 they govern, via a `plan_overrides` lock. Trial rounds
will therefore now cost the budgeted `0.1 × 0.1 = 1 %` instead of the ~0.2 %
silently running before — **up to ~5× more on the data-scaled component.**

**Confirms this lane's independent audit** (`A4-1`): zero readers of
`agent_input.trial_portion` / `train_portion` / `eval_portion` in the tuner
node; schema fallback `0.02 / 0.1 / 0.02`.

**Affected frozen policy.** None. `D-BUD-7` and `D-BUD-8` are unchanged, and
#320's typed values match them exactly, including the formal carrier's
`1.0 / 0.1 / 0.1` — the flag mapping recorded in plan §19.8.

**Measured-vs-computed disposition — the question the Supervisor asked.**
**Every budget, ceiling, portion and iteration count in Parts 1–8 is COMPUTED
from operator rulings, not calibrated from observed runs.** The 30 / 120 /
200-minute ceilings, the 10 → 20 iteration horizon, 36 GiB/band and every
portion are operator-supplied. **No Part 1–8 number is invalidated.**

Only four measured figures appear anywhere in the plan, all as context and none
load-bearing for a budget: FCNet inference ≈ 22 s/file (RTX 5090); v20 attempt 3
producing 38 records in ~7 h across 2 chains; token-usage aggregates (used only
for the LLM rate-limit headroom check, which has ~6.6× margin and is unaffected);
and the calibration-store per-step probes, which were **explicitly rejected as
unusable** (`segment_length: 625`, wrong GPU).

**Second-order consequence this lane owns.** `A4-5` — the 1 % / 10 % / 100 %
evaluation runtime witness — is `PENDING_RUNTIME_EVIDENCE` and **must now be
measured POST-fix.** A pre-fix measurement would understate trial evaluation
cost. Recorded so the witness is not taken from stale evidence.

**Disposition.** No plan change required. `A4-5` annotated. The Supervisor owns
the qualification-envelope recalibration.

---

### 2026-08-26 — #320 merged; post-fix baseline is `f310a264`

**Source.** Supervisor, with the implementing lane's §5.9 disposition verbatim.

**Finding.** Typed launch portions now govern trial execution via the
`plan_overrides` lock. Estimation agrees with execution in both regimes. Bare-run
behaviour, record schemas and the formal path are byte-unchanged.

**Disposition.** `A4-5`'s freshness constraint is now **satisfiable**: the
post-fix world starts at **`f310a264`**. Ledger updated with the exact baseline
SHA so no future witness is taken from stale ground.

---

### 2026-08-26 — `F-H100-WD-1`: watchdog disabled on every H100 path (Supervisor-owned)

**Independently verified here before recording.** `configs/runtime_profiles.yaml`
has exactly **5 non-comment lines** and **one** profile:

```yaml
profiles:
  nvidia_geforce_rtx_5090/single:
    watchdog_enabled: true
    watchdog_safety_factor: 3.5
    watchdog_floor_seconds: 120
```

No H100 key at any regime. `resolve_runtime_profile()` falls measured → shipped →
UNCALIBRATED, and that branch returns `watchdog_enabled=False`. **The campaign's
runaway protection does not exist on the target hardware.**

`ExecutionRegime = Literal["single", "dual_coresident", "four_way_coresident"]` —
`dual_coresident` is already first-class; only the row is missing.

**The resolver is correct** — it honestly refuses to borrow a 5090 number. The
defect is missing data. Confirms this lane's earlier independent finding.

**Affected frozen policy.** `D-BUD-13` (watchdog REQUIRED) — already recorded as
a BLOCKING GAP. **Owner: Supervisor.** Blocked on Q5.

---

### 2026-08-26 — Q5 dual-concurrency: 2.39x, and a treatment-correlated risk this lane owns

**Source.** Supervisor, Q5 first dual-concurrency data. Arithmetic re-derived
here.

**Measurement.** Band `0-3` solo **606.6 s** → **1449.17 s** at concurrency 2 =
**2.389x**. Band `4-9` 1726.52 s has no solo counterpart and a different file
count — the Supervisor correctly did **not** divide it. That discipline is
right and is recorded so nobody later treats 1726.52 as a ratio.

**Effective solo-equivalent work permitted by each frozen ceiling at 2.39x:**

| ceiling | wall clock | solo-equivalent |
|---|---|---|
| trial | 30 min | **12.6 min** |
| formal | 120 min | **50.2 min** |
| bypass | 200 min | **83.7 min** |

**The frozen policy is NOT invalidated.** §19.11 states the purpose explicitly —
*"the time budget is a SAFETY CEILING, not a target duration"* — and a runaway
bound is not falsified by work taking longer. The Supervisor's reasoning is
accepted.

**But a campaign-design risk follows, and it is this lane's to name.** Three
multipliers now stack on the **trial** ceiling, which is the binding one:

1. **5x** — post-#320 trial data is the budgeted 1 %, not the ~0.2 % silently
   running before;
2. **2.39x** — coresidency wall-time;
3. **model scale** — the goldpod advice encourages **10M–500M** parameters
   against v20's realized **0.9M–25.9M** (12x–345x below FCNet's 323M).

Under 2.39x a trial attempt has **12.6 solo-equivalent minutes**.

**Why this is scientific and not merely operational.** Exceeding a frozen ceiling
is classified by `D-FAIL-4` as **SCIENTIFIC / RESOURCE_INFEASIBLE** — it
*consumes a scientific attempt*. So a systematically-too-tight trial ceiling
does not merely slow the campaign; it **burns attempts on large candidates and
biases the search toward small ones.**

This is the same bias shape already recorded in the framework at
`core/runtime_control/phases.py:21-28` for un-priced validation: *"validation
cost grows with model size, so large candidates die in validation while small
ones survive and the tuner learns a false regularity."*

**And it is treatment-correlated.** goldpod's advice is precisely what pushes
toward larger models; blindpod has no such push. A ceiling that punishes large
candidates therefore punishes **goldpod more than blindpod** — which would
present as *"advice made things worse"* when it is a budget artifact. That is a
confound in the measured direction of the treatment effect.

**Disposition.** **No plan change.** The ceilings are frozen, the policy is
coherent, and the operator raised trial 20 → 30 for exactly this reason — though
before both the 5x portion fix and this 2.39x measurement existed. Recorded as a
**named campaign risk for operator awareness**, not escalated as a blocker.

**Resolution path, already owned:** `A4-5` (post-`f310a264` evaluation-runtime
witness, this lane) and `F-H100-WD-1` (H100 admission/prediction calibration,
Supervisor). **Both must size their envelopes against the model scale the advice
encourages, not against v20's observed 0.9M–25.9M.** Recorded so neither witness
is taken at a scale the campaign has deliberately moved away from.

**Open question flagged, not answered:** the 2.39x occurs at GPU utilisation
7–20 %, CPU 82–90 % idle, RAM 233/2015 GB, 208 CPUs at loadavg 50. Two processes
contending for no visible resource yet costing 2.4x wall time is **serialisation,
not saturation** — small kernels, launch overhead, or absent MPS. If addressable,
dual-coresident throughput improves substantially and the risk above shrinks with
it. Supervisor-owned; not a blocker.

---

### 2026-08-26 — 2.39x is a FLOOR, not the campaign factor — risk strengthens

**Source.** Supervisor, correcting the interpretation of its own measurement.

**Finding.** exp1's legs ran at **`--train-portion 0.05` on wavenet** — nowhere
near the 10M–500M scale the goldpod advice encourages. **The 2.39x is therefore
a FLOOR.** A larger model at dual coresidency may be worse. The Supervisor will
not quote 2.39x as the campaign's coresidency factor.

**Consequence for the numbers recorded in the previous entry.** The
solo-equivalent figures are **upper bounds on permitted work**, not estimates:

| ceiling | at the 2.39x FLOOR | at a hypothetical 3.5x |
|---|---|---|
| trial 30 min | ≤ 12.6 min solo-equiv | 8.6 min |
| formal 120 min | ≤ 50.2 min solo-equiv | 34.3 min |
| bypass 200 min | ≤ 83.7 min solo-equiv | 57.1 min |

The second column is illustrative only — no factor above 2.39x has been
measured. The point is directional: **the true factor can only move these
downward**, so the trial-ceiling risk recorded above is a lower bound on its own
severity.

**Disposition.** Recorded. No plan change. Reinforces `A4-5`'s
`model_scale_constraint` and the Supervisor's adopted scale requirement for
`F-H100-WD-1`.

---

### 2026-08-26 — Trial-ceiling confound ESCALATED TO OPERATOR by the Supervisor

**Source.** Supervisor, accepting this lane's finding and escalating it.

**Their reasoning, recorded because it sharpens the framing.** The arithmetic is
not the finding — the *classification* is. `D-FAIL-4` makes a ceiling breach
SCIENTIFIC / RESOURCE_INFEASIBLE, so it **consumes an attempt**. A tight trial
ceiling therefore *spends the campaign's scientific budget on the candidates it
cannot afford to run*, and the survivors are systematically the small ones.
**That is selection, not throughput.**

They judged it crosses from "named risk" into the operator's own stop condition
— *accepting an unresolved scientific-validity ambiguity* — because an
experiment whose headline is a treatment contrast cannot carry an unquantified
confound acting on the treatment axis.

**Neither lane proposes a policy change, and nothing is unfrozen.** The operator
raised trial 20 → 30 for exactly this reason and is entitled to know that
decision predates both the portion fix and the coresidency measurement.

**Independently confirmed by the Supervisor:** the identical bias shape is
already documented in their subsystem as a known defect
(`core/runtime_control/phases.py:21-28`). Its reappearance at campaign scale
through a different mechanism is the same physics reaching a different layer.

**Scale constraint ADOPTED unconditionally** for `F-H100-WD-1` and every
qualification envelope. Their formulation is worth preserving: **"Evidence
measured at the wrong scale is not weak evidence, it is evidence for a different
question."**

**Serialisation** accepted as their highest-leverage non-blocking item; py-spy
profiling in progress. If addressable, the confound shrinks by the same factor —
it would reduce a scientific risk, not merely a schedule.

**Status.** Awaiting operator. **This lane does not block on it** (directive
§14) and continues §2 work.

---

### 2026-08-26 — §2 corrections: iteration horizon 10 → 20; FCNet+2 blocked on `A2-FCNET`

**Source.** Standing directive §2, executed by this lane.

**`num_iterations` 10 → 20 per band — CORRECTED, FROZEN.** The v19/v20 value was
preserved by inheritance; the directive supersedes it and says explicitly that
`10` must not be kept merely because v19/v20 used it. `20` is a **maximum
horizon**, not a target. Plan §19.2, ledger `D-BUD-2` (`supersedes_value: 10`).

**FCNet+2 band-local early stop — the reference-scope confirmation RETURNS A
BLOCKER, not a value.**

The FCNet paper reproduction is **four band-split checkpoints** —
`FCNet_0_4.pth`, `FCNet_4_10.pth`, `FCNet_10_15.pth`, `FCNet_15_20.pth` — whose
deliverables are **pooled and scored in ONE `score_vector` call over all 20
files**. **The recorded FCNet reference is therefore a FULL-SCOPE (0..19)
scalar, and no per-band FCNet score exists anywhere in the repository.** The
preserved artefacts carry diversity metrics and `fcnet_reference_params =
323,000,000`, but no per-band `denoising_score`.

**Why it blocks.** A campaign band's formal score is band-scope; FCNet's
reference is full-scope. Aggregate scalars are comparable only within one scope,
and `scoring_utils` §3 forbids deriving one from the other by averaging. **"Band
beats FCNet + 2" is not computable today.**

**Resolution needs no new authority.** The FCNet deliverables are preserved.
Four per-band references can be produced by calling `score_vector` on a **scoped
SampleSet** per band — explicitly the construction `scoring_utils` §3 sanctions.
Recorded as `A2-FCNET`, owned by this lane, no framework change required.

**Open for the operator, deliberately not assumed:** whether "+2" is measured
against a **per-band** FCNet reference (band-local stop) or against the
**full-scope** reference applied to the composed-best result (a
*campaign-terminal* stop). Different rules, different stopping behaviour.

**Interim.** A band runs its full 20-iteration horizon.

