# Bring your own metric

**Audience**: someone declaring how their task is scored.
**Prerequisite**: [Objectives, metrics, and what "better" means](../concepts/objectives-and-metrics.md)
— this guide is the *how*; that page is the *why*.

A metric is two artifacts: a **declaration** (JSON — the identity, the
direction, the acceptance contract) and an **implementation** (a Python
class — the arithmetic, and nothing else). The declaration is the
authority; the implementation may not rewrite it.

Authority for everything below: `execute_tools/evaluation_metric.py`
(`MetricSpec`, `EvaluationMetric`, `ScoreabilityContract`) and
`workflows/task_composition.py::_compose_metric`. Where this page and those
modules disagree, the modules are right.

---

## The declaration surface

Your composition manifest's `metric:` section names both halves:

```yaml
metric:
  declaration: ./declared/my_metric.json
  implementation:
    file: ./plugins/my_metrics.py      # or module: my_package.metrics
    symbol: MyMetric
```

Secondary metrics use the *same* `{declaration, implementation}` shape under
`secondary_metrics:` (a list — **order is semantic**, it joins the
composition fingerprint), are resolved by the same authority, and are
purely observational: recorded, shown to the agents, influencing no
selection anywhere.

The declaration JSON is a `MetricSpec`:

| field | required | meaning |
|---|:---:|---|
| `id` | ✅ | **opaque identity.** No lexical rules — `accuracy`, `mse`, even `log_loss` are equally legal; nothing is inferred from the spelling. Empty or whitespace-padded is refused |
| `direction` | ✅ | `higher` or `lower` — explicit, never inferred from sign or name. The one field that silently inverts a whole campaign if wrong |
| `aggregation` | ✅ | the identity of the rule that reduces evidence to the scalar — a name you choose and your implementation honours |
| `scoreability` | ✅ | the executable acceptance contract (next section) |
| `transform` / `transform_params` | — | a named transform on the scalar, e.g. `log` |
| `references` | — | named reference kinds the interpretation layer may use |

`MetricSpec` is frozen and `extra="forbid"` — an unknown key in the JSON is
a refused declaration, not an ignored one.

## Scoreability: the contract that runs before the arithmetic

Before your `_compute` ever runs, the declared **scoreability contract**
answers "is this deliverable scoreable at all?" over
`{input_identity: deliverable_path}`. It must be total — it returns a
verdict for any input and never lets a filesystem error escape. A violated
requirement becomes a structured refusal (`NotScoreableResult` → an
`error_scoring` record with `failure_type="not_scoreable"`), never a garbage
number.

The declarable vocabulary is a **closed lookup, not a plugin surface** —
it grows only when a contract class is added to
`execute_tools/evaluation_metric.py`:

| `contract_id` | requires |
|---|---|
| `deliverable_presence` | every named deliverable exists as a file (and at least one was named). The right choice for most external tasks — the quickstart uses it |
| `tidmad_denoised_h5` | TIDMAD's HDF5 channel/attrs/dtype requirements |

Declaring anything else is refused at composition with:

```
unknown scoreability contract_id '<yours>'; known: ['deliverable_presence', 'tidmad_denoised_h5']
```

If `deliverable_presence` is too weak for your task — you want shape or
dtype checked before scoring — that is currently a framework contribution
(a new `ScoreabilityContract` subclass), not something a pack can ship.
Your implementation may still refuse malformed payloads itself by raising:
an exception inside the metric becomes a structured scoring error, not a
score.

## The implementation

Subclass `EvaluationMetric`. It is constructed with the declared spec, and
the base class runs the scoreability contract before your arithmetic; you
implement only `_compute`. The composed scoring child calls it in the
framework's calling vocabulary:

```python
def _compute(
    self,
    deliverables,            # Mapping[int, str] — what scoreability approved
    /,
    *,
    evaluation_payload,      # what your data path's read_evaluation_payload returned
    task_scope,              # the run's evaluation scope — task-owned vocabulary
    data_dir=None,           # the physical data root
) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
    ...                      # (scalar, optional per-sample evidence, references used)
```

Optionally declare `IMPLEMENTS: ClassVar[tuple[str, ...]]` — the ids your
arithmetic actually computes. An implementation making no claim composes
under any id (identity stays opaque); one that *does* claim is cross-checked
against the declaration.

## What refuses, verbatim

Every one of these is raised at composition — before any LLM call or GPU
work. (`<…>` marks the run-specific values interpolated into the message.)

| you got wrong | the refusal says |
|---|---|
| declaration JSON invalid as a spec | `metric declaration at '<path>' is not a valid MetricSpec: <error>` |
| no `implementation:` mapping | `metric requires an 'implementation' mapping naming the EvaluationMetric to instantiate; got <value>.` |
| constructor rejects the spec | `metric.implementation could not be instantiated with the declared spec: <error>` |
| wrong type entirely | `metric.implementation resolved to <ClassName>, which is not an EvaluationMetric. The metric handle is the ONE scoring contract (Step 06); a composition may choose which instance, never a different contract.` |
| implementation rewrites its own id | `metric: the declaration declares id '<a>' but the instantiated metric reports '<b>'. An implementation that rewrites its own spec breaks the declaration's authority.` |
| declared id absent from the class's `IMPLEMENTS` claim | `…Binding a metric id to an implementation that computes something else produces a terminal report labelled with one metric and populated by another — the declaration would name the science and the arithmetic would disagree with it, silently.` |
| blank / padded id | `id must be a non-empty identifier with no surrounding whitespace; got <value>.` |

For a secondary, the same messages appear prefixed `secondary_metrics[i]`
so you are told *which* declaration failed.

## Worked example: the quickstart pack's own metric

The shipped onboarding pack scores 2-class tabular accuracy. Its
declaration, `examples/quickstart/declared/metric_accuracy.json`, verbatim:

```json
{
  "aggregation": "fraction_correct_over_eval_rows",
  "direction": "higher",
  "id": "accuracy",
  "references": [],
  "scoreability": { "contract_id": "deliverable_presence" },
  "transform": null,
  "transform_params": {}
}
```

Line by line: `aggregation` names the reduction rule the implementation
honours literally (every eval row in the denominator); `direction: higher`
is stated even though "accuracy, higher" feels obvious — nothing downstream
guesses; `id: accuracy` is an opaque identity; `scoreability` declares the
presence contract — the deliverable is a JSON predictions file, so
existence is the acceptance bar; `transform`/`references` are explicitly
empty rather than omitted.

The implementation,
`examples/quickstart/plugins/_quickstart_metrics.py` (abridged — read the
file for the full comments):

```python
class QuickstartAccuracyMetric(EvaluationMetric):
    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("accuracy",)

    def _compute(self, deliverables, /, *, evaluation_payload, task_scope, data_dir=None):
        truth = _truth_from_scope(task_scope)   # {sample_id: label} — the scope IS
        if not truth:                           # the truth authority
            raise ValueError("accuracy needs a non-empty evaluation scope — …")
        correct = sum(
            1 for sample_id, label in truth.items()
            if evaluation_payload.get(sample_id) == label
        )
        return correct / len(truth), None, ()
```

(One honesty note from the pack's own `STATUS.md`: the quickstart's
*scoring leg* — this metric producing a live `metric_result` in a composed
chain — is not yet witnessed; its arithmetic is exercised by the pack's
deterministic tests, and the composed scoring surface itself is real — the
Pets and DAVIS packs scored through it end to end.)

What to imitate:

- **Truth comes from the scope**, not from re-reading the data directory or
  trusting the deliverable — the denominator cannot drift from what the run
  declared it would be evaluated on, and a prediction missing from a partial
  deliverable counts as not-correct.
- **Direction and scoreability are absent from the class.** They live in the
  declared spec; the class owns arithmetic only.
- The file is underscore-prefixed and reached *only* by the manifest's
  `implementation: {file: …}` reference — never imported by the framework,
  never picked up by a directory scan.

And the binding, from `configs/task_composition/quickstart.yaml`:

```yaml
metric:
  declaration: ../../examples/quickstart/declared/metric_accuracy.json
  implementation:
    file: ../../examples/quickstart/plugins/_quickstart_metrics.py
    symbol: QuickstartAccuracyMetric
```

Paths resolve against the manifest's own directory, so the same shape works
from a package anywhere on disk.

## Verifying yours composes

No live run is needed. The deterministic suite that composes the shipped
quickstart manifest — declaration, implementation, id cross-checks and all —
and then drives the composed metric through its scoreable, zero-accuracy and
*refused* outcomes (`test_shipped_manifest_composes_with_the_declared_values`,
`test_deliverable_codec_and_metric_outcomes`) is:

```bash
uv run pytest tests/unit/examples/test_quickstart_pack.py -q
```

Point the same machinery at your own manifest in a scratch test
(`compose_run_task_bindings("/path/to/composition.yaml")` is the whole
API), or just launch: composition — and every refusal above — runs at
startup, before any LLM call or GPU work.

---

## Next

- [Bring your own health checks](bring-your-own-health-checks.md)
- [Define your own task](define-a-task.md) — the surrounding steps
- [Task composition reference](../reference/task-composition.md)
