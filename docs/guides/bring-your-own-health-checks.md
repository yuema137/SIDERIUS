# Bring your own health checks

**Prerequisite**: [Health gates](../concepts/health-gates.md) — the concept;
this guide is the declaration surface.

Authority for everything below:
`execute_tools/health_checks/_task_health_config.py` (the document a task
writes), `_composition.py` (the binding states and composition), and
`registry.py` (the public registration API). Where this page and those
modules disagree, the modules are right.

---

## Two owners, one composed result

Health behaviour is split between two documents that *cannot* express each
other's concern:

- **You (the task)** write a task health config: which gates exist, which
  check each runs, the thresholds, the peek files, the physical value
  scale, the plugin refs, and the scientific `reason` prose.
- **The framework** owns what a failure *does*: gate role, cadence,
  short-circuit, `on_pass`/`on_fail`, severity. Your one policy-facing
  choice per gate is its **`disposition`** — `blocking` or `recording` —
  and everything operational is derived from that word.

The split is structural, not conventional. A roster entry that tries to
state a framework key is refused at parse time:

```
parameters ['on_fail', …] are framework policy, not task parameters. A task
selects a disposition and the framework derives gate role, actions,
short-circuit, severity and cadence from it. Declare the peek set once as
health_peek_files and opt in with uses_health_peek_files=true. The one
declarable policy key is 'aggregation'.
```

### The one exception: `aggregation`

A gate that peeks several files needs a rule for turning those per-file
verdicts into one gate verdict, and that rule is the strictness of *your*
measurement, not framework policy. So a roster entry may declare it:

```yaml
  - gate_id: my_strict_gate
    check: my_check
    disposition: blocking
    parameters:
      my_threshold: 0.95
      aggregation: all_pass    # every peeked file must clear the threshold
```

Valid modes are `any_pass`, `all_pass`, `max`, `min`, `mean` and `median`;
anything else is refused at parse time rather than surfacing later as a
check error. Declare nothing and you inherit the framework's default for
your disposition (`all_pass` for `blocking` today), which is what every
shipped roster does.

**Declare it or omit it — a blank line is neither.** A bare `aggregation:`
with nothing after the colon parses to YAML `null`, and that counts as a
declaration: the framework then withholds its default for the key, while no
check can act on the value. It is refused at parse time, naming the blank
explicitly. Delete the key to inherit the default; write a mode to override
it. The point of the exception is per-gate control: you
can make one gate strict without making every other gate strict, which was
impossible while the value was framework-only.

At startup the two compose into one pinned
`{workspace}/health_checks_effective.yaml`, sha256-recorded by the
run-invariants lock — resuming under changed health semantics fails closed.

## The three binding states

How a run comes to have (or not have) a task health family — one typed
union, three states:

| state | expressed by | meaning |
|---|---|---|
| `LEGACY_OMITTED` | the caller said nothing at all | the uncomposed neutral default; it selects no scientific task family. **A composition manifest cannot express this state** — it would let a composed run silently inherit another task's thresholds |
| `EXPLICIT_NONE` | `task_health: {none: true}` in the manifest | a **named absence**: this task declares no health family. Recorded, distinguishable from "was never asked", never satisfied by falling back to another task's family |
| an explicit path | `task_health: {config: ./declared/task_health.yaml}` | your family |

The manifest section is required *as a statement* — omit it entirely and the
composition refuses. The two ways to get the path wrong, verbatim:

```
task_health declares both 'none: true' and a 'config' path. A task either
has a Health family or explicitly has none.
```

```
task_health config not found at '<path>'. A composed run never falls back
to another task's Health family — declare 'none: true' if this task has none.
```

## The document you write

```yaml
facts:                       # what your data IS — applicability facts, not thresholds
  encoding_family: categorical_labels
  symbol_cardinality: 37     # ONE authority; composition injects it into checks
value_scale:                 # only if your task has a physical scale
  unit: mV
  units_per_sample: 0.3125   # unit and factor owned TOGETHER, so they cannot drift
health_peek_files: [3, 10, 17]   # declared ONCE; gates opt in per entry
plugins:                     # external code, loaded before Phase B resolution
  - kind: file               # 'file' = named module, failure to load is fatal;
    ref: ../plugins/_my_health.py   # 'directory' = scanned, per-member tolerance
providers:                   # view providers your plugins register
  - provider_id: my_task.prediction_views
roster:
  - gate_id: my_collapse_blocking   # persisted join key — unique
    check: categorical_dominant_fraction   # a registered check name
    disposition: blocking            # your ONE policy choice
    parameters:                      # task-owned thresholds and check params
      max_dominant_fraction: 0.95
    uses_health_peek_files: false
    reason: >-
      Why this gate exists, in your task's own scientific terms.
```

Validation happens in two phases, and the difference matters when you ship
plugins: **Phase A** (authoring) checks shape, non-empty ids, plugin-ref
syntax, duplicates and self-contradictions — it deliberately accepts *any*
check or provider name, because an externally supplied check does not exist
until its plugin loads. **Phase B** (binding) then resolves every name; a
check or provider that never appeared fails the startup closed. A
configuration error is never downgraded to a health verdict.

With a declared [`code_package`](../reference/task-composition.md), checks and
view providers may import listed helpers relatively. A named package integrity
or refused-dependency error, including one raised during a later callback, stops
the workflow as `code_package_integrity`; it is not converted into scientific
Health evidence. Ordinary check/provider exceptions retain existing Health ERROR
handling. Package loading does not add a global registry reset or permit
concurrent task rosters in one process.

Three generic, task-reusable checks ship with the framework:
`sample_dispersion_floor` (continuous outputs), and
`categorical_distinct_symbols` + `categorical_dominant_fraction`
(classification). The categorical pair needs your declared
`symbol_cardinality` — composition injects it; a roster that hand-authors
an injected key is refused:

```
Gate '<gate_id>' hand-authors injected parameter key(s) […] in its
parameters. These keys are composition-owned facts injected from the task's
declarations (value_scale, facts.symbol_cardinality); author the
declaration instead of the parameter.
```

## Shipping your own check as a plugin

A plugin file named under `plugins:` simply calls the public registration
API at import time:

```python
from execute_tools.health_checks.registry import register, register_view_provider

register(MyCheckSkill())                  # a HealthCheckSkill: name + run(ctx, config, *, view=None)
register_view_provider(MyViewProvider())  # optional: supplies what checks decide FROM
```

Rules that will actually bite:

- **Refs are relative to the config's own directory** — never absolute,
  never `~`. Verbatim: *"plugin ref '<ref>' is absolute. Refs are relative
  to the task health config's directory so the same task package pins one
  identity regardless of where it is checked out."*
- **Duplicate registration raises** (two modules racing for one name would
  otherwise resolve by import order): *"Health check '<name>' is already
  registered. …"*
- **Plugin content digests join the run's pinned `health_config_sha256`** —
  editing a health plugin between a run and its resume fails the resume at
  startup. Host paths are excluded, so the same package at two absolute
  paths pins one identity.
- The built-in checks' import list in
  `execute_tools/health_checks/__init__.py` is the *built-ins' bootstrap*,
  not the extension path — external checks arrive only through your
  `plugins:` refs.

## Worked example 1: a named absence (the quickstart pack)

The shipped onboarding pack declares **no** health family — and must say so
explicitly. Its `configs/task_composition/quickstart.yaml` binding is:

```yaml
task_health:
  none: true
```

That is the whole binding. It composes to `EXPLICIT_NONE`, the run records
that no gates were configured, and nothing falls back to anyone else's
thresholds. The deterministic proof is
`tests/unit/examples/test_quickstart_pack.py::test_shipped_manifest_composes_with_the_declared_values`,
which composes this exact manifest.

## Worked example 2: a shipped synthetic roster

The [masked-regression declaration](../../examples/synthetic_masked_regression/declared/task_health.yaml)
loads its task-owned view provider and selects the framework's
`sample_dispersion_floor` check with `min_dispersion: 0.1`. The check receives
valid continuous predictions; a constant output fails the synthetic control.
The value is a demonstration threshold, not scientific calibration.

```yaml
facts:
  encoding_family: continuous_float
plugins:
  - kind: file
    ref: ../plugins/_masked_health_views.py
providers:
  - provider_id: synthetic_masked_regression.valid_predictions
roster:
  - gate_id: synthetic_masked_prediction_dispersion
    check: sample_dispersion_floor
    disposition: blocking
    parameters:
      min_dispersion: 0.1
    reason: Demonstration boundary for continuous prediction dispersion.
```

This excerpt summarizes the binding; the linked file owns its exact reason text
and resulting identity. Policy supplies cadence, role and actions. The
[example guide](../../examples/synthetic_masked_regression/README.md) gives the
offline execution route. Real task rosters, including Pets and DAVIS, live in
siderius-exp and require their own thresholds and qualification.

## Production evaluation and its limits

The tuner reaches `round_health.apply_round_health` after successful scoring,
including the composed task-owned route. A scoring failure produces an
`error_scoring` record and returns before Health evaluation. When
`health_gate_enabled=False`, the Health engine is not called and no gate I/O
occurs; score-validity classification still runs.

When enabled, the effective policy selects gates for the round's position.
An empty roster, a position with no selected gates, and an inapplicable check
are not evidence that a scientific check passed. Applicability, blocking versus
observational roles, and enforcement are separate decisions; follow the
[Health mechanism](../agent-reference/mechanisms/health-gates.md).

The execution owner is
[execution.py](../../src/nodes/ml_hyperparameter_tune_agent/execution.py), with
[evaluation and persistence](../../src/nodes/ml_hyperparameter_tune_agent/round_health.py)
at the shared round boundary. The synthetic extension tests in
`tests/unit/execute_tools/health_checks/test_out_of_tree_extension.py` validate
external registration and composition. A real task still needs its own execution
evidence; its existence in a manifest is insufficient.

---

## Next

- [Bring your own metric](bring-your-own-metric.md)
- [Health gates](../concepts/health-gates.md) — dispositions, verdicts, actions
- [Task composition reference](../reference/task-composition.md) — the `task_health` section
