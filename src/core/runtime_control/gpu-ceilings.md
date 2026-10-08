# Aggregate GPU ceiling contract

Owner: `pair_admission.py`. Ordinary `admission.py` and
`isolated_admission.py` consume the same resolution. This is an aggregate
admission limit, separate from per-candidate trial/formal VRAM budgets.

## Inputs and precedence

1. Explicit `ceiling_gib` (CLI `--gpu_pair_ceiling_gib`) selects the operator
   ceiling. Otherwise use nonempty `SIDERIUS_PAIR_VRAM_CEILING_GIB`.
2. Independently read nonempty `SIDERIUS_GPU_VRAM_QUOTA_MIB`, in MiB, and convert
   using 1024 MiB per GiB. This quota constrains even explicit caller ceilings.
3. Device-backed admission supplies its already validated snapshot capacity in
   GiB. The resolver never discovers a device or assumes a GPU model.
4. The effective ceiling is the minimum of all applicable limits. With no
   operator limit or declared quota, it is the measured physical capacity.
   No deployment-specific numeric ceiling or percentage is added here.

The selected operator declaration, its source (`caller`, `environment`, `none`),
quota and capacity form a frozen `ResolvedGpuCeiling`. Its `effective_gib` is
derived. Admission records the resolution and effective ceiling; a missing
operator limit remains null, not a fabricated configuration value.

A valid explicit ceiling overrides a malformed *shadowed* operator environment
value, which is not parsed. The independent quota is always validated. Empty
strings retain unset semantics. Selected limits must be positive and finite;
booleans are refused before float coercion. `PositiveGpuGiB` is shared by the
existing tuner intake and admission policy; `WorkflowLaunchConfig` carries the
same annotation without becoming a second runtime validation authority.

## APIs and errors

- `resolve_gpu_ceiling(...)` snapshots the environment once and returns the
  typed resolution. An optional mapping supports explicitly supplied deployment
  configuration without global mutation.
- `pair_ceiling_gib(measured_capacity_gib=...)` projects that resolution for
  existing callers. It no longer supplies an implicit 28 GiB default.
- `evaluate_pair_admission` resolves configuration once.
  `evaluate_resolved_pair_admission` compares member demands against a supplied
  resolution without reading environment variables again.
- `evaluate_configured_caps` labels demands as configured caps, not measurements.
  A standalone configuration check may use an explicit ceiling or declared quota
  without a GPU. With neither limit nor capacity, resolution refuses and names
  the missing inputs. It never fabricates hardware qualification.

For example, an offline configuration check with an explicit ceiling is:

```bash
.venv/bin/python -m core.runtime_control.pair_admission \
  --caps first=6,second=8 --ceiling-gib 16 --json
```

CLI exits are 0 feasible, 1 infeasible, 2 invalid configuration. Invalid limits,
member demands and nonfinite aggregate overflow refuse with a usage error.
Device-backed ordinary admission converts resolver failures into a
`policy_unavailable` decision. Existing enforcement posture still determines
whether it stops execution. Namespace-limited mode retains its unconditional
`environment_headroom_unproven` refusal; no exception-driven trial bypass is
introduced.

## Scope and historical compatibility

This changes omitted configuration on larger devices and explicit ceilings
above a declared host quota. Demand ownership, current-occupancy arithmetic,
candidate budgets, model/batch selection and monitoring policies are separate
owners. Physical capacity is not a guarantee of future free memory or full
workload peak coverage.

Historical deployment values belong in external experiment configuration only
when supported by actual records. The old source fallback alone does not prove
a run had no environment override. Estimator source qualification changes with
this owner; never relax historical identity validation or rewrite frozen records
to hide it. Focused CPU tests cover resolution, finite arithmetic, both admission
paths and CLI refusals; they do not constitute physical GPU qualification.
