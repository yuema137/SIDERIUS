# Step 05a — Tuner data selection & sample-set construction — detailed design

Part of **Step 05** (roadmap §15 step 5, §7b). Step 05's three submodule
designs (`step_05a_*`, `step_05b_*`, `step_05c_*`) **jointly constitute the
Step-05 acceptance entry** per the frozen naming convention (roadmap §19).
The Step-level completion contract lives in roadmap **§15.1a**.

| Field | Value |
|---|---|
| Status | **DRAFT — READY FOR OPERATOR REVIEW. Not frozen. Implementation NOT authorized.** |
| Design base | `13b08550` — master after Step 04 Checkpoint E (04a `6458dd95`, 04b `096f2dbb`) |
| Depends on | **Step 02** (Dataset Profile) only |
| Blocks | nothing — see §7 |
| Roadmap row | §15.1 `§7b Tuner data selection` |

---

## 0. Why this design is much smaller than the roadmap predicted

The roadmap's §7b entry was written before Step 02 landed. Re-auditing the
production tuner at `13b08550` shows **Step 02b/02c already delivered the
capability §7b was created to deliver.**

```text
Previous assumption (roadmap §7b):
  "Couplings: DATASET_CONFIG import (:76), anchors-required-in-trial
   (:3800-3808), divisibility validation (:1099-1128), legacy single-file
   fallback (:4428-4433). Target: consume §4's resolved profile; zero
   direct singleton reads."

Audit evidence at 13b08550:
  ml_hyperparameter_tune_agent.py:4425-4448 already resolves the run
  profile ONCE and passes it EXPLICITLY to BOTH construction sites:

      run_profile = resolve_dataset_profile()
      train_sample_set = build_sample_set(..., profile=run_profile)
      eval_sample_set  = build_sample_set(..., profile=run_profile)

  with an in-source comment naming this as the Step-02b change and its
  two consequences. `anchor_selection_files=[0, 10, 19]` moved into
  `DatasetProfile` at Step 02c (dataset_config.py:487, :586). Seeds and
  ordering resolve through `ordering.py` (V19 PR 2), not through dataset
  semantics.

Corrected understanding:
  The ambient-singleton defect in SampleSet CONSTRUCTION is closed. What
  survives is a strictly smaller residue: five reads of the module-level
  TIDMAD singleton that sit on the tuner's *validation, scope and
  accounting* path rather than its construction path.

Implementation consequence:
  05a is a residue-closure PR, not the selection redesign §7b described.
  Its honest capability is stated in §1 and deliberately does not claim
  the Step-02b work.
```

**This design does not re-litigate Step 02.** It finishes Step 02's
consumer migration inside the tuner.

## 1. Observable final capability

> Every dataset fact the tuner uses to **validate, scope and account for**
> an attempt comes from the **run-resolved `DatasetProfile`** — the same
> object already threaded into sample-set construction — instead of the
> module-level `TIDMAD` singleton. A run bound to a non-default topology
> can no longer be validated, scoped or accounted against TIDMAD's numbers
> while selecting against its own.

**Deliberately NOT claimed:**

- not that sample-set *construction* becomes profile-driven — Step 02b did
  that, and this PR must not re-assert it as its own;
- not any change to strategy semantics, seeds, ordering, or portions;
- not metric, policy, resource or execution genericity.

## 2. Source census — the complete residue

Every module-level `DatasetConfig` singleton read in the tuner at
`13b08550` (`from execute_tools.dataset_config import TIDMAD as
DATASET_CONFIG`, `:76`):

| Site | Read | Path | Consequence under a contrast profile |
|---|---|---|---|
| `:1090` | `_validate_data_config(dataset_config=DATASET_CONFIG)` default arg | sample-shape **legality** | divisibility validated against TIDMAD's `psd_segment_length`; a legal config for the run's own topology can be rejected, or an illegal one accepted |
| `:2731` | `DATASET_CONFIG.num_files` → `full_scope=list(range(...))` | run-invariant **stamping/validation** | full-scope identity computed from the wrong file count |
| `:3657` | `DATASET_CONFIG.num_files` → `scope_is_partial` | **partial-scope** detection | a full scope can be mis-classified as partial (or vice versa), changing sampling legality |
| `:4465` | `DATASET_CONFIG.segments_per_file` | legacy `single_file` **segment accounting** | record/reflector segment counts wrong |
| `:4470` | same, eval side | legacy `single_file` accounting | same |

`_validate_data_config` already delegates the legal-value enumeration to
`dataset_config.valid_segmentation_sizes()` (`:1114`), so the **rule** is
already owned by Step 02's authority — only the **object it is asked about**
is ambient.

**Reachability of the legacy path.** `mode = "single_file"` is reached when
`trial_allowed` is false (`:4294-4298`), and `trial_allowed =
agent_input.is_trial` (`:3719`) is an operator CLI flag. The path is
**live legacy, not dead** — it must be migrated or explicitly recorded, not
deleted as unreachable.

## 3. Authority map

| Value | Disposition | Why |
|---|---|---|
| `psd_segment_length`, `segments_per_file`, `num_files` | **DERIVE** from the run-resolved `DatasetProfile.dataset` | Step 02 already declares them; the tuner must consume, not re-import |
| the divisibility rule itself | **already DERIVE** (`valid_segmentation_sizes()`) — unchanged | Step 02 owns it |
| strategies, portions, seeds, ordering | **KEEP RUNTIME / POLICY** | framework mechanics, not task semantics |
| `file_index` legacy field | **KEEP RUNTIME (legacy)** — record-only | a §7a/record concern, not a dataset fact |

**No new configuration field is created.** This PR only changes *which
already-declared object* five call sites read.

## 4. Upstream authorities consumed / first production consumer

Consumes **Step 02's `DatasetProfile`**, already resolved at `:4430`.
First production consumer is the **tuner's own validation/scope/accounting
path** — a consumer that exists today and is exercised by every run.

The design's one real structural question: `run_profile` is currently
resolved *inside* the round loop (`:4430`), while `:2731` and `:3657` run at
**startup**, before the loop. Implementation must resolve the profile once at
run scope and thread it to both regions — **not** call
`resolve_dataset_profile()` a second time, which would reintroduce the exact
ambient-resolution defect Step 02b removed.

## 5. Scope / non-goals

**In scope**: the five sites in §2; threading a single run-scoped profile to
startup and loop regions; deleting the `DATASET_CONFIG` import when the last
read is gone.

**Non-goals**: `build_sample_set` internals; strategy/portion/seed/ordering
semantics; `TrialConfig` field set; anchors; DataScope semantics; anything in
05b or 05c; any planner/policy or metric surface.

## 6. Stage-A compatibility surfaces

| Surface | Criterion | Oracle status |
|---|---|---|
| `trial_config` serialized JSON | **deep-equal** under TIDMAD | EXISTING — Step-00/Step-02 baselines |
| train/eval `SampleSet` identities | **deep-equal** under TIDMAD | EXISTING |
| `_validate_data_config` accept/reject + diagnostic text | **byte-identical** | **MISSING — Checkpoint 0 captures it** |
| `scope_is_partial` / stamped full-scope invariants | **identical** | EXISTING (run-invariants lock) |
| legacy `single_file` segment counts | **identical** | **MISSING — Checkpoint 0 captures it** |

Checkpoint 0 adds only the two missing captures. It must **not** duplicate
Step-02's Dataset Profile baselines.

## 7. Dependencies

Depends on **Step 02 only**. **Independent of 05b and 05c**: 05b consumes
`SampleSet` *values* (`resolve_training_workload(sample_set, …)`), whose shape
this PR is required to leave byte-identical; 05c consumes execution
transport. Neither reads the five sites above.

`05a → 05b → 05c` is a **preferred implementation order** (lowest risk
first), **not** a dependency. Any order is semantically legal.

## 8. Stage-B atomic contrast

**One axis: the resolved dataset topology, through the tuner's validation
and accounting path.**

Reds when the tuner validates or accounts against TIDMAD while the run is
bound to a contrast profile — i.e. when any of the five reads survives.

Reuses Step 02's existing contrast profile fixture. This PR must prove
**consumption**, not re-prove the Dataset Profile abstraction: asserting a
contrast profile is constructible is Step 02's test, not this one.

## 9. Checkpoint C — live integration

The **real production tuner path** (not a helper) must validate, scope and
account for an attempt under a bound contrast profile, with the resulting
`TrialConfig` / segment counts / partial-scope determination following the
**bound** profile. Deterministic — no LLM, no training, no GPU.

## 10. Failure classes

1. A site keeps reading the singleton → silent TIDMAD legality under another
   topology (the defect this PR closes).
2. **Ambient re-resolution** — a site calls `resolve_dataset_profile()`
   itself instead of receiving the run-scoped object. Passes a naive test
   while restoring the Step-02b defect. *The guard must assert the tuner
   resolves the profile exactly once per run.*
3. The legacy `single_file` accounting is "fixed" by deleting the branch →
   silent behavior change on a live operator path.
4. A dataset fact is copied into `TrialConfig` as a new field → a second
   authority.

## 11. Test disposition

| Test family | Verdict |
|---|---|
| Step-02 profile-injection tests | **KEEP** — upstream, untouched |
| tuner `_validate_data_config` tests | **UPGRADE** — parameterize on an injected profile |
| any pin asserting `DATASET_CONFIG` is read | **REWRITE** — it defends the defect |
| SampleSet/TrialConfig baselines | **KEEP** — the parity oracle |

## 12. Gates

| Gate | Decision | Flip condition |
|---|---|---|
| **Gate 1** | **NOT REQUIRED** — no LLM-visible surface changes | any rendered prompt byte or `LLMBridge` kwarg changes |
| **Gate 2** | **NOT REQUIRED** — no execution, training, inference, scoring or resource semantics change; the surfaces are validation/scope/accounting, all deterministic | a real execution or admission behavior becomes unprovable deterministically |

## 13. Validation budget

Checkpoint 0 captures (2) → focused unit tests on the five sites → the
single-resolution guard (§10.2) with a mutation → Checkpoint C → ruff/pyright
→ exact-head CI. **No local full suite. No Gate. No real LLM/GPU.**

## 14. Rollback boundary

`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` plus its
directly affected tests. Reverting restores the five ambient reads and
nothing else.

## 15. Convergence-ledger implications

Supplies the **second design** the §14 *Sample-shape legality (divisibility)*
row is waiting for (`§4, §6, §7b`, owner `§4`, "≥2 completed designs"). This
design's finding: the rule is **already** owned by Step 02 and delegated to
`valid_segmentation_sizes()`; only the object was ambient. **Disposition:
RECORD ONLY — no shared legality wrapper.** Threshold met ≠ abstraction
justified.

The §14 *SampleSet type + JSON key coercion* row wants "one consumer design".
05a is **not** that evidence — it does not change SampleSet transport. 05b is
the closer candidate (§15 of that design).

## 16. Stop conditions

- Closing a site requires a new dataset field or a second authority → STOP.
- The legacy `single_file` path cannot be migrated without changing operator
  behavior → surface it; do not delete the branch.
- Threading the run-scoped profile to startup requires re-ordering run phases
  → STOP (phase order is frozen; roadmap §7a/CLAUDE.md).

## 17. Implementation milestones (semantic — commit count NOT frozen)

1. Checkpoint 0: capture the two missing baselines.
2. Thread one run-scoped profile to the startup region (`:2731`, `:3657`).
3. Thread it to the legality and accounting sites (`:1090`, `:4465`, `:4470`);
   drop the `DATASET_CONFIG` import.
4. Single-resolution guard + Stage-B rung + Checkpoint C.

## 18. Implementation ledger

*(empty — populated at implementation kickoff)*

## 19. Remaining operator decisions

**None.** The only judgement call — whether the live legacy `single_file`
accounting is migrated or recorded — is resolved from source in §2
(live, therefore migrated).
