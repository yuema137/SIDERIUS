# PR F — Inspection-cost scaling study (measure only)

**Status: DESIGN DRAFT 2026-08-09 — NOT approved, no implementation begun.
No production code, test, schema, launcher or scorer file is touched by
this document.** Three operator decisions (Q-F-1 … Q-F-3) are listed at
the end; Q-F-1 gates the sweep's execution scale.

| | |
|---|---|
| Plan section | `docs/design/v21_priorities.md` — PR F section + P3 + §E.3d (binding, incl. §E.3d.11-12) |
| Gate | **NOT a V21 launch blocker.** PR F is a prerequisite for *changing the inspection budget*, nothing else |
| Depends on | PR E merged (`f1f4c30a`) — E.5 order "F after E (funnel data makes the sweep interpretable)"; the P6.3 overlay values are already recorded, so design can proceed now |
| Audit date | 2026-08-09, against `21352adc` (master) |

> **Fresh-audit rule (E.5, recorded at PR E closeout):** PR F starts from
> this audit, never from the old ledger premise. §0 below is that audit.

---

## A0. Verification toolchain

```bash
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright     # pyright 1.1.409
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

**Baseline at `21352adc`:** unit suite `8200 passed, 3 skipped, 1 xfailed`
(the 3rd skip is PR E's env-gated legacy check); pyright
`0 errors, 4 warnings`; ruff + format clean. Per §E.3d.12, **every**
checker runs at every final head.

---

## 0. Pre-design audit (performed 2026-08-09 against `21352adc`)

### 0.A What the budget actually bounds — the operations and their owners

The budgets live in one frozen Pydantic object,
`agent/skills/evaluate_vram_skill/probe_budgets.py`:

```text
single_inspection_seconds = 120     one torchinfo/structural inspection
single_candidate_seconds  = 120     ONE candidate batch inside the search
batch_search_seconds      = 600     the whole descending batch search
single_probe_seconds      = 180     one training/inference footprint probe
preflight_total_seconds   = 1200    backstop for the entire pre-flight
```

P3's "120 s inspection budget" is therefore **two distinct 120 s budgets**
bounding two distinct operations, and the V20 incident text
(`InconclusivePreflight ... 'batch candidate' step at candidate batch 64`)
names `single_candidate_seconds`, not `single_inspection_seconds`. The
study must measure and report **per operation** — collapsing them would
recreate the exact one-number-doing-several-jobs defect this module was
built to kill.

The operation under the incident budget is
`probe_activation_footprint(model, loss_module, input_sample, mode,
device="cpu")` (`structural_probe.py:225`), called per candidate batch by
`resolve_inference_batch` (`batch_resolver.py:113`) over
`_DEFAULT_CANDIDATE_BATCHES = (64, 32, 16, 8, 4, 2, 1)` (`:58`),
descending. **The probe is CPU-side by default and the predicted peak is
analytic** (`_predict_inference_peak_bytes`), so the study needs **no
GPU** — which also dissolves the shared-card concern the ledger's PR F
note raises, leaving only CPU-load noise (see §0.E).

### 0.B The sixth instance of §E.3d.1 — the cost is measured and discarded

`batch_resolver.py:175-200`: every candidate probe is wrapped in
`candidate_started = time.monotonic()` … `candidate_elapsed = ...` — and
the elapsed value is persisted **only when it exceeds the budget**
(inside a `ProbeTimeoutRecord`). A successful probe's cost is computed
and thrown away. Consequences for this PR:

1. **The curve cannot be reconstructed from existing records** — success
   timings were never persisted, and timeout records are right-censored
   by definition. A harness must produce the data.
2. The harness does **not** need a production change to get success
   timings: it times its own calls to the REAL production functions.
   Adding success-side timing telemetry to production is a candidate
   *outcome* of the study (like every budget change), not an input —
   recorded as deliberately out of scope.

`ProbeTimeoutRecord` (`probe_budgets.py:107`) is the existing typed shape
for over-budget events and the harness reuses it verbatim when a sweep
point times out — no new vocabulary.

### 0.C The sweep population already exists on disk

Two real populations, no synthesis required:

- **The realized V20 candidate population:** 83 generated plugins under
  `agent_generated/models/` — the actual models whose size regime P6.3
  recorded (663,488 – 12,772,096 trainable params). Sweeping THESE
  answers the censoring question for the population V20 actually
  produced, not a synthetic proxy.
- **The reference regime:** the built-in registry models (wavenet, punet,
  rnn, transformer, fcnet ≈ 323 M) span up to the size FCNet occupies —
  the regime P3 worries the budget censors.

P6.3's recorded distribution (663,488 · 7,280,256 · 8,409,280 ·
12,772,096 across attempts 2-3) is the overlay the ledger's validation
section demands; PR E's funnel provides the labels for any FUTURE overlay
but the study does not depend on new funnel data.

### 0.D Honest-absence contract — already structural, must not be weakened

PR #156's repair is live: a timeout is `inconclusive`, never
`measured_capacity_failure`, and `ProbeTimeoutRecord.is_capacity_evidence`
is always False for a timeout. The study inherits this vocabulary: a
sweep point that exceeds its bound is recorded as **right-censored at the
bound** (`>= bound`), never as a measurement of the model, and never as
"too big".

### 0.E Timing is noisy, and the ledger says so itself

P3's own history: *"the same configuration both failed and passed
depending on CPU load, which is what proves it was never a capacity
signal."* So "deterministic re-run reproduces the curve" cannot honestly
mean bit-identical wall times. The study defines reproducibility in two
layers (Q-F-2 freezes this):

```text
DETERMINISTIC (bit-identical across re-runs)
    the manifest: which model x config x batch x segment points run,
    their order, the seed, the input shapes
NOISY (measured with repeats, reported with dispersion)
    wall times: N repeats per point, median + min/max recorded,
    host identity + loadavg captured per point
VERDICT-STABLE (the acceptance property)
    the censoring classification of each point against the CURRENT
    budgets must be identical across re-runs — points near a budget
    boundary are classified "margin < dispersion: indeterminate",
    never flipped silently by noise
```

### 0.F Where study artifacts live — precedent, not a new artifact kind

`reports/` already holds committed study reports
(`pr3_citation_reliability_rev4_2026-07-29.md`,
`health_metrics_scan.md`, …). A committed measurement JSON + report
markdown under `reports/` follows that precedent; it is not a new
persistent-artifact *kind* in the O-E-3/§15 sense (nothing in production
reads it). Q-F-3 confirms.

### 0.G Runtime bound — estimated before asking, per policy

Worst case is budget-bounded by construction: one candidate's search is
capped at `batch_search_seconds=600`, so 83 plugins + ~15 scaled built-in
configs ≤ ~98 × 600 s ≈ 16 h **worst case** — far over the autonomous
limit. Realistically most points complete in seconds (C12 measured the
323 M baseline probe path healthy). The design therefore stages
execution:

```text
F2a PILOT   ~12 points spanning the size range, 3 repeats
            -> measures the actual per-point cost distribution
F2b FULL    launched only if the pilot projects the full sweep under
            ~1 h; otherwise STOP and present the projection to the
            operator with a proposed subset
```

---

## 1. Objective

> **Measure the curve `model scale → per-operation inspection cost →
> predicted peak VRAM` for the real candidate populations, decide from
> data which candidate classes the current budgets would censor, and
> write the recommendation — changing nothing.**

## 2. Non-goals

```text
NO  budget change of any kind (120→300 is explicitly forbidden)
NO  adaptive/staged/size-aware budget implementation — candidate
    OUTCOMES of the study, not inputs
NO  production code change at all — including success-side timing
    telemetry (a candidate outcome, recorded as such)
NO  prompt/advice change; the budget text the agent reads is frozen
NO  GPU use; no LLM calls; no scientific records produced
NO  new persistent artifact kind — reports/ precedent only
NO  funnel-distribution claims (§E.3d.6 still binds; the P6.3 overlay
    uses only already-recorded values)
NO  planner exposure of any study result (separate evidence + approval)
```

> **Template clauses deliberately not applicable** (recorded, not
> skipped): the ordering-specific requirements (*"validate the actual
> visited sample/file sequence"*, *"prove the default `shuffle` path
> unchanged"*) belong to a data-ordering feature. PR F touches no
> sampling, ordering, seeding-of-training, `file_order` or step-count
> surface — its determinism obligation is the MANIFEST (§0.E), which is
> the analogous property and is pinned in F1. Likewise §6's
> `file_order`/scope-mismatch cases are replaced by the failure cases a
> measurement harness actually has: unloadable plugins, budget-censored
> points, host-noise flips, and manifest drift.

## 3. Study contract

```text
manifest (deterministic, seeded)
  candidates:  83 agent_generated plugins @ default config
               + built-ins scaled across ~663k..323M params
  axes:        candidate batch (the REAL descending tuple) x
               segmentation_size (production values) x N repeats
harness      scripts/inspection_cost_study/  (new, non-production)
  drives      the REAL probe_activation_footprint and the REAL
              resolve_inference_batch with the REAL frozen ProbeBudgets —
              never a reimplementation (B1b-P2 / M-D3 lesson)
  records     per point: wall time (median + min/max of repeats),
              predicted peak bytes, realized parameter counts (both
              conventions, per O-E-6 naming), disposition
              (completed | right-censored-at-bound), host context
outputs      reports/v21_pr_f_inspection_cost/
              measurements.json  (schema-validated, committed)
              report.md          (curve + censoring analysis + P6.3
                                  overlay + recommendation)
consumers    the operator, and any FUTURE budget-change PR — nothing
             in production reads any of it
```

## 4. Commit plan

| # | Commit | Blocked on | Independently reviewable |
|---|---|---|---|
| **F0** | Audit + design synchronization (this document) | — | Yes (docs only) |
| **F1** | The measurement harness + manifest determinism pins | operator approval of this design | Yes |
| **F2a** | Pilot sweep (~12 points) + projection | F1 | Yes |
| **F2b** | Full sweep + curve + censoring analysis + recommendation | F2a projects < ~1 h, else operator decision | Yes |

---

### Commit F1 — The measurement harness, driving the real production functions

#### 1. Goal

Build the deterministic sweep harness so the curve can be produced,
reproduced, and audited — with the harness structurally unable to drift
from what production actually does, because it calls the same functions
under the same frozen budgets.

**Why this commit and not another.** The harness must exist and be pinned
before any number is produced, for the same reason D1/E1 pinned before
changing: evidence produced by an unpinned harness cannot be
distinguished from evidence produced by a subtly different one.

#### 2. Scope

**Changes**

```text
scripts/inspection_cost_study/manifest.py     deterministic point set
scripts/inspection_cost_study/harness.py      timing + recording
scripts/inspection_cost_study/schemas.py      SweepPoint / SweepResult
                                              (Pydantic, per CLAUDE.md)
tests/unit/scripts/test_inspection_cost_study.py
```

**Must remain unchanged**
- **Every production file.** `probe_budgets.py`, `batch_resolver.py`,
  `structural_probe.py`, every registry, every prompt — zero production
  diff. A diff in any is a finding, not a task.
- The frozen budget values — the harness READS the real `ProbeBudgets()`
  defaults; it never constructs modified budgets except in its own unit
  tests.

**Non-goals**
- Running the sweep (F2a/F2b).
- Any statistics beyond per-point medians/dispersion.

**Dependencies:** design approval.

#### 3. Implementation plan

- [ ] Re-read `batch_resolver.py:100-260` and `structural_probe.py:225+`
      immediately before writing the harness; confirm the call signatures
      and the descending candidate tuple import path
- [ ] Manifest: enumerate the 83 `agent_generated` plugins via the REAL
      plugin loader (never by filename globbing alone — the loader is the
      authority on loadability) plus scaled built-in configs; record for
      each point the model identity, config, both parameter-count
      conventions (O-E-6 names), batch, segmentation_size
- [ ] Manifest determinism: content-hash the manifest; a fixed seed
      orders any sampled subset; **no wall-clock or randomness outside
      the seeded generator**
- [ ] Harness: per point, call the REAL `probe_activation_footprint`
      (and, per model, one REAL `resolve_inference_batch` search) under
      the REAL frozen budgets; time around the calls; on budget excess
      record right-censored using the existing `ProbeTimeoutRecord`
      vocabulary — never a new one
- [ ] Repeats: N configurable (default 3), median + min/max per point;
      host identity + loadavg captured per point
- [ ] Output: schema-validated `measurements.json`; the writer refuses to
      overwrite an existing file (evidence is append-only, like the
      ledger)
- [ ] Unit-test the harness only with tiny fixture models (CPU,
      sub-second); the 83-plugin population is F2's business

#### 4. Validation plan

**Unit**
- [ ] Manifest is bit-identical across two generations (content hash)
- [ ] A fixture model produces a schema-valid SweepPoint with plausible
      fields; both parameter-count conventions present and independently
      correct on a frozen-parameter fixture (reusing E3's pattern)
- [ ] Right-censoring: a deliberately tiny budget on a fixture model
      yields `right-censored-at-bound` with the existing
      `ProbeTimeoutRecord` fields — and `is_capacity_evidence is False`

**Integration / pseudo**
- [ ] One end-to-end harness run over ≤3 fixture models writes a valid
      `measurements.json` and a re-run with the same seed produces an
      identical manifest and identical dispositions

**Negative / invalid input**
- [ ] An unloadable plugin is recorded as `unloadable` with the loader's
      error — never silently skipped, never a crash of the sweep
- [ ] Overwrite refusal: writing onto an existing measurements file fails
      loudly

**Backward-compatibility / default parity**
- [ ] Zero production diff — asserted by `git diff --name-only` in the
      commit boundary, and the harness imports are read-only
- [ ] The harness uses the REAL `ProbeBudgets()` defaults — a test pins
      that the values the harness reports as "current budgets" equal the
      production defaults, so budget drift is visible

**Real-training Gate:** none — the study is CPU-only by design. **Not to
be launched without operator approval** applies to F2b's full sweep, via
Q-F-1.

#### 5. Acceptance criteria

- Two manifest generations hash identically; the hash appears in
  `measurements.json`.
- A fixture sweep point's timing comes from wrapping the **real**
  production function (asserted structurally — the harness calls
  `probe_activation_footprint` / `resolve_inference_batch` by their real
  import, verified by an AST/identity test, not a substring — §E.3d.9).
- A budget-censored fixture point reproduces the existing
  `ProbeTimeoutRecord` vocabulary with `is_capacity_evidence False`.
- `git diff` for this commit contains only `scripts/inspection_cost_study/`
  + its tests + this document.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| A plugin fails to load | Point recorded `unloadable` with the loader error; sweep continues; the report must count them — silent skips would bias the curve toward loadable (small?) models |
| A point exceeds its per-operation budget | Right-censored at the bound; sweep continues to the next point |
| A point exceeds a harness hard-deadline (2× budget) | Killed and recorded `harness-deadline`; distinguishes "slow but measurable" from "stuck native call" (the in-process-alarm limitation `probe_budgets.py` already documents) |
| Host under load mid-sweep | loadavg recorded per point; the report flags points whose repeats disperse beyond the stated threshold |
| Manifest drift between pilot and full run | The full run REFUSES to start if its manifest hash differs from the pilot's for shared points |
| Existing measurements file | Overwrite refused loudly |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/scripts/test_inspection_cost_study.py -q
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright
```

- [ ] Harness unit counts / wall time — **to record**
- [ ] Mutations — **to record**, at minimum: harness reimplements the
      probe instead of calling it → must fail; censored point recorded as
      completed → must fail; manifest loses determinism (unseeded
      ordering) → must fail
- [ ] pyright vs baseline — **to record** (§E.3d.12: every checker, every
      final head)

#### 8. Commit boundary

- [ ] `scripts/inspection_cost_study/` + tests + this document only; zero
      production files
- [ ] No budget value anywhere in the diff except read from production
- [ ] Diff summary, staged file list, tests and deviations recorded here
      before committing

---

### Commit F2a — Pilot sweep and projection

#### 1. Goal

Produce the first real measurements on ~12 points spanning the size range
(663k → 323 M), and project the full sweep's runtime — the gate on F2b
that keeps execution inside the autonomous bound.

**Why this commit and not another.** §0.G: the worst case is ~16 h; the
policy requires estimating before asking. The pilot IS the estimate.

#### 2. Scope

**Changes**
- `reports/v21_pr_f_inspection_cost/measurements_pilot.json` (committed
  evidence)
- This design document (pilot numbers + projection).

**Must remain unchanged** — everything else; the harness itself is frozen
by F1 (a harness change after data exists restarts F2a).

**Dependencies:** F1.

#### 3. Implementation plan

- [ ] Select the pilot manifest: the smallest and largest generated
      plugins, ~8 spanning P6.3's recorded values, fcnet at reference
      scale, one known-deep dilated architecture (the incident class)
- [ ] Run with 3 repeats on an otherwise-idle host; record loadavg
- [ ] Project full-sweep runtime from the pilot's per-point distribution;
      state the projection method in the report

#### 4. Validation plan

**Unit** — none new; the harness is already pinned.

**Integration / pseudo**
- [ ] Re-run the pilot manifest once; assert identical manifest hash,
      identical dispositions, and timing dispersion within the report's
      stated threshold — the §0.E three-layer reproducibility, exercised
      on real data

**Negative / invalid input**
- [ ] If any pilot point is right-censored, verify the record follows
      §0.D (censored, not "too big") before any analysis

**Backward-compatibility / default parity**
- [ ] Zero production diff; zero test diff

**Real-training Gate:** none.

#### 5. Acceptance criteria

- `measurements_pilot.json` committed, schema-valid, manifest hash
  recorded.
- The projection states: full-sweep expected runtime, its method, and the
  GO/STOP verdict against the ~1 h autonomous bound.
- If STOP: the proposed subset and its projected runtime are stated for
  the operator — F2b does not start.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Pilot projects full sweep > ~1 h | **STOP.** Present projection + proposed subset to the operator (Q-F-1 escalation path) |
| Pilot dispersion exceeds the reproducibility threshold | Investigate host conditions first; if intrinsic, the report must carry the wider bands — never narrow the threshold to make the pilot "pass" |
| A pilot point right-censors | Legitimate data (that IS the censoring phenomenon) — recorded per §0.D and kept |

#### 7. Verification commands and evidence

- [ ] Pilot counts, dispositions, wall time — **to record**
- [ ] Re-run reproducibility result — **to record**
- [ ] Projection + GO/STOP — **to record**

#### 8. Commit boundary

- [ ] Evidence + this document only
- [ ] No harness edit after data exists
- [ ] Diff summary and deviations recorded before committing

---

### Commit F2b — Full sweep, curve, censoring analysis, recommendation

#### 1. Goal

The deliverable: the measured curve, the censoring analysis against the
CURRENT budgets with the P6.3 overlay, and the written recommendation.

**Why this commit and not another.** It is the study's product and must
be reviewable as one piece of evidence.

#### 2. Scope

**Changes**
- `reports/v21_pr_f_inspection_cost/measurements.json` + `report.md`
- This design document; the V21 ledger's PR F section (delivered block).

**Must remain unchanged** — every production file; the harness; the
budgets.

**Dependencies:** F2a GO (or an operator-approved subset).

#### 3. Implementation plan

- [ ] Run the full (or approved-subset) manifest, 3 repeats
- [ ] Report, per operation (§0.A — never collapsed): cost vs trainable
      params, cost vs total params, cost vs batch, cost vs segment
- [ ] Censoring analysis: for each population point, margin to
      `single_candidate_seconds`, `single_inspection_seconds`,
      `batch_search_seconds`; classify `clear / margin<dispersion:
      indeterminate / censored`
- [ ] Overlay P6.3's recorded values (already-ledgered numbers only —
      no new distribution claim, §E.3d.6)
- [ ] Recommendation: which of {adaptive budget, cheaper analytical
      pre-flight, staged inspection, size-aware budget, no change} the
      curve supports — **as a recommendation for a separate PR, never a
      change here**
- [ ] Ledger: PR F delivered block; Gate status unchanged (still not a
      launch blocker; still the prerequisite for any budget change)

#### 4. Validation plan

**Unit** — none new.

**Integration / pseudo**
- [ ] Full-sweep re-run of a seeded 10 % sample reproduces manifest hash,
      dispositions, and dispersion-bounded timings (re-running all ~98
      points twice is cost without new information — recorded as the
      deliberate sampling decision)

**Negative / invalid input**
- [ ] Unloadable-plugin count reported; if > 0, the report states the
      loadability bias explicitly

**Backward-compatibility / default parity**
- [ ] Zero production diff across the whole PR — `git diff base..HEAD`
      excluding `scripts/inspection_cost_study/`, `tests/`, `reports/`,
      `docs/` is EMPTY (the PR3-L2 allowlist shape)

**Real-training Gate:** none.

#### 5. Acceptance criteria

- Every manifest point has a disposition; none silently missing
  (`completed + censored + unloadable + harness-deadline = manifest size`).
- The censoring section names candidate classes with margins and
  dispersion, per operation — no collapsed "the budget" number.
- The recommendation cites specific curve regions, and the report's final
  line restates: **no budget was changed; a change is a separate PR
  justified by this data.**
- The P6.3 overlay uses only ledger-recorded values.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| The curve is flat (no censoring risk anywhere) | A legitimate outcome — the recommendation is "no change"; do NOT enlarge models to force an effect (§E.3d rule: never enlarge a workload to force an outcome) |
| Points cluster at a budget boundary | `indeterminate` class, reported as such — the honest answer may be "the study cannot decide for this class at N=3 repeats"; escalate repeats only with a runtime re-projection |
| A generated plugin's config makes it degenerate (0 params etc.) | Measured as-is; PR E3's finding says 0 is a real measurement |

#### 7. Verification commands and evidence

- [ ] Full counts, dispositions, wall time — **to record**
- [ ] Sample re-run reproducibility — **to record**
- [ ] Freeze proof (empty non-allowlisted diff) — **to record**
- [ ] Full suite + ruff + format + pyright at the final head — **to
      record** (§E.3d.12)

#### 8. Commit boundary

- [ ] Evidence + report + docs only
- [ ] No recommendation implemented
- [ ] Diff summary and deviations recorded before committing

---

## 5. Acceptance and merge criteria (PR level)

1. Zero production diff across the PR — proved by the allowlist-shaped
   empty diff.
2. The harness drives the real production functions under the real frozen
   budgets, proved structurally and by mutation.
3. Manifest deterministic; timings carried with dispersion; dispositions
   verdict-stable across re-runs (§0.E's three layers).
4. Every manifest point accounted for; unloadable and censored counts
   explicit.
5. Censoring analysis per operation with the P6.3 overlay from
   ledger-recorded values only.
6. A written recommendation that changes nothing.
7. Full checker set green at the final head (§E.3d.12).

### V21 review fields

```text
Metric-frozen proof:      trivially — zero production diff, to be proved by
                          the empty non-allowlisted diff at merge
Name-keyed dependency
added:                    none — the manifest records model identities as
                          labels; nothing keys behaviour on them
Transport contract:       none added — the study is read-side + a new
                          non-production script; no schema field, no hop
Subprocess evidence:      the harness measures the in-process functions the
                          budgets bound; the production worker-subprocess
                          spawn overhead is OUTSIDE the measured operations
                          and recorded as a known, stated limitation
Acceptance evidence:      deterministic manifest + dispersion-bounded
                          timings + verdict-stable dispositions; no Gate —
                          CPU-only by design
```

---

## Operator decisions required — NONE RESOLVED, implementation blocked

### Q-F-1 — Sweep population and the runtime gate

**Question.** Approve the two-population manifest (83 generated plugins @
default config + built-ins scaled to ~323 M) and the staged execution
rule: pilot first; full sweep autonomously **only if** the pilot projects
under ~1 h; otherwise STOP and present the projection with a proposed
subset.

**Recommendation:** approve as stated — the worst case (~16 h, §0.G) is
budget-bounded but far over the autonomous limit, and the pilot converts
"ask before expensive" from a guess into a measurement.

### Q-F-2 — The reproducibility definition

**Question.** Freeze §0.E's three-layer definition (deterministic
manifest / dispersion-carried timings / verdict-stable dispositions with
an explicit `indeterminate` class for margin < dispersion) as what
"deterministic re-run reproduces the curve" means for this study.

**Recommendation:** freeze it — bit-identical wall times are impossible
(the ledger's own load-flip evidence), and a definition that pretends
otherwise would invite exactly the silent verdict-flipping the
`indeterminate` class exists to prevent.

### Q-F-3 — Committed evidence location

**Question.** Commit `measurements*.json` + `report.md` under
`reports/v21_pr_f_inspection_cost/`, following the existing `reports/`
study precedent (§0.F).

**Recommendation:** approve — committed evidence is what makes the future
budget-change PR auditable against this study; nothing in production
reads it, so it is not a new artifact kind in the O-E-3/§15 sense.

---

**Nothing in this document is implemented.** On approval the sequence is
F0 (this document) → F1 → F2a → (gate) → F2b. Q-F-1 gates F2b's
autonomous execution; Q-F-2 and Q-F-3 shape F1's schemas and outputs and
should be answered before F1 begins.
