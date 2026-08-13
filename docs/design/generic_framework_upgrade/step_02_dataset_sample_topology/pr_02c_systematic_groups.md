# PR 02c — Task-owned file-set semantics (Step 02, child 3 of 3 + FINALIZER)

> **Renamed in revision 3.** Was *"Systematic group semantics"*. The old
> title encoded the refuted premise that three literals were one
> frequency-band group. Rename impact is assessed in §16.

## Status

**FROZEN / OPERATOR APPROVED FOR IMPLEMENTATION (2026-08-13).**

The operator froze this design at **revision 3**. Everything below — the
capability statement (§1), the declared-vs-derived classification (§2),
the consumer census (§3-§4), the one-PR decision (§5), ownership (§7),
the declaration model (§8), the compatibility contract (§9), the blocking
checkpoint ladder (§10), the commit plan (§11), the child Checkpoint-C
boundary and stop conditions (§12), the finalizer duties (§13), the
Q2/Q3/Q4 dispositions (§14-§16), the finalizer sequencing and
Checkpoint-E contract (§17), convergence (§18), mutation economy (§19)
and the reviews (§20, §20a) — may not change without a new operator
decision.

In particular, these are frozen and must not be re-litigated during
implementation:

- the **three-way classification** (§2): `[0,10,19]` DECLARE,
  `[3,10,17]` DECLARE, `range(20)` DERIVE. **No catch-all group map**,
  and **no `all_files` declared field**;
- the **governing principle** (§2.4): genericization is not moving legacy
  hardcodes into config — declare task-owned, derive topology-owned,
  preserve runtime/policy-owned semantics;
- the **injection shape** (§8.1): declaration B reaches ONLY the three
  sites that carry `peek_file_indices` today. Neither injecting where the
  key is absent nor deleting the key is permitted;
- the **campaign-policy freeze** (§6.1): exact-list, order-sensitive
  comparison preserved. No `set`, no `sorted`, no normalization;
- **fallback tiers are not homogenized** (§4.2, §7) — that is Step-08
  policy;
- **latent behaviours are recorded, never pinned** (§4.3, §14) —
  consistent with 02b §6.1.

Revision 3 was rewritten against merged 02a + 02b source after six
revision-2 claims were refuted (§0.2); the final genericity re-review
(§20a) then produced two corrections (§8.1, §4.3) and one strengthening
(§11.4).

**IMPLEMENTATION IS NOT AUTHORIZED IN THIS SESSION.** It begins only
after a filled **Implementation Working Rules contract** for this child,
in a NEW, fresh context with its own Context Continuity v2 handoff, in an
isolated worktree **outside `.claude/`** (the 02a/02b process lesson).

**Frozen design HEAD**: the commit that carries this status line. Resolve
it mechanically from the repository at kickoff
(`git log -1 --format=%H -- <this file>`); never from conversational
memory.

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
- [x] Re-read `campaign_artifacts.py:35-66` and the existing test module
      before writing. — done; the audit is recorded in §24.2.
- [x] Pin D1-a: `files_requested == [3,10,17]` (ints) with **complete**
      `per_file` → **no** error. —
      `TestDefaultHealthPeekCompletenessIsEnforced::test_complete_per_file_produces_no_error`
- [x] Pin D1-b: same, with a **missing** per-file entry → exactly
      `gate {id}: missing per-file entries [...]`, and `valid=False`. —
      `::test_missing_per_file_entry_is_reported_exactly` (exact message)
      plus `::test_incomplete_per_file_forces_retrain`, which carries the
      case through `decide_phase1_reuse` to `action == "train"` and
      `valid=False` — the POLICY consequence, not just the string.
- [x] Pin D1-c: **reordered** `[10,3,17]` → **skips**; assert the
      per-file error is ABSENT. (This is the anti-normalization guard.) —
      `TestNonDefaultRequestedListIsNeverEnforced::test_no_per_file_enforcement[reordered_default]`
- [x] Pin D1-d: custom non-triplet list → **skips**. — ids
      `custom_operator_list` and `out_of_range_member`.
- [x] Pin D1-e: full-file list → **skips**. — id `all_files_population`.
- [x] Pin D1-f: empty / absent `files_requested` → **skips**. — ids
      `explicitly_empty`, `key_absent`, `aggregation_absent` (the last
      covers `aggregation` missing entirely, distinct from present-but-empty).
- [x] Pin the `per_file` **str-key dependency** (`str(index) not in
      per_file`, `:59`) so a producer key-type change is caught. —
      `::test_per_file_lookup_is_str_keyed`.
- [x] Pin C2: config `peek_file_indices` beats a populated
      `ctx.denoised_paths`, for **all three** recording checks (today only
      `PerFileOutputStd` has any tier-2 test). —
      `TestAttemptedOpenSets::test_recording_checks_prefer_configured_list_over_denoised_paths`,
      parametrized over all three; the two candidate populations are
      deliberately **disjoint** (`{4,7,9}` configured vs `{5,8}` present)
      so the recorded set names which tier won.
- [x] Record in the ledger that blocking and recording resolvers differ
      (§4.2) and that this is PRE-EXISTING, not 02c's to unify. — §24.2,
      verified line-by-line at this HEAD.
- [x] **Do NOT** pin the float-element branch (§14 Q2 — latent
      unreachable; pinning it would repeat the mistake 02b's §6.1 rule
      exists to prevent). — not pinned. The C1 re-audit **confirmed** the
      classification: no shipped path produces float elements (§24.2).

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

**FROZEN / OPERATOR APPROVED FOR IMPLEMENTATION (revision 3,
2026-08-13).**

All six operator decisions are FINAL and applied (§21). The final narrow
genericity re-review (§20a) produced two corrections — the §8.1 injection
shape and the §4.3 falsy-hazard reclassification — plus one strengthening
(§11.4 cardinality). **No remaining operator questions.**

Implementation begins only after a filled Implementation Working Rules
contract, in a fresh context with its own Context Continuity v2 handoff,
in an isolated worktree outside `.claude/`. See the head-of-file status
block for what may not be re-litigated.

**Implementation STARTED 2026-08-13** under a filled Implementation
Working Rules contract. §1-§23 above are the frozen contract and do not
change; everything the implementation discovers, decides, runs and
proves is recorded in **§24, the LIVE implementation ledger**.

---

## 24. Implementation ledger (LIVE)

> Everything below this line is written **during** implementation. §1-§23
> are frozen. Where an audit refutes a frozen premise the refutation is
> recorded here in the `Previous assumption / evidence / corrected
> understanding` form — the frozen text is never rewritten to pretend the
> premise was always right.

### 24.0 Kickoff facts — resolved mechanically, never from memory

| Fact | Value | How resolved |
|---|---|---|
| Frozen design HEAD | `0fbe3556989be29354e45cc2ae0c12413fe05e9a` | `git log -1 --format=%H -- <this file>` |
| PR 02a | **MERGED** — PR #202, merge `473595386598e732f52a573486d2012c1f0daf2d` | `git merge-base --is-ancestor … origin/master` → YES |
| PR 02b | **MERGED** — PR #203, merge `c17469ec1077c54d727b55ef3c743adc45301d58` | `== origin/master`; matches the authorization SHA exactly |
| `origin/master` | `c17469ec` | `git rev-parse origin/master` |
| Implementation base | `0fbe3556` | see the note below |
| Implementation branch | `feat/generic-framework-step-02c-task-owned-file-sets` | created at kickoff |
| Worktree | `/home/yuema137/siderius-worktrees/pr02c-impl` | outside `.claude/`, not shared with the design session |
| Interpreter | `/home/yuema137/SIDERIUS/.venv/bin/python` (3.12.13) | |

**Why the base is `0fbe3556` and not `origin/master`.** The frozen PR-02c
design is doc-only and lives on `docs/step02c-revision3` — three commits
on top of `origin/master`, never merged and with no open PR. The
authorization requires a base "containing the frozen PR-02c design", so
the implementation branch is cut from that tip. `origin/master`
(`c17469ec`) is its direct ancestor, so every merged prerequisite is
present. The three doc commits ride in this PR.

**Environment note carried forward from 02a/02b.** A linked worktree
inherits **no** gitignored files. `tidmad_data_config.yaml`,
`dashboard_config.yaml` and `.env` (Gate-2 credentials) were copied in by
hand. Import provenance was verified before any test ran: from this
worktree `import core` resolves to
`/home/yuema137/siderius-worktrees/pr02c-impl/core/__init__.py`, i.e. cwd
outranks the editable-install finder that points at the main checkout.

**Gate-config governance, recorded explicitly (§16 / parent §10.2).**
Step-02 Gate 2 uses **`llm_configs/openai_tiered_pro.json`**. This is the
operator's standing production-validation policy and it **overrides** the
stale `openai_tiered_v1.json` wording at
`docs/gates/gate_testing_standard.md:97` for this Step. The conflict is
recorded, not silently resolved by picking a third config.

### 24.1 Progress

| Stage | State | Evidence |
|---|---|---|
| C1 — capture the two missing baselines | **DONE** | §24.3 |
| **CP0 — BASELINE COMPLETE** | **PASS** | §24.4 |
| C2 — declarations + anchor / blocking-peek consumers | **DONE** | §24.7 |
| **CP-C1 — DECLARATIONS LIVE + TIDMAD PARITY** | **PASS** | §24.9 |
| C3 — campaign trigger + profile-derived all-files | **DONE** | §24.10 |
| **CHECKPOINT A — Stage-A TIDMAD parity complete** | **PASS** | §24.12 |
| C4 — 4.8-C atomic contrast | **DONE** | §24.13 |
| **CHECKPOINT B — generic file-set semantics complete** | **PASS** | §24.14 |
| **PR-02c CHECKPOINT C — live consumer evidence** | **PASS** | §24.16 |
| C5 / PR-02c Checkpoint D | — | |
| Step-02 aggregate reconciliation | — | |
| Terminal local full unit suite (ONCE) | — | |
| Step-02 Gate 2 (ONCE) | — | |
| C6 / Checkpoint E | — | |
| Exact-final-head CI | — | |

### 24.2 C1 source re-audit — every frozen claim re-verified at `0fbe3556`

Re-audited **before** writing any test, as §11.1 requires. **No frozen
claim was refuted.** The census below is the implementation-time record.

**Anchor selection (A).**

| Fact | Evidence at this HEAD |
|---|---|
| production literal | `execute_tools/sample_set_builder.py:29` `ANCHOR_FILES = [0, 10, 19]` — **exactly one** |
| production reader | `:105` `files = list(ANCHOR_FILES)` — **exactly one** |
| partial-scope guard | `:96-103` raises for `anchors`/`target` when the scope is not full |
| profile already threaded | `:85` `resolved_profile = profile if profile is not None else resolve_dataset_profile()` — 02b's explicit hop is live and is where declaration A will be read from |
| uncoupled test duplicate | `tests/unit/agent/tune_ml_hyperparam_agent/test_formal_sample_set.py:212` `assert set(sample_set.keys()) == {0, 10, 19}` — hardcoded, will NOT follow a declaration change. C2 must update it |
| oracle | `GOLDEN["anchors"] = "e025a270e0b1acc1"` at `tests/unit/execute_tools/test_sample_set_builder.py:245` (seed=42, portion=0.05) |

**Health peek (B).**

| Fact | Evidence at this HEAD |
|---|---|
| YAML sites | `configs/health_checks.yaml` `:35`, `:60`, `:82` — **exactly three**, and all three gates carry `gate_role: blocking` (`:27`, `:52`, `:74`) |
| keyless gates | `:104`, `:125`, `:142` — all three `gate_role: observational`, **no `peek_file_indices` key at all**. §8.1's injection trap is real and mechanically confirmed |
| class-A comments | `:35, :45, :60, :71, :82, :92` — six, exactly as §15 counted |
| second consumer | `core/campaign_artifacts.py:57` `if requested == [3, 10, 17]:` — the hardcoded **copy** |
| record producer | `execute_tools/health_checks/evaluation.py:202` copies `peek_file_indices` **verbatim**; the `:208` fallback arm int-normalizes. Producer asymmetry confirmed (§14 Q2's named owner) |

**Resolver tiers (§4.2) — re-verified line by line, and they genuinely differ.**

| Tier | BLOCKING `_multi_file_peek._resolve_indices:113-131` | RECORDING `_resolve_files` |
|---|---|---|
| 1 configured | dedupe **preserving input order** | `sorted({int(i) for i in configured})` |
| 2 `denoised_paths` | `[min(ctx.denoised_paths.keys())]` — **ONE** file | `sorted(ctx.denoised_paths.keys())` — **all** |
| 3 fallback | `[0]` | `list(_DEFAULT_FILE_RANGE)`, guarded by `denoised_filename_fn is not None` |
| 4 | — | `[]` |

The three recording bodies are **byte-identical** to one another:
`pearson_dispersion.py:151-167`, `per_file_output_std.py:110-120`,
`spectral_peak_ratio.py:145-155`. `_DEFAULT_FILE_RANGE: range = range(20)`
at `pearson_dispersion.py:34` (its own comment reads `# TIDMAD NUM_FILES`),
`per_file_output_std.py:30`, `spectral_peak_ratio.py:39`.

**This divergence is PRE-EXISTING and is NOT 02c's to unify** (§4.2, §7 —
Step-08 policy). C1 pins it as it stands.

**Coverage findings — the two "missing" rows are genuinely missing, and
the two "EXISTS" rows genuinely exist.**

| §9 row | Verdict | Evidence |
|---|---|---|
| D1 campaign matrix | **MISSING, confirmed** | all 12 pre-existing tests in `tests/unit/core/test_campaign_artifacts.py` build `"aggregation": {"files_requested": []}` (`:36`). The if-branch had **zero** coverage. Read all 12 to confirm — not inferred from a grep |
| C2 recording tier-1 > tier-2 | **MISSING, confirmed** | `test_health_scope.py:253` covers tier-2 > tier-3 for `PerFileOutputStd` **only**; `:232` passes a configured list against a ctx with `denoised_filename_fn` and no `denoised_paths`, i.e. tier-1 > tier-**3**. No module pinned tier-1 > tier-2 |
| C1 recording full-file fallback | **EXISTS — reused, not duplicated** | `test_health_scope.py:246-251` asserts `rec.requested == set(range(20))`. R4 upheld |
| E1 `apply_monitored_files` | **EXISTS** | `test_health_scope.py:70-77` |
| A1/A2 anchors | **EXISTS** | `GOLDEN["anchors"]`; `TestAnchorsStrategy::test_only_anchor_files` |

**§14 Q2 float-element residue — classification RE-CONFIRMED, not pinned.**

The re-audit chased every producer of `files_requested` to its int
guarantee: `CheckRef.config: dict[str, Any]` (`health_checks/config.py:57`,
untyped so Pydantic never coerces) → but every shipped path upstream is
int-only. `health_gate_files: list[int] | None`
(`agent/schemas/hyperparam_tuning.py:1798`); CLI parsing exclusively
through `DataScope.from_cli` (`dataset_config.py:239-282`), which builds
indices with `int(token)` / `int(lo_str)` and raises on anything else;
`apply_monitored_files` normalizes with `int(i)` (`config.py:310`); and
the shipped `configs/health_checks.yaml` spells the triplet as ints.
**Verdict: latent, production-unreachable — unchanged.** Not fixed, not
pinned, no STOP. Consistent with 02b §6.1 and with §4.3's falsy-`[]`
hazard, which is likewise recorded only.

**Shape inputs discovered for C2** (decision deferred to C2, recorded now
so it is not re-derived):

- `DatasetProfile` (`dataset_config.py:438-468`) is `frozen=True` and
  composes `dataset` / `channels` / `encoding`; `TIDMAD_PROFILE` at `:478`.
- The subsystem **already has** a call-time derivation seam for exactly
  the C-classification: `health_checks/config.py:333`
  `num_files = resolve_dataset_profile().dataset.num_files` inside
  `validate_health_scope`. C3 should follow that pattern rather than
  invent one, and must resolve at **call time** (02b §13.9's
  default-argument lesson).
- **Watch — atomicity baselines read the profile dump.**
  `tests/unit/execute_tools/test_step02a_c6_contrast_rungs.py:59` and
  `tests/unit/execute_tools/test_step02b_b4_topology_contrast.py:56` both
  flatten `TIDMAD_PROFILE.model_dump()` as a mechanical
  "nothing-else-changed" baseline. Adding profile fields changes that
  dump; both must be re-read before the field shape is chosen.
- **Watch — external profile JSON.** `load_dataset_profile` (`:518`)
  validates operator-supplied profile files. New **required** fields
  would break existing ones.

### 24.3 C1 — the two captured baselines (test-only, ZERO production diff)

`tests/unit/core/test_campaign_artifacts.py` (+179):
`TestDefaultHealthPeekCompletenessIsEnforced` (5 tests) and
`TestNonDefaultRequestedListIsNeverEnforced` (7 parametrized ids).

`tests/unit/execute_tools/health_checks/test_health_scope.py` (+38/-1):
`TestAttemptedOpenSets::test_recording_checks_prefer_configured_list_over_denoised_paths`,
parametrized over the three recording checks. `_RecordingCtx` gained an
optional `denoised_paths` argument defaulting to `{}` — behaviour for
every existing caller is unchanged.

Two design points worth naming, because a weaker test would have looked
equally green:

1. **Every skip case asserts the per-file error is ABSENT**, with a
   deliberately EMPTY `per_file`. Asserting `valid` instead would pass
   even if the branch started firing, since a record can be invalid for
   unrelated reasons. This is what makes D1-c a real anti-normalization
   guard.
2. **The C2 pin's two candidate populations are disjoint** — `{4,7,9}`
   configured against `{5,8}` present in `ctx.denoised_paths`. The
   recorded request set therefore *names* which tier won instead of merely
   being consistent with the right one.

Beyond the frozen plan, two extra pins were added (bounded deviation,
§24.6): the `aggregation`-absent case (distinct from present-but-empty —
`(result.get("aggregation") or {})` handles them on different code paths)
and `test_incomplete_per_file_forces_retrain`, which carries an enforced
failure through `decide_phase1_reuse` to prove the branch is POLICY and
not presentation.

**Deliberately NOT captured**: the `range(20)` recording fallback (R4 —
`test_health_scope.py:246-251` already owns it) and the §14 Q2 float
branch.

### 24.4 CP0 — BASELINE COMPLETE: **PASS**

```text
Validation:
  command:      .venv/bin/python -m pytest tests/unit/core/test_campaign_artifacts.py \
                    tests/unit/execute_tools/health_checks/ -q
  purpose:      every behaviour whose AUTHORITY C2/C3 will change has a
                pre-change oracle
  environment:  worktree pr02c-impl @ 0fbe3556, python 3.12.13, CPU only
  result:       318 passed, 0 failed, 0 skipped — 14.63 s (pytest rc=0,
                read from the log, not a wrapper exit status)
  production diff: ZERO — `git diff --name-only` returns only tests/
  static:       ruff check clean; ruff format --check "2 files already
                formatted"
```

Acceptance against §11.1's criteria:

- [x] `git diff --stat` shows zero files outside `tests/`.
- [x] The campaign if-branch is executed by **≥2** tests — five enter it
      (four in the enforced class plus the retrain-policy test); today it
      was zero.
- [x] Each skip class asserts **ABSENCE** of the per-file error.
- [x] Recording tier-1-over-tier-2 asserted for **all three** modules.
- [x] Each pin fails when its behaviour is perturbed — dossier §24.5.
- [x] **No duplicate** of any §9 EXISTS row; `range(20)` was not re-pinned.

### 24.5 C1 mutation dossier — 4 mutations, 4 distinct failure classes

Method (per the project's mutation-hygiene rule): exactly one textual
substitution per run, asserted to occur **exactly once** in the target
file before it is applied; `__pycache__` cleared before and after; the
file restored and byte-compared afterwards.

| # | Failure class (§19) | Mutation | Expected | Observed |
|---|---|---|---|---|
| M-C1-1 | 3 — campaign trigger **normalizes** | `campaign_artifacts.py:57` `requested == [3,10,17]` → `sorted(requested) == sorted([3,10,17])` | only the reordered case reds | **CAUGHT** — `1 failed, 23 passed`; the single failure is `test_no_per_file_enforcement[reordered_default]`. Exactly the anti-normalization guard, and nothing else moved |
| M-C1-2 | 3 — enforcement silently dropped | same line → `if False and …` | the enforced class reds | **CAUGHT** — `4 failed, 20 passed`, including `test_incomplete_per_file_forces_retrain` flipping `train` → `reuse`, i.e. the POLICY consequence is pinned, not just a string |
| M-C1-3 | 5 — recording fallback **tier order** changed | `spectral_peak_ratio.py` `_resolve_files`: `denoised_paths` moved above `configured` | only `spectral_peak_ratio`'s id reds | **CAUGHT** — `1 failed, 27 passed`; `…[spectral_peak_ratio]` resolved `[]`. The per-module parametrization discriminates, and the pre-existing `test_monitored_files_bound_the_attempted_set[spectral_peak_ratio]` stayed **green** — which is precisely why this pin was missing |
| M-C1-4 | producer/consumer key type | `campaign_artifacts.py:59` `str(index) not in per_file` → `index not in per_file` | the str-key pin reds | **CAUGHT** — `3 failed, 21 passed` |

No mutation survived. M-C1-3 was run on **one** module rather than three:
the question it answers is "does the parametrized pin discriminate per
module", and one mutant answers it — three would be one mutant per test,
which §19 forbids.

### 24.6 Deviations from the frozen plan

```text
Deviation:  C1 adds two pins beyond §11.1's enumerated list — the
            `aggregation`-absent case and a policy-consequence test
            through `decide_phase1_reuse`.
Reason:     §11.1's own validation plan asks for "`aggregation` absent vs
            present-but-empty", and §6 states the branch is "POLICY, not
            presentation". Neither was expressible in the enumerated
            D1-a..f list.
Source:     `campaign_artifacts.py:56` `(result.get("aggregation") or {})`
            — absent and present-but-empty reach the `or {}` on different
            paths; `:80` `decide_phase1_reuse` → `ValidationReport(valid=
            not errors)` → `action="train"`.
Impact:     test-only; classification BOUNDED.
Validation: both are killed by M-C1-2.
```

```text
Deviation:  `_RecordingCtx` in test_health_scope.py gained an optional
            `denoised_paths` parameter.
Reason:     the C2 pin needs a ctx with BOTH a populated `denoised_paths`
            and recording path fns; duplicating the helper would have been
            worse.
Impact:     default `None` -> `{}` reproduces the previous constructor
            exactly; all pre-existing tests unaffected (318 green).
Classification: BOUNDED.
```

No material deviation. No stop condition reached.

---

### 24.7 C2 — the two declarations and their first consumers

#### The decision that shaped this commit, and the fact that forced it

§8 froze the semantics and left the shape open. The shape question is:
**how can a task's declared health-peek set become the authority behind
the three blocking checks, when `configs/health_checks.yaml` must stay
the operator's policy surface?**

The audit found a constraint the frozen design does not mention, and it
is the one that decides the answer:

```text
Previous assumption (implied by §8.1's framing):
  changing the shipped YAML text is the expensive move, because
  `health_config_sha256` is pinned and every workspace invariant lock
  keys off it.

Audit evidence:
  `legacy_config_body_sha` (candidate_eligibility.py:75-95) hashes
  `load_health_gates_config(path).model_dump(mode="json")` with
  `gate_role` popped — the RESOLVED MODEL, not the file bytes.
  `materialize_effective_config` computes its sha the same way
  (config.py:395). `test_honest_gate_labels.py:187` pins
  3b5521…655b74 for the shipped config and d133a12d…5ef58d for the
  observe-mode one, with the explicit acceptance rationale that these
  must not shift "or every workspace invariant lock would break at the
  boundary". `test_step00_health_config_baseline.py` additionally
  deep-equals the resolved dump against a Step-00 golden.

Corrected understanding:
  the frozen surface is the RESOLVED VALUE, not the YAML text. YAML text
  is free to change; what may never change is that the three blocking
  checks resolve to exactly [3, 10, 17] under TIDMAD.

Implementation consequence:
  the YAML can carry a DECLARED-DEFAULT MARKER in place of the literal,
  resolved at config-validation time. Both pinned shas and the Step-00
  golden stay byte-identical, because all three read the resolved model.

Validation consequence:
  the two config shas and the HC-1 golden become the primary CP-C1
  parity evidence, asserted by running the existing modules UNMODIFIED.
```

#### What landed

**Declaration model** — `DatasetProfile` (`execute_tools/dataset_config.py`)
gains **two separate REQUIRED fields**, `anchor_selection_files` and
`health_peek_files`, plus one `model_validator(mode="after")`.

Three shape choices, each source-grounded rather than stylistic:

1. **Top-level fields, not a `file_sets` sub-model.** The validation
   requirement decides it: a declared index must be legal against
   `dataset.num_files`, and `num_files` is a **sibling** field. A
   sub-model cannot see it. §8's "two named fields are the default" and
   the validation contract agree.
2. **REQUIRED, no default.** `test_step02a_c2_profile_injection.py:240`
   is a merged 02a invariant named
   *"the declaration must not smuggle TIDMAD in as a required default"*.
   A TIDMAD-shaped default for either field is exactly that smuggling —
   a new task would inherit somebody else's frequency bands silently.
   Blast radius measured before committing to it: **one** direct
   `DatasetProfile(...)` construction exists outside the shipped
   `TIDMAD_PROFILE` (that same 02a test), and profile JSON is always
   generated fresh from `model_dump()` by
   `sandbox_executor._write_dataset_profile_config`, so nothing stale
   round-trips.
3. **Reject rather than repair.** Empty, duplicate and out-of-range are
   all rejected. Empty is the sharpest: it does not mean "none" to any
   consumer — it falls THROUGH into a fallback tier, which is the same
   falsy-list trap `apply_monitored_files` already refuses
   (`config.py:304-309`). Duplicates are rejected because the profile's
   existing validators (`_distinct_from_input`,
   `_alphabet_covers_the_shifted_range`) establish that this object fails
   loudly; **consumer-side dedupe of RUNTIME lists is untouched**.

**Consumer A — anchors.** `ANCHOR_FILES` is **deleted**;
`sample_set_builder.py` now reads
`list(resolved_profile.anchor_selection_files)` from the profile it
already resolved once at `:85` (02b's explicit hop). No new resolution
site, no second authority, and the "resolved ONCE" invariant 02b wrote
into that function is preserved verbatim.

**Consumer B — blocking peeks.** `TASK_HEALTH_PEEK = "task_health_peek"`
may stand where a literal list stands; `CheckRef._resolve_declared_peek_selection`
resolves it at field validation. This satisfies §8.1 exactly:

- it appears at **exactly the sites that carry the key today** — the
  three blocking checks in each of the two shipped configs;
- the key is **not deleted**, so nothing falls through to `[min(paths)]`;
- **no key is added** where none exists, so the three recording checks
  keep evaluating every file.

Resolution reads the ambient profile rather than an argument because
Pydantic field validation is precisely the case
`resolve_dataset_profile`'s own docstring reserves the Regime-A seam for
(*"Pydantic field validation and module-scope constants, which run at
import or validation time with no caller to thread a parameter
through"*). Resolution is idempotent — a concrete list passes through
untouched — so `apply_monitored_files`' `model_validate` round-trip and
`core/resume.py`'s mirror are unaffected.

**One safety property added deliberately.** Any *other* string in
`peek_file_indices` now raises. Without it a typo'd marker is a truthy
string, and `_resolve_indices` would iterate it **character by
character**, peeking file indices like `'t'` — a silent wrong answer
where an error belongs. `CheckRef.config` is `dict[str, Any]`, so no
type declaration catches this; it is validator logic and it has its own
test.

**Files changed (production)**: `execute_tools/dataset_config.py`,
`execute_tools/sample_set_builder.py`,
`execute_tools/health_checks/config.py`, `configs/health_checks.yaml`,
`configs/health_checks_baseline_observe_mode.yaml`.

**Tests changed**: `tests/unit/execute_tools/test_sample_set_builder.py`
(imports the declaration instead of the deleted constant — the assertion
body is unchanged), `tests/unit/agent/tune_ml_hyperparam_agent/test_formal_sample_set.py:212`
(the uncoupled `{0, 10, 19}` duplicate §3 identified — now reads the
declaration, so it follows a declaration change),
`tests/unit/execute_tools/test_step02a_c2_profile_injection.py:243` (the
one direct construction; the added fields are legal against **its**
`num_files=3`, not TIDMAD's 20, which strengthens the very invariant that
test exists for).

**Test added**: `tests/unit/execute_tools/test_step02c_task_file_set_declarations.py`
— declaration legality as ONE concept asserted across BOTH fields (per
the project's "test the concept, not the field" rule), the §8.1 injection
shape over both shipped configs, marker idempotence, and the
unrecognized-marker rejection.

**Explicitly NOT in this commit** (they are C3): the campaign validator's
`[3, 10, 17]` trigger and `_DEFAULT_FILE_RANGE`. `range(20)` was **not**
converted into a declared field, and no `all_files` field exists.

### 24.8 C2 mutation dossier — including one that SURVIVED

| # | Failure class (§19) | Mutation | Observed |
|---|---|---|---|
| M-C2-1 | 1 — anchor consumer still reads a literal | `sample_set_builder.py`: `files = list(resolved_profile.anchor_selection_files)` → `files = [0, 10, 19]` | **SURVIVED at first — see below.** After the fix: **CAUGHT**, `1 failed, 54 passed` |
| M-C2-2 | 2 — blocking peek consumer ignores declaration B | `config.py`: the resolved value → the literal `[3, 10, 17]` | **CAUGHT** — `1 failed, 311 passed` |
| M-C2-3 | §8.1 injection leak | resolve the declaration where `peek_file_indices` is **absent** (the tempting-but-wrong shape §8.1 names) | **CAUGHT, hard** — `10 failed, 302 passed`, including BOTH pinned config shas, the Step-00 HC-1 golden deep-equal, and `test_runner.py::test_nonempty_check_config_passed_verbatim` |

#### The survived mutation, and what it exposed

```text
Previous assumption (implicit in §11.2's acceptance criteria):
  the existing anchors oracles — GOLDEN["anchors"] and
  test_only_anchor_files — establish that the migrated consumer reads
  the declaration.

Audit evidence:
  M-C2-1 replaced the declaration read with the literal [0,10,19] and
  the ENTIRE selection suite stayed green (53 passed, 0 failed).
  Of course it did: under TIDMAD the declaration IS [0,10,19], so no
  TIDMAD-only assertion can tell "reads the declaration" apart from
  "still hardcodes the same three numbers". test_only_anchor_files now
  imports the declaration, which makes it follow a change — but it
  compares the consumer's output against the same profile the consumer
  would ignore, so it is satisfied either way.

Corrected understanding:
  a compatibility oracle can never prove an authority migration. Only a
  profile declaring something OTHER than TIDMAD separates the two, and
  that evidence belongs at C2 — §11.2 asks for it — not deferred to C4.

Implementation consequence:
  added TestTheDeclarationsAreActuallyTheAuthority: one reachability
  test per declaration, topology held at TIDMAD, only the declaration
  varied. Anchors is driven through the real `build_sample_set` with an
  explicitly supplied profile; the blocking peeks are driven by binding
  a contrast profile and loading the SHIPPED config through an explicit
  path (the default-path cache would otherwise be able to serve a
  config resolved under a different profile).

Validation consequence:
  M-C2-1 and M-C2-2 now both red, each on exactly one test. C4 still
  owns what these do NOT cover: atomicity (asserting the UNVARIED
  declaration's consumer is unchanged) and cardinality variation.
```

This is the 02a-M9 / 02b-M10 lesson recurring, and it is recorded rather
than quietly patched: **the mutation was the only thing that noticed.**

### 24.9 CP-C1 — DECLARATIONS LIVE + TIDMAD PARITY: **PASS**

```text
Validation:
  scope 1:  tests/unit/core/ + test_formal_sample_set.py
            -> 2395 passed, 2 skipped, 0 failed — 270.58 s
  scope 2:  tests/unit/execute_tools/ + test_campaign_artifacts.py
            + test_formal_sample_set.py
            -> 834 passed, 1 skipped, 0 failed — 17.13 s
               (the first pass surfaced exactly ONE failure, diagnosed
               below; this is the re-run after the fixture fix)
  scope 3:  tests/unit/execute_tools/test_step02c_task_file_set_declarations.py
            -> 18 passed — 0.09 s

  Timing note: an earlier pass of scope 2 reported 346 s. That was CPU
  contention from three concurrent pytest processes on this box, not a
  slow suite — run alone it is 17 s. Recorded so a future session does
  not mistake the suite for expensive and start trimming scope.
  static:   ruff check clean; ruff format --check "585 files already
            formatted"
  pyright:  UNAVAILABLE LOCALLY — the venv ships pyright but Node is
            v10.19.0 and its bundled bundle needs >= 14; invoking it
            throws a JS parse error. Recorded, not worked around;
            blocking exact-head CI is the type authority.
```

Acceptance against §11.2's criteria:

- [x] Declaration A resolves to exactly `[0,10,19]`, B to exactly
      `[3,10,17]` under TIDMAD.
- [x] `GOLDEN["anchors"] = e025a270e0b1acc1` byte-identical, asserted by
      running `test_sample_set_builder.py` — the golden and every
      assertion body are **unmodified**; only the deleted constant's
      import changed.
- [x] The **hc1 golden** (`test_step00_health_config_baseline.py`) and
      **both pinned config shas** (`3b5521…655b74`, `d133a12d…5ef58d`)
      byte-identical, modules unmodified. Under the §8.1-violating shape
      all three go red (M-C2-3), so this is a live guard, not a
      coincidence.
- [x] `segment_anchors.json` untouched — `test_step00_numeric_baselines.py`
      green, no file in the diff.
- [x] **Two** declarations exist, not one merged mapping; no `groups`
      field, no `all_files` field.
- [x] No surviving literal at a C2-owned site: `ANCHOR_FILES` is deleted
      (`grep -rn ANCHOR_FILES` finds no production hit) and the six YAML
      `[3, 10, 17]` literals are gone from the two shipped configs. The
      remaining `[3, 10, 17]` in `campaign_artifacts.py:57` is **C3's**,
      by plan.
- [x] Mutations: A and B each proven live and independent (§24.8).

#### The one failure, diagnosed before it was touched

```text
Failure:
  test_step02a_c3_profile_transport.py::TestConfigFileRoundTrip::
  test_profile_survives_json[contrast]
  ValueError: anchor_selection_files=[0, 10, 19] indexes files [10, 19]
  that this dataset does not have (num_files=3).

Classification: TEST FIXTURE, and the validator behaving correctly.

Evidence:
  `_contrast_profile` builds its variant with `model_copy`, which does
  NOT revalidate. Narrowing `num_files` to 3 while inheriting TIDMAD's
  declared file sets produces an internally incoherent profile — one
  that claims a 3-file dataset and declares file 19. It survived in
  memory and was caught only where this test round-trips it through
  `load_dataset_profile`, i.e. through `model_validate`. That is exactly
  the defect class the new validator exists to catch, on exactly the
  parent->child transport 02a built.

Fix: the fixture now narrows its declared sets to its own topology.
  NOTHING is derived on the production side — a task declares its own
  sets, and auto-narrowing them would be inventing behaviour.

Broader consequence, recorded for C4:
  every `model_copy`-built contrast profile in the repo can now be
  incoherent without failing, because `model_copy` skips validation.
  Only ONE test round-trips, which is why only one failed. C4's contrast
  fixtures must declare sets legal for the topology they declare.
  Production is unaffected: `grep` finds NO production `model_copy` on a
  `DatasetProfile` — production either uses the shipped `TIDMAD_PROFILE`
  or validates on load.
```

---

### 24.10 C3 — the campaign trigger and the topology-derived all-files tier

Two literals removed. They are separate commits' worth of thinking even
though the diff is small, because they are **different classifications**:
one is a policy TRIGGER whose authority moves, the other is DERIVED
topology that should never have been a constant.

**Campaign trigger** (`core/campaign_artifacts.py`). The hardcoded
`[3, 10, 17]` becomes the bound task's declared health-peek set, resolved
**once per call** into a local before the gate loop. The import is local
to the function, mirroring the existing convention in
`validate_phase1_baseline` and guaranteeing call-time resolution — a
module-level default would freeze a topology at import (02b §13.9).

**The comparison operator is untouched**: still `requested == declared`,
exact and ordered. §6.1's trap is that `set()` or `sorted()` would newly
ENFORCE reordered lists that skip today. C1's D1-c pins that for TIDMAD's
order and `test_a_reordered_declared_set_still_skips` pins it against a
contrast declaration; mutation M-C3-3 reds **both**, which is the shape
that distinguishes "the comparison is exact" from "TIDMAD happens to be
special-cased".

**All-files tier** (`pearson_dispersion.py`, `per_file_output_std.py`,
`spectral_peak_ratio.py`). `_DEFAULT_FILE_RANGE: range = range(20)` is
**deleted** from all three; tier 3 becomes
`list(range(resolve_dataset_profile().dataset.num_files))`, evaluated
inside `_resolve_files`. Nothing else about the resolver moves: tier
ORDER is unchanged, tier 1 still `sorted({int(i) …})`, tier 2 still
`sorted(keys)`, tier 4 still `[]`, and the blocking resolver's
`[min(paths)]` / `[0]` is not touched at all. **Only the tier-3 VALUE
moved**, exactly as §4.2 scopes it.

`spectral_peak_ratio.py` already resolved the profile for
`sampling_frequency` (`:56`), so its population now comes from the same
object it was already reading — no new resolution seam. The other two
gained the import.

**No declared `all_files` field exists**, and
`test_all_files_is_not_a_declared_field` asserts that mechanically across
every field name on the profile, so the §12.2 stop condition is guarded
rather than merely intended.

**Tests added.** Both exist because, under TIDMAD, the migrated code and
the literal it replaced produce identical answers — the same blind spot
that let M-C2-1 survive:

- `tests/unit/core/test_step02c_campaign_declared_trigger.py` — under a
  task declaring `[2, 8, 14, 18]`, that set triggers enforcement **and**
  TIDMAD's `[3, 10, 17]` stops triggering it. The second half matters on
  its own: an implementation enforcing on *"declared OR [3,10,17]"* would
  satisfy the first half alone.
- `tests/unit/execute_tools/health_checks/test_step02c_derived_all_files.py`
  — the fallback population tracks `num_files` in **both** directions
  (7 and 32). `7` alone would still pass against a hidden `min(20, n)`;
  `32` alone would still pass against a `max`. Together they pin
  derivation.

The TIDMAD compatibility oracle (`test_health_scope.py:246-251`,
`set(range(20))`) is **reused unmodified and deliberately not
duplicated** — R4 upheld.

### 24.11 C3 mutation dossier

| # | Failure class (§19) | Mutation | Observed |
|---|---|---|---|
| M-C3-1 | 3 — campaign validator retains literal `[3,10,17]` | `declared_health_peek = resolve_dataset_profile().health_peek_files` → `= [3, 10, 17]` | **CAUGHT** — `2 failed, 26 passed`; both halves of the authority claim red |
| M-C3-2 | 4 — all-files retains the fixed-20 assumption | `pearson_dispersion.py`: derived range → `range(20)` | **CAUGHT** — `2 failed, 299 passed`; both directions (`fewer`, `more`) red, and only this module's ids |
| M-C3-3 | campaign POLICY change (§6.1) | `requested == declared` → `sorted(requested) == sorted(declared)` | **CAUGHT** — `2 failed`: the C1 TIDMAD pin **and** the C3 contrast pin. Exactly the pair that separates "exact comparison" from "TIDMAD special-cased" |

No survivors. M-C3-2 was run on one of the three byte-identical
resolvers: the question is whether the derived population is real, and
one mutant answers it — three would be one mutant per test (§19).

### 24.12 CHECKPOINT A — Stage-A TIDMAD parity complete: **PASS**

Per-surface against §9, never as one "health behaviour unchanged"
assertion:

| §9 | Surface | Evidence at this head |
|---|---|---|
| A1 | anchor selection identity | `GOLDEN["anchors"] = e025a270e0b1acc1` byte-identical; `test_sample_set_builder.py` assertions unmodified |
| A2 | anchor population | resolves exactly `[0,10,19]` |
| A3 | anchors strategy identity + partial-scope rejection | unchanged — `build_sample_set`'s strategy branch, seed derivation and scope guard are untouched |
| B1 | blocking peek resolution | resolves exactly `[3,10,17]`; **HC-1 golden deep-equal** and **both pinned config shas** (`3b5521…655b74`, `d133a12d…5ef58d`) byte-identical, modules unmodified |
| B2 | blocking tier-2/tier-3 | `[min(paths)]` / `[0]` — `_multi_file_peek.py` not in the diff at all |
| C1 | recording full-file population | `set(range(20))` under TIDMAD — `test_health_scope.py:246-251` unmodified |
| C2 | recording tier-1 beats tier-2 | the C1-captured pin, green across C2 and C3 |
| D1 | campaign exact-list matrix | C1's full matrix green **unmodified** across the trigger migration |
| E1 | `apply_monitored_files` override | unchanged; `apply_monitored_files` not in the diff |
| E2 | `validate_health_scope` | unchanged; not in the diff |
| F1 | thresholds / verdicts / `gate_role` / `on_fail` | unchanged — no threshold or action value appears in the diff |
| G1 | `segment_anchors.json` | untouched; `build_anchor_map.py` not in the diff |
| G2 | SampleSet digests / algorithm / seeds / portions | unchanged — the only edit inside `build_sample_set` is where the anchors branch OBTAINS its list |
| G3 | DataScope + runtime override precedence | unchanged |

```text
Validation:
  command:  .venv/bin/python -m pytest tests/unit/execute_tools/ \
                tests/unit/core/ tests/unit/agent/tune_ml_hyperparam_agent/ -q
  purpose:  every Stage-A surface in the §9 table, at the C3 head
  result:   4236 passed, 3 skipped, 0 failed — 388.34 s (0:06:28)
            (pytest rc=0, read from the log; the wall time reflects an
            unrelated 211%/133%-CPU workload sharing this host, not
            suite cost)
  focused:  329 passed — campaign + health_checks + the two new C3
            modules, 1.89 s
  static:   ruff check .          -> All checks passed
            ruff format --check . -> 833 files already formatted
  pyright:  unavailable locally (Node v10.19.0 < 14) — exact-head CI
```

The scope is the honest affected set — selection, health checks, core
and the tuner node — and it is **not** the full local suite. That single
terminal run is reserved for the assembled Step-02 head (§13.2).

---

### 24.13 C4 — the 4.8-C atomic contrast (test-only)

`tests/unit/execute_tools/test_step02c_c4_file_set_contrast.py`, 13
tests, **zero production diff**.

Two atomic subcases, never one combined fixture:

```text
C-anchor   vary ONLY anchor_selection_files -> [2, 7, 11, 15, 18]  (FIVE)
           anchors follow;  blocking peeks + campaign trigger UNCHANGED

C-health   vary ONLY health_peek_files      -> [6, 13]             (TWO)
           blocking peeks + campaign trigger follow;
           anchors UNCHANGED;  recording gates UNCHANGED at all-files
```

Atomicity is **machine-checked** with 02b B4's `_diff_paths` helper —
`_diff_paths(TIDMAD.model_dump(), contrast.model_dump())` must equal
exactly `["anchor_selection_files"]` / `["health_peek_files"]`. A prose
promise would not survive a careless fixture edit. Topology is asserted
identical to TIDMAD's in both subcases: 02b's `num_files` contrast is
deliberately NOT reused (§11.4), because re-answering another child's
question would also drag in the Step-10 residue §12.1 avoids.

**Cardinality varies, per §20a Q11**: five and two against TIDMAD's
three, in both directions, with a test asserting `len(declared) != 3` so
the property cannot silently erode.

**All-files is not a third axis.** It derives from topology, and its
genericity is proved as derived reachability in C3's
`test_step02c_derived_all_files.py`.

### 24.14 C4 mutation dossier — the classes only a contrast can expose

The mutations for "consumer still reads its literal" were already killed
at C2/C3 (M-C2-1, M-C2-2, M-C3-1, M-C3-2) and are not repeated. C4 adds
the two classes that only an atomic, cardinality-varying contrast can
reach:

| # | Class | Mutation | Observed |
|---|---|---|---|
| M-C4-1 | §12.2 — the two declarations collapse, or a consumer reads the WRONG one | anchors reads `health_peek_files` | **CAUGHT** — `2 failed, 11 passed`: `TestCAnchor::test_the_anchors_strategy_follows_the_declaration` **and** `TestCHealth::test_the_anchors_population_is_UNCHANGED`. The second is the "unvaried consumer" assertion §19 exists for; without it this mutant would look like an ordinary single-consumer bug |
| M-C4-2 | a consumer silently assumes a TRIPLET | `files = list(profile.anchor_selection_files)[:3]` | **CAUGHT by the rung ALONE** — `1 failed, 67 passed`. Every other test stayed green, **including C2's reachability test**, whose contrast declaration `[1, 5, 12]` is itself three files. This is §20a Q11 vindicated empirically: a membership-only contrast would have missed it |

### 24.15 CHECKPOINT B — generic file-set semantics complete: **PASS**

Against §11.4's acceptance criteria:

- [x] Each subcase varies **exactly one** declaration, machine-checked
      against the TIDMAD declaration rather than asserted in prose.
- [x] The **unvaried** consumer is asserted unchanged in each subcase —
      and M-C4-1 proves that assertion is load-bearing.
- [x] A consumer still holding its literal reds its subcase (M-C2-1,
      M-C2-2, M-C3-1 at their own commits; M-C4-1/M-C4-2 here).
- [x] Zero production diff.
- [x] No non-declaration axis moves: topology, geometry, encoding,
      channels, DataScope, strategy, seed and portion are all held, and
      the topology hold is asserted.

**Both declared task-owned semantics now vary through declarations with
no source-code edit.** That is the capability statement of §1, and it is
now evidenced rather than intended.

---

### 24.16 PR-02c CHILD CHECKPOINT C — live consumer evidence: **PASS**

`tests/unit/execute_tools/test_step02c_checkpoint_c_live_consumers.py`,
16 tests, 1.46 s.

§12.1's rule — *"a test that constructs a declaration and calls a
resolver directly does NOT satisfy this"* — is honoured literally.
**Nothing in this module calls `_resolve_indices` or `_resolve_files`.**
Each claim goes through the entry point production uses:

| §12.1 requirement | Production entry point | Evidence |
|---|---|---|
| a real HealthGate evaluation resolves monitored files from declaration B | `runner.evaluate_gate(gate_id, ctx, config_path)` — what the tuner calls at a round boundary; loads the SHIPPED YAML, dispatches registry skills | opened set `== {6, 13}` |
| the files actually opened/evaluated follow it | the checks really open real HDF5 files written for the test; the observable is captured at the path-resolution boundary the skills go through | same assertion — this is the judged population, not a resolver's return value |
| the campaign validator consumes the same declared semantic | `decide_phase1_reuse` — the entry point whose output is `action`, so the branch is exercised as POLICY | an incomplete declared peek → `action="train"`; the same shape requesting TIDMAD's `[3,10,17]` → `action="reuse"` |
| the anchors path resolves from declaration A | `build_sample_set(..., trial_strategy="anchors")` | population `== [2,7,11,15,18]` |
| no old literal survives unnoticed | static sweep over the eight migrated sites, comments stripped | green |
| HealthGate thresholds and verdict semantics unchanged | `evaluate_gate` with degenerate data | healthy → `passed=True`/`CONTINUE`; degenerate declared files → `passed=False`/`INVALIDATE_ROUND` (the shipped `on_fail`) |

Two assertions carry more than they look:

- **The recording gate opens all twenty** at the real evaluation
  boundary. This is §8.1's leak guard where it actually matters: had the
  declaration reached the keyless path, it would open two files — and
  every one of the recording gate's own tests would still pass, because
  a two-file population is perfectly self-consistent.
- **A degenerate file OUTSIDE the declaration does not flip the
  verdict.** File 3 is TIDMAD's first declared peek file; under a task
  declaring `[6, 13]` it must be irrelevant. This distinguishes "the
  declaration decides what is READ" from "the declaration decides what
  is JUDGED" — only the second is the capability.

Topology is held at TIDMAD and only the declarations vary, per §12.1 —
a non-TIDMAD topology would import the Step-08/Step-10 residue this PR
does not own. No real LLM; no scientific-quality result claimed.

#### Two defects found while building it, both in the test, both recorded

```text
1. IMPORT PROVENANCE — the contract's own hazard, hit live.

   A standalone diagnostic script run as
   `python /home/yuema137/.claude/jobs/.../diag.py` reported that the
   campaign branch fired under a contrast profile, and that
   TIDMAD_PROFILE had no `health_peek_files` attribute at all.

   Cause: for a SCRIPT, `sys.path[0]` is the script's own directory, not
   the cwd. The editable-install finder then resolved `execute_tools` to
   /home/yuema137/SIDERIUS — the MAIN CHECKOUT, without this branch's
   changes. The `python -c` invocations used elsewhere put cwd first and
   were unaffected, as is pytest via its rootdir.

   Re-run with the worktree explicitly on sys.path, the "finding"
   evaporated: the only error was a checkpoint hash mismatch.

   Consequence: no production defect. Recorded because a session that
   trusted that output would have "fixed" a bug that does not exist.

2. AN OVER-DETERMINED VERDICT in the first draft of this module.

   `_record` omitted `checkpoint_sha256`, so `validate_phase1_baseline`
   reported a hash mismatch and BOTH campaign cases returned "train".
   The retrain case passed — for the wrong reason: the peek branch had
   decided nothing. Fixed by stamping the real sha, so the declared-peek
   branch is the ONLY variable between the two cases.

   This is why the pair is asserted in BOTH directions. A single
   assertion that "an incomplete peek forces a retrain" is satisfied by
   any unrelated invalidity.
```
