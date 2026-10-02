# Health gates

**Semantic owner**: `execute_tools/health_checks/`
**Status**: ✅ Current

---

## Purpose

Decide whether a model's output is **valid enough to trust and to keep spending
compute on** — a question deliberately separate from how good it is.

## Non-responsibilities

- Not scoring. `score_vector` is pure scoring and returns a 2-tuple; it does not
  return `is_degenerate` or `failure_reason`. Never call it expecting health
  results.
- Not model selection.
- Not task science. The framework owns *consequences*; the task owns *thresholds*.

## Position

Gates fire at **tuner round boundaries** in the tuner node, **not** inside
`score_vector`.

## The check protocol

```python
class HealthCheckSkill(Protocol):
    def run(self, ctx, config, *, view=None) -> HealthCheckResult: ...
```

A `Protocol`, not a base class — counting subclasses will always give the wrong
answer. A check that needs no view is invoked as `run(ctx, config)` exactly as
before; only a view-consuming check receives `view=`.

Checks declare their inputs as data (`CheckInputDeclaration`). **Applicability is
decided in `runner.evaluate_gate` before the skill is invoked**, so an
inapplicable check opens no artifact.

Nine built-ins ship: `amplitude_collapse`, `output_diversity`, `output_std`,
`pearson_dispersion`, `per_file_output_std`, `spectral_peak_ratio`,
`sample_dispersion_floor`, `categorical_distinct_symbols`,
`categorical_dominant_fraction`.

> The `__init__` import list is the built-ins' **bootstrap, not the extension
> path.** External checks register through the public `register` /
> `register_view_provider`.

## Verdicts

`CheckVerdict` — `passed` | `failed` | `inapplicable` | `error`.

| verdict | semantics |
|---|---|
| `passed` | evaluated, condition held |
| `failed` | evaluated, condition violated |
| `inapplicable` | declared inputs not present — never evaluated. **Never blocks and never counts as a pass** |
| `error` | could not complete. On a blocking check, **fails closed** via `on_fail` |

`passed` keeps its exact meaning: it selects `on_pass`/`on_fail` and drives
`short_circuit`, so gate *actions* are unchanged by the verdict vocabulary.
Honesty moved to counting, persistence (`PersistedHealthGateResult.check_verdicts`)
and eligibility — an all-inapplicable gate is excluded from the required set; an
errored one never is.

`HealthCheckResult` enforces verdict ↔ `passed` equivalence at construction.
Classification lives once, in `classify_verdict`.

## Gate actions

`continue` | `invalidate_round`.
Severity: `invalidate_round > continue`. The retired `skip_iter` and
`skip_to_formal` actions are rejected; gates do not control the iteration loop.

## Policy composition — two owners

| owner | file | declares |
|---|---|---|
| framework | packaged default via `execute_tools.health_checks.config.default_health_policy_path()` | `health_policy.{blocking,recording}`: gate role, cadence, short-circuit, `on_pass`/`on_fail`, default `aggregation` |
| task | external task's declared Health YAML | `facts`, `value_scale`, `health_peek_files`, `roster[]` with **thresholds** in `parameters`, and `reason` prose |

The task selects YAML `disposition: blocking` or `recording`;
the framework derives role, cadence, short-circuit, actions and
severity from it, so the two cannot disagree. Framework-policy keys appearing in a
roster entry's `parameters` are rejected.

`aggregation` is the task-declarable exception: an explicit roster parameter
overrides the framework's `health_policy.<disposition>.check_config` default.
Both configuration surfaces use the same presence-based validator and the
runtime's aggregation vocabulary. Omitting the key preserves existing default
resolution; explicitly declaring a blank YAML value, an unknown mode or a
non-string value is rejected during configuration validation, before it can
become a runtime Health error. Other check parameters remain open mappings.

The two compose deterministically into `{workspace}/health_checks_effective.yaml`,
sha256-pinned by the run-invariants lock. **`load_health_gates_config()` returns
the composed result**, and every path-based loader reads that file — never
override the config in memory.

`TaskHealthConfig` is frozen, `extra="forbid"`, **every field optional**.

## Binding states

| state | meaning |
|---|---|
| `LEGACY_OMITTED` | omitted uncomposed binding; current neutral default, not a scientific task family; **a composition may not express it** |
| `EXPLICIT_NONE` | `none: true` — a named absence that must never fall back to another task's family |
| a path | the declared task health config |

## Candidate eligibility

`candidate_eligibility.py` owns the scientific classifier. Role resolution uses
every gate's declared `gate_role`, never historical hashes, IDs or actions. Any
missing role yields `None` (UNKNOWN); an explicit empty roster yields an empty
set. The classifier consumes this value without config I/O: omitted or explicit
`None` remains UNKNOWN. Status failure/nonfinite score takes precedence, followed
by the explicit record-level `health_gate_enabled=False` waiver.

The uncomposed tuner resolves its effective policy before building RunBindings;
composed runs resolve their own task binding. Pinned readers use the workspace
policy, with resume additionally verifying the output's body-hash stamp. Neither
reader substitutes a current default for a missing/mismatched artifact.
Resume additionally requires independent VALID classification before consulting
stored authority, including its committed-best shortcut. Unknown evidence cannot
be repaired by a stored valid verdict. Summary-only scientific aggregation still
checks stored consistency without that artifact context; independent aggregation
evidence is tracked separately in [#445](https://github.com/Galileo-Sandbox/SIDERIUS/issues/445).

Removed compatibility APIs: `legacy_config_body_sha`, `required_blocking_gate_ids`
and its package export. Use `resolve_scientific_gate_ids` and retain UNKNOWN.
Removed marker: `task_health_peek`; use task-owned `health_peek_files` or a concrete
effective `peek_file_indices` list. String refusal precedes profile access.
Historical artifacts are not rewritten or migrated.

## Run-level inputs, not YAML

`health_gate_enabled` (subsystem switch) and `health_gate_files` (shared monitored
list, overriding every check's `peek_file_indices`) are **run inputs**, recorded by
the invariants lock.

## Extension

An external task supplies its own health YAML anywhere on disk and lists:

```yaml
plugins:
  - kind: file          # or `directory`
    ref: ./plugins/_my_checks.py
providers:
  - provider_id: my_view
    config: {...}
```

Refs resolve relative to the task config's directory, so identity is
host-independent. Plugin content digests join the pinned `health_config_sha256`
— an edited plugin fails a resume closed — while host paths are excluded, so the
same package at two absolute paths pins one identity. Plugins get their own
`sys.modules` prefix (`siderius_health_plugin_`).

Directory scanners skip `_`-prefixed members: pack-local plugins are loaded only
by explicit `kind: file` refs.

Standard view capabilities (`categorical_predictions`, `continuous_samples`) have
a frozen NumPy ABI: 1-D typed streams, strict dtype kinds, **no coercion**,
read-only no-copy views, native dtype preserved, engine-opaque.

## Invariants worth not re-breaking

- `spectral_peak_ratio` reads **only** the denoised channel.
- `threshold_parameter_names` means *thresholds*, not parameters read —
  recording-only checks declare `()`.
- A check must declare an input only if it **consumes** it.
- `symbol_cardinality` reaches checks only by declaration-driven composition
  injection from the frozen `INJECTABLE_AXIS_PARAMETERS` table; a roster
  hand-authoring an injected key is a deterministic `HealthCompositionError`.
- Verdict boundary: unreadable/empty ⇒ `error`; read-but-invalid ⇒ `failed`.

## Source map

| concern | location |
|---|---|
| protocol | `execute_tools/health_checks/protocol.py:24-61` |
| verdicts, actions, results | `schemas.py:29-51, 330-430, 436-632` |
| input declarations | `schemas.py:978, 1148` |
| framework policy schema | `config.py:69-283`, loader `:370` |
| task policy schema | `_task_health_config.py:265-395`, disposition `:62-87` |
| composition + injection | `_composition.py` |
| plugin binding | `_plugin_binding.py` |
| view providers | `_view_provider.py`, `standard_views.py` |
| runner | `runner.py` |

## Related

- [Health gates, for humans](../../concepts/health-gates.md)
- [Configuration map](../../reference/configuration-map.md) · [Plugins](plugins.md)
- Design history: `docs/design/pluggable_health_checks.md`
