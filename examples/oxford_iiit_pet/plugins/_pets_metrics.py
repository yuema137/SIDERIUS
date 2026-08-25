"""Oxford-IIIT Pet — the pack's OWN terminal metric implementations.

Step 12 / PR-12d D4c (ruling A2-b). A metric that is DECLARED but not
implemented is not L4: the frozen metric set has to compute, and composition
has to prove it bound *this* implementation rather than something that merely
accepted the declaration.

**Why these live here and not in `execute_tools/evaluation_metric.py`.** They
are this task's science. `macro_f1` over *37 classes* is a fact about Oxford
pets, not about classification in general, and the framework has no business
holding it. `examples/<pack>/plugins/` is the sanctioned location for
task-owned code (`test_pack_governance.py` guard (b)); production never
imports `examples/` — these are reached only through an explicit
``implementation: {file: …}`` reference, which is the same dynamic route the
`fourth_task` fixture already exercises end to end. The leading underscore
keeps them out of the directory scanners, exactly like `_pets_health_views.py`.

Both read the generic scoring vocabulary — ``evaluation_payload``,
``task_scope``, ``data_dir`` — the three values the FRAMEWORK owns. Truth
comes from the evaluation scope, which is the run's ground-truth authority;
nothing here re-reads a manifest or invents a second source.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from execute_tools.evaluation_metric import EvaluationMetric

#: Oxford-IIIT Pet has 37 breeds. Declared here, in the task's own file,
#: because it is a fact about THIS dataset — the framework must never learn it.
#: It is also the denominator the shipped declaration names
#: ("unweighted_mean_of_per_class_f1_over_37_classes"), so a class that is
#: never predicted and never present still counts, at F1 = 0.
PETS_CLASS_COUNT = 37


def _truth_from_scope(task_scope: Any) -> dict[str, int]:
    """``{image_id: class_index}`` from the run's evaluation scope.

    The scope IS the truth authority — it is what the run declared it would be
    evaluated on. Deriving truth from anything else (a manifest re-read, the
    deliverable itself) would let the denominator drift from the scope the
    scoreability contract already validated.
    """
    rows = getattr(task_scope, "rows", None)
    if rows is None:
        raise ValueError(
            "the Pets metrics need the run's evaluation scope to read truth from; "
            f"got {type(task_scope).__name__}, which declares no `rows`."
        )
    return {str(row.image_id): int(row.class_index) for row in rows}


class PetsAccuracyMetric(EvaluationMetric):
    """Fraction of the evaluation scope whose predicted breed is correct.

    **Why this exists beside the framework's `AccuracyMetric`.** The two
    compute the identical arithmetic; they differ in the vocabulary they are
    called with, and that difference is the whole point.

    ``execute_tools.evaluation_metric.AccuracyMetric`` takes ``predictions``
    and ``truth`` — two already-assembled mappings. That is the right shape
    for an IN-PROCESS caller like ``scripts/run_pets_gate2.py``, which loads
    the manifests itself and hands both over. It is the wrong shape for the
    composed SCORING CHILD, which owns only the three values the FRAMEWORK
    owns — ``evaluation_payload``, ``task_scope``, ``data_dir`` — because
    assembling truth from a scope is TASK knowledge the framework must not
    have.

    Binding the framework metric into a composed run therefore fails with
    ``TypeError: AccuracyMetric._compute() got an unexpected keyword argument
    'evaluation_payload'``, which is exactly what a real scoring child did.
    The fix is not to teach generic core how a Pets scope stores truth; it is
    for the pack to bring a metric that already knows.

    The DENOMINATOR is the truth mapping, so a prediction missing from a
    partial deliverable counts as not-correct — the declared aggregation read
    literally, and the same rule ``PetsMacroF1Metric`` applies.
    """

    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("accuracy",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, int],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        truth = _truth_from_scope(task_scope)
        if not truth:
            raise ValueError(
                "accuracy needs a non-empty evaluation scope — an empty scope is a "
                "caller wiring defect, not a scoreability case."
            )
        correct = sum(
            1 for image_id, label in truth.items() if evaluation_payload.get(image_id) == label
        )
        return correct / len(truth), None, ()


class PetsMacroF1Metric(EvaluationMetric):
    """Unweighted mean of per-class F1 over all 37 breeds.

    **Macro, not micro, and the difference is the point.** Micro-F1 on a
    single-label problem equals accuracy, so it would say nothing accuracy does
    not already say. The macro mean weights every breed equally, which is what
    makes it able to see the failure Pets actually exhibits: the D14 collapse
    predicted essentially one class, scoring 0.027 accuracy — chance — while a
    metric that ignored per-class structure would have reported one number and
    no clue why.

    A class with no support and no predictions has undefined precision and
    recall; it contributes **0.0** over a denominator of
    :data:`PETS_CLASS_COUNT`. That is the declared aggregation read literally
    ("over 37 classes"), and it is deliberately the pessimistic reading: a
    model that never predicts a breed should not be rewarded for it.
    """

    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("macro_f1",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, int],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        truth = _truth_from_scope(task_scope)
        if not truth:
            raise ValueError(
                "macro_f1 needs a non-empty evaluation scope — an empty scope is a "
                "caller wiring defect, not a scoreability case."
            )

        true_positive = [0] * PETS_CLASS_COUNT
        predicted = [0] * PETS_CLASS_COUNT
        actual = [0] * PETS_CLASS_COUNT

        for image_id, label in truth.items():
            actual[label] += 1
            prediction = evaluation_payload.get(image_id)
            # A missing prediction is NOT-CORRECT, never an exclusion: the
            # denominator is the scope, so a partial deliverable is penalised
            # rather than silently flattered. Same rule AccuracyMetric applies.
            if prediction is None:
                continue
            predicted[int(prediction)] += 1
            if int(prediction) == label:
                true_positive[label] += 1

        total = 0.0
        for cls in range(PETS_CLASS_COUNT):
            if predicted[cls] == 0 or actual[cls] == 0:
                continue  # undefined -> 0.0, already the running contribution
            precision = true_positive[cls] / predicted[cls]
            recall = true_positive[cls] / actual[cls]
            if precision + recall > 0:
                total += 2 * precision * recall / (precision + recall)
        return total / PETS_CLASS_COUNT, None, ()


class PetsLogLossMetric(EvaluationMetric):
    """Multi-class cross-entropy of the predicted distribution, LOWER better.

    The reason this identity exists at all: §22.9a chose it deliberately to
    force the question of whether a metric id may look like a loss name. D16
    settled it — `MetricSpec.id` is OPAQUE, and what separates a metric from a
    loss is the CONTRACT (a deliverable, an aggregation, an executable
    scoreability contract), not the spelling.

    **It consumes a probability payload, not argmax labels**, which is the
    whole point of declaring it beside `macro_f1`: accuracy and F1 see only the
    arg-max decision, while log-loss sees the confidence behind it. A model
    that is right for weak reasons and one that is right for strong reasons are
    indistinguishable to the first two and separated by this one.

    Probabilities are clipped to ``[eps, 1-eps]`` before the log — an
    over-confident zero on the true class is otherwise ``-inf``, which would
    make one sample dominate every aggregate and turn a real (if bad) score
    into a non-number.
    """

    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("log_loss",)

    #: Standard clip, matching the convention scikit-learn uses, so a value
    #: computed here is comparable to one computed with a familiar tool.
    EPSILON: ClassVar[float] = 1e-15

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, Any],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        import math

        truth = _truth_from_scope(task_scope)
        if not truth:
            raise ValueError(
                "log_loss needs a non-empty evaluation scope — an empty scope is a "
                "caller wiring defect, not a scoreability case."
            )

        # The pack's payload is a Mapping of arg-max LABELS carrying the
        # distribution alongside (`PetsEvaluationPayload`), so that every
        # label-reading metric is unchanged. This is the one metric that needs
        # the other half, and it asks for it by name rather than by indexing —
        # indexing returns the label, which is how this silently scored a
        # class index as a probability the first time.
        distributions = getattr(evaluation_payload, "probabilities", None)

        total = 0.0
        for image_id, label in truth.items():
            distribution = None if distributions is None else distributions.get(image_id)
            if distribution is None:
                raise ValueError(
                    f"log_loss needs a probability vector for {image_id!r} and this "
                    "deliverable carries none. The pack writes one beside the CSV "
                    "whenever the model produced a distribution; a producer that "
                    "handed back an already-decided class index has nothing to "
                    "write, and a class index read as a probability would be a "
                    "plausible number computed from the wrong thing."
                )
            probability = float(distribution[label])
            clipped = min(max(probability, self.EPSILON), 1.0 - self.EPSILON)
            total += -math.log(clipped)
        return total / len(truth), None, ()
