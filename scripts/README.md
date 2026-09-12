# `scripts/` — operator utilities and point-in-time harnesses

**Audience**: a coding agent or engineer looking for the right tool — or
wondering whether an old script here is maintained.
**Authority**: the source; the operator-facing command surface is
[docs/reference/entrypoints.md](../docs/reference/entrypoints.md).
Template:
[`docs/agent-reference/MODULE_README_TEMPLATE.md`](../docs/agent-reference/MODULE_README_TEMPLATE.md).

## Purpose

Python/bash utilities, including the maintained chain launchers in
[`launch/`](launch/) and Slurm entrypoints in [`slurm/`](slurm/)
and durable runtime utilities in [`runtime/`](runtime/). This directory contains the
small durable operator surface. Historical investigation and gate harnesses
are maintained by their owning experiment repository, not shipped here.

The directory is excluded from the Python distribution. Task-specific scripts
are historical source evidence only: active scientific utilities belong in
the task or campaign package that owns their semantics. No framework launch
may select a script or advice artifact from this archive by default.

## Public interface

The durable operator surface:

| script | role |
|---|---|
| `launch/inspect_run_state.py` | auto-resume inspector |
| `runtime/rebuild_per_file_best.py` | rebuild the per-partition best-of table from records |
| `launch/validate_path_component.py` | path-component hygiene used by launchers |
| `runtime/campaign_admission.py` · `runtime/campaign_spend.py` · `runtime/replay.py` | resumable bookkeeping and runtime-control operations |
| `diagnostics/bg_gpu_sampler.sh` | background GPU utilisation sampler |
| [`diagnostics/check_agent_environment.py`](diagnostics/README.md) | opt-in provider environment diagnostic; source-checkout-only and network-capable |

The chain entry is [`launch/run_chain.sh`](launch/run_chain.sh); Slurm submits
through [`slurm/submit_one_iteration.slurm`](slurm/submit_one_iteration.slurm).

The dated study and calibration tooling formerly under
`inspection_cost_study/` and `pr3_l2_calibration/`, along with retired
diagnostic launch helpers, is no longer shipped in this checkout. Historical
evidence remains linked from `docs/design/`; it is not an active script API.

## Inputs

Workspace paths, run names and data roots are explicit CLI inputs. The active
framework launch does not load the retired task-specific machine path config;
dated investigation scripts are not an alternative launch authority.

## Outputs

Active summaries belong under caller-owned workspaces; historical `reports/`
files are evidence only.

## Owned semantics

- `inspect_run_state.py` owns the **"which iteration is next"** answer the
  chain launcher trusts; its manifest verdicts come from the shared
  `core/iteration_manifest.py` predicate, so "trustworthy" has one
  definition everywhere.

## Non-owned semantics

- Launching the real multi-iteration chain →
  [`launch/`](launch/README.md).
- The workflow itself → [`workflows/`](../src/workflows/README.md).
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
admitted).

## Files normally edited

The durable operator surface, under review. Point-in-time scripts are
normally **not** edited — a new investigation gets a new script (and its
ledger names it), so the old evidence keeps pointing at what actually ran.

## Files normally NOT edited

Anything a design ledger cites as historical gate evidence is preserved in
the experiment provenance archive rather than treated as a current framework
operator surface.

## Minimal example

```bash
.venv/bin/python scripts/launch/inspect_run_state.py --workspace /path/to/ws --next-iter
```

## Related tests

`tests/unit/scripts/` (inspector, campaign admission, and calibration
preflight), plus the minimal-example suites that exercise supported framework
contracts.
