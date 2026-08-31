#!/usr/bin/env python3
"""Score one composed task deliverable in an isolated child process.

The framework owns process isolation, scope transport, scoreability ordering,
and result persistence. The active task composition owns deliverable decoding,
ground-truth construction, metric arithmetic, and scientific references.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%m/%d/%Y %I:%M:%S %p",
    level=logging.INFO,
)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """The child's argv surface — declaration only, no side effects.

    Step 12 / PR-12d D4a. Split out so the surface can be inspected
    without RUNNING the child, which is what made every observable below
    reachable only through a subprocess before.
    """
    parser = argparse.ArgumentParser(
        description="Score one deliverable through its composed task metric.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["fix", "agent"],
        default="fix",
        help="Baseline (fix) or agent-produced (agent) denoised file.",
    )
    parser.add_argument(
        "--data_dir",
        "-d",
        type=str,
        default=None,
        help="Directory containing the denoised HDF5 file.",
    )
    # Step 12 / PR-12d D4b — the SAME four flags the training and inference
    # children accept, emitted by the SAME `task_scope_argv`. The training
    # pair is accepted and ignored here; what this child consumes is the
    # EVALUATION scope, because a task-owned metric's ground truth lives in it
    # (`read_evaluation_payload` is a codec and decodes the deliverable only).
    parser.add_argument("--task_scope_ref", type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--task_scope_digest", type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--task_eval_scope_ref",
        type=str,
        default=None,
        help=(
            "Path to the run-scoped evaluation-scope artifact. The child "
            "verifies it against --task_eval_scope_digest before task-owned "
            "deserialization."
        ),
    )
    parser.add_argument(
        "--task_eval_scope_digest",
        type=str,
        default=None,
        help="Out-of-band sha256 of --task_eval_scope_ref. Half a pair is refused by name.",
    )
    parser.add_argument(
        "--dataset_profile_json",
        type=str,
        default=None,
        help="Required path to the composed run's resolved Dataset Profile JSON.",
    )
    parser.add_argument(
        "--raw_data_dir",
        type=str,
        default=None,
        help="Required directory containing the raw source files used by scoring.",
    )
    parser.add_argument(
        "--anchor_map",
        type=str,
        default=None,
        help="Deprecated compatibility option; task metrics own scientific references.",
    )
    parser.add_argument("--denoising_model", "-m", type=str, default="punet")
    parser.add_argument(
        "--exp_id", type=str, default="default_run", help="Experiment ID (required for agent mode)."
    )
    parser.add_argument(
        "--run_name", type=str, default="test_run", help="Run name for the auto-exploration."
    )
    parser.add_argument(
        "--file_index", "-i", type=int, default=6, help="Validation file index (0-19 fine)."
    )
    parser.add_argument(
        "-c",
        "--coarse",
        action="store_true",
        help="(Deprecated no-op; kept for CLI compatibility.)",
    )
    parser.add_argument(
        "-p", "--parallel", action="store_true", help="Use parallel workers inside score_vector."
    )
    parser.add_argument("-n", "--num_workers", type=int, default=8)
    parser.add_argument(
        "-w", "--weak", action="store_true", help="(Deprecated no-op; kept for CLI compatibility.)"
    )
    parser.add_argument(
        "--output_json", type=str, help="Optional path; denoising_score is merged into this JSON."
    )
    parser.add_argument(
        "--task_manifest",
        type=str,
        default=None,
        help="Required task-composition manifest emitted by the parent run binding.",
    )
    parser.add_argument(
        "--task_data_path_id",
        type=str,
        default=None,
        help="Required task-data-path identifier emitted by the parent run binding.",
    )
    parser.add_argument(
        "--task_data_path_identity",
        type=str,
        default=None,
        help="Step 12 / PR-12bc C2: the PARENT-PINNED IDENTITY of the implementation named by --task_data_path_id. The id says WHICH implementation; this says WHICH CODE. Verified BEFORE the implementation is consumed, because a registry hit is never proof of identity — a stale registration answers to the right name while running different bytes. ABSENT -> a parent that predates this transport made no claim, and a child must not invent one.",
    )
    return parser


def _resolve_child_data_path(args):
    """The run-bound TaskDataPath, child side. ONE resolution authority.

    All scoring paths use this one task-data-path resolution authority.
    """
    from execute_tools.task_data_path import TaskDataPathResolutionError
    from workflows.task_composition import resolve_child_task_data_path

    if args.task_data_path_id is None:
        raise TaskDataPathResolutionError(
            "Scoring requires --task_data_path_id from an explicit task composition."
        )
    return resolve_child_task_data_path(
        args.task_data_path_id,
        identity=args.task_data_path_identity,
        manifest_path=args.task_manifest,
    )


def _emit_task_owned_score(args, dataset_profile, metric, *, declared_naming=None) -> None:
    """Score a composed task's OWN deliverable through its OWN metric.

    Step 12 / PR-12d D4b. The frozen rule (§D.D):

        the scorer consumes the task-owned evaluation payload through the
        already-bound task/data authority, then invokes the composed metric
        implementation with the semantic payload THAT IMPLEMENTATION OWNS.

    **What the framework hands over, and why exactly these three.** The
    decoded ``evaluation_payload`` (from ``read_evaluation_payload``, a FROZEN
    protocol method), the ``task_scope`` the deliverable was produced from,
    and the physical ``data_dir``. All three are values the FRAMEWORK owns; a
    task-owned metric derives its ground truth from them in its own
    vocabulary.

    **Why the framework does not build ``truth`` itself.**
    ``read_evaluation_payload`` is a codec by contract and decodes the
    DELIVERABLE, which does not contain truth. Truth is task vocabulary —
    ``{image_id: class_index}`` for one task, decoded future frames for
    another — and a generic child that learned either shape would have
    re-acquired exactly the knowledge this seam removes. So it is derived
    where it belongs: inside the task's own metric implementation.
    **No new capability family, and no fifth protocol method** (§Q D-12d-27).

    ``deliverables`` still carries the task's own artifact path, so the
    metric's declared scoreability contract runs before any arithmetic.
    """
    from execute_tools.dataset_config import bind_dataset_profile
    from execute_tools.deliverable_spec import declared_naming_binding
    from execute_tools.scope_artifact import load_transported_scope
    from execute_tools.task_data_path import (
        EvaluationReadRequest,
        bind_task_data_path,
        task_declared_deliverable_name,
    )

    # ORDER IS LOAD-BEARING. The scope's bytes must be deserialized by the
    # implementation that WROTE them, and `load_transported_scope` resolves
    # that implementation from the run-scoped BINDING — so the binding is
    # established first. Resolving the scope before binding could select an
    # unrelated ambient implementation instead of the declared task codec.
    data_path = _resolve_child_data_path(args)
    with bind_task_data_path(data_path):
        task_eval_scope = load_transported_scope(
            args.task_eval_scope_ref, args.task_eval_scope_digest, leg="evaluation"
        )
    request = EvaluationReadRequest(
        deliverable_dir=args.data_dir,
        exp_id=args.exp_id,
        run_name=args.run_name,
        model_type=args.denoising_model,
    )
    # F-COV-8 — the run's DECLARED naming must be in force for BOTH of these.
    # `read_evaluation_payload` is the task's own codec and
    # `task_declared_deliverable_name` reads the task's own module-level namer;
    # a task that resolves EITHER through the framework's naming capability
    # reached `resolve_deliverable_naming()` unbound here and was refused —
    # the same defect the inference child had, in the child that already knew
    # how to bind. `main` composes the declaration ONCE and passes it in, so
    # this route cannot read a differently-composed manifest than the spec
    # derivation did.
    #
    # The two are under ONE `with` so the NAME reported and the payload SCANNED
    # are resolved under the same binding — reporting a name the scan did not
    # use is exactly the disagreement this fix exists to remove.
    with bind_dataset_profile(dataset_profile), declared_naming_binding(declared_naming):
        payload = data_path.read_evaluation_payload(request)
        deliverable = os.path.join(
            args.data_dir, task_declared_deliverable_name(data_path, request)
        )
    print(f"Scoring task-owned deliverable: {os.path.basename(deliverable)}")

    # `data_dir` here is the task's PHYSICAL DATA ROOT, which on this leg
    # arrives as `--raw_data_dir`. In the SCORING child `--data_dir` is the
    # DELIVERABLE directory, and the two must never be conflated — the Step-11
    # distinction recorded at `core/sandbox_executor.py:894` and in CLAUDE.md.
    #
    # It matters for any metric that reads ground truth from disk. Passing the
    # deliverable directory sends such a metric to the wrong filesystem tree;
    # a scope-only metric would not expose the same transport defect.
    compute_kwargs = {
        "evaluation_payload": payload,
        "task_scope": task_eval_scope,
        "data_dir": args.raw_data_dir,
    }
    outcome = metric.evaluate({0: deliverable}, **compute_kwargs)
    secondaries = _evaluate_task_owned_secondaries(args, deliverable, compute_kwargs)
    _emit_outcome(args, outcome, secondaries=secondaries)


def _evaluate_task_owned_secondaries(args, deliverable: str, compute_kwargs: dict) -> dict:
    """The run's DECLARED observational secondaries, on the task-owned route.

    Step 12 / PR-12d. Without this the composed contrast path evaluated the
    PRIMARY only: ``_evaluate_secondary_metrics`` has exactly one call site,
    inside the tuner's ``ScoringRoute.ANCHOR_NORMALIZED`` branch, and every
    composed contrast run takes ``TASK_OWNED``. So `macro_f1`, `log_loss`,
    `psnr` and `mae` were DECLARED, composed, and never computed — the
    "declared but not implemented is not L4" failure A2-b names, arriving one
    layer further along than D4c closed it.

    The tuner cannot do it here: on this route the deliverable is read by the
    CHILD, so the child is the only party holding the payload and the scope.

    A THIN ADAPTER — the frozen catch-order taxonomy (design §4.2, Q-P2b-2)
    moved to the SHARED owner,
    ``execute_tools.evaluation_metric.evaluate_declared_secondaries``, which
    this route and the tuner's in-process ANCHOR route both call. Before this
    extraction, this function and
    ``nodes/ml_hyperparameter_tune_agent/execution.py::_evaluate_secondary_metrics``
    each carried an independent copy of the same try/except order — the exact
    twinning hazard ``test_the_secondary_evaluator_has_exactly_one_owner``
    (Step 09a C6) exists to catch, and did.

    Returns a JSON-ready mapping with the three keys the record already
    carries, or ``{}`` when the run declared no secondaries — in which case
    nothing is written and the output payload is byte-unchanged.
    """
    from execute_tools.evaluation_metric import evaluate_declared_secondaries

    secondaries = _compose_child_secondary_metrics(args)
    if not secondaries:
        return {}

    results, refusals, errors = evaluate_declared_secondaries(
        secondaries, lambda secondary: secondary.evaluate({0: deliverable}, **compute_kwargs)
    )
    return {
        "secondary_metric_results": [r.model_dump(mode="json") for r in results],
        "secondary_metric_refusals": [r.model_dump(mode="json") for r in refusals],
        "secondary_metric_errors": errors,
    }


def _compose_child_secondary_metrics(args) -> tuple:
    """The declared secondaries, composed through the SAME authority as the primary.

    A composed child must never re-derive what the manifest declares; it asks
    the composition layer, exactly as it already does for the primary metric
    and the data path. A run with no manifest, or one declaring none, gets
    ``()`` and this whole path costs nothing.
    """
    if args.task_manifest is None:
        return ()
    from workflows.task_composition import compose_run_task_bindings

    return tuple(compose_run_task_bindings(args.task_manifest).secondary_metrics or ())


def _emit_outcome(args, outcome, *, secondaries: dict | None = None) -> None:
    """The child's ONE result-emission path — refusal or score.

    This is the single result emitter: structured stderr on refusal, exit 1,
    and the merged ``--output_json`` payload share one implementation.
    """
    from execute_tools.evaluation_metric import NotScoreableResult

    if isinstance(outcome, NotScoreableResult):
        for failure in outcome.verdict.failures:
            print(
                f"Deliverable not scoreable [{outcome.verdict.contract_id}] "
                f"{failure.requirement}: {failure.detail}",
                file=sys.stderr,
            )
        _merge_output_json_for(
            args,
            {
                "denoising_score": None,
                "file_vector": None,
                "not_scoreable": outcome.model_dump(mode="json"),
            },
        )
        sys.exit(1)

    print(f"\nFinal Denoising Score: {outcome.scalar:.4f}")
    payload = {
        "denoising_score": outcome.scalar,
        "file_vector": outcome.per_sample,
        # Step 12 / PR-12d — F-12d-32. The primary's IDENTITY, not only its
        # value. `outcome` is already a `MetricResult` carrying `metric_id`
        # and `direction`; emitting only `scalar`/`per_sample` dropped exactly
        # the two fields §I requires the terminal report to carry ("accuracy /
        # HIGHER", "mse / LOWER", each proven to be the implementation
        # production bound). The tuner sets `metric_payload` only inside its
        # ANCHOR_NORMALIZED branch, so on the task-owned route nothing else
        # could supply it and the record persisted `metric_result: null`
        # beside a perfectly good score — the value crossed, the identity did
        # not.
        #
        # `per_sample` is excluded for the same reason the tuner excludes it:
        # it is a POINTER to `file_vector` on the same record, not a second
        # copy. Emitted for BOTH routes through this emitter — it is strictly
        # additive information about what actually computed the number, and
        # the tuner's own value still takes precedence.
        "metric_result": outcome.model_dump(mode="json", exclude={"per_sample"}),
    }
    # Step 12 / PR-12d: the DECLARED observational secondaries, when the
    # task-owned route evaluated any. Merged only when non-empty, so a run
    # that declares none writes the same keys it always did — the §4.7
    # semantic-emptiness rule P2b froze, applied one route further along.
    if secondaries:
        payload.update(secondaries)
    _merge_output_json_for(args, payload)


def _merge_output_json_for(args, payload: dict) -> None:
    """Merge ``payload`` into ``--output_json`` (only when the parent pre-created it)."""
    from execute_tools.scoring_utils import coerce_nonfinite_to_none

    if args.output_json and os.path.exists(args.output_json):
        with open(args.output_json) as f:
            data = json.load(f)
        data.update(payload)
        with open(args.output_json, "w") as f:
            json.dump(coerce_nonfinite_to_none(data), f, indent=4)
        print(f"Updated {args.output_json} with score.")


def _require_composed_scoring_args(args: argparse.Namespace) -> None:
    """Refuse a scoring child that was not launched from a task composition."""
    required = {
        "--task_manifest": args.task_manifest,
        "--task_data_path_id": args.task_data_path_id,
        "--dataset_profile_json": args.dataset_profile_json,
        "--task_eval_scope_ref": args.task_eval_scope_ref,
        "--task_eval_scope_digest": args.task_eval_scope_digest,
    }
    missing = [flag for flag, value in required.items() if value is None]
    if missing:
        raise ValueError(
            "scoring requires an explicit task composition and transported "
            f"evaluation scope; missing {', '.join(missing)}"
        )


def main(argv: list[str] | None = None) -> None:
    """Score one deliverable through the active task composition."""
    args = build_parser().parse_args(argv)
    _require_composed_scoring_args(args)

    # ---------------------------------------------------------------------------
    # Deprecation notices for legacy flags
    # ---------------------------------------------------------------------------

    if args.coarse:
        logging.warning("--coarse is a deprecated scoring-child no-op.")
    if args.weak:
        logging.warning("--weak is a deprecated scoring-child no-op.")

    # ---------------------------------------------------------------------------
    # Resolve defaults
    # ---------------------------------------------------------------------------

    from execute_tools.data_paths import resolve_dataset_dir
    from execute_tools.dataset_config import load_dataset_profile

    args.data_dir = resolve_dataset_dir(args.data_dir, purpose="scoring deliverables")
    args.raw_data_dir = resolve_dataset_dir(args.raw_data_dir, purpose="scoring source data")
    dataset_profile = load_dataset_profile(args.dataset_profile_json)
    from workflows.task_composition import compose_deliverable_naming_from_manifest

    declared_naming = compose_deliverable_naming_from_manifest(args.task_manifest)

    # There is deliberately NO fallback: `compose_metric_from_manifest` raises
    # `TaskCompositionError` and this child lets it terminate the scoring
    # subprocess. A composed run must never silently score with an unrelated
    # metric; such a fallback would be indistinguishable from success.
    from workflows.task_composition import compose_metric_from_manifest

    metric = compose_metric_from_manifest(args.task_manifest)

    # Step 12 / PR-12d D4b — the TASK-OWNED scoring route.
    #
    # The framework hands the metric only the task-owned payload, transported
    # scope, and physical data root that the generic scoring contract owns.
    _emit_task_owned_score(args, dataset_profile, metric, declared_naming=declared_naming)


if __name__ == "__main__":
    main()
