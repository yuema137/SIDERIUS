# Stage Artifact & Layout Contract (Gold campaign) — FROZEN-BY-CONTRACT

**Status**: the minimum stable contract the three Stage-3 writers and the
Stage-1/2 launcher build against (operator scheduling ruling, 2026-08-26:
this contract lands BEFORE the launcher; any later launcher change that
moves a path is a CONTRACT change to this file, never a surprise).
Owner: Lane F. Everything marked **FROZEN** below is load-bearing for at
least two lanes. Where a layout already exists in production, this file
DOCUMENTS it (with the source of truth cited); where it does not
(Stage-2/3), it fixes the simplest shape consistent with the frozen
architecture.

Conventions: `{workspace_root}` = the campaign's persistent root (R1-checked
mount). `{arm}` ∈ the campaign's two arm labels (opaque strings; stamped as
`experiment_arm`, which is in `RunInvariants._CANONICAL` — a wrong label is
pinned and compared, so the launcher stamps it once, correctly). `{BAND}` ∈
`0-3 | 4-9 | 10-14 | 15-19` (the DS8 band vocabulary; the band launcher's
own map is the authority, `campaign_preflight.sh` R6 cross-checks it).

---

## 1. Stage-1 — per-band chain workspaces (EXISTING layout, documented)

**FROZEN paths** (source of truth: `run_chain.sh` + `run_one_iteration.py
prepare_iteration_dir`, `:805` — "Create `{workspace}/iter_{N:03d}`"):

```
{workspace_root}/{arm}_band{BAND}/                  # one chain workspace per band per arm
  run_invariants_lock.json                          # core/run_invariants.py — pins scope, arm, health sha
  health_checks_effective.yaml                      # the run's pinned effective Health config
  iter_{N:03d}/                                     # N from 1, zero-padded width 3
    manifest.json                                   # write-once, self-digested (#258); status ∈ completed|failed|no_records
    <node output records>                           # {node}_{run_name}.json per the storage contract
    <tuner sub-workspace>/                          # the tuner sandbox base_dir for this iteration
      configs/ data/ ...                            # TidmadSandbox.dirs
```

**FROZEN deliverable naming**: filenames resolve EXCLUSIVELY through the
run's `DeliverableNaming` authority (`execute_tools/deliverable_spec.py`;
construction helper `records._build_denoised_filename`). The shipped TIDMAD
template renders `abra_validation_denoised_{model_type}_{run_name}_{exp_id}_file{NNNN}.h5`
with `NNNN` = the input identity 0–19 zero-padded width 4. Deliverables are
ABRA-format HDF5, written into the iteration's tuner sandbox data dir
(`base_dir`); every path a consumer receives from a record is ABSOLUTE
(Bug-A contract, `records.py:573`).

**FROZEN retention clause**: Stage-1 campaign chains run with formal-round
deliverable RETENTION — the launcher must NOT pass `--cleanup_denoised`
for campaign runs (the historical standard command did; a cleaned formal
winner leaves Stage-3 nothing to pool). The F-LAUNCH-1 entrypoint binds
this; until it exists, any hand launch of a campaign chain must omit the
flag.

**FROZEN winner identification** (field names, from the persisted
`ExperimentRecord` dicts in the iteration records; authorities cited):

A record is the band's *cumulative best HealthGate-valid FORMAL winner* iff
it maximizes `denoising_score` under `MetricOrder` (direction from the
run's `MetricSpec`; do NOT assume higher-is-better in code) over all
records in the band workspace satisfying ALL of:

| condition | field / authority |
|---|---|
| completed scoring | `status == "success"` |
| FORMAL round | **absence of the `is_trial` key** (`BestTracks` authority, `policy.py`: "Formal records have no `is_trial` key … absence == formal"; the top-level `trial_portion` key is likewise trial-only — #316 B2) |
| HealthGate-valid | `is_valid_candidate(record)` == True (`execute_tools/health_checks/candidate_eligibility.py:310` — the ONE eligibility authority; never re-implement from gate fields) |
| identity | `exp_id`, `model_type`, `iteration` (dir), `experiment_arm` (lock + manifest) |

Its deliverables are the 20 files named by the `DeliverableNaming`
authority for (`model_type`, `run_name`, `exp_id`, file 0–19) in that
iteration's sandbox data dir.

---

## 2. Stage-2 — frozen-design retrain units (NEW layout, fixed here)

**FROZEN**: one directory per retrain unit, 16 units, launched as 4 GPU
waves (wave membership is launcher policy, not layout):

```
{workspace_root}/stage2/{design}_{target_band}/     # e.g. wavenetA_0-3
  workspace/                                        # a normal single-iteration chain/tuner workspace (Stage-1 rules apply inside, incl. iter_001/)
  deliverables/                                     # the unit's 20 ABRA-format HDF5 files, COPIED (not symlinked) from the workspace after completion, named by the SAME DeliverableNaming authority
  COMPLETE.json                                     # completion marker, written LAST (atomic rename), schema below
```

`{design}` = the frozen-design identifier (16 total; the design registry is
the campaign plan's, not this contract's). `{target_band}` uses the same
band vocabulary as Stage-1.

**FROZEN `COMPLETE.json` schema** (the marker is the ONLY thing Stage-3
polls; absence == unit not done; partial dirs without it are ignored):

```json
{
  "design": "<design id>",
  "target_band": "<band>",
  "exp_id": "<the retrain's exp_id>",
  "model_type": "<plugin model_type>",
  "repo_sha": "<git sha the unit ran at>",
  "denoising_score": <float, the unit's own formal score>,
  "healthgate_valid": <bool, is_valid_candidate of its record>,
  "deliverable_count": 20,
  "completed_utc": "<ISO8601>"
}
```

---

## 3. Stage-3 — consumption points (NEW, fixed here)

```
{workspace_root}/stage3/
  composed_best/        # writer A: pools the 4 Stage-1 winners' SOURCE-BAND deliverables
  strict_best/          # writer B: pools Stage-2's 4×4 (per design-quad selection rule, writer-owned)
  terminal_eval/        # writer C: the ISOLATION namespace — see the rule below
    <input>/            # whatever terminal evaluation consumes
    <results>/
```

**FROZEN consumption rules**:
- `composed_best` reads, for each band, the Stage-1 winner's deliverables
  for THAT band's files only (winner identified per §1; files outside the
  winner's source band are never read from it).
- `strict_best` reads Stage-2 `deliverables/` dirs, only from units whose
  `COMPLETE.json` exists and has `healthgate_valid: true`.
- **Isolation rule for `terminal_eval` (FROZEN)**: nothing under
  `{workspace_root}/stage3/terminal_eval/` is ever read by any search,
  selection, tuning, or scoring-for-selection code path — structurally
  guaranteed because (a) no Stage-1/2 workspace and no Stage-3 writer A/B
  takes a path under `terminal_eval/` as input (their input roots are
  enumerated above and are disjoint from it), and (b) the directory name
  is reserved by this contract: any future consumer adding a read from it
  is making a CONTRACT change here first.

---

## 4. The shared compose-and-score interface (ONE wrapper, reused 3×)

**FROZEN signature** (module suggested: `scripts/stage3/compose_and_score.py`;
the implementer may relocate the module — the SIGNATURE and semantics are
the frozen part):

```python
def compose_and_score(
    deliverable_dirs: list[str],      # pooled dirs; each holds ABRA-format .h5 deliverables
    *,
    files: range = range(20),         # the full 0..19 file set — full-scope by contract
    sample_set: None = None,          # None == the FULL sample set; partial scopes are not legal here
) -> tuple[list[float], float]:       # (file_vector, scalar) — score_vector's own 2-tuple
```

Semantics, all FROZEN:
- Wraps the existing `score_vector` authority (`execute_tools`/scoring)
  EXACTLY ONCE — one call over all 20 files with the canonical committed
  anchor map (global `s_max` ruler). **No per-band scalars exist anywhere**
  (F-SCAND-1: the slice-mean aggregation is refused; F-SCAND-4 verified
  the valid construction). Reuse anchor:
  `scripts/score_tidmad_official_banded.py` — writes per-band outputs into
  one pooled temp dir, then "scores all 20 files in one `score_vector`
  call".
- For each file 0–19, exactly ONE deliverable must resolve across
  `deliverable_dirs` (missing → `NotScoreableError`-class refusal, never a
  silent skip; duplicates → refusal naming both paths).
- The frozen TIDMAD score formula is byte-untouched; this wrapper composes
  INPUTS, never arithmetic.
- All three writers (composed_best / strict_best / terminal_eval) call THIS
  function; none re-inlines `score_vector`.

---

## Change control

Every field above marked FROZEN is release-contract material: a change is a
PR to THIS file with the supervisor's review, announced to lanes B/C/D —
never an incidental edit riding a launcher or writer PR.
