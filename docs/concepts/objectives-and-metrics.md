# Objectives, metrics, and what "better" means

**Answers**: why there are several numbers, and which one actually decides anything.

---

## Four roles, not four formulas

A run produces several numbers. They differ by the **role they play in the
lifecycle**, not necessarily by their mathematics. The same computation can
legitimately occupy more than one role.

| role | question it answers | who consumes it |
|---|---|---|
| **Training objective** | what is optimisation minimising, right now, on this batch? | the optimiser |
| **Validation history** | how is the model behaving across epochs, on held-out data? | the diagnosis, the agents |
| **Primary metric** *(golden metric)* | how good is the finished model, scientifically? | **model selection** |
| **Secondary metric** | what else is worth knowing about this result? | the agents, as evidence |

![The four quantities a run produces and who consumes each](../assets/three-kinds-of-number.svg)

The distinction that matters most: **only the primary metric selects models.**
Everything else informs.

## Why the same formula appears twice

DAVIS is the clearest illustration. Its training objective is exact L1 (MAE) —
declared *authoritative* by the pack, so the task's declaration overrides
whatever loss the LLM planner picks — its validation history is mean validation
MAE per epoch, and MAE is also a declared terminal secondary metric — while the
primary metric is MSE. Three roles, one formula, and that is correct: "what
optimisation descends" and "what the science is judged on" are different
questions that happen to have related answers.

This is why SIDERIUS does not distinguish losses from metrics by *name*. A metric
identity is opaque — `log_loss` is as declarable as `accuracy`. What makes
something a metric is that it has a deliverable to read, an aggregation, and an
executable scoreability contract. What makes something an objective is that it is
what training minimises.

## Direction is declared, never inferred

Every metric declares `direction: higher` or `direction: lower`. There is no
`higher_is_better` boolean and no heuristic anywhere.

This is not pedantry. TIDMAD's denoising score is **negative-valued and
higher-is-better** — any rule that guessed direction from sign, or from the word
"loss" or "error" in a name, would invert the entire run. One authority
(`MetricOrder`) interprets direction, and every ordering decision in the
framework asks it. Even the prose the agents read — "higher is better", "the best
score so far" — is rendered from that authority rather than written by hand.

Practical consequence: if you declare a metric, declare its direction correctly
and you are done. Nothing downstream needs to know your metric's sign, scale, or
name.

## Secondary metrics are evidence, not objectives

Secondary metrics are **observational**. They are evaluated wherever the primary
is evaluated, recorded, and shown to the agents — and they influence no ordering
expression anywhere in the framework. Ranking, incumbent selection and
per-partition best-of all ignore them entirely.

That constraint is deliberate. It is what lets you watch six quantities during a
run without accidentally turning the run into a multi-objective optimisation
whose trade-off nobody declared.

If you want a quantity to *decide* something, it must be the primary metric.

## When a result cannot be scored at all

Before any arithmetic runs, a metric's **scoreability contract** answers "is this
deliverable scoreable?" — is the output present, the right shape, readable. If
not, the run records a structured refusal: an `error_scoring` record with
`failure_type="not_scoreable"` and the reason.

This matters because the alternative is worse. A missing or malformed output that
falls through to the arithmetic produces *a number* — and a number that is
actually an artefact is far more damaging to a research loop than an honest
refusal.

## The three example tasks

| | TIDMAD | Oxford-IIIT Pet | DAVIS 2017 |
|---|---|---|---|
| shape | 1-D scientific signal | RGB image | RGB spatiotemporal |
| task | denoising | 37-way classification | 8→4 future-frame prediction |
| **training objective** | focal loss | categorical cross-entropy | MAE / L1 |
| **validation history** | per-epoch validation loss | mean validation CE per epoch | mean validation MAE per epoch |
| **primary metric** | denoising score — **higher**, negative-valued | accuracy — **higher** | MSE over all predicted pixels × channels × frames — **lower** |
| **declared secondaries** | — | macro-F1 (higher), `log_loss` (lower) | PSNR (higher, `data_range=1.0`), MAE (lower) |
| status of those secondaries | — | ✅ **implemented pack-locally and evaluated** | ✅ **implemented pack-locally and evaluated** |

The last row records the historical composed `G-12d` runs. Scientific metric
implementations now live in siderius-exp under
`tasks/oxford_iiit_pet/plugins/_pets_metrics.py` and
`tasks/davis_future_prediction/plugins/_davis_metrics.py`; they resolve through
the same manifest mechanism as the primary. In those historical runs — each `ExperimentRecord` carries their values in
`secondary_metric_results`, in both directions at once (Pets records a
higher-is-better `macro_f1` beside a lower-is-better `log_loss`). Declared *and*
evaluated — the earlier state, declarations with no production implementation,
ended when PR-12d landed.

TIDMAD's primary metric is a frozen scientific definition. It is the task's
definition, not a tunable — it is never reweighted, clipped or renormalised to
make a result look better.

---

## Next

- [Health gates](health-gates.md) — the other kind of number, and why it is not a score
- [Task composition reference](../reference/task-composition.md) — how to declare a metric
- [Metrics mechanism reference](../agent-reference/mechanisms/metrics.md) — for implementers
