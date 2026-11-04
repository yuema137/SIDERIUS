# Declare how your task judges candidates

A SIDERIUS run trains many candidate models and keeps the best one. Out of the
box, "best" means one thing: the highest (or lowest) value of the task's main
metric. Often a scientist means more than that. You may want the agents to
know that the score is the mean per-class recall, a number from 0 to 1, to trade accuracy
against a second error measure, or to require a minimum accuracy.

The optional `evaluation:` section of your task manifest (`task.yaml`) says
this in one place. Every agent that proposes, implements, reviews, tunes or
interprets a model then reads the same declaration. The framework's own
code does all the arithmetic; no agent computes a score.

This page walks through the section one step at a time, using the
[CSV classification template](../../../examples/task_templates/csv_classification/README.md)
as the running example.

## What works today

The section is new in SIDERIUS 1.1. Almost all of it can be declared,
checked and shown to the agents, but some parts cannot drive a run yet. When
a run starts, a launch check refuses any declaration whose runtime is not
available, so nothing is silently ignored.

| You declare | Checked and shown to agents | A run can launch with it |
| --- | --- | --- |
| Meanings, units and ranges, with `selection: {kind: primary}` (step 2) | yes | yes |
| A weighted combination, `selection: {kind: formula}` (step 3) | yes | yes |
| A natural-language balancing rule, `selection: {kind: rubric_balance}` (step 4) | yes | yes, as guidance for the agents |
| Rubric components, `kind: rubric` (step 4) | yes | yes, as guidance for the agents |
| Requirements, `constraints:` (step 5) | yes | yes, on metric and measurement components |
| Model measurements such as latency or parameter count, `kind: measurement` (step 5) | yes | yes |

## Before you start

- A task package that composes, for example a copy of the CSV template set
  up as its [README](../../../examples/task_templates/csv_classification/README.md)
  describes. Your task package lives in your own project, outside the
  SIDERIUS checkout.
- A SIDERIUS checkout installed with `uv sync --group dev --frozen`. The
  commands below run from the checkout's root folder with its
  `.venv/bin/python`.
- Every quantity you want to combine or constrain must already be a declared
  metric: the main `metric:` or an entry under `secondary_metrics:`.
  [Bring your own metric](../bring-your-own-metric.md) shows how to declare
  one. The evaluation section refers to metrics; it never computes them.

## Three questions SIDERIUS keeps apart

Each finished candidate goes through three separate checks, in this order:

1. **Valid?** Health checks decide whether the result is usable at all, for
   example "the model predicts more than one class". They read the task's
   original values, never a combined score.
2. **Acceptable?** Constraints decide whether a valid result meets your hard
   requirements, for example "balanced accuracy at least 0.9".
3. **Preferred?** Selection decides which acceptable result is better.

The `evaluation:` section declares questions 2 and 3, and describes what each
quantity means. Question 1 stays with your `task_health:` section.

## Step 1: one main metric needs no evaluation section

If one number with a direction says everything, leave `evaluation:` out. The
run ranks candidates by the main metric in the direction its declaration JSON
states. The CSV template does this: `declared/metric_balanced_accuracy.json`
declares `balanced_accuracy` with `"direction": "higher"`.

Leaving the section out adds nothing to the task's identity or to any
agent's prompt.

## Step 2: tell every agent what each number means

Add the section with one *component* per quantity. A component points at a
declared metric and adds its scientific meaning. This example assumes that
the task also declares a secondary metric `worst_class_error` (the error rate
on the hardest class, lower is better). Without a secondary metric, keep
only the first component; that is the commented example in the template's
`task.yaml`.

```yaml
evaluation:
  components:
    - kind: metric
      id: balanced_accuracy             # your name for this component
      metric: balanced_accuracy         # a declared metric id
      meaning: Mean per-class recall on validation.csv; each species counts equally.
      units: fraction (0 to 1), mean over classes
      range: {lower: 0.0, upper: 1.0}   # descriptive only
    - kind: metric
      id: worst_class_error
      metric: worst_class_error         # declared under secondary_metrics:
      meaning: Error rate on the hardest species.
      units: fraction (0 to 1) of the hardest class's rows
      range: {lower: 0.0, upper: 1.0}
  selection:
    kind: primary                       # still rank by the main metric
```

What each field does:

- `kind: metric` says the component reads a declared metric.
- `id` is the name the rest of the section uses for this component. It starts
  with a letter and contains only letters, digits, `_` and `-`.
- `metric` is the `id` from a metric declaration JSON, main or secondary.
  Each metric can appear in only one component.
- `meaning` is the scientific meaning in your words.
- `units` (optional) is the unit label shown to agents.
- `range` (optional) tells agents the values to expect. It is only a
  description: it does not reject, clip or rescale any value.
- `selection: {kind: primary}` keeps the usual ranking by the main metric.

There is no `direction` field. Each component takes its direction from its
metric declaration, so "higher is better" is stated in exactly one place.
Every value in the section (ranges, formula bounds, thresholds) is in the
units of the metric's reported score: the value after any `transform` its
declaration applies.

The agents now see this block in their prompts (shortened):

```text
[TASK EVALUATION]
These are task-declared evaluation rules, not observed results.
...
Components:
- balanced_accuracy (metric: balanced_accuracy)
  Meaning: Mean per-class recall on validation.csv; each species counts equally.
  Units: fraction (0 to 1), mean over classes
  Preference: maximize (higher is better)
  Descriptive range: [0, 1] (descriptive only)
- worst_class_error (metric: worst_class_error)
  Meaning: Error rate on the hardest species.
  Units: fraction (0 to 1) of the hardest class's rows
  Preference: minimize (lower is better)
  Descriptive range: [0, 1] (descriptive only)
Selection:
- kind: primary
- Deterministic ranking: balanced_accuracy; maximize (higher is better).
Constraints:
- None declared.
[END TASK EVALUATION]
```

Listing a secondary metric as a component only describes it. It still does
not influence which candidate wins. That needs step 3 or step 5.

## Step 3: combine two numbers with a weighted sum

To let both numbers decide the ranking, replace `selection` with a formula.
The only formula family is `weighted_sum`:

```yaml
  selection:
    kind: formula
    formula:
      family: weighted_sum
      params:
        terms:
          - component: balanced_accuracy
            weight: 3
            lower: 0.5
            upper: 1.0
            out_of_range: clip
          - component: worst_class_error
            weight: 1
            lower: 0.0
            upper: 0.5
            out_of_range: clip
```

Each term names a component `id` (not a metric id) and needs four values:

- `weight`: a positive number. Only the ratio between weights matters.
- `lower` and `upper`: the interval that is mapped onto 0 to 1 for this term,
  with `lower` below `upper`. These bounds are required and separate from
  the component's descriptive `range`.
- `out_of_range`: what happens to a value outside `[lower, upper]`.
  `clip` moves it to the nearest bound first. `refuse` gives the candidate
  no score at all.

### How a candidate's score is computed

Each term turns its raw value into a *utility* between 0 and 1, where 1 is
best for that term:

- for a higher-is-better metric: `u = (value - lower) / (upper - lower)`;
- for a lower-is-better metric: `u = (upper - value) / (upper - lower)`.

The candidate's score is the weighted average of the utilities:
`(3 * u_balanced_accuracy + 1 * u_worst_class_error) / 4`. It is always
between 0 and 1, and higher is always better, whatever the directions of
the components.

Take two candidates:

| | balanced_accuracy | worst_class_error |
| --- | --- | --- |
| Candidate A | 0.90 | 0.20 |
| Candidate B | 0.94 | 0.40 |

Candidate A:

- `u_balanced_accuracy = (0.90 - 0.5) / 0.5 = 0.80`
- `u_worst_class_error = (0.5 - 0.20) / 0.5 = 0.60`
- score `= (3 * 0.80 + 1 * 0.60) / 4 = 0.75`

Candidate B:

- `u_balanced_accuracy = (0.94 - 0.5) / 0.5 = 0.88`
- `u_worst_class_error = (0.5 - 0.40) / 0.5 = 0.20`
- score `= (3 * 0.88 + 1 * 0.20) / 4 = 0.71`

A wins, although B has the higher balanced accuracy: B gained 0.04 balanced
accuracy but doubled its error on the hardest class.

A third candidate with balanced accuracy 0.45, below `lower`, shows the
`out_of_range` policy. With `clip` its value counts as 0.5, so
`u_balanced_accuracy = 0`; the other term still contributes. With `refuse`
the candidate gets no score and cannot be ranked.

### Read the trade-off before you run

The check in step 6 prints a `marginal_rates` entry for each term: how much
the score changes per raw unit of that component, inside its bounds. For this
formula:

```json
"marginal_rates": [
  {"component": "balanced_accuracy", "utility_per_raw_unit_exact": "3/2", "out_of_range": "clip"},
  {"component": "worst_class_error", "utility_per_raw_unit_exact": "-1/2", "out_of_range": "clip"}
]
```

(The real output prints each field on its own line.) The rate is
`weight / (sum of weights) / (upper - lower)`, negative for a lower-is-better
component. Read it as an exchange rate:

- +0.01 balanced accuracy adds 0.015 to the score (3/2 × 0.01);
- +0.01 worst-class error removes 0.005 (1/2 × 0.01);
- so 0.01 of balanced accuracy is worth 0.03 of worst-class error.

Check it against the example: B gained 0.04 × 3/2 = 0.06 and lost
0.20 × 1/2 = 0.10, a net change of −0.04, which is 0.71 − 0.75.

The bounds change the rate as much as the weights do. With
`lower: 0.0` instead of 0.5 for balanced accuracy, the same weight 3 gives a
rate of 3/4, half as strong. Outside its bounds a clipped term has rate 0,
because further changes no longer move its utility. If the exchange rate is
not the one you mean scientifically, change the weights or the bounds in
your own `task.yaml` until it is.

### What a formula changes in a run

A run can launch with a formula, and the step 6 check prints
`Launch check: admitted` for it. With a formula:

- the run ranks candidates by a new score named
  `evaluation.weighted_sum.v1.<identity>`; the step 6 check prints it as
  `effective_metric_id`, with `effective_units` `utility [0,1]`;
- Health checks still read the original metric values, never the combined
  score;
- any score threshold you set must name that new id, because 0.8 utility is
  not 0.8 balanced accuracy. For example `--target_score 0.8` also needs
  `--target_score_metric <effective_metric_id>`, and research-loop stop
  conditions that compare a score must use the same id. A threshold written
  for the main metric is refused rather than compared with the utility;
- two optional tuner settings are measured in score units:
  `--enable_chain_incumbent_formal_gates` (the formal skip/bypass gates) and
  `--degenerate_penalty_score`. When you set either one, also pass
  `--score_units_metric <effective_metric_id>` for the same reason;
- formulas work only when your task's own metric code scores the candidates
  (the CSV template does). Other scoring routes are refused: an external
  `CandidateEvaluationExecutor` when the run binds the task, and
  anchor-normalized scoring before the first training attempt. The step 6
  check does not test the scoring route, so `Launch check: admitted` does not
  prove your task scores its own candidates; see the
  [evaluation contract](../../../src/execute_tools/evaluation-contract.md).

## Step 4: a balancing rule in words

Some trade-offs are judgments, not formulas: "when two models are within
0.01 balanced accuracy, prefer the simpler one". `rubric_balance` records
such a rule for SIDERIUS's [LLM judges](../workflow-declarations.md#7-literature-reviews-and-llm-aggregation). It needs a rubric file declared in
the manifest's `rubrics:` section, for example
`declared/rubrics/deployability_v1.yaml`:

```yaml
schema_version: siderius.rubric/v1
id: deployability
version: "1"
scale_min: 1
scale_max: 5
criteria:
  - name: simplicity
    description: The model is small and easy to run on the field instrument.
    weight: 1.0
```

The manifest then names the rubric and the rule:

```yaml
rubrics:
  - config: declared/rubrics/deployability_v1.yaml

evaluation:
  components:
    - kind: metric
      id: balanced_accuracy
      metric: balanced_accuracy
      meaning: Mean per-class recall on validation.csv; each species counts equally.
      units: fraction (0 to 1), mean over classes
  selection:
    kind: rubric_balance
    rubric: {id: deployability, version: "1"}
    guidance: When balanced accuracy differs by less than 0.01, prefer the simpler model.
    deterministic_ranking:
      kind: primary
```

What the rule decides, and what it does not:

- `guidance` and the rubric are shown to every agent (proposer, interpreter,
  tuner planner and reflector, implementor, validator, literature review and
  data analysis), which then aim for it when they propose and refine models.
  No LLM judge scores your trained models against it yet, and the rubric adds
  no LLM calls or cost.
- The rule never produces a number. It cannot be a formula term or a
  constraint, and it is never compared like a metric.
- `deterministic_ranking` is required. It is either `{kind: primary}` or a
  `{kind: formula, ...}` block exactly as in step 3. Every place that ranks
  by number, including all comparisons inside one tuning run, uses it. It
  cannot itself be another `rubric_balance`.

A rubric can also be listed as a component (`kind: rubric`, with `id`,
`meaning` and `rubric: {id, version}`), so the agents see it as qualitative
evidence. It has no units, range or direction:

```yaml
    - kind: rubric
      id: judgment
      meaning: Whether the model is practical to run on the field instrument.
      rubric: {id: deployability, version: "1"}
```

Both forms launch. The run still ranks models only by
`deterministic_ranking`. For a formula, the inspection's
`required_capabilities` therefore also lists `formula aggregation`.

## Step 5: hard requirements (constraints)

A constraint says what a candidate must achieve to count at all:

```yaml
  constraints:
    - {component: balanced_accuracy, op: '>=', threshold: 0.9}
```

- `component` is a component `id` from the same section. It must be a
  numeric component such as a metric component; a rubric component is
  refused.
- `op` is one of `'>='`, `'>'`, `'<='`, `'<'`. Quote it: an unquoted `>`
  starts a different YAML construct and the file no longer parses.
- `threshold` is a number in the metric's own units, the value before any
  formula scaling or clipping.
- Several constraints must all hold. Two that no value can satisfy together,
  such as `>= 0.9` and `< 0.8` on the same component, are refused.

What works now, and what comes later:

- **What happens in a run:** after each round is scored, the framework
  compares the round's raw values with every constraint. A round that breaks
  one, or has no finite value for one, is recorded as not scoreable, with the
  reason in its record, for example
  `constraint balanced_accuracy >= 0.9 violated: 0.85`. Such a round is never
  chosen as the best result, the Trial winner or the incumbent, and the
  planner and interpreter see the reason. Trial and Formal rounds follow the
  same rule. The check in step 6 still warns about a constraint that works
  against the metric's own direction (for example
  `balanced_accuracy <= 0.99`).
- **Scoring route:** constraints need the native task-owned scoring step,
  the same one formula selection uses; other scoring routes refuse at launch.
- **Measurements:** a `kind: measurement` component measures the trained
  checkpoint once per candidate, after scoring the deliverable. Choose
  `measurement: trainable_parameter_count`, `total_parameter_count`,
  `model_bytes` or `inference_latency_ms`, and say which way is better with
  `direction: lower` or `higher`. Latency also needs a `protocol`: the input
  shape including batch, warm-up and repeat counts. The value is the median
  of the timed forward passes on the training device, in milliseconds; data
  loading is not included. For example:

  ```yaml
  - kind: measurement
    id: latency
    measurement: inference_latency_ms
    direction: lower
    meaning: Median forward latency of one input batch.
    protocol: {input_shape: [1, 1, 4096], warmup: 10, repeats: 50}
  ```

  Use the component in a formula term or a constraint like a metric. If the measurement
  fails, the record shows `measurement_results` with the reason and the
  candidate is not scoreable. A task such as "keep balanced accuracy at
  least 0.9 and minimize latency" combines a constraint on the metric with a
  formula term on the latency measurement.
- **Rubric components:** they launch as guidance for the agents; see step 4.

## Step 6: check your declaration

Save this script in your own project, for example as
`check_evaluation.py`:

```python
import json
import sys

from agent.evaluation_context import build_evaluation_prompt_context
from agent.prompt_templates.evaluation import render_evaluation_spec
from workflows.evaluation_composition import require_evaluation_runtime
from workflows.task_composition import TaskCompositionError, compose_run_task_bindings

try:
    task = compose_run_task_bindings(sys.argv[1])
except TaskCompositionError as error:
    sys.exit(f"Composition refused: {error}")
if task.evaluation is None:
    print("No evaluation section: candidates are ranked by the main metric.")
    sys.exit(0)
context = build_evaluation_prompt_context(task.evaluation, task.metric.spec, task.judge_task)
print(render_evaluation_spec(context))
print(json.dumps(task.evaluation.inspect(), indent=2))
try:
    require_evaluation_runtime(task.evaluation)
except TaskCompositionError as error:
    sys.exit(f"Launch check: {error}")
print("Launch check: admitted")
```

Run it from the SIDERIUS checkout's root folder:

```bash
.venv/bin/python /absolute/project/check_evaluation.py /absolute/project/tasks/iris/task.yaml
```

It reads the manifest and imports your plugin code, but reads no data and
starts no training or LLM call. Lines beginning `[PluginLoader]` come from loading the
model plugins and can be ignored. It prints three things:

1. **The block the agents see**, from `[TASK EVALUATION]` to
   `[END TASK EVALUATION]`.
2. **The inspection**: for a formula first `effective_metric_id`,
   `effective_direction` and `effective_units`; then `warnings`,
   `marginal_rates` (step 3),
   `required_capabilities` (the runtime parts your declaration needs) and
   `identity` (a 64-character fingerprint of the declaration).
3. **The launch check.** For the step 2 example it ends with
   `Launch check: admitted` and exit status 0. The formula of step 3
   ends the same way, and the inspection above it shows the
   `effective_metric_id` `evaluation.weighted_sum.v1.<identity>`, the
   `effective_units` `utility [0,1]` and the `marginal_rates` of step 3.

   Rubric guidance (step 4) and constraints on metric components (step 5)
   end the same way. Measurement components (step 5) end with exit status 1
   and a message such as the following, naming `measurements`:

   ```text
   Launch check: Evaluation composition succeeded, but launch requires unimplemented capabilities: measurements. Their runtime owners must land before this task can run.
   ```

   A real run performs this check before it reads any data, and stops with the
   same message.

A mistake in the declaration stops the script at the composition call with
`Composition refused: evaluation could not be composed:` followed by the
reason, such as:

| Message (after the prefix) | Cause |
| --- | --- |
| `component 'acc' names undeclared metric 'accuracy'` | `metric:` is not a declared main or secondary metric id |
| `multiple evaluation components alias the same metric` | two components point at one metric |
| `evaluation references undeclared component 'balanced_accuracy'` | a term or constraint names a metric id or a typo instead of a component `id` |
| `component 'judgment' is not deterministic quantitative evidence` | a term or constraint names a rubric component |
| `constraints on 'balanced_accuracy' have no feasible value` | contradictory constraints |
| `undeclared evaluation rubric 'deployability' version '1'` | the rubric is missing from `rubrics:` or its version differs |
| `evaluation must be a mapping; omit it to disable evaluation` | `evaluation:` is empty or a list |
| `... Extra inputs are not permitted` | an unknown field, such as `direction` on a component |
| `... Field required` | a required field, such as a term's `out_of_range`, is missing |
| `... Input should be a valid number` | a number written as a string, such as `threshold: '0.9'` |
| `... term.lower must be less than term.upper` | term bounds in the wrong order or equal (`range.lower must be less than range.upper` for a component range) |

A file that is not valid YAML at all, for example an unquoted `op: >=`,
stops at the same call with a different prefix:
`Composition refused: task composition manifest at '...' is not valid YAML (...)`.

Validation messages also name the field path, for example
`selection.formula.formula.weighted_sum.params.terms.0.out_of_range`.

## Limits

These limits are owned by the [evaluation contract](../../../src/execute_tools/evaluation-contract.md).

- At most 32 components and 64 constraints in one section.
- `meaning` and `guidance`: at most 1000 characters each. `units`: at most
  128 characters.
- Component `id`: starts with a letter; letters, digits, `_` and `-`; at
  most 100 characters.
- Every number is a finite number written as a number, not a string.
- Weights are greater than 0; for every term and range, `lower` is less than
  `upper`.
- Rubric files have their own limits (1 to 32 criteria, weights up to 100);
  see the [rubric section of the composition reference](../../reference/task-composition.md).

## Common mistakes

- **Using `range` as the formula bounds.** A component's `range` only informs
  the agents. The formula uses each term's own `lower` and `upper`, and they
  may differ from the range.
- **Writing a direction.** Direction comes from the metric declaration JSON.
  A `direction` field in the evaluation section is refused; to reverse a
  preference, the metric declaration itself must say `"lower"`.
- **Reading weights as absolute importance.** Weights are relative, and they
  act over the declared bounds: a term with weight 3 over a wide interval can
  move the score less than a term with weight 1 over a narrow one. Read the
  `marginal_rates` to see the real exchange rate.
- **Writing constraint thresholds as utilities.** A threshold is in the
  metric's own units (0.9 balanced accuracy), never on the 0 to 1 formula
  scale.
- **Expecting a listed secondary metric to change the ranking.** Only a
  formula term or a constraint makes a component part of the decision.
- **Forgetting to quote `op` or a rubric `version`.** Write `op: '>='`, not
  `op: >=`, and `version: "1"`, not `version: 1`; the version is text.

## Where to go next

- The [CSV template's `task.yaml`](../../../examples/task_templates/csv_classification/task.yaml)
  contains a commented `evaluation:` example you can uncomment.
- [Bring your own metric](../bring-your-own-metric.md): declare the
  secondary metrics your components refer to.
- [Structured evaluation in the composition reference](../../reference/task-composition.md#structured-evaluation-declarations-composition-and-inspection):
  the section's place among the other manifest sections.
- The [evaluation contract](../../../src/execute_tools/evaluation-contract.md)
  is the exact technical reference: every field, default, identity rule, the
  custom `component_kinds` extension and the downstream rules.
