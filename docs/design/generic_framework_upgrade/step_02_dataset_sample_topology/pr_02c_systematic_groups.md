# PR 02c — Systematic group semantics (Step 02, child 3 of 3)

## Status

**REVISION 2 — pending the parent's operator freeze. NOT FROZEN.
IMPLEMENTATION NOT AUTHORIZED.**

Parent: [`../step_02_dataset_sample_topology.md`](../step_02_dataset_sample_topology.md).

Position in the DAG: **after 02a** semantically (the declaration lives
on the profile). It does not technically depend on 02b — but the
governance order is FROZEN as `02a → 02b → 02c` because **02c is the
Step-02 FINALIZER** (parent §6.2).

## 0. Finalizer duties (in addition to this child's own scope)

Once all three executable capabilities are present, 02c owns:

- assembled Step-02 **Checkpoint C** reconciliation;
- the ONE Step-level **Gate 2** — real LLM + real training, trial-only
  smoke, `--llm_config llm_configs/openai_tiered_pro.json`;
- the single **local full unit suite** at the assembled head;
- **Checkpoint E** — §15.1 row, §14 ledger rows, folder README, parent
  status;
- Step-02 closeout.

This is governance, not a technical dependency. It exists so aggregate
evidence has a named owner instead of falling to whichever child merges
last.

## 1. Scope

**OWNS**: named group declarations (the frequency bands) and
group-aware selection, replacing four independent literals:

| Literal | Site | Consumer |
|---|---|---|
| `[0, 10, 19]` | `sample_set_builder.py:24` `ANCHOR_FILES` | anchors strategy |
| `[3, 10, 17]` | shipped `configs/health_checks.yaml` `peek_file_indices` | health gates |
| `[3, 10, 17]` | `core/campaign_artifacts.py:57` — `if requested == [3, 10, 17]:` | campaign-artifact validation |
| `range(20)` ×3 | `health_checks/{pearson_dispersion,per_file_output_std,spectral_peak_ratio}.py` `_DEFAULT_FILE_RANGE` | health-check file fallback |

**DOES NOT OWN**: HealthGate policy, thresholds or verdict semantics
(Step 08); which files an operator scopes a run to (`DataScope`, a
runtime input); the anchors ARTIFACT contents.

## 2. Why this is a PR

After it merges, a task declares its own band structure and anchors,
health peeks and campaign validation all read that declaration.

Its consumers are disjoint from 02a's and 02b's (health + campaign
validation, not the data path), its oracle is different (gate verdicts,
not tensors or digests), and its failure class is different: a wrong
group map silently changes **which files the health gates judge** — a
scientific-integrity failure rather than a crash.

`core/campaign_artifacts.py:57` is the sharpest evidence the concept has
no owner: a *validator* branches on an exact list value.

## 3. Compatibility contract

| Surface | Criterion | Baseline |
|---|---|---|
| Anchors identity | the declared map resolves to exactly `[0, 10, 19]`; the anchors artifact and `segment_anchors.json` untouched | EXISTS (Step-00 numeric baselines) |
| Health peek | the shipped declaration resolves to exactly `[3, 10, 17]`; gate verdicts identical on fixture outputs | PARTIAL — behaviour tested; **literal-vs-declaration equivalence MISSING → capture first** |
| Full-file fallback | the three `_DEFAULT_FILE_RANGE` sites resolve to the same file list as `range(20)` | **MISSING → capture first** |
| Campaign validation | the validator accepts/rejects the same records as today | **MISSING → capture first** |

## 4. Checkpoints

| CP | Closing evidence |
|---|---|
| 0 | the three missing equivalence pins captured BEFORE the change |
| A | every §3 criterion identical under TIDMAD |
| B | **4.8-C group semantics only** — TIDMAD shape, a DIFFERENT declared group map; anchors and peeks follow the declaration |
| C | health gates evaluate a real round through the declared map, and the campaign validator runs on a real record |
| D | targeted → affected package (health + core) → focused integration/mutation → **exact-head CI**; then, as FINALIZER, the ONE local full unit suite at the assembled Step-02 head |

**Mutations**: change the declared map and confirm anchors AND peeks
both follow (a literal left behind reds only one); revert
`campaign_artifacts` to its literal comparison and confirm the
equivalence pin reds.

## 5. Gates

- **Gate 1 — NOT REQUIRED** (roadmap §17.0; assignment table: config /
  loader-renderer → Unit only).
- **Gate 2 — RUN BY THIS CHILD as FINALIZER**, once, on the assembled
  Step-02 head. Fitting: Gate 2 exercises HealthGates, and this is the
  child that changes which files those gates judge. Its Step-02 PASS
  criteria are the parent §10.2 table's, including the precise
  SampleSet criterion (compare against the deterministic reference
  resolution for Gate 2's ACTUAL inputs — never a digest captured under
  different arguments).

## 6. Convergence note

Whether §8 HealthGates should eventually own its own view of groups is
**Step 08's** call. This child declares and consumes; it does NOT merge
the §14 "systematic groups" row (parent §12 — DO NOT MERGE YET).

## 7. Stop conditions

- anchors and health peeks end up reading two different declarations;
- the anchors artifact or `segment_anchors.json` changes;
- HealthGate thresholds, policy or verdict semantics change — out of
  scope, Step 08;
- a literal survives at any of the four sites.
