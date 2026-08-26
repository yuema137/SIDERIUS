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
| plan / ledger tracking | **TRACKED ON MASTER** as of `979e798b` (#322). `git ls-files 'docs/campaign/*'` returns all three. F-GOV-1 CLOSED. Content hash not yet frozen — corrections ongoing. |
| master / release SHA | **`979e798b`** (**#322 merged — F-GOV-1 CLOSED, the campaign authority is tracked**). Prior: `dce0ba42`, `f310a264` (origin/master, per Supervisor 2026-08-26 — #320 Lane F2 campaign-portion authority merged; #321 `d74785bb` before it). **`f310a264` is the POST-FIX baseline: every runtime witness must be taken at or after it.** Tag `v0.1.0-rc.1` on `6b123947`. |
| Parts 1–8 | **all OPERATOR-FROZEN** (see §B). §21 hardware disposition frozen. **THE CURRENT CAMPAIGN IS GOLD-ONLY (`D-CAMP-1`) — Blind is not required for Gold launch, completion, finalization or scientific deliverables** |
| ledger status counts | **213** entries · **5** PENDING_OPERATOR_DECISION (`Q-LIT-1`, `Q-ISO-1`, `F-LLM-2`, `F-SCANH-2`, **`Q-FCNET-REF-1`**) · **17 RELEASE BLOCKERs** · the rest FROZEN / PENDING_AUDIT / PENDING_IMPLEMENTATION / PENDING_HARDWARE_EVIDENCE |
| **blocker ledger** | `final_campaign_review_package.md` **§6** — **25** RELEASE BLOCKER (**13 of them are one defect**, `F-LAUNCH-1` ⇒ 25 → **13** once row `L` is ruled) · 5 POST-TAG · 4 GOLD LAUNCH PRECONDITION *(proposed)* · 2 CONDITIONAL_ON_BLIND · 1 ACCEPTED · 0 ICLR-FUTURE. **This is the ONLY blocker ledger; never create a second.** |
| post-plan adversarial scan | **C, D, G, H, I COMPLETE** (2026-08-26); F done in-lane. **A, B, E remain** |
| standalone package | **NOT STARTED** |
| testpod state | not rehearsed; H100 qualification is issue #314, BLOCKED on `v0.1.0-rc.N` |
| release readiness | Supervisor-owned; not ready |

### A.1 Immediate next actions (directive §2, before any scanning)

1. ~~`num_iterations` 10 → 20~~ — **DONE.** `D-BUD-2` corrected; plan §19.2.
2. ~~FCNet+2 reference-scope confirmation~~ — **DONE, returns a blocker.**
   `A2-FCNET`; plan §19.2a. The rule stays PENDING until four per-band FCNet
   reference scores exist.
3. ~~Parts 1–8 consistency pass~~ — **DONE 2026-08-26.** Five stale items found
   and fixed; see §C. Open `PENDING_OPERATOR_DECISION` dropped 5 → 3.
4. ~~§4 consolidated parameter table~~ — **DONE**, 95 rows + rows `L` and `W`.
5. ~~§6 GAP disposition triage~~ — **DONE 2026-08-26** per `D-GOV-9`.
6. **Send the Supervisor the RELEASE BLOCKER subset only** — **NEXT**.
7. **Scans A–I** — after that.
8. `A2-FCNET` — four per-band FCNet reference scores (blocks §6.3 row 10).

### A.2 Open `PENDING_OPERATOR_DECISION` (5, all inherited — none from Part 8)

| id | item |
|---|---|
| `Q-LIT-1` | literature-review enabled state for the formal campaign |
| `Q-ISO-1` | `--baseline_isolation` disposition (I1/I2/I3/I4) |
| `F-LLM-2` | timeout/connection retry divergence from the frozen policy |
| **`F-LAUNCH-1`** | **which launcher is the official campaign entrypoint?** Raised 2026-08-26. The band fleet calls `launch_prior_baseline_experiment.sh`, which types **none** of the twelve campaign parameters. Review-package row `L`. **Twelve RELEASE BLOCKERs collapse to one work item if this resolves to the band-fleet path.** |
| ~~`D-TOPOLOGY-1`~~ | **RESOLVED** by `D-HW-5` |
| ~~`A6-2`~~ | **RESOLVED** by `D-BUD-9` — per band |

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
| `F-H100-WD-1` | **watchdog DISABLED on every H100 path** — Supervisor-owned |
| **Gold host** | **VERIFIED** `7b18f5b84834` — 4 × H100 80GB HBM3, 224 cores, 2015 G RAM, `/workspace` 2.0 T xfs. `A-HW-VERIFY-1` DISCHARGED |
| **Gold host is SHARED** | baseline loadavg **60.17/59.00/56.23 on 224 cores ≈ 27 %** consumed by other tenants with nothing of ours running → `F-CONFOUND-2` |
| transfer | RUNNING — direct testpod → Gold, 84 G / 40 h5, rsync `--include="*.h5" --exclude="*"`, ETA ~3 h |
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

---

### 2026-08-26 — FORMAL HARDWARE DISPOSITION frozen (operator, relayed §11)

**Provenance.** Operator ruling, **relayed by the RTX 5090 Supervisor** under
directive §11 required relay. Recorded as operator authority; the relay path is
stated so the provenance is honest rather than implied.

**Frozen.** `4 × H100_SXM` · `EXCLUSIVE_SINGLE_BAND` residency · GPU 0/1/2/3 →
bands `0-3` / `4-9` / `10-14` / `15-19` · **Gold first**, Gold finalization does
not wait for Blind · Blind only if resources permit · **`SCIENTIFIC_VRAM_CEILING
= 60GB`** (up from 36) · `30 / 120 / 200` nominally frozen but requiring fresh
single-resident qualification.

**Supersedes:** the 8-GPU simultaneous option · the `dual_coresident` formal
topology · `D-CONC-1` max-2-with-backfill · `D-CONC-2` / `D-BUD-12` 36 GiB ·
`D-HW-3` two-way rehearsal · §9A's four-way→max-two consequence map. All
retained as history with `superseded_by` markers, never deleted.

**Recorded as CAUSAL, per instruction:** 36 → 60 GB is a resource-policy
revision *caused by* exclusive-GPU execution, not a cosmetic bump. Flagged a
unit hazard the implementer must settle explicitly: the shipped VRAM flags are
**GiB** (`_GB = 1024**3`), and the ruling says GB — do not assume.

**Evidence relevance, updated.** Q5's four-way factor was already
non-applicable; **the 2.389× dual measurement is now also non-applicable to the
formal campaign.** Neither prior topology is the formal one. `F-H100-WD-1` is
unchanged in substance and narrowed in target: the row now needed is **H100
single-resident**, and `ExecutionRegime` already types `single` first-class, so
no vocabulary extension is required.

---

### 2026-08-26 — `F-CONFOUND-1` RE-DERIVED — direction unchanged, magnitude unknown, and a NEW mechanism

**Re-derived on Supervisor request rather than deleted.**

| multiplier | before | now |
|---|---|---|
| coresidency | 2.389× wall-time penalty | **GONE** — exclusive residency removes it |
| trial data | 5× post-#320 | **unchanged** |
| model scale | 10M–500M under a 36 GiB ceiling | **LARGER** — 60 GB permits materially bigger candidates |

**One removed, one unchanged, one increased.** The confound's direction is
unchanged and it remains treatment-correlated; **only its magnitude is now
unknown** and must come from fresh measurement.

**NEW mechanism identified in the re-derivation — the admission/completion
envelope gap.** Raising VRAM 36 → 60 GB **without** raising the time ceilings
widens the gap between what is **admissible** and what is **completable**.
Admission checks VRAM; the time gate checks predicted time. **A candidate can
pass VRAM admission at 60 GB and then breach the 30-minute trial ceiling — which
`D-FAIL-4` classifies as SCIENTIFIC / RESOURCE_INFEASIBLE and which therefore
CONSUMES a scientific attempt.**

The agent is now permitted to build candidates the clock cannot finish, and each
one costs a scientific attempt rather than being refused cheaply at admission.
That is **the same selection pressure arriving through a second door** — and
goldpod's advice is what pushes toward the larger candidates the 60 GB ceiling
now permits, so this door also opens preferentially for goldpod.

**Resolution path unchanged:** `A4-5` (post-`f310a264`, sized at the
advice-encouraged scale) and `D-HW-7` (single-resident ceiling qualification).

---

### 2026-08-26 — ⚠️ The provider-drift mitigation is GONE (this lane's finding)

§9.15 recorded provider-side model drift as a limitation the campaign cannot
engineer away, and named exactly one mitigation: *"launch goldpod and blindpod
within a narrow time window."*

**Gold-first / Blind-later removes that mitigation entirely.** An arbitrary and
possibly large interval now separates the arms.

Therefore:

1. **`D-LLM-13` — pinning `gpt-5.5` → `gpt-5.5-2026-04-23` — is no longer
   hygiene. It is the ONLY remaining defence against a provider-side model
   change between the two arms.** Priority raised.
2. **`D-PROV-1`** — DeepSeek exposes **no immutable revision at all**. If
   literature review is in the campaign (`Q-LIT-1`, open), that authority is
   unpinnable and the temporal gap makes its drift risk materially worse.
   **Strengthens the case for resolving `Q-LIT-1` toward OFF.**
3. Every §21.6 provenance record must capture the **resolved model snapshot**
   per arm, not merely the configured alias, or the temporal separation cannot
   be audited after the fact.

**Disposition.** Recorded, not escalated as a blocker — the operator accepted
the temporal asymmetry knowingly as a cost decision, and §21.6's provenance
requirement is the correct response to it. This entry names what that
requirement must therefore capture.

---

### 2026-08-26 — ⚠️ CORRECTION to the `F-CONFOUND-1` re-derivation: multiplier 1 is NOT gone

**Source.** Supervisor observation on host-layer sharing, which forced this
lane to re-examine its own re-derivation from four hours earlier.

**What this lane got wrong.** The re-derivation recorded the coresidency
multiplier as **"GONE — exclusive single-band residency removes it."** That was
premature.

**Why.** Exclusive residency removes **GPU** contention. But the measured 2.389×
occurred at **7–20 % GPU utilisation with 82–90 % CPU idle** — so **GPU
contention was almost certainly never its cause.** The mechanism was never
established, and the host layer (shared CPU, RAM, filesystem) is where it most
plausibly lives.

On the Gold pod the four bands have **exclusive GPUs but share one host**. So
the process count on the layer that was never ruled out rises **2 → 4**.

> **The first re-derivation removed a multiplier on the strength of a mechanism
> nobody had established.** That is precisely the reasoning error this campaign's
> own evidence rules exist to catch — a green result accepted for the wrong
> reason.

**Corrected net.** Zero multipliers safely removed · one unchanged (trial data
5×) · one **increased** (model scale, 36 → 60 GB) · one **UNKNOWN and possibly
larger at four processes than at two**. Direction unchanged, still
treatment-correlated, and **the earlier claim that its magnitude had shrunk was
premature.**

**Resolution.** `A-HOST-1` — the four-band host-side witness. Not a formality:
it is where the unexplained 2.389× actually lands.

---

### 2026-08-26 — Canonical data authority CORRECTED, and the transfer boundary

**Source.** Supervisor, both locations measured.

| | location | size | files | status |
|---|---|---|---|---|
| **canonical** | testpod `/workspace/DATA/TIDMAD_DATA` | 84 G | **40** h5 (20 training + 20 validation) | Q3 manifest `39270b45…33ad85`, verified complete |
| **NOT canonical** | 5090 `/home/klz/Data/TIDMAD` | 862 G | **423** | a **different, larger set** |

**The operator ruling's conditional 5090 → Gold transfer allowance requires a
byte-identical canonical source. The 5090 does not have one, so that path is
closed.** §3's "generate a manifest before transfer" is **already satisfied** by
the Q3 manifest — do not generate a second.

**Transfer scope is FILE-EXACT, never the directory.** It holds **42 entries;
only 40 are data.** `download_data.py` must come from the **release SHA**, and
`segment_anchors.json` is a **task asset the repo owns** at
`reference_data/segment_anchors.json` — from the frozen authority, **never an
rsync of a mutable working tree**. Copying the directory wholesale would violate
the ruling's own provisioning rule.

**Runbook requirement**, recorded because the runbook is what someone follows at
3am: state the file-exact boundary explicitly.

**Note for local work:** `/home/klz/Data/TIDMAD/` remains the local development
data. It is simply **not** the campaign input, and the two must never be
conflated in a provisioning step.

---

### 2026-08-26 — `4 × H100` is a DISPOSITION, not a measurement

Gold pod access is **BLOCKED** — endpoint alive, key offered and **rejected**.
An **authorization gap, not a network problem.** Escalated by the Supervisor.

**§1 topology verification cannot proceed. "4 × H100 verified" must not be
recorded anywhere.** `FORMAL_GPU_COUNT = 4` is the operator's frozen disposition
— what the campaign *shall* use — and is currently a **claim**. Tracked as
`A-HW-VERIFY-1`; plan §21.2 carries the warning inline so it cannot be read as
verified.

Applying the standing evidence principle: *existence is not function* — a row is
satisfied by a check that could have failed, never by the presence of a thing.

---

### 2026-08-26 — Transfer unit is NOT `/workspace/DATA` — §8 would have been violated while §2 was followed

**Source.** Supervisor, mechanically determined.

The ruling's §2 asked whether the canonical immutable authority is exactly the
**complete** `/workspace/DATA` tree. **It is not.**

```text
SIDERIUS_DATA          196G   RUN ARTIFACTS    -> EXCLUDE
TIDMAD_DATA             84G   immutable input  -> TRANSFER
TIDMAD_OFFICIAL_MODELS  5.7G  immutable input  -> TRANSFER (testpod; see below)
                       ~90G transferred, not 285G
```

`SIDERIUS_DATA` is v18/v18r campaign run directories — `wavenet` 94 G,
`legacy_v18r_undersized` 53 G, dated `.log` files. It holds **all 96 `.pyc` and
all 21 `.log` files in the tree**, and **58 of the 98 `.h5` are denoised
OUTPUTS, not inputs.** §8 forbids transferring old campaign workspaces, model
outputs, checkpoints and logs.

> **The point is not the saving. Transferring the complete tree would have
> VIOLATED §8 while APPEARING TO FOLLOW §2.** *"copy /workspace/DATA"* is the
> obvious wrong thing to write in a runbook, and a runbook is what someone
> follows under time pressure.

Recorded on `D-DATA-1` as a second runbook requirement, alongside the file-exact
boundary. **§5 source stability VERIFIED**: zero files modified in 120 minutes,
no open write handles.

---

### 2026-08-26 — `A2-FCNET` execution plan: the Gold pod needs the NUMBER, not the checkpoints

**Answering the Supervisor's direct question.**

**Only the number.** `A2-FCNET` is a **pre-campaign computation**. The Gold pod
never needs the FCNet checkpoints or deliverables — it needs **four scalars plus
their provenance**.

**Recommended route: run it on TESTPOD, before transfer.** There is a cheaper
route and I am deliberately not taking it:

* The FCNet **deliverables already exist** on the 5090
  (`…/tidmad_reproduction/fcnet/full_20_files/`, 20 files, ~75 G, *"canonical
  location, do not delete"*). Scoring them directly needs **no inference at
  all.**
* **But `D-DATA-1` establishes testpod's 84 G / 40-file set as the canonical
  data authority**, and the 5090 holds a different, larger set. **This number
  becomes a campaign stopping threshold (`D-BUD-17`)**, so it must be computed
  against the canonical authority rather than against a set whose equivalence is
  unverified.
* Cost of doing it properly: FCNet inference over 20 files is **~22 s/file,
  about 7.3 minutes total**. The provenance gain is worth far more than the
  compute saved.

**One thing to confirm by name before relying on this.** The Supervisor listed
`TIDMAD_OFFICIAL_MODELS` as *"17 .pth (WaveNet_0_20, Transformer_0_4/4_10/10_15/
15_20, RNN_*)"* — **FCNet was not spelled out.** The count reconciles exactly —
PUNet ×4 + RNN ×4 + Transformer ×4 + WaveNet ×1 = 13, plus FCNet ×4 = **17** —
and 5.7 G matches the archive recorded in
`docs/design/paper_and_collapse_reference_baselines.md` §2.1.

> **A count that reconciles is not the same as a file that exists.** Confirm
> `FCNet_0_4.pth`, `FCNet_4_10.pth`, `FCNet_10_15.pth`, `FCNet_15_20.pth` by
> name — the whole `D-BUD-17` rule depends on it.

`TIDMAD_OFFICIAL_MODELS` is **required on testpod, not on the Gold pod.** Cheap
enough to carry, but it must not be described as a Gold-pod campaign input.

---

### 2026-08-26 — Gold pod: the failure changed shape

`103.207.149.153:11267` **refuses the connection.** Host is UP (ICMP 2/2,
243.9 ms) but nothing is listening. **A closed port — not an auth failure and
not a filter.** The pod is most likely not started, or the port mapping differs.
Escalated by the Supervisor.

`A-HW-VERIFY-1` unchanged: **`4 × H100` remains a disposition. Nothing has been
measured.**

---

### 2026-08-26 — FCNet checkpoints CONFIRMED BY NAME; `A2-FCNET` route settled

All four present on testpod at `/workspace/DATA/TIDMAD_OFFICIAL_MODELS/TIDMAD_Model/`
— `FCNet_0_4.pth` · `FCNet_4_10.pth` · `FCNet_10_15.pth` · `FCNet_15_20.pth`,
each ~1.29 GB. Full inventory 17 = FCNet ×4 + PUNet ×4 + RNN ×4 + Transformer ×4
+ WaveNet_0_20.

**`A2-FCNET` has its testpod route. No 5090 fallback, no provenance caveat.**

**Worth preserving as a method note, in the Supervisor's framing:** *the count
reconciling told us the set was self-consistent; only the by-name check told us
the four specific files `D-BUD-17` depends on exist. Those are different
properties and the first does not imply the second.* Same shape as a census whose
population is empty for a mechanical reason.

**Transfer scope refined:** Gold pod gets **`TIDMAD_DATA` only, 84 G** —
`TIDMAD_OFFICIAL_MODELS` **stays on testpod** for `A2-FCNET`; `SIDERIUS_DATA`
excluded. Describing the checkpoints as a Gold-pod input would imply **the Gold
pod recomputes a reference it should only ever be handed** — a semantic error no
byte count would catch.

**Gold pod diagnosis complete and it is NOT auth:** host UP (ICMP 2/2, 243.9 ms)
· port 22 OPEN but that is RunPod's *physical node*, not our pod · port 11267
**REFUSED**, nothing listening. **The pod is not up.** `A-HW-VERIFY-1`
unchanged.

---

### 2026-08-26 — Parts 1–8 CONSISTENCY PASS complete (directive §2)

Mechanical scan over the fourteen stale-pattern classes. **Five stale items
found and corrected; classes 1, 3, 4, 12, 14, 15 and 16 were clean.**

| # | finding | fix |
|---|---|---|
| 1 | §9.16 status summary still read `max active bands = 2, dynamic backfill` | struck through, superseded by §21 |
| 2 | §9.16 still tracked `F-BAND-1` band scheduler as `PENDING_IMPLEMENTATION` | **MOOT** — exclusive one-band-per-GPU needs no backfill queue |
| 3 | §9.16 still read per-band VRAM `36 GiB PROVISIONALLY_FROZEN` | **60 GB**, superseded by §21.4 |
| 4 | **§15 formal launch preconditions still required launching the arms "within a narrow time window"** | **SUPERSEDED by §21.3** — Gold-first removes that mitigation; the block now points at §21.7 and `D-LLM-13` as the only remaining defence |
| 5 | `D-TOPOLOGY-1` and `A6-2` were still `PENDING_OPERATOR_DECISION` although already answered | **RESOLVED** by `D-HW-5` and `D-BUD-9` respectively, with `resolved_by` and the prior status retained |

**Finding 4 was the one worth having.** §15 is the *formal launch preconditions*
section — not marked superseded, and it carried an instruction that the hardware
ruling had silently invalidated hours earlier. A launch protocol contradicting a
frozen topology is exactly the failure the consistency pass exists to catch.

**Finding 2 is a small piece of good news:** the max-2 backfill scheduler that
did not exist is no longer needed. Exclusive one-band-per-GPU is closer to the
*existing* per-chain model than max-2-with-backfill ever was.

**Open `PENDING_OPERATOR_DECISION`: 5 → 3.** Remaining, all genuinely open:
`Q-LIT-1` (lit-review enabled state) · `Q-ISO-1` (`--baseline_isolation`
disposition) · `F-LLM-2` (timeout/connection retry divergence).

**Duplicate-authority check:** zero duplicate `decision_id`s across 171 entries.

---

### 2026-08-26 — `A-HW-VERIFY-1` DISCHARGED: the Gold topology is MEASURED

Host `7b18f5b84834` · **4 × NVIDIA H100 80GB HBM3**, 81559 MiB / 700 W each,
four distinct UUIDs · `nproc = 224` · 2015 G RAM (1909 G available) ·
`/workspace` = `/dev/md127` xfs **2.0 T** · `/` overlay 30 G (**data must not
live there**) · `rsync` present.

`FORMAL_GPU_COUNT = 4` has moved from **disposition** to **verified execution
fact**. Plan §21.2's warning replaced with the measurement. **Operational
topology only — no frozen scientific parameter changes follow.**

The endpoint diagnosis went auth-gap → closed-port → *pod not up* → up on a
third port (`16043`). Worth remembering that each intermediate reading was
honestly derived and each was wrong about the cause.

---

### 2026-08-26 — ⚠️ THE GOLD HOST IS SHARED, and it creates `F-CONFOUND-2`

**Measured on the freshly-started pod with nothing of ours running: loadavg
`60.17 / 59.00 / 56.23` on 224 cores — ~27 % of the host CPU already consumed by
other tenants.** testpod's exp1 baseline was ~50 on 208 ≈ 24 % — the same order.

**The Supervisor's methodological point, adopted:** a single-band-vs-four-band
comparison on a shared host measures our contention **plus a neighbour's**, and
the neighbour's load is not ours to control. **`A-HOST-1` must record concurrent
baseline load alongside every measurement**, or a four-band slowdown cannot be
attributed to our own concurrency — *"exactly the error you just retracted."*

**`F-CONFOUND-2` — a consequence for the campaign that neither lane had stated.**
Three frozen facts interact:

1. the time ceilings are **wall-clock and fixed**;
2. the host is **shared**, with uncontrolled, time-varying neighbour load;
3. Gold and Blind run at **materially different times**.

A candidate needing 25 solo-minutes **fits** a 30-minute trial ceiling on a quiet
host and **breaches it on a busy one** — and `D-FAIL-4` makes a breach
SCIENTIFIC / RESOURCE_INFEASIBLE, **consuming a scientific attempt**. So
**neighbour load becomes a source of attempt-loss that can differ between the
arms for reasons entirely unrelated to their science.**

**It amplifies `F-CONFOUND-1` rather than being independent.** Neighbour-load
variance hurts most the arm whose candidates sit closest to the ceiling — and
the treatment is precisely what pushes candidates there, via both the 10M–500M
advice and the 60 GB budget. **The arm the treatment makes larger is the arm
most sensitive to a variable neither arm controls.**

**Required response is PROVENANCE, not a policy change.** Record concurrent host
baseline load per attempt. Nothing here reopens a frozen decision.

**Open hypothesis, explicitly not a claim:** the two hosts' baselines are the
same order, so **neighbour load is a live candidate for part of the unexplained
2.389×**. That hypothesis could not exist before a second host's baseline did.

---

### 2026-08-26 — Transfer running; the filter IS the boundary

Direct testpod → Gold, no 5090 relay. Dedicated `testpod-to-goldpod-transfer`
ed25519 key, authorized only on the Gold pod — the narrowest authorization the
ruling contemplates. `rsync -aH --partial --info=progress2`, no compression
(HDF5 already compressed), filter `--include="*.h5" --exclude="*"`, scope
`TIDMAD_DATA` only, 84 G / 40 h5, in tmux `goldxfer`. ETA ~3 h.

> **Runbook note worth keeping:** the file-exact boundary is enforced **by the
> transfer itself**, not by an operator remembering it. `download_data.py` and
> `segment_anchors.json` cannot be copied even by accident. **A mechanically
> enforced boundary beats a remembered rule** — that is the form the runbook
> should prefer everywhere it can.

**Verification is stronger than it looks.** The destination is checked against
**Q3's existing manifest**, which predates both the transfer and any recent
source activity — so a destination PASS proves **two things at once**: the
source was unchanged since Q3 *and* the transfer was faithful. One check, both
properties. On failure, verify the source to disambiguate.

`TIDMAD_OFFICIAL_MODELS` deliberately **not** transferred, per this lane's
reasoning that the Gold pod receives the number and never recomputes the
reference.

---

### 2026-08-26 — **THE CAMPAIGN IS GOLD-ONLY** — complete census, not a patch

**Operator correction, relayed by Supervisor.** `D-CAMP-1`.

```text
GOLD FIRST / GOLD REQUIRED · four Gold bands, one exclusive H100 each
after Stage-A: freeze Gold search -> Composed Best -> Strict Best -> terminal eval
BLIND NOT REQUIRED for Gold launch, completion, finalization, or deliverables
Blind may run later only if budget/time permits; Gold never waits for Blind
```

**§2 — census swept for the CLAIM, not the string.** Nine locations where a
Blind-dependent condition gated Gold, plus two of this lane's own escalations
that needed downgrading:

| # | location | correction |
|---|---|---|
| 1 | **§15 formal launch preconditions** | restructured: **§15.1 Gold-only operative list** · §15.2 Blind conditions `CONDITIONAL_ON_BLIND_EXECUTION` · §15.3 the paired-launch policy retained as history |
| 2 | §5.7 blindpod leakage audit, *"Launch is blocked until it passes"* | `CONDITIONAL_ON_BLIND_EXECUTION` — a full gate **on Blind**, not on Gold |
| 3 | §13 freeze process, "no gold/blind difference outside TREATMENT" | conditional |
| 4 | §14 testpod rehearsal, "blind absence" | conditional; not required for a Gold-only rehearsal |
| 5 | §7 decision order row 18, final symmetry audit | conditional |
| 6 | §9.12 concurrency derivation "2 pods × 2 bands" | now 4 Gold bands on one host; peak count unchanged at 4, headroom conclusion stands |
| 7 | ledger `D-TREAT-9` / `D-LLM-2` / `D-TOPOLOGY-1` `required_evidence: arm-symmetry PASS` | conditional |
| 8 | ledger `D-TREAT-6` formal-launch-gate flag | annotated "ON BLIND" |
| 9 | `topics_not_yet_opened` order 18 | conditional |

**Verified**: zero surviving *"Launch is blocked"* by a Blind condition; the two
remaining `gold/blind … PASS` strings sit inside §15.2 (conditional) and §15.3
(history) only.

**§3 — `F-CONFOUND-2` RECLASSIFIED, not discarded.** Now **GOLD RUNTIME /
RESOURCE-SELECTION RISK**. The measurement stands, the mechanism stands; only
the claim about what it biases changes. **Do not claim it biases Gold relative
to Blind while Blind is not run.** The amplification argument survives as a
**within-Gold selection effect** — a busy neighbour preferentially removes
exactly the large candidates the treatment exists to encourage, distorting
*which science Gold gets to do* whether or not a second arm exists.

**New measurement:** `66.88 / 51.09 / 51.60` on 224 cores, all four GPUs at 0 %,
nothing of ours running — against `60.17 / 59.00 / 56.23` minutes earlier.
**~23–30 % consumed by other tenants, and it MOVES.** Time-variance is now
**measured, not assumed**.

**§4 — `D-ARM-1` → `CONDITIONAL_ON_BLIND_EXECUTION`.** The whole
arm-comparability apparatus preserved intact, reactivating if and when Blind
runs. **If Blind is never run, none of it blocks or invalidates completed
Gold.**

**§5 — `A-HOST-1` NOT weakened.** Purpose restated: *qualify the Gold execution
environment and detect resource-selection distortion*, not *prove
simultaneous-arm symmetry*. Required measurements now enumerated, including
concurrent unrelated host load.

---

### 2026-08-26 — ⚠️ This lane over-escalated `D-LLM-13`, and the correction is recorded

**What I wrote.** When Gold-first was frozen, I concluded the snapshot pin had
become *"the ONLY remaining defence against a provider-side model change between
the two arms"* and asked the Supervisor to treat it as **release-blocking**.

**Why it was overstated.** The campaign is **Gold-only**. There is no between-arm
comparison to protect, so **the escalation rested on a comparison the campaign is
not making.**

**What survives.** The pin remains correct for **Gold's own reproducibility and
provenance** — a campaign should be able to say from its own artifacts which
model produced its results, and an alias cannot. Eight strings, one file, no
code. But it is **provenance hygiene, not a defence against a confound**, and
should be prioritised as such. It reactivates in full if Blind runs.

`D-PROV-1` follows the same reclassification.

**This is the second escalation this lane has had to walk back in one day** —
the first was "coresidency multiplier GONE". Both had the same shape: a
conclusion drawn one step past what the evidence supported, on a premise that
had just changed. Recorded together so the pattern is visible rather than each
looking like an isolated slip.

**§6 verified — ZERO frozen scientific parameters changed:** `num_iterations 20`
· `60GB` · `−2.0` · `+0.5` · epochs `2/1` · ceilings `30/120/200` — all
mechanically re-checked and unchanged. Scheduling and interpretation only.


---

### 2026-08-26 — Operator rulings; and the launcher the campaign calls types nothing

**Four rulings recorded** (`D-GOV-9`, `D-LLM-13-RULING`, `F-H100-WD-1-PRETAG`,
`F-LAUNCH-1`; ledger 174 → 178). **Route B ruled** for `F-H100-WD-1`: numeric
H100 calibration is post-tag. **Both halves of `D-LLM-13` are release
blockers**, assigned to Lane E, with the operator's witness — *request identity
A, resolve B, prove provenance records B rather than echoing A.*

**The pre-tag boundary test.** The operator: *if making the official Gold run
consume the hardware-derived artifact requires changing tracked code, that
smallest support repair happens BEFORE `v0.1.0`.* The Supervisor ran it. The
released system fails on **invisible default** (no explicit launch binding),
**no hash identity** (zero hash lines in `watchdog_profile.py`; positive control
`health_config_sha256` in 70 files elsewhere), and **fail-open** (`_load_measured`
returns `{}` → `UNCALIBRATED` → watchdog silently OFF). That third one is
`F-H100-WD-1` reproducing itself *through the artifact meant to fix it*. New
blocker row `W`; the numeric row it supports stays post-tag.

#### ⚠️ `F-LAUNCH-1` — verified this lane, and it inverts the cross-check

```text
launch_band_fleet.sh:59  LAUNCHER=".../launch_prior_baseline_experiment.sh"
                         NOT launch_v20_campaign.sh
```

**That launcher passes NONE of the twelve campaign parameters.** All twelve fall
through to `_chain_common.sh` defaults: portions **untyped ⇒ AGENT_CONTROLLED**
(`:85-87`), formal portions **inverted** (`:101,138,139`), time budgets
**empty ⇒ no budget at all** (`:99-100`), deltas `−1.0` / `0.0` against frozen
`−2.0` / `+0.5`.

**The `plan_overrides` lock from #320 genuinely binds. Nothing feeds it.** The
mechanism is present and unused.

> **The rule this yields: a row can be `VERIFIED` at the consumer and still
> `GAP` at the campaign.** The Supervisor had marked rows 19–22 VERIFIED on the
> strength of the lock binding — correct about the lock, wrong about the
> campaign. This is the stated-versus-effective distinction one level deeper,
> and it is the seventh census-blindness shape: **verifying the mechanism
> instead of its use.**

The operator's own Rule 2 settles the repair target: proof must inspect
**effective resolved values after all override, planner and carrier logic has
run**; source text is explicitly not proof. A repair in `launch_v20_campaign.sh`
is source text in a file the effective path never invokes.

**I did NOT pick an entrypoint.** `F-LAUNCH-1` is `PENDING_OPERATOR_DECISION`
with all twelve resolved values recorded — freezing one by implication is
exactly the "never make a pending value look frozen" failure.

#### §6 triage — 25 blockers, twelve of which are one defect

`D-GOV-9`'s axis applied to all 30 GAPs. **Twelve of the twenty-five blockers
are `F-LAUNCH-1`**; if row `L` resolves to the band-fleet path the count falls
**25 → 14 with no value downgraded**. **Six are missing capabilities** no
launcher repair reaches — rows 27, 60, 61 produce the campaign's headline
numbers and are the longest genuine pole.

**Row 93's repair already exists, unmerged**: `090e601b` (F8), `d9c08404` (F13),
`df3f1c04` (F-Q5-1) on `fix/failure-honesty-exit-status`, mechanically verified
**not ancestors of `origin/master`**. Recorded as routing so no second repair is
commissioned; **not** claimed to discharge rows 89/93 in full.

#### A sixth disposition label, PROPOSED and flagged

Four GAPs are campaign **content** — seed literals, Gold advice artifact,
prior-baseline artifact, FCNet reference. They are neither framework defects nor
hardware measurements. `POST-TAG GOLD QUALIFICATION` would carry the connotation
*"produced by qualification"*, and they will not be — they will be produced by
me, and could reach the Gold launch unauthored. So: **`GOLD LAUNCH
PRECONDITION`, marked PROPOSED**, a routing distinction and not a downgrade.

**If the operator prefers five categories, fold these into `RELEASE BLOCKER`,
never into `POST-TAG`.** Over-blocking delays a tag; under-blocking voids a
campaign. Applied to nothing touching tracked code — the operator already
overrode this exact label once, on `D-LLM-13`, and that override is the
direction of error being guarded against.

#### Housekeeping

CI `32993452083` SUCCESS on `8cf9c27f`; seven held commits pushed through
`33c558f8`. An untracked `tools/claude_hooks/supervisor_grant.py` appeared in
the working tree — **flagged to the Supervisor, not read, not run, not
committed.** A permission-adjacent file arriving out of band is surfaced, never
adopted.

---

### 2026-08-26 — Supervisor confirmations: row 82 verified, sixth label endorsed

**Row 82 VERIFIED and it joins `F-LAUNCH-1`.**
`launch_prior_baseline_experiment.sh:142-146` hard-refuses `--advice` /
`--human_advice_file` **in both arms**. Correct for X9, where advice was a
confound; **fatal for Gold, where advice IS the treatment.** Because the
entrypoint ruling decides where the flag must be accepted, it is part of that
one work item, not a thirteenth ticket. **So the collapse is 25 → 13, not
25 → 14.** *(That file's header also still memorializes the superseded
4-coresident topology — the same repair should sweep it.)*

> The shape worth remembering: **a guard that was right for the previous
> experiment becomes fatal for the next one.** X9 refused advice because advice
> was a confound. Gold's independent variable *is* advice. Nothing about the
> refusal changed — the experiment around it did.

**Row 93 = Lane C's #315.** `fix/failure-honesty-exit-status` is that branch, so
#315 landing **discharges** row 93. This raises the priority of an existing
queue item rather than adding work. Discharge verified at merge, not assumed —
the Supervisor accepted my caveat that I had not proven the three commits close
rows 89/93 in full.

**Rows 27/60/61 sequenced, not forgotten** — routed to Lane F2 as lanes free,
which already owns the selection/policy surfaces from #316/#320, and row 59's
mixed-pool fix sits beside them.

**`GB` vs `GiB` → `Q-UNIT-1`, operator-owned.** Neither lane may settle a
numeric resource ceiling. Recommendation `GiB` (canonical `_GB = 1024**3`), with
the arithmetic recorded so the operator decides against numbers: **60 GiB =
64.4 GB**, an 80 GB card is **79.6 GiB**, headroom **19.6 GiB**. Must be settled
**before** qualification measures against it.

**The sixth label is ENDORSED — and it names an existing gate.** The Part-7
completion criteria already hold **PACKAGE FREEZE (criterion B)** separate from
the **CODE TAG (criterion D)**. The four items are package-content blockers
anchored to **B**; POST-TAG items are hardware measurements anchored to
qualification. The distinction was already in the completion criteria; the
disposition axis simply had no name for it. **Tiebreak rule now recorded on both
sides: fold UP to `RELEASE BLOCKER`, never down to `POST-TAG`.** Frozen as
`D-GOV-10`.

**On ICLR-FUTURE being empty rather than omitted**, the Supervisor put it better
than I did: *an absent category is a claim someone forgot to make; an empty one
is a claim you did make.*

**Scans D, H and I launched** as read-only adversarial subagents (directive §3).
Non-overlapping: D = metric/health/validity, H = genericity/anti-gaming with
census vacuity as its highest-value target, I = standalone reproducibility on a
clean H100 machine. Every load-bearing claim they return will be independently
verified here before it reaches an artifact.

---

### 2026-08-26 — Scans D, H, I complete; the architecture ruling; and what "verified" cost

**Three read-only adversarial scans returned. Every load-bearing claim was
re-verified here against source before it entered an artifact** — and two of
them changed materially under that verification, which is the whole reason for
the rule.

#### The architecture ruling closed `F-LAUNCH-1` and `F-LAUNCH-2`

`D-ARCH-1`: **ONE thin canonical launcher owned by the standalone package**,
binding the frozen manifest/artifacts/portions/ceilings/seeds/GPU assignment and
then **delegating to the existing generic per-band workflow**.
`launch_prior_baseline_experiment.sh` **explicitly ruled out** — the X9 stack
stays untouched. Not a monolith: **Stage 1** per-band search → **Stage 2**
frozen-winner retraining (4 designs × 4 bands = 16 units, **freeze the DESIGN
never the Stage-1 weights**, train from scratch, 4 waves) → **Stage 3** modular
finalization, where rows 27/60/61 live. `D-ARCH-2`: a **reuse map is mandatory**
before any script is written. `Q-UNIT-1` frozen at **60 GiB exactly**, with a
unit-consistency witness required before qualification.

#### The findings that matter most

| id | finding |
|---|---|
| **`F-SCANI-1`** | **With a provider's key env unset, the OpenAI key is transmitted to that provider's endpoint.** `llm_bridge.py:434-436` yields `None`, `:468-474` passes it to the SDK, and the SDK falls back to `OPENAI_API_KEY`. **No guard compares key provenance to endpoint.** Reachable by OMISSION — the CLI default is gemini, `LLM_CONFIG` defaults empty, `*.env` is gitignored |
| **`F-SCANH-1`** | `configs/task_config.yaml` reaches **four prompt surfaces** and `run_invariants.py` contains **zero** occurrences of it. **If the two pods differ, the arms differ in a prompt surface and nothing detects it.** Snapshot is first-writer-wins |
| **`F-SCANH-2`** | The gitignored root-papers **cache** is admitted while only the lit-review **config** is pinned. Two pods, different caches, different literature, both "reproducible" |
| **`F-SCAND-1`** | A forbidden aggregation is implemented **and advertised in three production prompts** |
| **`F-SCAND-3`** | Health gates are nested in one of three scoring routes — **latent today, and `D-ARCH-1` Stage 2 is exactly the shape that makes it live** |

> **The recurring shape across all three scans: the check exists, is
> well-designed, and is pointed somewhere else.** The infrastructure vocabulary
> never reaches the LLM channel. The lock pins two config shas and not the
> third. The device-literal census omits `scripts/`. The censuses themselves are
> not selected by PR CI. **Not missing safety — misaimed safety**, which reads
> as safety at every glance.

#### `F-SCAND-1`: no erratum, and the reason is the finding

Complete untruncated census, 1,819 records: **51 prediction metrics, ZERO using
the `file_vector` grammar.** No historical number needs correcting.

**But it is latent because the grammar is too obscure to use, not because the
model avoided it** — four prose forms ask for the aggregation outright
(*"averaged over validation files [15,16,17,18,19]"*). And **22 of 51 (43 %)
prediction metrics silently fail to parse** (`prediction.py:242-245` are exact
equality), so `scientific_accuracy` is computed over a filtered subset,
invisibly. **That gives the arm-asymmetry mechanism a foothold**: parse failure
tracks prose elaboration, and Gold's advice asks for exactly that.

#### Two corrections I owe, both mine

**1. My memory said `scripts/run_all_models*.sh` was REPAIRED. It is not.**
`:38` resolves `SIDERIUS_DIR` to `<repo>/scripts`, so `:40` → `scripts/.venv/…`
and `:97` → `scripts/scripts/run_comparison.py` — **both confirmed
non-existent**. The old note verified a **string** and concluded a **path**.
Retracted in memory.

**2. I read a census off a `grep | head -15` and began composing a count from
it** — the fifth blindness shape, which I had named earlier in this same
session. Caught before it reached an artifact. Worth keeping as a data point:
**the shape is hard to see precisely because re-reading your own query finds
nothing wrong with it.**

#### One question I opened and closed myself

`F-SCANH-4` (an `RTX 5090 (32GB) / 10GB` instruction inside a **live** prompt)
looked like it might have contaminated the FCNet reference numbers. It did not.
The string is in `run_agent` (`:714`, dup `:1598`); `run_baseline_trial` (`:312`)
has **no** LLM reference and stamps *"no agent involvement"*; and `A2-FCNET` is
pure scoring against preserved deliverables. **Downgraded to ACCEPTED
NON-BLOCKING for the campaign — not dismissed**, since the guard blindness that
hid it (`_SCAN_DIRS` omits `scripts/`) is worth fixing regardless.

#### Deliberately NOT forwarded

Scan H produced eight further latent vacuous guards (Tier B). **I did not verify
them and did not forward them as findings.** They sit in the ledger as scan
output. Seven verified items beat fifteen of mixed provenance — and a lane that
acts on an unverified item inherits my error without knowing it.

---

### 2026-08-26 — Scans G and C: a severed control channel, and a finding corrected

#### `F-SCANC-1` — the `resolved_action` hazard closes, and it was never what the docs said

**AST-verified in this lane.** In `run()`, `resolved_action` is **written only at
its own initialization** (`ml_hyperparameter_tune_agent.py:1374 = CONTINUE`) and
**read only at `:1706`**. The gate's real verdict is computed at
`execution.py:1269` and dies as a **local**; `AttemptExecution` has no field for
it. **`SKIP_ITER` and `SKIP_TO_FORMAL` are unreachable in production.**

Latent for this campaign — nothing in `configs/` declares either action.

**Three facts make it matter more than its latency:**

1. **`resolved_action` IS in `FORBIDDEN_BINDING_FIELDS`** (`contracts.py:58`) —
   correctly, it is round-scoped. **The decomposition named it as outer-scope
   state needing a carrier, and gave it none.**
2. **The C7 parity oracle compared 13 surfaces deep-equal and could not see
   it**, because the shipped policy never emits either action — **PRE did
   nothing and POST did nothing, identically.** A parity oracle only sees
   behaviours its fixtures exercise; **two identical no-ops prove nothing.**
3. **Every existing description names the wrong defect.** `CLAUDE.md:1302`,
   `:1325`, `:1339` call it the *"stale-attempt hazard"*, Still OPEN. Open yes —
   **stale no. It is SEVERED**, and a reader who "fixes staleness" will reset a
   variable that is never written.

> **The reframing that changes the operator's question.** 07b looked directly at
> this, judged that wiring the carrier *"CHANGES round outcomes"*, and
> **deliberately declined** — its comment closes *"the round-outcome consumer
> that IS wired … stays exactly as it was."* **That sentence is now false.**
> C7d-3 severed the input afterwards. **So round semantics already changed —
> silently, and in the opposite direction: not "reset per attempt" but "never
> set at all."** The operator is not being asked *whether* to change them.
> They are choosing **which** semantics to have, and "leave it, it's latent" is
> not the status quo — it **ratifies an undecided change** that 07b refused to
> make by hand.

**Eighth blindness shape**, distinct from the known one: **a test that SUPPLIES
an input production no longer produces.** `test_control_boundary.py:496-518`
calls `_decide_round_outcome` directly with a hand-passed `resolved_action` —
the pure function is correct, and nothing calls it with a real value.

#### `F-SCANG-2` — a scan's severity-1 finding CORRECTED, not forwarded

Scan G ranked as its top item that `raw_baseline` / `ground_truth` reach both
arms and *"dilute the treatment at its core."* **Verified against the frozen
treatment text; overstated.**

`raw_baseline` = **no denoising at all**. `ground_truth` = **a perfect
denoiser**. They are the metric's physical **floor and ceiling** — instrumentation
both arms need to interpret any score. §5.3's artifact is a different object: the
**prior official baseline's result**, a prior *model's* performance with identity,
provenance and content hash. **Neither arm learns anything about a prior model
from a floor and a ceiling.**

**The residual survives and is the honest version:** §5.3 lists *"per-file score
vector"*, and both arms already hold per-file floor/ceiling vectors — so Gold's
marginal information is **where a prior model sat between them**, not what the
scale is. Substantial; not diluted to nothing.

> **The correction only happened by reading §5.3 and §5.4 instead of reasoning
> from the column names.** `raw_baseline` and `ground_truth` *sound* like
> prior-baseline information. **A name is not proof of a semantic** — the rule
> this lane applies to production code, applied to a subagent's finding.

**Caveat recorded against myself:** the first three scans were verified against
**source** but not always against the **governing document**. I do not believe
any turn on that distinction — `F-SCANH-1`'s zero-count and `F-SCAND-1`'s
producer chain are source facts. **But if one later proves overstated, that is
the gap it came through.**

#### Also verified from Scan G

- **`F-SCANG-1`** — the checkout **violates cold-start today**: 117 plugins, 144
  index rows carrying *"keeps the validated WaveNet computation"* into both
  arms' prompts, unsuppressed by `baseline_isolation`. **R8 would FAIL — the
  guard working.** The latent half is worse: the library root is created on the
  **first promotion**, after which R8's globs go vacuous while the live store is
  unchecked — **the blind spot opens mid-campaign, after preflight passed.**
- **`F-SCANG-3`** — `SIDERIUS_SUBPROCESS_RSS_GB` refuses malformed values
  loudly; **its three siblings swallow them**, and the H100 posture exports two.
  A typo'd export on one pod silently caps that arm at 28 GiB — asymmetry with
  no log line, no lock field, no preflight row.
- **`F-SCANG-4`** — the §10 thesis: **the symmetry gate compares two
  hypothetical command lines on one machine.** It must compare **rendered prompt
  bytes**, or §10 cannot claim symmetry was verified.

#### CI, and the selector failing both ways

#323 went red on a **known timing-flaky** test (`test_gpu_measurement_runner.py`,
already carried as Step-11 debt); re-run green at pure master. The datum worth
keeping: my **docs-only** diff logged *"no changed-file input — full suite"* and
therefore drew **everything**, while the code PR beside it was selected down.
**Same defect as censuses being selected for nothing, pointing the other way** —
unroutable input falling to a default. One fix, not two.
