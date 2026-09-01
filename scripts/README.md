# `scripts/` — operator utilities and point-in-time harnesses

**Audience**: a coding agent or engineer looking for the right tool — or
wondering whether an old script here is maintained.
**Authority**: the source; the operator-facing command surface is
[docs/reference/entrypoints.md](../docs/reference/entrypoints.md).
Template:
[`docs/agent-reference/MODULE_README_TEMPLATE.md`](../docs/agent-reference/MODULE_README_TEMPLATE.md).

## Purpose

Python/bash utilities that are *not* the chain. **The chain launchers live in
[`sdsc_submission_scripts/`](../sdsc_submission_scripts/README.md), not
here** — several older documents said otherwise. This directory mixes two
populations with different maintenance contracts: a small durable operator
surface, and a large set of point-in-time investigation and gate harnesses
kept as provenance for dated campaigns.

The directory is excluded from the Python distribution. Task-specific scripts
are historical source evidence only: active scientific utilities belong in
the task or campaign package that owns their semantics. No framework launch
may select a script or advice artifact from this archive by default.

## Public interface

The durable operator surface:

| script | role |
|---|---|
| `run_comparison.py` | ⚠ TIDMAD-only baseline/agent comparison harness (imports TIDMAD's dataset and sandbox directly; no `--task_composition`) |
| `inspect_run_state.py` | the auto-resume inspector — `--next-iter` reports the first incomplete iteration from each `iter_NNN/manifest.json`; one of the three callers of the shared manifest-verification predicate |
| `run_pets_gate2.py` · `run_davis_gate2.py` | the D14 direct-execution harnesses for the two contrast packs (real training/inference/scoring in-process; the historical Gate-2 evidence path that predates the composed chain reaching those tasks) |
| `_gate2_health_stage.py` | the ONE shared Health evidence stage both D14 runners call (explicit binding, every selected gate persisted) |
| `rebuild_per_file_best.py` | rebuild the per-partition best-of table from records |
| `record_wave_summary.py` · `build_diagnostic_summary.py` | wave/diagnostic summary builders |
| `validate_path_component.py` | path-component hygiene used by launchers |
| `campaign_admission.py` · `campaign_spend.py` · `runtime_campaign.py` · `runtime_bootstrap.py` · `runtime_replay/` | resumable-campaign bookkeeping and runtime-control operations |
| `run_all_models.sh` · `run_all_models_trial.sh` | screen-based group orchestration of `run_comparison.py` across the five built-in TIDMAD models |
| `bg_gpu_sampler.sh` | background GPU utilisation sampler |

Everything else — `fcnet_*`, `investigate_*`, `score_tidmad_official_*`,
`official_paper_health_scan.py`,
`phase2_diagnostic_no_dynamic_search.py`, `pregate_runtime_control_validation.py`,
`vram_preflight_validation.py`, `c2_prephase_validation.py`,
`c12_stamp_failure_class.py`, `checkpoint_*`, `step10_p3_gate1.py`,
`step12_pr12a_gate1.py` / `step12_pr12a_gate2_evaluate.py`,
`finalize_recovered_diagnostic_round.py`, `render_*`, `v18_wave_summary.py`,
`verify_iter005_estimator.py`, `fcnet_full_file_scan.py`,
`inspection_cost_study/`, `pr3_l2_calibration/` — is **point-in-time**: each
was written for a dated investigation, campaign or gate whose evidence lives
in `docs/design/` ledgers or `reports/`. They are kept because the evidence
cites them, not because they are products. Read the header docstring before
trusting one against current source.

## Inputs

Workspace paths, run names and data roots as CLI arguments; several scripts
read the machine-local `tidmad_data_config.yaml`.

## Outputs

Summaries and tables under the workspace or `reports/`; the gate harnesses
write full run workspaces.

## Owned semantics

- `inspect_run_state.py` owns the **"which iteration is next"** answer the
  chain launcher trusts; its manifest verdicts come from the shared
  `core/iteration_manifest.py` predicate, so "trustworthy" has one
  definition everywhere.
- `run_comparison.py` owns the paper-aligned baseline launch (its
  `--max_epochs 1` posture is the TIDMAD paper spec).

## Non-owned semantics

- Launching the real multi-iteration chain →
  [`sdsc_submission_scripts/`](../sdsc_submission_scripts/README.md).
- The workflow itself → [`workflows/`](../workflows/README.md).
- Record/manifest integrity rules → `core/record_log.py` /
  `core/iteration_manifest.py`
  ([persistence concepts](../docs/concepts/persistence-and-records.md)).

## Extension points

New operator scripts follow the portability rules (CLAUDE.md): derive the
repository root from the file location, take machine paths from
configuration or arguments, never hardcode a developer's absolute path.

## State and filesystem effects

Scripts write only where pointed. The gate harnesses create and populate
workspaces; the campaign tools append manifests under their campaign roots.

## Failure modes

`inspect_run_state.py` reports a manifest problem verbatim from the shared
predicate (a tampered or hash-less completed manifest is named, not
admitted); `run_comparison.py` refuses non-TIDMAD use by construction —
it has no composition entrypoint.

## Files normally edited

The durable operator surface, under review. Point-in-time scripts are
normally **not** edited — a new investigation gets a new script (and its
ledger names it), so the old evidence keeps pointing at what actually ran.

## Files normally NOT edited

`_gate2_health_stage.py` binding semantics (explicit, keyword-only, no
default); anything a design ledger cites as gate evidence.

## Minimal example

```bash
.venv/bin/python scripts/inspect_run_state.py --workspace /path/to/ws --next-iter
```

## Related tests

`tests/unit/scripts/` (inspector, comparison harness, campaign admission,
calibration preflight), plus the example-pack suites that pin the two D14
harness declarations.
