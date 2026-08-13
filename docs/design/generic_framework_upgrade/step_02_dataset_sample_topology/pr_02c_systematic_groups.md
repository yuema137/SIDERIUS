# PR 02c — Task-owned file-set semantics (Step 02, child 3 of 3 + FINALIZER)

> **Renamed in revision 3.** Was *"Systematic group semantics"*. The old
> title encoded the refuted premise that three literals were one
> frequency-band group. Rename impact is assessed in §16.

## Status

**DESIGN — READY FOR OPERATOR FREEZE (revision 3, 2026-08-13).
NOT YET FROZEN. IMPLEMENTATION NOT AUTHORIZED.**

All operator decisions are recorded and FINAL (§21). The final narrow
genericity re-review (§20) produced **two corrections**, both applied:
the effective-config injection shape (§8.1) and the falsy-hazard
reclassification (§4.3). No new material contradiction remains.

Revision 3 was rewritten against **merged 02a + 02b source**. Six
load-bearing revision-2 claims were refuted by source audit (§0.2). The
capability is reframed, and the one-PR decision was re-run from scratch
because its original rationale no longer holds (§5).

Parent: [`../step_02_dataset_sample_topology.md`](../step_02_dataset_sample_topology.md)
(LIVE governance). Predecessors: merged 02a and 02b ledgers (immutable).

02c carries **two distinct responsibilities**, kept separate throughout:

```text
CHILD capability : task-owned file-set semantics (§1-§12)
FINALIZER duty   : assembled Step-02 reconciliation, ONE Gate 2,
                   ONE local full suite, Checkpoint E (§13-§17)
```

---

## 0. Repository truth and the historical correction

### 0.1 Verified state

| Fact | Value |
|---|---|
| PR 02a | **MERGED** — PR #202, merge `47359538`, verified ancestor of `origin/master` |
| PR 02b | PR **#203**, operator-approved, head `6fcbcdd2`, merge pending exact-head CI |
| Audit basis | the PR-02b branch tree (= `master` + 02b) — the state 02c actually starts from |

### 0.2 Revision-2 claims REFUTED (preserved, not rewritten away)

```text
Previous assumption (rev 2 §1):
  [0,10,19], [3,10,17] and range(20) are one concept —
  "named group declarations (the frequency bands)".

Audit evidence:
  three different semantics, different owners, different consumers,
  different resolution rules, and TWO different resolver
  implementations. Details in §2-§4.

Corrected understanding:
  02c is not "move the literals into config". It is three DIFFERENT
  correct actions:
      [0,10,19]  -> DECLARE
      [3,10,17]  -> DECLARE
      range(20)  -> DERIVE

Implementation consequence:
  a single "group map" replacing all four sites would change behaviour
  in at least two places, and would duplicate 02a's topology authority.
```

| # | Revision-2 claim | Source verdict |
|---|---|---|
| R1 | `[3,10,17]` is "the health gates'" peek list | **PARTLY FALSE.** Only the **three BLOCKING** gates carry `peek_file_indices`. The **three RECORDING** gates ship no such key and currently evaluate **all 20 files** (§4) |
| R2 | the three `_DEFAULT_FILE_RANGE` sites are one shared fallback | **FALSE.** Two different resolvers with different tier-2 and tier-3 semantics (§4.2) |
| R3 | "the anchors artifact and `segment_anchors.json`" belongs under *Anchors identity* | **CONFLATION.** `ANCHOR_FILES` is a 3-file selection subset; `segment_anchors.json` is a 20×200 SNR normalization table. Mechanically unrelated (§3.3) |
| R4 | full-file fallback equivalence is MISSING → capture first | **FALSE — it already EXISTS** (`test_health_scope.py:241-251`). Capturing again would duplicate an oracle |
| R5 | campaign validation "accepts/rejects the same records as today" | **TOO BROAD, and the branch is UNTESTED** — no existing test enters the if-branch (§6) |
| R6 | `validate_health_gate_files_against_scope` | **SYMBOL DOES NOT EXIST.** Real name `validate_health_scope` (`config.py:319`). Corrected in the 02b ledger before merge |

---

## 1. Capability and final effect

> **A task declares its own anchor-selection and health-peek file sets on
> the bound Dataset Profile, and the consumers that today branch on
> hardcoded triplets resolve them from that declaration — while all-files
> populations derive from the profile's topology instead of a literal
> `20`, and every existing TIDMAD selection, HealthGate verdict and
> campaign-validation outcome stays identical.**

Three explicit classifications, never merged into one mapping:

```text
A. DECLARED ANCHOR-SELECTION FILE SET   [0,10,19]  -> declare
B. DECLARED HEALTH-PEEK FILE SET        [3,10,17]  -> declare
C. TOPOLOGY-DERIVED ALL-FILES           range(20)  -> derive from
                                                      profile.num_files
```

**Deliberately NOT claimed**: that a fully generic non-TIDMAD campaign
runs end-to-end. Step-08 and Step-10 residue (§7) remains outside 02c.

---

## 2. Classification — the three semantics

### 2.1 A — `ANCHOR_FILES = [0,10,19]` → **DECLARED** (operator decision Q1, 2026-08-13)

`execute_tools/sample_set_builder.py:29`, comment *"low, mid, high
frequency extrema"*.

**Operator decision**: this is a **DECLARED ANCHOR-SELECTION FILE SET**.
It is **NOT** derived as `[0, n//2, n-1]`.

Rationale recorded verbatim from the decision: the shipped TIDMAD value
happens to equal that expression at `n=20`, and the "extrema" comment is
evidence of *intent* — but neither is a sufficient contract for
**inventing new non-TIDMAD behaviour**. Auto-deriving a formula would
create generic behaviour no source establishes.

Frozen consequences:
- TIDMAD anchor selection remains exactly `[0, 10, 19]`;
- the `anchors` strategy identity is unchanged;
- no sampling-algorithm change;
- the declaration becomes the authority;
- a future non-TIDMAD task explicitly declares its own anchor subset.

**Do NOT call this a frequency band.**

### 2.2 B — `[3,10,17]` → **DECLARED HEALTH-PEEK FILE SET**

`configs/health_checks.yaml:35,60,82`, mirrored as a policy trigger at
`core/campaign_artifacts.py:57`.

Evidence it is declared, not derivable: the YAML calls it a *"low/mid/high
frequency-band triplet"* — **interior** representatives, not extrema; no
natural arithmetic on `num_files` yields it; and it already lives in
config, i.e. it is already declared data. What is missing is that a second
consumer hardcodes a **copy**.

### 2.3 C — `range(20)` ×3 → **DERIVED TOPOLOGY. Not a group.**

`_DEFAULT_FILE_RANGE: range = range(20)` at `pearson_dispersion.py:34`,
`per_file_output_std.py:30`, `spectral_peak_ratio.py:39`.

Evidence: its only meaning is "every file"; the authority already exists
(`dataset_config.py:320 num_files=20`); the sibling validator in the same
subsystem already derives it (`config.py:333`); and
`pearson_dispersion.py:34`'s own comment says `# TIDMAD NUM_FILES`.

**Therefore**: becomes `range(profile.dataset.num_files)`. **Do NOT add
`all_files = [...]` or any equivalent profile field** — that would
duplicate 02a's topology authority (§12 stop condition).

### 2.4 The governing principle (operator, FINAL 2026-08-13)

> **Genericization is not moving legacy hardcodes into config.**
>
> Each semantic must resolve from its **correct authority**:
>
> ```text
> declare  task-owned semantics      (A, B)
> derive   topology-owned semantics  (C)
> preserve runtime/policy-owned semantics  (DataScope,
>          health_gate_files, HealthGate policy — untouched)
> ```

A catch-all "group map" is forbidden merely because the legacy
implementation happens to contain several file-list literals. A/B/C are
**not** forced into one abstraction unless implementation-time source
evidence truly requires one.

---

## 3. Consumer census — anchors

| Fact | Evidence |
|---|---|
| Production readers of `ANCHOR_FILES` | exactly **one**: `sample_set_builder.py:105` |
| Reachability | **production-reachable AND LLM-selectable** — LLM plan (`prompts.py:128,1264`; `ExperimentPlan.trial_strategy` `Literal[...]` at `hyperparam_tuning.py:822`, no normalization in `parse_with_fallback`); `--formal_strategy anchors` (`ml_hyperparameter_tune_agent.py:6453-6458`); `plan_overrides` |
| Guard | rejected under partial DataScope (`sample_set_builder.py:96`); tuner normalizes partial-scope plans to `snapshot` (`:4241-4254`). Under FULL scope nothing normalizes it |
| Existing oracle | `GOLDEN["anchors"] = "e025a270e0b1acc1"` (`test_sample_set_builder.py:243`), `seed=42, portion=0.05` |
| **Uncoupled duplicate** | `test_formal_sample_set.py:212` hardcodes `{0, 10, 19}` instead of importing `ANCHOR_FILES` — will NOT follow a declaration change; 02c must update it |

### 3.3 `segment_anchors.json` is a DIFFERENT concept — terminology correction

| | `ANCHOR_FILES` | `segment_anchors.json["anchors"]` |
|---|---|---|
| What | 3-file **selection** subset | 20×200 per-segment **SNR normalization table** |
| Produced by | literal in `sample_set_builder.py` | `execute_tools/build_anchor_map.py:57-105` |
| Consumed by | `build_sample_set` anchors branch | `load_anchor_map` → scorer, tuner, sandbox |
| Coupling | **none** — `build_anchor_map.py` never imports `sample_set_builder` |

Binding consequences:
- do **NOT** claim they share one semantic authority;
- do **NOT** use `segment_anchors.json` parity as evidence that the
  `ANCHOR_FILES` migration is correct — the correct oracle is
  `GOLDEN["anchors"]`;
- `segment_anchors.json` stays **untouched** as an out-of-scope artifact
  invariant (`test_step00_numeric_baselines.py:63-66`).

---

## 4. Consumer census — the six-gate fallback matrix

**Mechanically enumerated and independently re-verified.** This replaces
revision 2's single "health gates" row.

### 4.1 Per-gate

| Gate | Role | `peek_file_indices` shipped | Resolver | Primary population |
|---|---|---|---|---|
| `output_diversity_blocking` | blocking | `[3,10,17]` (`:35`) | `_multi_file_peek._resolve_indices` | **declared health-peek (B)** |
| `output_std_blocking` | blocking | `[3,10,17]` (`:60`) | same | **declared health-peek (B)** |
| `amplitude_collapse_blocking` | blocking | `[3,10,17]` (`:82`) | same | **declared health-peek (B)** |
| `pearson_dispersion_recording` | observational | **absent** | own `_resolve_files` | **topology-derived all-files (C)** |
| `spectral_peak_ratio_recording` | observational | **absent** | own `_resolve_files` | **topology-derived all-files (C)** |
| `per_file_output_std_recording` | observational | **absent** | own `_resolve_files` | **topology-derived all-files (C)** |

### 4.2 Tier semantics — the two resolvers differ

| Tier | BLOCKING (`_multi_file_peek.py:113-131`) | RECORDING (`_resolve_files`) |
|---|---|---|
| 1 — configured | dedupe **preserving input order** | `sorted({int(i) …})` — sorted, deduped, **int-coerced** |
| 2 — `denoised_paths` | **`[min(keys)]` — ONE file** | `sorted(keys)` — **all** |
| 3 — fallback | **`[0]`** | **`range(20)`** (guarded by `denoised_filename_fn`) |
| 4 | — | `[]` → "not applicable" |

The three recording modules are byte-identical to each other; the
divergence is **blocking vs recording**.

**02c changes ONLY the tier-1 authority source and the tier-3 VALUE for
recording (C).** It does **not** unify tier-2 semantics, tier ordering, or
the blocking `[0]` fallback. Homogenizing them is a **STOP — Step-08
policy** (§12).

### 4.3 Run-level override

`health_gate_files` → `build_run_invariants` (`core/run_invariants.py:325`)
→ `materialize_effective_config` (`config.py:377-385`) →
`apply_monitored_files` (`config.py:288-316`), which **replaces
`peek_file_indices` on every check**, creating the key on recording checks
via `setdefault`. It refuses an empty list (`config.py:293-297`).

So an explicit run-level override collapses all six onto tier 1 —
membership converges, **iteration order does not** (input-order vs
sorted). This precedence is **runtime-input semantics and is NOT 02c's**
(§7).

**Falsy-check hazard (all six)**: `if configured:` means an explicit
`peek_file_indices: []` does **not** mean "monitor nothing" — it falls
through to the next tier. `apply_monitored_files` refuses an empty list
(`config.py:293-297`), so this is reachable only via hand-edited YAML.

> **Reclassified by the §20 re-review (was "pin, do not fix").** This is
> the same class as the Q2 float residue: latent, reachable only through
> a hand-authored config that does not exist in the shipped path.
> Pinning it would freeze an unreachable behaviour into a compatibility
> promise — precisely what 02b §6.1 forbids and what §14 declines for
> Q2. Treating the two inconsistently was an error in the first draft of
> this revision.
>
> **Disposition: RECORD, do NOT pin, do NOT fix.** Same stop condition:
> if implementation proves it production-reachable, the classification
> has changed — STOP and report.

---

## 5. One-PR decision — RE-RUN from source

Revision 2's rationale ("one group concept") was refuted, so the split
test is re-run rather than inherited.

| Criterion | A — anchor selection | B — health peek |
|---|---|---|
| Independently useful | yes | yes |
| Production consumer | `sample_set_builder.py:105` (LLM-selectable) | 3 blocking checks + campaign validator |
| Parity oracle | `GOLDEN["anchors"]` sha16 | hc1 resolved-config golden |
| Failure class | wrong training file population | wrong files judged by gates / wrong campaign verdict |
| Checkpoint | Stage-B **C-anchor** | Stage-B **C-health** |
| Lifecycle / authority | task-level static file-set on the bound Dataset Profile | **same** |
| Rollback value | low independently — both are one-line authority swaps | low independently |

**VERDICT: KEEP ONE PR 02c.**

Justification from source, not from "the parent said three children":

- both are **task-level static file-set declarations consumed from the
  same Dataset Profile lifecycle** — identical authority and identical
  validation needs (integer, in-range against `num_files`, duplicates);
- they share one migration mechanism (literal → declaration) and one
  oracle style (exact-population parity under TIDMAD);
- splitting would produce two PRs whose diffs are each a handful of lines
  plus a full checkpoint ladder — evidence cost far exceeding review value;
- and 02c must remain the FINALIZER regardless, so a split would leave one
  child carrying aggregate duties for a capability it does not own.

**They remain SEPARATE fields/semantics internally.** One PR is not one
abstraction: there is no generic `groups` mapping (§8), and C-anchor /
C-health are independent contrast subcases (§11).

**Split trigger if implementation contradicts this**: if source shows the
two declarations need materially different lifecycles, validation or
ownership — e.g. if the health-peek declaration must live on a
HealthGate-owned model rather than the profile — **STOP and propose a
revised decomposition** rather than silently creating a child.

---

## 6. Consumer census — campaign-artifact validator

`validate_experiment_completeness` (`core/campaign_artifacts.py:35-66`).

- `requested` = `health_gate_results[i].aggregation.files_requested`,
  produced verbatim from `peek_file_indices` at
  `health_checks/evaluation.py:202` (the **fallback** arm at `:208` is
  int-normalized; the primary arm is **not**).
- `if requested == [3, 10, 17]:` gates a **per-file completeness check**.
- **Else-branch = silent skip.** Any non-triplet list gets *no*
  enforcement.
- **POLICY, not presentation**: errors →
  `ValidationReport(valid=not errors)` → `decide_phase1_reuse` returns
  `action="train"` (retrain instead of reuse); and
  `scripts/run_comparison.py:1407-1413` raises `RuntimeError`.
- **No normalization** — `[10,3,17]` takes the else-branch.
- Reachability: **campaign tooling only**; the tuner loop never imports it.
- **The if-branch has ZERO existing test coverage** — every test in
  `tests/unit/core/test_campaign_artifacts.py` uses `files_requested: []`.

### 6.1 The migration trap — stated so it cannot be walked into

```text
old:  requested == [3, 10, 17]
new:  requested == <the declared health-peek set>
```

**FORBIDDEN**: `set(requested) == set(declared)`, or any sorting /
de-duplication of `requested`. Today `[10,3,17]` **skips**; a set/sorted
comparison would newly **ENFORCE** it. That is a **policy change**
disguised as an authority change, and a §12 stop condition.

Any genuine policy improvement is Step-08 / separate work.

---

## 7. Ownership

**OWNS**: the two declarations (A, B) and their validation; the tier-1
authority of the blocking peeks; the campaign validator's trigger source;
the tier-3 value for recording checks (C); the anchors consumer.

**DOES NOT OWN**:

| Not owned | Why |
|---|---|
| Dataset Profile topology/geometry/encoding/channels | **merged 02a** — consume, never re-derive |
| SampleSet population semantics, selection algorithm, seeds, portions, packing | **merged 02b** — 02c changes how `anchors` OBTAINS its list, never the strategy |
| HealthGate thresholds, policy, verdicts, `gate_role`, `on_fail.action`, **fallback tier semantics** | **Step 08** |
| operator `DataScope`; run-level `health_gate_files` override precedence | runtime inputs — 02c changes DEFAULTS only |
| `validate_runtime_config(..., dataset=TIDMAD)` + tuner startup full-scope comparison | **Step 10** (02b §13.9). **Do not absorb merely because 02c touches health file selection** |
| `validate_health_scope`'s ambient-profile read | **Step 08** consumer-side (02b §13.9) |
| `segment_anchors.json` / `build_anchor_map.py` | unrelated artifact (§3.3) |
| `evaluation.py:202` int-normalization gap | producer-side; see Q2 disposition (§14) |

> **Explicitly NOT Step 06** — Step 06 is *metric*. The 02b §13.9
> correction applies unchanged.

---

## 8. Declaration model — semantics frozen, shape not

**Frozen (observable):**
- two **separate** declarations: anchor-selection set, health-peek set;
- each resolves against the bound Dataset Profile;
- validation: integer indices; in-range against
  `profile.dataset.num_files`; duplicate handling matching today's
  consumers (blocking dedupes preserving order; recording sorts+dedupes);
- empty-declaration behaviour stated explicitly given §4.2's falsy hazard;
- TIDMAD defaults resolve to exactly `[0,10,19]` and `[3,10,17]`;
- explicit runtime `health_gate_files` continues to override declared
  defaults, unchanged.

**NOT frozen (implementation-time):** field names, YAML nesting, Pydantic
decomposition, helper names, fixture placement, assertion mechanics, the
exact Checkpoint-C mechanism.

**Forbidden**: a generic `groups: dict[str, list[int]]` mapping unless
source proves one abstraction matches both declarations' semantics,
lifecycle **and** validation. Two named fields are the default.

### 8.1 The injection-shape trap — found by the §20 re-review

**This is the sharpest implementation hazard in 02c and it is not
obvious.**

Mechanical fact: `configs/health_checks.yaml` contains the
`peek_file_indices` key at **exactly three sites — `:35`, `:60`, `:82`,
all BLOCKING**. The three recording gates have **no key at all** and
therefore resolve to tier-3 all-files (C).

```text
TEMPTING BUT WRONG:
  "inject declaration B wherever peek_file_indices is absent"

CONSEQUENCE:
  the three RECORDING gates would jump from all-files (20)
  to the health-peek triplet (3).

  That is a HealthGate POLICY change — a §12.2 stop condition —
  introduced while nominally only moving an authority.
```

**Required shape**: declaration B must reach **only the sites that carry
the key today**. The absent-key path must continue to fall through to
tier 2/3 exactly as now.

Equally forbidden in the other direction: **removing** the literal from
the three blocking sites so they "fall back to the declaration" — the
absent-key tier is `[min(paths)]` / `[0]`, not the declaration, so that
would silently move blocking gates to a single-file peek.

Resulting precedence, which must be **unchanged** end to end:

```text
explicit run-level health_gate_files   (apply_monitored_files)
  > per-check peek_file_indices        (now resolved from declaration B)
  > tier 2  (blocking [min(paths)] | recording all keys)
  > tier 3  (blocking [0]           | recording all-files from C)
```

**Acceptance consequence**: C2 must assert the recording gates' resolved
population is **still `set(range(20))`** under TIDMAD — i.e. §9's C1 row
green and unmodified — as direct evidence the injection did not leak.

---

## 9. Compatibility contract — Stage A, per surface

Never as one "health behaviour unchanged" assertion.

| # | Surface | Criterion | Baseline |
|---|---|---|---|
| A1 | anchor selection identity | `GOLDEN["anchors"]` = `e025a270e0b1acc1` byte-identical | **EXISTS** |
| A2 | anchor population | resolves exactly `[0,10,19]` | **EXISTS** (`test_sample_set_builder.py:123`) |
| A3 | anchors strategy identity | unchanged; partial-scope rejection unchanged | EXISTS |
| B1 | blocking peek resolution | resolves exactly `[3,10,17]`; hc1 golden deep-equal | **EXISTS** |
| B2 | blocking tier-2/tier-3 | `[min(paths)]` / `[0]` unchanged | **EXISTS** (`test_multi_file_peek.py:53-98`) |
| C1 | recording full-file population | all three resolve to `set(range(20))` under TIDMAD | **EXISTS** (`test_health_scope.py:241-251`) — reuse, do NOT duplicate |
| C2 | recording tier-1 beats tier-2 | config wins over populated `denoised_paths` | **MISSING → capture (C1 commit)** |
| D1 | campaign exact-list matrix | §6 matrix preserved exactly | **MISSING → capture (C1 commit)** |
| E1 | `apply_monitored_files` override | all six checks receive the list; precedence unchanged | **EXISTS** (`test_health_scope.py:70-83`) |
| E2 | `validate_health_scope` | raises identically | EXISTS (`test_health_scope.py:113-135`) |
| F1 | HealthGate thresholds / verdicts / `gate_role` / `on_fail` | unchanged | EXISTS (per-check suites) |
| G1 | `segment_anchors.json` | untouched | **EXISTS** (`test_step00_numeric_baselines.py:63-66`) |
| G2 | SampleSet digests / sampling algorithm / seeds / portions | unchanged | EXISTS (02b) |
| G3 | DataScope + runtime override precedence | unchanged | EXISTS |

---

## 10. Blocking checkpoint ladder

```text
C1  capture the TWO genuinely missing baselines     (test-only)
  └─ CP0 — BASELINE COMPLETE          FAIL => stop

C2  the two declarations + first consumers          (production)
  └─ CP-C1 — DECLARATIONS LIVE + TIDMAD PARITY      FAIL => stop

C3  campaign trigger + profile-derived all-files    (production)
  └─ CHECKPOINT A — Stage-A parity complete         FAIL => stop

C4  4.8-C atomic contrast: C-anchor + C-health      (test-only)
  └─ CHECKPOINT B                                   FAIL => stop

assembled 02c executable head
  └─ PR-02c CHECKPOINT C — live production evidence FAIL => stop

C5  child docs + regression closeout                (docs)
  └─ PR-02c CHECKPOINT D

=== FINALIZER duties begin (§13) ===

assembled STEP-02 executable head
  └─ STEP-02 AGGREGATE CHECKPOINT-C RECONCILIATION
  └─ ONE terminal local full unit suite
  └─ ONE Step-02 Gate 2
C6  Step docs / status closeout
  └─ CHECKPOINT E -> exact-final-head CI
     -> STEP 02 READY FOR OPERATOR REVIEW
```

> **Naming discipline**: "PR-02c Checkpoint C" (child, §12) and "Step-02
> aggregate Checkpoint C" (finalizer, §13.1) are different gates. Never
> write bare "Checkpoint C".

---

## 11. Commit plan

| # | Commit | Kind |
|---|---|---|
| **C1** | capture the two missing baselines | test-only |
| **C2** | the two declarations + first consumers | production |
| **C3** | campaign trigger + profile-derived all-files | production |
| **C4** | 4.8-C atomic contrast (C-anchor, C-health) | test-only |
| **C5** | child docs + closeout | docs-only |
| **C6** | finalizer: aggregate, Gate 2, Checkpoint E | docs + evidence |

---

### 11.1 Commit C1 — capture the two missing baselines (test-only)

**1. Goal.** Pin the only two §9 surfaces with **no** existing oracle —
C2 (recording tier-1 precedence) and D1 (the campaign exact-list matrix)
— BEFORE any production change. Capture-after-edit proves nothing (S1-E
precedent; 02a C1; 02b B1).

Belongs here because C2/C3 change exactly these surfaces.

**2. Scope.**
Changes: `tests/unit/core/test_campaign_artifacts.py` (extend);
`tests/unit/execute_tools/health_checks/test_health_scope.py` (extend).
Unchanged: **ALL production code — zero production diff.**
Depends on: nothing.

**3. Implementation plan.**
- [ ] Re-read `campaign_artifacts.py:35-66` and the existing test module
      before writing.
- [ ] Pin D1-a: `files_requested == [3,10,17]` (ints) with **complete**
      `per_file` → **no** error.
- [ ] Pin D1-b: same, with a **missing** per-file entry → exactly
      `gate {id}: missing per-file entries [...]`, and `valid=False`.
- [ ] Pin D1-c: **reordered** `[10,3,17]` → **skips**; assert the
      per-file error is ABSENT. (This is the anti-normalization guard.)
- [ ] Pin D1-d: custom non-triplet list → **skips**.
- [ ] Pin D1-e: full-file list → **skips**.
- [ ] Pin D1-f: empty / absent `files_requested` → **skips**.
- [ ] Pin the `per_file` **str-key dependency** (`str(index) not in
      per_file`, `:59`) so a producer key-type change is caught.
- [ ] Pin C2: config `peek_file_indices` beats a populated
      `ctx.denoised_paths`, for **all three** recording checks (today only
      `PerFileOutputStd` has any tier-2 test).
- [ ] Record in the ledger that blocking and recording resolvers differ
      (§4.2) and that this is PRE-EXISTING, not 02c's to unify.
- [ ] **Do NOT** pin the float-element branch (§14 Q2 — latent
      unreachable; pinning it would repeat the mistake 02b's §6.1 rule
      exists to prevent).

**4. Validation plan.**
Unit: the new pins.
Integration/pseudo: none.
Negative/invalid: out-of-range indices; `aggregation` absent vs
present-but-empty; `metrics` absent. **Pin today's behaviour, whatever it
is.**
Backward-compat: n/a (no production change).
Gate: none.

**5. Acceptance criteria.**
- `git diff --stat` shows ZERO files outside `tests/`.
- The campaign if-branch is executed by **≥2** tests (today: zero).
- Each skip class asserts **ABSENCE** of the per-file error — a test that
  merely asserts `valid` would not catch a normalization regression.
- Recording tier-1-over-tier-2 asserted for **all three** modules.
- Each pin fails when its behaviour is perturbed (recorded mutation).
- **No duplicate** of any §9 EXISTS row — in particular the `range(20)`
  fallback is NOT re-pinned (R4).

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| a pin needs a production change | STOP — design finding, not a licence to edit |
| the float branch proves reachable | STOP and report — contradicts §14 Q2 |
| malformed `health_gate_results` raises `AttributeError` | pin today's behaviour; do NOT add a graceful path (policy change) |

**7. Verification commands and evidence.** Intended: `pytest
tests/unit/core/test_campaign_artifacts.py
tests/unit/execute_tools/health_checks/`. Record counts and wall time
after execution. Never claim an unrun test.

**8. Commit boundary.** Test-only, zero production diff. Before
committing: show diff summary, staged files, test output, deviations.

---

### 11.2 Commit C2 — the two declarations + first consumers (production)

**1. Goal.** Establish the two task-owned declarations (A, B) and migrate
their first consumers off the literals.

Separate from C3 because its failure class is *declaration/resolution*,
while C3's is *policy trigger* and *derived topology*.

**2. Scope.**
Changes: the two declarations (shape decided after re-reading
`DatasetProfile`); `sample_set_builder.py` anchors consumer; the
blocking-peek default source; `test_formal_sample_set.py:212`'s uncoupled
duplicate.
Unchanged: HealthGate thresholds/policy/verdicts/`gate_role`/`on_fail`;
**all fallback tier semantics**; `apply_monitored_files` precedence;
DataScope; selection algorithm/seeds/portions; `segment_anchors.json`.
Depends on: C1.

**3. Implementation plan.**
- [ ] Re-read merged `DatasetProfile` (`dataset_config.py:438+`) BEFORE
      choosing where the declarations live.
- [ ] Default: **extend 02a's profile** with two named fields. A separate
      authority requires written source evidence (§12 stop).
- [ ] Add validation: integer; in-range vs `num_files`; duplicate
      handling matching today's consumers; explicit empty-declaration
      behaviour.
- [ ] Migrate `ANCHOR_FILES` to declaration A.
- [ ] Migrate the blocking-peek default to declaration B, keeping the
      YAML as the operator-facing surface. **Follow §8.1 exactly**:
      declaration B reaches ONLY the three sites that carry
      `peek_file_indices` today (`:35,:60,:82`). Do NOT inject where the
      key is absent, and do NOT delete the key so it "falls back".
- [ ] Assert the recording gates still resolve to `set(range(20))` under
      TIDMAD (§9 row C1, unmodified) as direct evidence the injection did
      not leak into the keyless path.
- [ ] Update `test_formal_sample_set.py:212` (`{0, 10, 19}` hardcoded).
- [ ] Confirm no second topology authority is introduced.
- [ ] Confirm `range(20)` is NOT converted into a declared field (§2.3) —
      that is C3.

**4. Validation plan.**
Unit: A1/A2/A3 and B1/B2 green **unmodified**; declaration validation
(in-range, duplicate, empty).
Integration/pseudo: none required here.
Negative/invalid: out-of-range member; empty declaration; non-integer.
Backward-compat: every §9 EXISTS row green, unmodified.
Gate: none.

**5. Acceptance criteria.**
- Declaration A resolves to exactly `[0,10,19]`; B to exactly `[3,10,17]`
  under TIDMAD.
- `GOLDEN["anchors"]` and the hc1 golden byte-identical, asserted by
  running the existing modules **unmodified**.
- `segment_anchors.json` digest unchanged.
- **Two** declarations exist — not one merged mapping.
- No surviving literal at a C2-owned site (greppable).
- Mutation: change declaration A → anchors follow, blocking peeks
  UNCHANGED. Change B → peeks follow, anchors UNCHANGED. (This is what
  proves they are independent, and is exactly C4's structure.)

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| the profile cannot express a declaration | STOP and report before adding a second authority |
| a digest changes | **STOP** — experiment identity invalidated |
| the declaration would change a gate verdict | STOP — Step-08 semantics |
| a fallback tier changes | STOP — not 02c's |

**7. Verification commands and evidence.** Targeted + selection module +
health-checks package. Counts and wall time recorded here.

**8. Commit boundary.** Declarations + first consumers only. No campaign
change, no `range(20)` change, no rung.

---

### 11.3 Commit C3 — campaign trigger + profile-derived all-files (production)

**1. Goal.** Remove the last two literals: the campaign validator's
`[3,10,17]` trigger, and the recording checks' `range(20)`.

Separate from C2: the campaign change is a **policy-trigger** change
needing C1's matrix green across it; `range(20)` is **derived topology**,
a different classification entirely.

**2. Scope.**
Changes: `core/campaign_artifacts.py:57` trigger source;
`health_checks/{pearson_dispersion,per_file_output_std,spectral_peak_ratio}.py`
`_DEFAULT_FILE_RANGE`.
Unchanged: **campaign-validation POLICY**; the else-branch skip; exact-list
order-sensitive semantics; both resolvers' tier ordering; blocking
tier-2/tier-3.
Depends on: C1, C2.

**3. Implementation plan.**
- [ ] Re-read `campaign_artifacts.py:35-66` and `evaluation.py:202-208`
      before editing.
- [ ] Replace the literal with the declared health-peek set, **preserving
      exact-list equality**.
- [ ] **Do NOT normalize `requested`** — no `sorted`, no `set`, no
      `int()` (§6.1). D1-c is the guard.
- [ ] Replace `_DEFAULT_FILE_RANGE` with a **call-time** profile-derived
      population — never import-time (the 02b §13.9 default-argument
      lesson applies directly).
- [ ] Confirm recording tier ORDER is unchanged; only the tier-3 VALUE
      moves.
- [ ] Keep C1's pins green **unmodified**.

**4. Validation plan.**
Unit: C1's matrix green unmodified; C1 (§9) recording fallback still
`set(range(20))` under TIDMAD, `test_health_scope.py:241-251` unmodified.
Integration/pseudo: none required here.
Negative/invalid: reordered still skips; out-of-range still skips.
Backward-compat: all §9 EXISTS rows green.
Gate: none.

**5. Acceptance criteria.**
- For TIDMAD the validator accepts/rejects **exactly** the same records,
  demonstrated by C1's matrix passing unmodified.
- The recording fallback equals `range(profile.dataset.num_files)`, and
  equals `range(20)` under TIDMAD.
- No `20`, `[3,10,17]` or `range(20)` literal survives at a migrated site.
- Mutation: revert a site to its literal → the corresponding C1/C4 pin
  reds; make the trigger normalize order → **D1-c reds**.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| the migration would newly enforce on a previously-skipped list | **STOP** — policy change |
| profile resolved at import time | forbidden (02b §13.9) |
| a recording tier order changes | STOP — pre-existing |

**7. Verification commands and evidence.** Targeted + `tests/unit/core/`
+ health-checks package. Counts and wall time recorded here.

**8. Commit boundary.** Two consumers. No declaration change, no rung.

---

### 11.4 Commit C4 — 4.8-C atomic contrast (test-only)

**1. Goal.** Prove each consumer reads **its own** declaration.

**2. Scope.** Contrast fixtures under `tests/`. Zero production diff.
Depends on: C2, C3.

**3. Implementation plan.**
Topology stays **TIDMAD**. **Do NOT reuse 02b's `num_files` contrast** —
it re-answers another child's question and collides with the Step-10
residue that can block generic `num_files` runs under default HealthGate
settings.

Two subcases within the **one** 4.8-C rung:

- [ ] **C-anchor**: vary declaration A only; B held fixed → the anchors
      strategy follows A; **blocking peeks assert UNCHANGED**.
- [ ] **C-health**: vary declaration B only; A held fixed → blocking
      monitored-file selection follows B, and the campaign validator's
      trigger follows the same declared semantic **without any policy-matrix
      change**; **anchors assert UNCHANGED**;
      **recording gates assert UNCHANGED at all-files** (the §8.1 leak
      guard).
- [ ] **Vary CARDINALITY, not only membership** (§20 Q11). A contrast of
      `[0,10,19] → [1,5,9]` is still "three files" and could pass while a
      consumer silently assumes a triplet. Each subcase uses a set of a
      DIFFERENT SIZE (e.g. 2 or 5) so the rung varies the semantic rather
      than swapping one TIDMAD-shaped list for another. Source shows no
      consumer asserts cardinality (`sample_set_builder.py:105` copies the
      list; `_resolve_indices` dedupes; the campaign validator iterates),
      so a non-3 set is legal — if one proves otherwise, that is itself
      the finding.
- [ ] Assert atomicity **mechanically** against the TIDMAD declaration, as
      02a's and 02b's rungs do.
- [ ] Confirm each subcase reds when its consumer re-hardcodes its literal.

**All-files (C) is NOT a third declaration axis.** Its genericity follows
02a's topology authority and is tested as **derived reachability** (the
recording fallback tracks `profile.num_files`), not as a declaration
contrast.

**4. Validation plan.**
Unit: both subcases.
Negative/invalid: a declared set containing an out-of-range index.
Backward-compat: TIDMAD digests and goldens green.
Gate: none.

**5. Acceptance criteria.**
- Each subcase varies **exactly one** declaration, machine-checked.
- The **unvaried** consumer is asserted unchanged in each subcase — this
  is what proves independence and what a single combined fixture could
  not show.
- A consumer still holding its literal reds its subcase.
- Zero production diff.

**6. Failure and edge cases.**
| Case | Handling |
|---|---|
| a subcase needs both declarations to vary | STOP — the declaration model is wrong |
| it passes with a literal still present | strengthen it (02a M9 / 02b M10 lesson) |

**7. Verification commands and evidence.** Targeted + selection + health
+ core. Counts and wall time recorded here.

**8. Commit boundary.** Test-only.

---

### 11.5 Commit C5 — child docs + closeout (docs-only)

**1. Goal.** Leave this document and the **class-A** operator-facing docs
true.

**2. Scope.** This document; the **six class-A comment hits** in
`configs/health_checks.yaml` (`:35,45,60,71,82,92`) that state the triplet
as current fact. Docs-only. Depends on: C1-C4.

**Explicitly NOT in scope**: the two node `.md` files — see §15 Q3. They
are false for a *different, pre-existing* reason and 02c is not a
documentation-cleanup vehicle.

**3. Implementation plan.**
- [ ] Reconcile every checklist box with recorded evidence.
- [ ] Record the PR-02c Checkpoint-C mechanism actually used.
- [ ] Update the six class-A YAML comments, quote-verifying against the
      merged source.
- [ ] Record Checkpoint-D evidence actually run.

**4. Validation plan.** `ruff check`, `ruff format --check`; exact-head CI.

**5. Acceptance criteria.** Every `[ ]` resolved or deferred with a
reason; ruff clean; exact-head CI green; clean tree; **not merged without
operator approval**.

**6. Failure and edge cases.** A stale ledger at the final head is a
defect in its own right.

**7-8.** Recorded at execution; docs-only boundary.

---

### 11.6 Commit C6 — FINALIZER closeout

See §13-§17. Governance, not this child's capability.

---

## 12. PR-02c CHILD Checkpoint C + stop conditions

### 12.1 Child Checkpoint C — boundary frozen, command not frozen

Must prove the **REAL** health-check and campaign consumer paths obtain
the declarations.

> A test that constructs a declaration and calls a resolver directly does
> **NOT** satisfy this — 02b §5's rule applies unchanged.

PASS must establish:

- [ ] a real HealthGate evaluation resolves monitored files from
      declaration B;
- [ ] the files actually opened/evaluated follow it;
- [ ] the campaign validator consumes the same declared semantic;
- [ ] the anchors path resolves from declaration A;
- [ ] no old literal survives unnoticed at any migrated site;
- [ ] HealthGate thresholds and verdict semantics unchanged;
- [ ] exact executable HEAD, artifacts and log recorded.

**Use TIDMAD topology with CONTRAST declarations.** This isolates 02c and
deliberately avoids the Step-10 residue.

No real LLM required unless source makes it unavoidable. No
scientific-quality result. Environment requirements carried from 02a/02b:
worktree outside `.claude/`; verify child-process import provenance if
children are launched; **verdicts from the authoritative log, never a
wrapper exit code**.

### 12.2 Stop conditions

- anchors and health peeks collapse into one declaration, or a consumer
  reads the wrong one;
- a claimed migrated literal survives at any C2/C3 site;
- a declaration duplicates Dataset Profile topology authority;
- "all files" is restated as a declared field instead of deriving from
  `num_files`;
- **any fallback tier semantic is unified or changed** (Step 08);
- `segment_anchors.json` or `build_anchor_map.py` changes;
- sampling algorithm, seed derivation, portions or any SampleSet digest
  changes;
- runtime `DataScope` / `health_gate_files` override precedence changes;
- HealthGate thresholds, policy, `gate_role`, `on_fail.action` or verdict
  semantics change;
- **campaign-validation POLICY changes** rather than only its authority
  source — specifically, any list that skips today must still skip;
- Step-08 or Step-10 residue is absorbed;
- the Stage-B contrast varies topology or any non-declaration axis;
- a declared field lands without a production consumer;
- the Gate-1 flip condition fires;
- Gate 2's budget or shape materially exceeds the parent contract.

---

## 13. FINALIZER duties

### 13.1 Step-02 AGGREGATE Checkpoint-C reconciliation

Distinct from §12.1. Uses the **merged child ledgers as evidence
authorities** — do not blindly re-run every child test.

Confirm at the assembled executable head:
- **02a**: Dataset Profile production authority live; topology / geometry
  / encoding / channel semantics intact.
- **02b**: the tuner still supplies the explicit profile to both selection
  sites; SampleSet TIDMAD identity intact; **no ambient fallback has
  reappeared**.
- **02c**: declarations drive the anchors, blocking-peek and campaign
  consumers; all-files derives from topology; TIDMAD behaviour preserved.

Record the exact assembled executable HEAD. **Do not turn the parent into
a duplicate run log.**

### 13.2 Terminal local full unit suite — EXACTLY ONCE

**Terminal evidence, not an inner-loop tool.**

Before it: directly affected tests → true affected packages (selection +
health + core) → focused integration/mutations → child checkpoints. **Do
not progressively broaden "affected package" into most of
`tests/unit/`** (02a's drift; 02b corrected it and stayed at 4192).

Run once, only after: 02a merged; 02b merged; 02c executable capability
complete; PR-02c Checkpoint C complete; assembled head identified.

Record exact SHA, command, counts, wall time, log path. **A docs-only
closeout afterwards does NOT re-trigger it** unless executable code
changed.

### 13.3 Step-02 Gate 2 — EXACTLY ONCE

Instantiated from `docs/gates/gate_testing_standard.md` (read 2026-08-13)
and parent §10.2, per roadmap §17.0.

| Field | Value |
|---|---|
| Tier | real LLM + real training, **trial-only smoke** |
| Shape | `--no-force_formal_round`; partial scope with matching `--health_gate_files`; **cold start** (no `--seed_paths`); `--trial_portion 0.02`; `--trial_time_budget_minutes 5`; `--formal_time_budget_minutes 30` |
| LLM config | **`--llm_config llm_configs/openai_tiered_pro.json`** — see §16 authority resolution |
| Budget | ~30-45 min, ~$1-1.5 (PR-01b precedent: 33m35s actual) |
| Position | after PR-02c Checkpoint C, on the assembled head — ONE chain, once |

**PASS** = the standard's HealthGate-framework criteria verbatim (chain
exits 0; every round records a `gate_action`; every `denoising_score`
finite or accounted; no phantom `5.5762667`; ≥1 HealthGate evaluation),
**plus** the parent's two Step-02 criteria: the resolved profile in the
run artifacts deep-equals TIDMAD; and **for Gate 2's ACTUAL inputs** the
production SampleSet equals the deterministic reference resolution for
that same input tuple.

> **Never compare a digest across different arguments.** Gate 2 runs a
> partial scope at `trial_portion=0.02`; the five existing digests were
> captured at `seed=42, portion=0.05` and do **not** apply.

**NOT pass/fail**: denoising quality, beating a baseline, any threshold.

**Claim boundary.** Gate 2 detects regression in the assembled Step-02
feature under its approved real workflow. It does **NOT** prove a fully
generic non-TIDMAD campaign end-to-end — Step-08/Step-10 residue remains
outside its inputs. Do not overstate it in the closeout.

**Do NOT invent a reduced or intermediate Gate tier.**

### 13.4 Gate 1 — NOT REQUIRED

Assignment table: *"Config files, YAML, schema-only → Unit only"* and
*"New loader/renderer (pure Python) → Unit only"*.

**Flip condition**: if any commit changes a rendered prompt byte or a
proposal-affecting schema field, this child takes Gate 1 per the *"New
LLM-facing system prompt"* row.

> `agent/prompts.py:128` describes `anchors` as *"a small fixed subset of
> files (workflow-defined)"* — deliberately value-free. If an
> implementation renders the declared MEMBERS into a prompt, the flip
> fires. **Accidental prompt drift must be FIXED, not justified by
> running Gate 1.**

---

## 14. Q2 — float-element false-reject: **LATENT UNREACHABLE RESIDUE**

Source verdict (audited 2026-08-13):

| Question | Answer |
|---|---|
| A. Site | `campaign_artifacts.py:56-61`; `[3.0,10.0,17.0] == [3,10,17]` is True, and `str(3.0)` = `"3.0"` never matches an int-keyed `per_file` |
| B. Trigger | `files_requested` with **float** elements, exactly `[3.0,10.0,17.0]` in that order |
| C. Reachable today? | **NO.** `CheckRef.config: dict[str, Any]` (`config.py:57`) is untyped so Pydantic never coerces; all shipped YAMLs use int spelling; `health_gate_files: list[int]` (`hyperparam_tuning.py:1798`) with CLI parsing exclusively via `int(token)`; `apply_monitored_files` does `int(i)` (`config.py:310`). Only reachable via a hand-authored float-spelled custom YAML on a full-scope run — none exists in-repo |
| D. On 02c's path? | the SITE is; the float behaviour is not a distinct path |
| E. Does the authority swap change reachability? | **NO — zero change.** The operator (`==`), the LHS producer, and the `str(index)` lookup (which reads the **LHS**, not the declared RHS) are all untouched |
| F. Classification | **(ii) latent unreachable residue** |
| G. Owner if deferred | producer-side asymmetry at `health_checks/evaluation.py:202` (primary arm copies verbatim while the fallback arm at `:208` int-normalizes) — health-checks owner. Blast radius if it ever fired: a spurious retrain, not silent bad science |

**RECOMMENDED DISPOSITION: ROUTE/DEFER — record, do NOT pin, do NOT fix.**

Rationale, applying 02b §6.1's established rule: *"freezing an unreachable
bug's output would promote it into a compatibility promise nobody can
later change — the opposite of what a capture-first baseline is for."*
Pinning `[3.0,10.0,17.0]` behaviour in C1 would repeat exactly the mistake
02b deliberately avoided with the lexicographic branch.

**Stop condition**: if C1's audit finds the float branch IS
production-reachable, the classification has changed — STOP and report.

---

## 15. Q3 — stale node docs: **NOT 02c's**

Source verdict (audited 2026-08-13). The finding is bigger than the
literal.

**The two node `.md` files are already false for a reason unrelated to
02c**: DS7 **deleted the fields themselves**.

- `agent/schemas/hyperparam_tuning.py:1159-1165`: *"the operator-side
  `trial_strategy` / `target_files` / `eval_strategy` input fields were
  deleted: dead at both ends"*.
- `agent/schemas/proposal.py:704-707`: the mirrored fields *"were
  deleted: consumed by nobody"*.
- CLI: `ml_hyperparameter_tune_agent.py:6420` —
  `help="DEPRECATED no-op (DS7) — warns and is ignored."`

Yet `ml_hyperparameter_tune_agent.md:50` and
`ml_model_proposal_agent.md:30` still document them as **live input fields
with defaults**, incidentally mentioning `(files 0/10/19)`.

**Therefore they are NOT 02c literal-migration targets.** The rows should
eventually be **deleted**, not redeclared; the `0/10/19` mention is
incidental to an already-dead field.

| Class | Count | Disposition |
|---|---|---|
| **A** — production surface 02c redeclares | **6** — all `configs/health_checks.yaml` comments (`:35,45,60,71,82,92`) | **update in C5** |
| **B** — already false on current master, independent of 02c | **2** primary (+3 collateral rows) — the two node `.md` tables | **record as explicit docs debt; NOT 02c's.** 02c is not a documentation-cleanup vehicle |
| **C** — unrelated debt / historical | **73** | out of scope. Includes **merged ledgers and dated reports — HISTORICAL RECORDS, must NOT be edited** |

---

## 16. Q4 (new) — Gate-config authority: the **standard is stale**

Audited 2026-08-13. Recorded rather than silently resolved.

**The conflict**

- `docs/gates/gate_testing_standard.md:97` — `--llm_config
  openai_tiered_v1.json` | **mandatory** | rationale: *"gpt-4o-mini
  (`certify_minimal.json`) cannot reliably generate proposals that pass
  the validator"*.
- Step-02 parent `:915` — `--llm_config llm_configs/openai_tiered_pro.json`
  *"under standing production-validation policy (never `openai_tiered_v1`,
  never a substituted config)"*.

**Authority relationship**: roadmap §17.0 (BINDING, operator-approved
2026-08-13) makes the standard *"the ONLY authority for Gate semantics"*
— but its four concrete obligations are all about the **assignment table,
tier separation and flip conditions**, not per-flag values. **No
value-level tiebreak exists anywhere in the repository.**

**Verdict: the STANDARD is stale, and the parameter choice is correct.**

1. the standard's own rationale is a **floor argument against
   `certify_minimal`**; `openai_tiered_pro` (uniform `gpt-5.5`) strictly
   dominates `openai_tiered_v1` (`gpt-5.4` / `-mini` / `-nano`) on exactly
   that axis, so using `pro` cannot violate the rationale;
2. the standard has been untouched since **2026-07-27**, predating the
   2026-08-13 policy; no commit ever adds `tiered_pro` to it;
3. **precedent**: PR-01b **executed and passed** Gate 2 under `pro`
   (33m35s actual);
4. PR-01b §7a already resolves the collision explicitly: *"the standard
   still names `openai_tiered_v1.json` as mandatory… For this PR the
   operator's production-validation policy governs; amending the standard
   is a separate change with its own approval."*

**Residual defect**: the Step-02 parent cites the standard for everything
*except* the one row it contradicts — a **silent** override, unlike
PR-01b's explicit one. That is a documentation defect in the parent, not a
substantive violation.

**Proposed minimal correction (docs-only, outside 02c's implementation
scope, operator's call):**

- **Preferred** — fix the stale standard at
  `docs/gates/gate_testing_standard.md:97`: change the parameter to
  `openai_tiered_pro.json` and extend the rationale to keep the
  `certify_minimal` floor while naming `openai_tiered_v1.json` as the
  historical mixed-tier config superseded by standing policy (operator
  2026-08-13; precedent PR-01b Gate 2 PASS). Optional consistency sweep at
  `:33, :78, :226, :246`. This prevents recurrence at Step 03.
- **Cheaper** — add a PR-01b-§7a-style parenthetical to the Step-02 parent
  `:915`. Removes the silent contradiction but leaves the standard stale.

**Step-02 keeps `openai_tiered_pro.json` either way.** Implementation must
NOT be left to infer authority.

---

## 17. Finalizer sequencing and Checkpoint E

### 17.1 Evidence lifecycle

```text
1. 02c executable capability complete        (C2-C4)
2. PR-02c child Checkpoint C                 (§12.1)
3. Step-02 aggregate reconciliation          (§13.1)
4. ONE local full unit suite   <- exact EXECUTABLE head
5. ONE Gate 2                  <- same exact EXECUTABLE head
6. docs / status / Checkpoint-E closeout     (C6, docs-only)
7. exact-head CI on the final DOCS head
```

**Record both SHAs distinctly**: the final *executable* head (which the
full suite and Gate 2 attest) and the final *docs* head (which CI
attests). A commit cannot contain its own SHA, so the closing docs
commit's CI pass is reported to the operator, not embedded — the 02b
precedent.

**If executable code changes after step 4/5, that evidence is STALE** and
must be re-run or explicitly re-justified.

### 17.2 Checkpoint E — closeout contract

Owner: **02c**. Step 02 may be marked COMPLETE **only** when every item is
evidence-backed:

- [ ] 02a MERGED (merge SHA recorded);
- [ ] 02b MERGED (merge SHA recorded);
- [ ] 02c implementation complete;
- [ ] PR-02c Checkpoint D complete;
- [ ] aggregate reconciliation complete;
- [ ] terminal full suite PASS (exact executable SHA);
- [ ] Gate 2 PASS (same SHA);
- [ ] exact-final-head CI green.

Then update: Step-02 parent status; roadmap §15.1 row; §18 convergence
rows; Step-02 folder README mirror.

**Do not mark Step 02 COMPLETE merely because 02c code exists.**

---

## 18. Convergence-ledger implications

| Row | Disposition |
|---|---|
| systematic groups / task-owned file sets | 02c establishes **two** declarations and migrates their CURRENT consumers. This does **not** mean HealthGates owns a shared abstraction forever — **Step 08 retains the right** to determine consumer-side ownership in its own design |
| "all files" | must **not** become a declared field; derives from `profile.dataset.num_files` (§2.3) |
| SampleSet | unchanged by 02c — no typed wrapper, no consumer migration; 02b's row stays DO NOT MERGE |
| Dataset Profile → selection | closed by merged 02b |
| latent key-coercion divergence (02b) | remains recorded and deferred |
| latent float-element false-reject (§14) | newly recorded, deferred, producer-side owner named |
| Step-10 runtime-binding residue | **must not** be pulled into 02c |

Convergence rule unchanged: **no cross-module ownership merge without ≥2
completed designs** demonstrating the same semantics, lifecycle and
ownership. Two declarations inside one PR do **not** satisfy that bar —
they stay separate fields.

---

## 19. Mutation / failure-class economy

| # | Class | Demonstrates |
|---|---|---|
| 1 | anchor consumer still reads the `ANCHOR_FILES` literal | declaration A not live |
| 2 | blocking peek consumer ignores declaration B | declaration B not live |
| 3 | campaign validator retains exact `[3,10,17]` knowledge | trigger not live |
| 4 | recording all-files still assumes 20 | topology not derived |
| 5 | fallback tier behaviour unified/changed | Step-08 semantics violated |
| 6 | runtime override precedence reversed | a default now beats an explicit operator choice |

Minimum set that kills each distinct class. **Not one mutant per test.**

**Design note**: a mutation changing ONE declaration and making BOTH
consumers follow would be *misleading* evidence — it cannot distinguish
"both read their own declaration" from "one reads it and the other
coincidentally matches". C4's two subcases, each asserting the **unvaried**
consumer is unchanged, exist precisely to separate those.

---

## 20. Adversarial review (2026-08-13, 17 questions)

| # | Attack | Verdict |
|---|---|---|
| 1 | Are `[0,10,19]`, `[3,10,17]`, `range(20)` one concept? | **NO — refuted.** Three semantics, three different correct actions (§2). Revision 2's central premise was wrong |
| 2 | Is any "group" actually derivable topology? | **YES** — `range(20)` (§2.3). Anchors was ambiguous; operator decided DECLARED (§2.1) |
| 3 | Does 02c create a second Profile/config authority? | **NO** — §11.2 defaults to extending 02a's profile; a separate authority is a STOP requiring source evidence |
| 4 | Can anchors and HealthGates silently read different profiles? | **Guarded** — C4's subcases assert the unvaried consumer is unchanged, which is what detects divergence |
| 5 | Can explicit runtime overrides be overwritten by defaults? | **Guarded** — §7 puts override precedence out of scope; failure class 6 mutates it; §4.3 documents the mechanism |
| 6 | Did 02c absorb Step-08 policy? | **NO** — thresholds/verdicts/`gate_role`/`on_fail` **and all fallback tier semantics** explicitly not owned (§7); unifying them is a stop condition |
| 7 | Did 02c absorb Step-10 residue? | **NO** — §7 and §12.2 forbid it; §12.1 avoids the axis that would drag it in |
| 8 | Does campaign validation preserve current behaviour? | **YES — the sharpest risk, explicitly trapped.** §6.1 forbids set/sorted comparison because it would newly ENFORCE where today it skips. D1-c is the guard, captured BEFORE the change |
| 9 | Is Stage-B declaration-only and atomic? | **YES**, machine-checked, two subcases because the declarations are independent (§11.4) |
| 10 | Can child Checkpoint C pass while a literal survives? | **Addressed** — §12.1 requires "no old literal survives unnoticed" plus failure classes 1-4; a direct resolver call is explicitly insufficient |
| 11 | Are child and aggregate Checkpoint C distinct? | **YES** — §10 forbids bare "Checkpoint C"; §12.1 vs §13.1 |
| 12 | Is the full suite terminal and once? | **YES** — §13.2, with the 02a-drift lesson named |
| 13 | Is Gate 2 once and standard-grounded? | **YES** — §13.3, instantiated per §17.0, with the authority conflict resolved in §16 rather than assumed |
| 14 | Does Gate 2 claim only what its inputs prove? | **YES** — §13.3's claim boundary forbids asserting end-to-end generic-campaign readiness |
| 15 | Can a docs-only closeout trigger needless repetition? | **NO** — §13.2 and §17.1 |
| 16 | Is Checkpoint E's authority explicit? | **YES** — §17.2, named owner, explicit "not merely because code exists" |
| 17 | Is any new abstraction consumer-less or speculative? | **NO** — §12.2 makes a consumer-less field a stop; §8 forbids a generic `groups` mapping without source evidence; every declaration has a named migrated consumer |

**Findings this review produced and the document already applies**: the
campaign-normalization trap (#8); the need for two Stage-B subcases (#9);
and the "misleading single mutation" note (§19). None were in revision 2.

---

## 20a. FINAL genericity re-review — contract quality (2026-08-13)

Narrow, pre-freeze, focused on whether the contract is genuinely generic
rather than a configurable replica of TIDMAD.

| # | Question | Verdict |
|---|---|---|
| 1 | Is every declared field genuinely useful for a non-TIDMAD task? | **YES.** A task with different informative bands must set both A and B; neither is inferable from topology |
| 2 | Is any field merely a configurable replica of a legacy literal? | **A and B are, by construction — and legitimately so.** They are task-owned scientific choices with no formula. The test that separates "legitimate declaration" from "config-ised hardcode" is Q12, which passes |
| 3 | Can any declared value instead derive from an existing authority? | **Only C, and it does.** A was the live candidate (`[0,n//2,n-1]`); the operator decided DECLARE rather than invent non-TIDMAD behaviour (§2.1) |
| 4 | Does every declaration have a live production consumer? | **YES** — A: `sample_set_builder.py:105`; B: the three blocking checks **and** the campaign validator. §12.2 makes a consumer-less field a stop condition |
| 5 | Are anchor-selection and health-peek kept semantically distinct? | **YES** — separate fields, separate consumers, separate Stage-B subcases, and each subcase asserts the *other* is unchanged |
| 6 | Is all-files derived, never declared? | **YES** (§2.3), and adding an `all_files` field is a stop condition |
| 7 | Did any latent bug become a frozen compatibility contract? | **NO — and this review CORRECTED one.** The Q2 float residue is routed, not pinned; the falsy-`[]` hazard was originally marked "pin, do not fix" and is now reclassified to RECORD-only (§4.3) for consistency. Two latent, hand-edited-YAML-only behaviours are treated identically |
| 8 | Did any HealthGate policy behaviour change while migrating authority? | **NO — and this review FOUND the trap that would have caused it.** §8.1: injecting B where the key is absent would move recording gates from 20 files to 3. Required shape and a leak-guard assertion are now specified |
| 9 | Did campaign validation become more permissive or more enforcing? | **NEITHER.** §6.1 forbids set/sorted comparison; D1-c pins the reordered-skip BEFORE the change |
| 10 | Did runtime/operator choices migrate into task config? | **NO.** `health_gate_files` and `DataScope` remain runtime inputs; §4.3's precedence is unchanged; failure class 6 mutates it |
| 11 | Is Stage-B varying semantics, or swapping one TIDMAD-shaped list for another? | **CORRECTED.** Membership-only contrast keeps cardinality at three and could pass with a consumer assuming a triplet. C4 now varies **cardinality too** (§11.4) |
| 12 | Could the profile describe a task whose anchor/health selections genuinely differ from TIDMAD, with no source edits? | **YES, given §8.1's shape.** A new task sets A and B on its profile; anchors and the three blocking checks resolve from them; all-files derives from `num_files`; the campaign trigger follows B. **Caveat recorded honestly**: the shipped `configs/health_checks.yaml` remains the operator surface, so a task shipping its own health-checks config is a Step-08 concern, not 02c's |

**Two corrections applied** (#7 and #8), plus one strengthening (#11).
Nothing else changed. The audit was not broadened.

---

## 21. Remaining operator decisions

**ALL DECIDED — operator, 2026-08-13. None remain open.**

| # | Question | FINAL decision |
|---|---|---|
| **Q1** | anchors DECLARED vs DERIVED | **DECLARED task-owned anchor-selection file set.** Not derived as `[0,n//2,n-1]`: the TIDMAD value merely coincides with that expression, and the "extrema" comment is intent, not a contract for inventing non-TIDMAD behaviour (§2.1) |
| **Q2** | float-element false-reject | **ROUTE / DEFER.** Do not fix in 02c; do **not** add a compatibility pin; record the finding and its reachability classification. STOP only if an implementation re-audit proves it production-reachable (§14) |
| **Q3** | stale node docs | **OUT of 02c.** They describe DS7-deleted fields and a warned no-op CLI; recorded as existing documentation debt for the owning cleanup. 02c updates only docs describing a live surface it changes — i.e. the six `configs/health_checks.yaml` comments (§15) |
| **Q4** | Gate-config authority | **Step-02 Gate 2 uses `llm_configs/openai_tiered_pro.json`** — explicit operator approval. The standard's `openai_tiered_v1` wording is recorded as stale governance debt for the gate-standard owner. 02c does not rewrite the standard beyond a minimal factual correction if one is needed to avoid contradictory repository truth (§16) |
| **Q5** | PR title | **Renamed in body to "Task-owned file-set semantics"; filename unchanged** to preserve links from merged 02a/02b ledgers (§22) |
| **Q6** | one PR vs split | **KEEP ONE PR and ONE canonical child design document.** A somewhat broader coherent PR is preferred over proliferating narrowly sliced children. Internal subparts keep separate milestones and atomic contrast subcases inside 02c (§5) |

**Not operator questions** (implementation-time): declaration field names,
YAML nesting, Pydantic decomposition, helper names, fixture placement,
assertion mechanics, the exact Checkpoint-C mechanism.

---

## 22. Rename impact (Q5)

Recommended new title: **"Task-owned file-set semantics"** — source-accurate,
and it does not imply the refuted single-group model.

Cross-reference impact, measured: the phrase "systematic group" appears in
the Step-02 parent's child table and DAG rows, the roadmap §15.1 row, and
the folder README mirror. The **filename**
`pr_02c_systematic_groups.md` is referenced by relative link from the
parent and from the 02a/02b ledgers.

**Recommendation**: rename the **title and prose** now (pre-freeze, cheap);
**keep the filename** `pr_02c_systematic_groups.md`. Renaming the file
would break links from **merged, immutable** 02a/02b ledgers, which must
not be edited. The title/prose carries the semantic correction; the
filename is an address.

---

## 23. Status

**DESIGN — READY FOR OPERATOR FREEZE (revision 3, 2026-08-13).
NOT YET FROZEN. IMPLEMENTATION NOT AUTHORIZED.**

All six operator decisions are FINAL and applied (§21). The final narrow
genericity re-review (§20a) produced two corrections — the §8.1 injection
shape and the §4.3 falsy-hazard reclassification — plus one strengthening
(§11.4 cardinality). **No remaining operator questions.**

Implementation begins only after operator freeze and a filled
Implementation Working Rules contract, in a fresh context with its own
Context Continuity v2 handoff, in an isolated worktree outside
`.claude/`.
