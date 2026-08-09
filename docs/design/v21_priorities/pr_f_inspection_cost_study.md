# PR F — Inspection-cost scaling study (measure only)

**Status: DESIGN REVISION 3 — 2026-08-09, returned for final operator
approval. NOT approved for implementation; no production code, test,
schema, launcher or scorer file is touched by this document.**
Q-F-1 APPROVED, Q-F-3 APPROVED (operator, 2026-08-09). Q-F-2 approved in
principle; this revision applies the five narrow methodology
reconciliations the operator required — per-operation timeout semantics
matched to production's own enforcement styles, native
`BatchSearchTimeout` outcomes preserved verbatim, the wall-expiry
completion rule, the timing-blind grid rule, and the interpretation
boundary.

| | |
|---|---|
| Plan section | `docs/design/v21_priorities.md` — PR F section + P3 + §E.3d (binding, incl. §E.3d.11-12) |
| Gate | **NOT a V21 launch blocker.** PR F is a prerequisite for *changing the inspection budget*, nothing else |
| Depends on | PR E merged (`f1f4c30a`) |
| Audit dates | 2026-08-09 rev 1 against `21352adc`; rev 2 census audits against `9e4065bf` |

> **Fresh-audit rule (E.5):** PR F starts from this audit, never from the
> old ledger premise. Revision 2 adds the five operator-required audits:
> the complete budget-consumer census, manifest cardinality and runtime
> accounting, the population/scaling definition, censoring semantics
> grounded in the native typed outcomes, and the hard-deadline mechanism.

---

## A0. Verification toolchain

```bash
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright     # pyright 1.1.409
.venv/bin/python -m pytest tests/unit -q -m "not real_run" > /tmp/pytest.log 2>&1; echo $?
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

**Baseline at `21352adc`:** unit suite `8200 passed, 3 skipped, 1 xfailed`;
pyright `0 errors, 4 warnings`; ruff + format clean. Per §E.3d.12,
**every** checker runs at every final head.

---

## 0. Pre-design audit

### 0.A COMPLETE budget-consumer census (operator requirement 1)

All five `ProbeBudgets` fields traced from declaration
(`agent/skills/evaluate_vram_skill/probe_budgets.py:85-95`) to every
production consumer. Nothing inferred from names.

| budget | production consumer(s) | operation it bounds | enforcement style | native typed outcome | PR F |
|---|---|---|---|---|---|
| `single_candidate_seconds` = 120 | `batch_resolver.py:201` | ONE candidate-batch probe (`probe_activation_footprint`, inference mode) inside the descending search | **POST-HOC**: elapsed compared AFTER the probe returns — an over-budget probe still completes and yields an EXACT elapsed | `BatchSearchTimeout` carrying `ProbeTimeoutRecord(operation="batch_candidate", disposition="inconclusive")` | **MEASURED** — the V20 incident budget |
| `batch_search_seconds` = 600 | `batch_resolver.py:157` | the whole descending search across `(64, 32, 16, 8, 4, 2, 1)` | **POST-HOC**: checked at loop top before each next candidate | `BatchSearchTimeout` (`operation="batch_search"`) | **MEASURED** |
| `single_probe_seconds` = 180 | `wrapper.py:591` (training), `:648` (inference) via `_forward_pass_timeout` | one training / inference footprint probe | **PREEMPTIVE SIGALRM** (`wrapper.py:111`) — interrupts the call; documented limitation: cannot interrupt a stuck native call | `ForwardPassTimeoutError` → inconclusive | **MEASURED** (one training-mode probe per entry; the inference-mode cost is already covered by the candidate-probe axis — same function, same mode) |
| `single_inspection_seconds` = 120 | `wrapper.py:806` **ONLY** — constructs an inconclusive `ProbeTimeoutRecord(operation="model_inspection", elapsed_seconds=0.0)` after a torchinfo **tracing failure**, with the literal comment "NO deadline elapsed here" | nominally one torchinfo/structural inspection — but `probe_forward_layers` runs INSIDE `probe_activation_footprint` (`structural_probe.py:255, :294`) and no code path uses this value as a bound | **NONE — declared, never enforced** | the record exists but is used for tracing-failure reporting, not timeouts | **OUT OF SCOPE as a bound** — there is nothing to censor against. The torchinfo cost is measured *transitively* inside every candidate probe. **Finding F-A1 below** |
| `preflight_total_seconds` = 1200 | **NONE** — appears only in `probe_budgets.py`'s own `for_operation` map | nominally the whole pre-flight | **NONE.** The REAL end-to-end bound is `deadline_seconds=900.0`, **hardcoded** in `run_isolated_preflight` (`isolated_probe.py:441`) and `preflight_adapter.py:222` — a parent-side subprocess kill (`subprocess_deadline` provenance) | `IsolatedProbeResult` outcomes; its validator refuses a timeout claim faster than its own budget (`isolated_probe.py:327`) | **OUT OF SCOPE as a budget**; the 900 s subprocess deadline is recorded as context. **Finding F-A2 below** |

**Finding F-A1 (recorded, NOT fixed — PR F changes nothing):**
`single_inspection_seconds` is the **seventh** instance of §E.3d.1 — a
declared budget no code enforces. P3's premise ("the 120 s inspection
budget") actually names TWO 120 s budgets of which only
`single_candidate_seconds` is live; the V20 incident text names that one.

**Finding F-A2 (recorded, NOT fixed):** `preflight_total_seconds=1200` is
inert, and the enforced end-to-end bound is a **hardcoded 900** — the
declared and enforced values contradict each other and nobody noticed
because the declared one is never consulted. Filed as **FU-F-1**
(reconcile or retire the two inert budgets — a follow-up PR's decision,
after this study's data says what the bounds should even be).

**Consequence for F2b's language:** "against the current budgets" means,
precisely: `single_candidate_seconds=120` (post-hoc),
`batch_search_seconds=600` (post-hoc), `single_probe_seconds=180`
(preemptive), and the `900` s subprocess deadline as the outer context.
The two inert budgets appear in the report only as findings.

### 0.B The sixth instance of §E.3d.1 — the cost is measured and discarded

`batch_resolver.py:175-200` times EVERY candidate probe
(`candidate_started = time.monotonic()` …) and persists the elapsed value
**only when it exceeds the budget**, inside a `ProbeTimeoutRecord`. A
successful probe's cost is computed and thrown away. Hence:

1. the curve cannot be reconstructed from existing records (success
   timings never persisted; timeout records are bound-censored);
2. the harness times its own calls to the REAL production functions — no
   production change; success-side production telemetry is a candidate
   *outcome*, recorded as out of scope.

### 0.C Populations — approved as two, never pooled (operator requirement 3)

```text
population = "v20_generated_realized"
    the 83 real generated plugins under agent_generated/models/, each at
    its default config — the REALIZED population P6.3 recorded
population = "builtin_reference"
    deliberately constructed reference configs of the six built-ins,
    extending toward fcnet's ~323 M — a DESIGNED sweep, not evidence
    about what the agent proposes
```

Every manifest row and every report figure carries the population label;
no statistic ever pools the two. The realized population answers "does
the budget censor what V20 actually produced"; the reference population
answers "does it censor the regime FCNet occupies".

**Built-in scale knobs — from the config schemas, not invented** (audited
via `ml_models/models_format_sandbox.py`; fcnet's config class is
`AEConfig`):

| architecture | config class | natural scale-controlling fields (defaults) |
|---|---|---|
| wavenet | `WaveNetConfig` | `residual_channels=32, gate_channels=64, skip_channels=32, num_blocks=10, kernel_size=12` |
| punet | `PUNetConfig` | `multi=40, depth=4, embedding_dim=32, kernel_size=9` |
| fcnet | `AEConfig` | `latent_dims=[4000, 400, 40]` (the dense widths — the ~323 M regime) |
| transformer | `TransformerConfig` | `embedding_dim=32, nhead=4, num_layers=2, dim_feedforward=128` |
| rnn | `RNNSeq2SeqConfig` | `embedding_dim=128, hidden_dim=256, num_layers=2` |
| gated_fno | `GatedFNOConfig` | `width=64, num_layers=2, num_gates=128` |

**Grid rule (frozen here, exact values fixed in F1 after instantiation
checks — and TIMING-BLIND, operator rule):** grid selection may depend
ONLY on config/schema validity, the deterministic ladder rules, and
instantiation validity. It must NEVER depend on measured wall time,
censoring outcomes, curve appearance, or whether a point supports a
preferred recommendation. The flow is one-directional — generate the
deterministic candidate grid, instantiate, valid stays valid, invalid
stays in the manifest as `invalid_config` — never "try, dislike the
timing, swap the multiplier". The manifest hash freezes the population
before F2a, which makes this rule mechanically checkable. each architecture scales its OWN primary width/depth knobs
through a small deterministic ladder (multipliers on the defaults, e.g.
×{½, 1, 2, 4, 8} on the primary width, respecting each field's validity;
fcnet scales `latent_dims[0..1]`). Realized parameter counts (both O-E-6
conventions) are RECORDED per config; **no architecture is forced onto a
common parameter grid** — the reachable points are what they are. Every
exact config appears verbatim in the manifest. Invalid/uninstantiable
grid configs are recorded `invalid_config` with the constructor error and
excluded from timing, never silently dropped.

### 0.D Definitions: entry, operation point, measurement (operator requirement 2)

```text
MODEL ENTRY       (population, model identity, exact config) — the
                  config carries its own production segmentation_size;
                  no separate segment axis in this study (recorded as a
                  deliberate scope bound: the segment dependence enters
                  through each config's own value, and a segment sweep
                  is a widening the pilot data can motivate later)
OPERATION POINT   one timed call of a REAL production function:
                    - candidate_probe(entry, B)   for each B in the real
                      tuple (64, 32, 16, 8, 4, 2, 1)      -> 7 per entry
                    - full_search(entry)          one real
                      resolve_inference_batch call        -> 1 per entry
                    - training_probe(entry)       one training-mode
                      probe_activation_footprint call     -> 1 per entry
                  = 9 operation points per entry
MEASUREMENT       one repeat of one operation point (default R = 3)
```

**Cardinality:**

```text
entries   A: 83 plugins x 1 config                     =  83
          B: 6 built-ins x |ladder| (~5)               =  ~30
          total                                        ~ 113 entries
operation points   113 x 9                             ~ 1017
measurements       1017 x 3 repeats                    ~ 3051
pilot     12 entries -> 108 operation points -> 324 measurements
```

### 0.E Runtime accounting — a real upper bound, then a structural wall
(operator requirement 2, continued)

The rev-1 formula (`~98 × 600 s`) was **not** an upper bound: it counted
only search caps and ignored the direct candidate probes, the training
probes, and repeats. The honest per-measurement worst cases, from the
enforcement census:

```text
candidate_probe   POST-HOC budget: the call is not interrupted at 120 s.
                  Harness bound = SIGALRM at 2 x 120 = 240 s
full_search       search cap 600 s is checked BETWEEN candidates; the
                  in-flight probe can overrun. Harness bound = 600 + 240 = 840 s
training_probe    production SIGALRM at 180 s already preempts;
                  harness adds nothing                       = 180 s
per-entry worst   7 x 240 + 840 + 180                        = 2 700 s
theoretical worst 113 entries x 3 repeats x 2 700 s          ≈ 254 h
```

That theoretical number is why the harness is **wall-bounded, not
estimate-bounded**: trusting a projection alone would repeat the
one-number-optimism this subsystem's history warns about. Structure:

```text
per-measurement bounds — PER OPERATION, matching production's own
enforcement style (operator reconciliation 1; a uniform "2x everything"
would BYPASS the native preemptive semantics for the training probe):

  candidate_probe   production 120 s is POST-HOC (never interrupts).
                    Harness EMERGENCY backstop: SIGALRM at 2 x 120 = 240 s
                    via production's _forward_pass_timeout. Exact elapsed
                    in [0, 240); >= 120 is an exact over-budget datum.
  full_search       the REAL resolve_inference_batch runs with its own
                    NATIVE semantics untouched (post-hoc 120/600 checks
                    raising BatchSearchTimeout with the typed record).
                    Harness EMERGENCY backstop: SIGALRM at 840 s
                    (600 + one overrunning probe's 240) around the call.
  training_probe    production 180 s is PREEMPTIVE, and the harness
                    PRESERVES it: the probe runs under production's own
                    _forward_pass_timeout(single_probe_seconds) exactly
                    as wrapper.py:591 does. A fired 180 s alarm IS the
                    production behaviour being studied — right-censoring
                    at lower bound 180. NO 2x relaxation exists for this
                    operation.

per-run WALL      --max-wall-seconds, checked BETWEEN measurements
                  (post-hoc, exactly like batch_search_seconds);
                  on expiry the run STOPS CLEANLY with everything
                  measured so far already persisted (append-per-point)
pilot wall        1 800 s (30 min) — the pilot CANNOT exceed the
                  autonomous bound no matter what the models do
full-sweep wall   set from the pilot projection; F2b runs autonomously
                  only if projection < ~1 h, else STOP with projection
                  + proposed subset (Q-F-1)
pilot ramp        the pilot runs its 2 extreme entries (smallest and
                  largest by declared scale) FIRST; if those two alone
                  consume > 600 s, the pilot stops and reports before
                  touching the remaining 10
```

Per-entry worst case is unchanged (7 × 240 + 840 + 180 = 2 700 s): the
training probe was already accounted at its native 180.

Expected reality, for calibration only (never a bound): C12 measured the
323 M baseline's probe path at ~17.7 ms/step scale — most measurements
should take seconds. The wall exists for the tail the study is about.

### 0.F Censoring and reproducibility semantics (operator requirement 4)

Grounded in the native outcomes from §0.A — no second vocabulary, and
(operator reconciliation 1+2) **per-operation**, because the three live
budgets enforce differently. The exception payloads were audited:
`BatchSearchTimeout.record` IS the typed `ProbeTimeoutRecord`
(`batch_resolver.py:103-105` — "carries the typed record rather than a
message"), and `ForwardPassTimeoutError` carries a message only
(`wrapper.py:106`), so the training-probe timeout's evidence is the
operation name + the native 180 s bound.

**Per-repeat raw record — a study-level ENVELOPE around native evidence,
never a replacement for it:**

```text
execution_outcome:
  completed          the call returned. elapsed_seconds is EXACT — and for
                     the POST-HOC operations this includes elapsed >= the
                     production budget (an exact over-budget observation)
  native_timeout     PRODUCTION's own bounded semantics ended the call:
                       full_search: BatchSearchTimeout raised — the native
                         ProbeTimeoutRecord is preserved VERBATIM
                         (model_dump) on the measurement, including its
                         operation ("batch_candidate" | "batch_search"),
                         its budget, and its EXACT elapsed (post-hoc: the
                         record's elapsed is a real measurement)
                       training_probe: ForwardPassTimeoutError at the
                         NATIVE 180 s — right-censored,
                         lower_bound_seconds = 180, exact elapsed UNKNOWN;
                         operation recorded as "training_probe"
  harness_backstop   the STUDY's emergency SIGALRM fired (candidate_probe
                     at 240 s; full_search outer at 840 s):
                     lower_bound_seconds = the backstop value, exact
                     elapsed UNKNOWN. Distinct from native_timeout by
                     construction — a backstop firing means production's
                     own semantics had NOT ended the call
  harness_deadline   the external kill (§0.G stuck-native residual)
  unloadable         plugin/config failed to load; loader error recorded
  invalid_config     reference-grid config refused by its own schema
```

The report can therefore always distinguish, verbatim: a
candidate-budget native refusal, a whole-search native refusal, a native
preemptive training timeout, a harness backstop, and an ordinary
completed call.

**Summary rule:** `median/min/max` are computed **over exact `completed`
elapsed values only** (including exact over-budget ones, flagged).
`native_timeout(full_search)`'s exact elapsed values (post-hoc, real
measurements) are summarised SEPARATELY per native operation, never mixed
into the completed-call statistics. Every summary carries
`n_completed / n_native_timeout / n_backstop / n_deadline` explicitly.
Censored lower bounds (training-probe native, backstops) contribute only
to the censoring narrative.

**Point-level classification against a production budget** (conservative
reconciliation; per repeat):

```text
under          completed with elapsed < budget
over-exact     an EXACT observation >= budget: a completed post-hoc
               overrun, or a native BatchSearchTimeout record whose exact
               elapsed >= the budget under classification
over-censored  a censored bound >= budget: a native training-probe
               timeout (bound 180 = its budget) or a harness backstop
               (bound = 2x budget)

all repeats under                          -> CLEAR
all repeats over (exact or censored)       -> WOULD_BE_CENSORED
repeats straddle the budget                -> INDETERMINATE
any harness_deadline repeat                -> INDETERMINATE (and reported)
```

Re-run reconciliation is the same rule over the union of repeats: a
re-run can move a point only TO `INDETERMINATE`, never flip
`CLEAR ↔ WOULD_BE_CENSORED` silently. The straddle test IS the dispersion
test, in the budget's own units; native semantics
(`ProbeTimeoutRecord`, `_a_timeout_must_have_reached_its_deadline`) are
reused, never re-invented.

**Three-layer reproducibility (unchanged from rev 1, now with exact
lower layers):** deterministic manifest (content-hashed, seeded) /
noisy raw timings (repeats, dispersion recorded, loadavg per point) /
verdict-stable classification (the rule above).

### 0.G Hard-deadline mechanism — existing primitives only
(operator requirement 5)

Repository census of bounded-execution mechanisms:

| mechanism | where | property | fit for the harness |
|---|---|---|---|
| `_forward_pass_timeout` (SIGALRM) | `wrapper.py:111` | preemptive, in-process, float-budget-safe (rounds up); **documented limitation: cannot interrupt a stuck native call** | **CHOSEN**, per operation: for `training_probe` at the NATIVE 180 s (production's exact seam, `wrapper.py:591` — the harness preserves, never relaxes, the preemptive semantics); for `candidate_probe`/`full_search` only as the EMERGENCY backstop (240 s / 840 s) beyond the post-hoc production checks |
| post-hoc elapsed checks | `batch_resolver.py:157,:201` | zero interference with the measured call | **CHOSEN** for the run WALL (checked between measurements) |
| `run_isolated_preflight` subprocess kill | `isolated_probe.py:438` | a real kill that stops stuck native calls — but it runs a whole pre-flight, and worker spawn + torch import overhead would pollute per-operation timings; the worker does not emit per-operation success timings | **REJECTED** for per-point use, for exactly the reason the operator flagged: the measured operation would no longer be the production operation |
| external `timeout(1)` on the whole study process | invocation wrapper | kills anything, including stuck native calls | **CHOSEN** as the outer backstop only |

**Honest residual, stated per the operator's instruction:** if a native
call ignores SIGALRM, the harness CANNOT kill that call without changing
what is measured. In that case the study run itself hangs, the external
backstop (or the operator) kills the process, the append-per-point
`measurements` file retains everything completed, and the in-flight point
is recorded `harness_deadline` on restart (its absence from the file +
the run log identify it). This is the same limitation production accepts
and documents in `probe_budgets.py`; the harness does not pretend to a
stronger property.

### 0.H Artifact location — RESOLVED (Q-F-3, operator 2026-08-09)

`reports/v21_pr_f_inspection_cost/` — `measurements_pilot.json`,
`measurements.json`, `report.md`, committed; production reads none of it;
existing `reports/` study precedent.

---

## 1. Objective

> **Measure the curve `model scale → per-operation inspection cost` for
> the two labelled populations against the ENFORCED budgets, classify
> every point CLEAR / WOULD_BE_CENSORED / INDETERMINATE under the frozen
> reconciliation rule, and write the recommendation — changing nothing.**

## 2. Non-goals

```text
NO  budget change of any kind (120->300 explicitly forbidden)
NO  fixing findings F-A1/F-A2 (the inert budgets) — filed as FU-F-1
NO  production code change at all, incl. success-side timing telemetry
NO  prompt/advice change
NO  GPU use; no LLM calls; no scientific records produced
NO  new persistent artifact kind (reports/ precedent, Q-F-3)
NO  pooling the two populations in any statistic
NO  segment-size sweep axis (deliberate scope bound, §0.D)
NO  funnel-distribution claims (§E.3d.6; the P6.3 overlay uses recorded
    values only)
NO  planner exposure of any study result
```

> **Template clauses deliberately not applicable** (recorded): the
> ordering/`shuffle` clauses belong to a data-ordering feature; PR F's
> analogous determinism obligation is the MANIFEST, pinned in F1. §6's
> `file_order`/scope cases are replaced by the harness's real failure
> cases (§0.F's disposition set + manifest drift + wall expiry).

## 3. Study contract

As §0.C-§0.G. One addition: `measurements*.json` rows are append-per-point
(a wall expiry or kill loses nothing already measured), schema-validated
on write AND on read-back by the report generator.

## 4. Commit plan

| # | Commit | Blocked on | Independently reviewable |
|---|---|---|---|
| **F0** | Audit + design (this document, rev 2) | — | Yes (docs only) |
| **F1** | Harness + manifest + determinism/censoring pins | Q-F-1/Q-F-2 approval | Yes |
| **F2a** | Pilot (12 entries, ramped, 30-min wall) + projection | F1 | Yes |
| **F2b** | Full sweep + curve + classification + recommendation | F2a GO (< ~1 h projection) or operator subset | Yes |

---

### Commit F1 — Harness, manifest, and the pins that keep them honest

#### 1. Goal

Build the wall-bounded, append-per-point measurement harness driving the
REAL production functions under the REAL frozen budgets, with the
manifest, dispositions and classification rule pinned before any real
number exists.

**Why this commit and not another.** Same as D1/E1: evidence from an
unpinned harness cannot be told apart from evidence from a subtly
different one — and here the classification RULE is part of the
methodology, so it must be frozen (and tested) before data can tempt
anyone to bend it.

#### 2. Scope

**Changes**

```text
scripts/inspection_cost_study/manifest.py    entries, ladder, hashing
scripts/inspection_cost_study/harness.py     timing, walls, dispositions
scripts/inspection_cost_study/schemas.py     SweepEntry (incl.
                                             architecture_family) /
                                             OperationPoint / Measurement
                                             (the §0.F envelope with
                                             preserved native records) /
                                             PointVerdict (Pydantic, per
                                             CLAUDE.md)
scripts/inspection_cost_study/classify.py    the frozen §0.F rule
tests/unit/scripts/test_inspection_cost_study*.py
```

**Must remain unchanged**
- **Every production file** — `probe_budgets.py`, `batch_resolver.py`,
  `structural_probe.py`, `wrapper.py`, all registries, all prompts. A
  diff in any is a finding, not a task.
- The harness reads the real `ProbeBudgets()` defaults; modified budgets
  appear only inside its own unit tests.

**Non-goals** — running any real sweep (F2a/F2b); any statistic beyond
§0.F's summaries.

**Dependencies:** Q-F-1 and Q-F-2 approval of this revision.

#### 3. Implementation plan

- [ ] Re-read `batch_resolver.py:100-260`, `structural_probe.py:225+`,
      `wrapper.py:111,:580-660` immediately before writing; confirm
      signatures, the candidate tuple import, and `_forward_pass_timeout`'s
      import path
- [ ] Manifest: population A via the REAL plugin loader (loadability
      authority; failures recorded `unloadable`, never skipped);
      population B from §0.C's per-architecture ladders, instantiation-
      checked, `invalid_config` recorded; every entry carries population
      label, exact config, both O-E-6 parameter counts
- [ ] Manifest determinism: content hash; seeded ordering; no wall-clock
      or unseeded randomness anywhere in manifest generation
- [ ] Harness — PER-OPERATION invocation seams (§0.E/§0.F; the
      operator's reconciliation 1, do not unify):
      `candidate_probe`: REAL `probe_activation_footprint` under a 240 s
      emergency backstop (`_forward_pass_timeout`); exact elapsed kept,
      including exact over-120 observations.
      `full_search`: REAL `resolve_inference_batch` with its NATIVE
      semantics untouched; `BatchSearchTimeout` caught and its
      `ProbeTimeoutRecord` preserved VERBATIM on the measurement
      (`execution_outcome=native_timeout`); 840 s outer backstop only.
      `training_probe`: REAL `probe_activation_footprint(mode="training")`
      under production's OWN
      `_forward_pass_timeout(ProbeBudgets().single_probe_seconds)` —
      exactly the `wrapper.py:591` seam; a fired 180 s alarm records
      `native_timeout`, lower bound 180. **NO 2× relaxation for this
      operation** — bypassing the native preemptive bound would measure
      something production never runs
- [ ] Walls: `--max-wall-seconds` checked between measurements; clean
      stop with a wall-expiry marker in the file
- [ ] Append-per-point writes; overwrite of an existing file refused
      loudly
- [ ] `classify.py`: the frozen §0.F reconciliation rule, pure function
      over raw measurements — the report may only call it, never inline
      its own
- [ ] Unit fixtures: tiny CPU models only (sub-second); the real
      populations are F2's business

#### 4. Validation plan

**Unit**
- [ ] Manifest bit-identical across two generations (hash equality)
- [ ] Population labels present on every entry; a pooled-statistics
      helper does not exist (the report tests assert per-population
      grouping)
- [ ] Ladder configs instantiation-checked; an invalid config yields
      `invalid_config` with the constructor error
- [ ] §0.F classification rule: parametrized truth table —
      all-under → CLEAR; all-over → WOULD_BE_CENSORED; exact-over
      (post-hoc completed OR a native `BatchSearchTimeout` record's exact
      elapsed) counts as over WITH exact time; native training-probe
      timeout counts as over-CENSORED at bound 180; harness backstop
      counts as over-censored at its backstop value and is DISTINCT from
      native_timeout; straddle → INDETERMINATE; any deadline →
      INDETERMINATE; union-of-reruns can only move toward INDETERMINATE
- [ ] Envelope preservation: a `native_timeout(full_search)` measurement
      carries the native `ProbeTimeoutRecord` verbatim (`model_dump`
      round-trips), and the report can name which native operation
      (`batch_candidate` vs `batch_search`) refused
- [ ] Summaries exclude censored repeats from median/min/max and carry
      `n_completed/n_censored/n_deadline`

**Integration / pseudo**
- [ ] End-to-end over ≤3 fixture models: valid append-per-point file;
      same-seed re-run → identical manifest hash and dispositions
- [ ] Wall expiry mid-run: file retains completed points + expiry marker

**Negative / invalid input**
- [ ] A fixture with a deliberately tiny backstop produces
      `harness_backstop` with `lower_bound_seconds = backstop` and **no
      elapsed value**; the record reuses `ProbeTimeoutRecord` fields and
      `is_capacity_evidence is False`
- [ ] Overwrite refusal

**Backward-compatibility / default parity**
- [ ] Zero production diff (commit-boundary `git diff --name-only`)
- [ ] The harness's reported "current budgets" equal the production
      `ProbeBudgets()` defaults — budget drift is visible

**Real-training Gate:** none — CPU-only by design.

#### 5. Acceptance criteria

- Manifest hash identical across two generations and embedded in every
  measurements file.
- An AST/identity test proves the harness calls the REAL
  `probe_activation_footprint` / `resolve_inference_batch` /
  `_forward_pass_timeout` imports — not reimplementations (§E.3d.9;
  B1b-P2/M-D3 lesson).
- The §0.F truth table passes, including the exact-over-vs-censored
  distinction and the reruns-only-toward-INDETERMINATE property.
- A censored fixture point carries a lower bound and no exact time; a
  post-hoc-overrun fixture point carries an exact time and classifies
  `over`.
- A fixture driving the training-probe seam with a deliberately slow
  model is interrupted at the NATIVE 180 s path (unit-tested with a
  reduced `ProbeBudgets` instance in the harness's own tests), recording
  `native_timeout` — proving the harness preserves, not relaxes, the
  preemptive production semantics.
- A fixture `BatchSearchTimeout` is preserved verbatim as
  `native_timeout` with its typed record — never collapsed into
  `completed` or a generic harness censoring event.
- `git diff` for this commit: `scripts/inspection_cost_study/` + tests +
  this document only.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Plugin fails to load | `unloadable` + loader error; sweep continues; report must count them (loadability bias stated) |
| Ladder config invalid | `invalid_config` + constructor error; excluded from timing; counted |
| Post-hoc overrun (elapsed ≥ budget, call completed) | EXACT time kept; classifies `over`; never written as censored |
| Native `BatchSearchTimeout` during `full_search` | `native_timeout`, typed record verbatim; never `completed`, never a generic harness event |
| Native 180 s training-probe alarm | `native_timeout`, lower bound 180 — the production behaviour under study, preserved |
| Harness backstop fires (240 s / 840 s) | `harness_backstop`, lower bound only — distinct from `native_timeout` by construction |
| Stuck native call (SIGALRM ignored) | run hangs → external backstop kills; file intact; point recorded `harness_deadline` on restart (§0.G residual, stated) |
| Wall expires | clean stop, marker written, everything measured retained |
| Manifest drift between pilot and full | full run REFUSES to start on hash mismatch for shared entries |
| Existing measurements file | overwrite refused loudly |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/scripts/test_inspection_cost_study*.py -q
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright
```

- [ ] Unit counts / wall time — **to record**
- [ ] Mutations — **to record**, at minimum: harness reimplements a probe
      → fail; censored point written with an exact elapsed → fail;
      exact-over point written as censored → fail; **training probe
      wrapped at 2×360 instead of the native 180 → fail**; **native
      `BatchSearchTimeout` collapsed into `completed` or into a generic
      harness event → fail**; classification rule inlined in the report
      instead of calling `classify.py` → fail; unseeded manifest ordering
      → fail; pooled-population statistic → fail
- [ ] Full checker set at the final head (§E.3d.12) — **to record**

#### 8. Commit boundary

- [ ] `scripts/inspection_cost_study/` + tests + this document only;
      zero production files
- [ ] No budget value in the diff except read from production
- [ ] Diff summary, staged files, tests, deviations recorded here before
      committing

---

### Commit F2a — Ramped pilot and projection

#### 1. Goal

First real measurements on 12 entries spanning both populations and the
size range, under a 30-minute wall — and the runtime projection that
gates F2b.

#### 2. Scope

**Changes:** `reports/v21_pr_f_inspection_cost/measurements_pilot.json`;
this document (pilot numbers + projection). **Must remain unchanged:**
everything else; the harness is frozen once pilot data exists (a harness
change after data restarts F2a). **Dependencies:** F1.

#### 3. Implementation plan

- [ ] Pilot manifest: smallest + largest entries by declared scale FIRST
      (the ramp), then ~6 spanning P6.3's recorded values (population A)
      and ~4 reference entries incl. fcnet at `latent_dims=[4000,400,40]`
      and one deep dilated architecture (the incident class)
- [ ] Ramp rule: if the 2 extreme entries consume > 600 s combined, STOP
      and report before the remaining 10
- [ ] Run with R=3 on an otherwise-idle host; loadavg per point;
      wall = 1 800 s
- [ ] Projection: per-operation-point cost distribution → full-sweep
      projection with the method stated; GO iff projected < ~1 h

#### 4. Validation plan

- [ ] **Integration:** one same-seed pilot re-run — identical manifest
      hash; classification of every point identical or moved only to
      INDETERMINATE (the §0.F property, exercised on real data)
- [ ] **Negative:** any censored/deadline point re-checked against §0.F
      recording rules before analysis
- [ ] **Parity:** zero production diff, zero test diff

**Real-training Gate:** none.

#### 5. Acceptance criteria

- Pilot file committed, schema-valid, hash recorded, wall respected.
- Projection states method, number, and GO/STOP against ~1 h.
- If STOP: proposed subset + its projection stated; F2b does not start.

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Ramp trips (extremes > 600 s) | STOP, report the two entries' data |
| Projection > ~1 h | STOP, present projection + subset (Q-F-1 path) |
| Dispersion re-classifies a point on re-run | Only toward INDETERMINATE — anything else is a harness bug, stop and audit |
| A pilot point censors | Legitimate data — that IS the phenomenon; kept per §0.F |

#### 7. Verification commands and evidence

- [ ] Pilot counts, dispositions, wall time — **to record**
- [ ] Re-run reconciliation result — **to record**
- [ ] Projection + GO/STOP — **to record**

#### 8. Commit boundary

- [ ] Evidence + this document only; no harness edit after data exists
- [ ] Diff summary + deviations recorded before committing

---

### Commit F2b — Full sweep, curve, classification, recommendation

#### 1. Goal

The deliverable: per-operation curves for both populations separately,
every point classified under the frozen rule, the P6.3 overlay, findings
F-A1/F-A2 restated, and the recommendation — changing nothing.

#### 2. Scope

**Changes:** `reports/v21_pr_f_inspection_cost/measurements.json` +
`report.md`; this document; the ledger's PR F delivered block.
**Must remain unchanged:** every production file; the harness; the
budgets. **Dependencies:** F2a GO or operator-approved subset.

#### 3. Implementation plan

- [ ] Full (or approved-subset) manifest, R=3, wall from the projection
- [ ] Report, per operation and per population (never pooled, never
      collapsed across operations): cost vs trainable params, cost vs
      total params, cost vs batch — every entry and figure carrying its
      `architecture_family`
- [ ] **Interpretation boundary (operator rule, frozen):** the pointwise
      censoring question is answered directly; scatter across
      heterogeneous architectures may be PLOTTED, but **no pooled
      cross-architecture regression/slope is fitted or interpreted as
      "parameter count causes cost to scale as X"**. Any recommendation
      attributing cost growth to model size must cite
      within-architecture ladder evidence (population B's per-family
      ladders) or otherwise clearly controlled comparisons
- [ ] Classification table: every point CLEAR / WOULD_BE_CENSORED /
      INDETERMINATE against `single_candidate_seconds`,
      `batch_search_seconds`, `single_probe_seconds`; margins in seconds
- [ ] P6.3 overlay from ledger-recorded values only
- [ ] Findings section: F-A1/F-A2 (the inert budgets) + the 900-vs-1200
      contradiction, restated as FU-F-1 for a future PR
- [ ] Recommendation: which of {adaptive, cheaper analytic pre-flight,
      staged inspection, size-aware, no change} the curves support — a
      recommendation for a separate PR, never a change here
- [ ] Ledger delivered block; Gate status unchanged

#### 4. Validation plan

- [ ] **Integration:** seeded 10 % sample re-run — manifest hash equal;
      classifications identical or toward INDETERMINATE only (full
      double-run rejected as cost without information; recorded)
- [ ] **Negative:** unloadable + invalid_config counts in the report; if
      > 0, loadability bias stated
- [ ] **Parity:** the PR-wide freeze — `git diff base..HEAD` excluding
      `scripts/inspection_cost_study/`, `tests/`, `reports/`, `docs/` is
      EMPTY

**Real-training Gate:** none.

#### 5. Acceptance criteria

- Disposition accounting closes exactly **over the APPROVED COMPLETED
  manifest (or operator-approved subset)**:
  `completed + native_timeout + harness_backstop + harness_deadline +
  unloadable + invalid_config = approved manifest measurements`.
- **Wall expiry is a clean interruption, NOT successful F2b completion**
  (operator rule, frozen): if the wall fires before the approved
  manifest/subset completes — persist everything, record exact coverage,
  STOP; **PR F is NOT complete**. It resumes under a freshly projected
  wall, or the operator explicitly approves the completed subset as the
  formal F2b population. The study population is never silently
  redefined because runtime exceeded the projection.
- Every classification row shows its per-repeat dispositions and margin;
  INDETERMINATE rows say why (straddle vs deadline).
- The recommendation cites specific curve regions per population; any
  size-causation claim cites within-architecture ladders only; no pooled
  cross-architecture slope appears anywhere in the report. The report's
  final line restates: **no budget was changed; a change is a separate PR
  justified by this data.**

#### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Flat curve, nothing censored | Legitimate outcome — recommendation "no change"; never enlarge models to force an effect |
| Boundary cluster | INDETERMINATE class reported as such; escalating repeats requires a fresh runtime projection |
| Degenerate plugin config (0 params) | Measured as-is (E3's finding: 0 is a real measurement) |
| Wall fires mid-full-sweep | Clean interruption, NOT completion: everything measured retained, exact coverage recorded, STOP — F2b (and PR F) remain incomplete until the approved manifest finishes under a fresh projected wall, or the operator explicitly re-approves the completed subset as the formal population |

#### 7. Verification commands and evidence

- [ ] Full counts, dispositions, wall time — **to record**
- [ ] Sample re-run reconciliation — **to record**
- [ ] PR-wide freeze proof (empty non-allowlisted diff) — **to record**
- [ ] Full suite + ruff + format + pyright at the final head — **to
      record** (§E.3d.12)

#### 8. Commit boundary

- [ ] Evidence + report + docs only; no recommendation implemented
- [ ] Diff summary + deviations recorded before committing

---

## 5. Acceptance and merge criteria (PR level)

1. Zero production diff across the PR (allowlist-shaped empty diff).
2. Harness drives the real functions under the real frozen budgets —
   proved structurally and by mutation.
3. Manifest deterministic; raw dispositions preserved; censored bounds
   never mixed into exact-timing statistics; classifications
   verdict-stable under the frozen §0.F rule.
4. The disposition arithmetic closes over the APPROVED COMPLETED
   manifest/subset; a wall-interrupted partial run never counts as
   completion (F2b §5).
5. Per-operation, per-population analysis; the two populations never
   pooled; the two INERT budgets reported as findings, not measured
   against.
6. A written recommendation that changes nothing; FU-F-1 filed.
7. Full checker set green at the final head (§E.3d.12).

### V21 review fields

```text
Metric-frozen proof:      trivially — zero production diff, proved by the
                          empty non-allowlisted diff at merge
Name-keyed dependency
added:                    none — model identities are labels in evidence
                          files; nothing keys behaviour on them
Transport contract:       none added — no schema field, no hop
Subprocess evidence:      the harness measures the in-process functions the
                          budgets bound, using production's own SIGALRM
                          primitive for its 2x bound; the 900 s worker
                          subprocess deadline is recorded as OUTER context,
                          and worker spawn overhead is excluded by
                          construction (the worker path is not used per
                          point — §0.G)
Acceptance evidence:      deterministic manifest + §0.F semantics +
                          wall-bounded execution; no Gate — CPU-only
```

---

## Operator decisions

### Q-F-3 — RESOLVED (operator, 2026-08-09)

`reports/v21_pr_f_inspection_cost/` as written. Production reads none of
it.

### Q-F-2 — censoring and reproducibility semantics (FINAL FORM — awaiting approval)

Freeze §0.F verbatim, now per-operation and grounded in the audited
payloads:

- execution outcomes `completed / native_timeout / harness_backstop /
  harness_deadline / unloadable / invalid_config`, with
  `native_timeout` preserving production's typed evidence VERBATIM
  (`BatchSearchTimeout.record` = `ProbeTimeoutRecord`, exact elapsed for
  the post-hoc operations; the native 180 s `ForwardPassTimeoutError`
  right-censors the training probe at ITS OWN bound — no 2× relaxation);
- summaries over exact `completed` values only, native-timeout exact
  values summarised separately per native operation, censored bounds
  never mixed in, all `n_*` counts explicit;
- point classification CLEAR / WOULD_BE_CENSORED / INDETERMINATE via
  under / over-exact / over-censored and the straddle rule; re-runs move
  points only toward INDETERMINATE;
- no second vocabulary anywhere.

### Q-F-1 — RESOLVED (operator, 2026-08-09): APPROVED

Populations, cardinality, wall-bounded execution and the pilot gate as
§0.C-§0.E, **plus the timing-blind grid rule** (§0.C) and the
wall-expiry-is-not-completion rule (F2b §5).

---

**Nothing in this document is implemented.** On approval of Q-F-1/Q-F-2
as revised, the sequence is F1 → F2a → (gate) → F2b. Findings F-A1/F-A2
and FU-F-1 are recorded for a future PR and are untouched here.
