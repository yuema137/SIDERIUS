#!/usr/bin/env python3
"""
denoising_score_single.py — single-file denoising score CLI.

Thin wrapper around :func:`execute_tools.scoring_utils.score_vector` that
produces one scalar denoising score for one validation file. Used by
``core/sandbox_executor.py::execute_scoring`` via subprocess (it runs under
a separate RSS-limited preexec, which is why the interface is CLI, not
in-process).

**Scoring convention** — Option B, anchor-normalized, global ``s_max``:

    per_segment  = (snr_sg[i] / s_max_GLOBAL) · snr_squid[i]
    grand_mean   = mean_i(per_segment)                # 200 segments / file
    score        = log_{5.27}(grand_mean)  if grand_mean > 0 else -inf

where ``s_max`` is read from ``segment_anchors.json`` (built on the fine
validation files 0-19). This is the same formula and the same global ruler
used by ``scoring_utils.score_vector`` and by the ground-truth ceiling, so
baseline, model, and ceiling scores are directly comparable.

The legacy ``--coarse`` and ``--weak`` flags are accepted for CLI backward
compatibility (sandbox_executor would break without them) but are no-ops;
a warning is logged when they are used.
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
        description="Single-file denoising score (Option B, global s_max).",
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
            "Step 12 / PR-12d: path to the run-scoped EVALUATION scope "
            "artifact. SUPPLIED -> this child scores the TASK's own "
            "deliverable through the TASK's own metric, with the scope its "
            "ground truth is derived from. Verified against "
            "--task_eval_scope_digest BEFORE deserialization. ABSENT -> "
            "regime-A TIDMAD scoring, unchanged."
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
        help=(
            "Path to a resolved Dataset Profile JSON. OMITTED resolves the "
            "Regime-A TIDMAD adapter; SUPPLIED but broken fails closed."
        ),
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
        help="Path to segment_anchors.json (used for global s_max). "
        "Default: the committed reference_data/segment_anchors.json, resolved from "
        "the package location (independent of the working directory).",
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
        help="Step 11 C5: the composed run's task-composition manifest, emitted "
        "by the parent FROM its resolved run binding only — never an operator "
        "flag. SUPPLIED -> the run's DECLARED metric is composed through the "
        "same authority the parent used, and a failure to compose terminates "
        "this subprocess rather than falling back. ABSENT -> the legacy "
        "un-composed derivation, byte-identical.",
    )
    parser.add_argument(
        "--task_data_path_id",
        type=str,
        default=None,
        help="D14-1: the child side of the task-data-path transport. Emitted by "
        "the parent process FROM its resolved run binding only — never an "
        "operator flag. SUPPLIED -> explicit binding (an unknown id fails "
        "closed, never falls back); ABSENT -> regime-A (TIDMAD compatibility).",
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

    Lifted verbatim from the agent-mode branch so the task-owned route and
    the TIDMAD agent route cannot drift into two resolutions.
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
    metric's declared scoreability contract runs BEFORE any arithmetic,
    exactly as it does for TIDMAD.
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
    # established first. Resolving the scope before binding gets TIDMAD's
    # regime-A default, which refuses a foreign payload BY NAME: the pairing
    # rule working, and the wrong question asked.
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
    # It matters for any metric that reads GROUND TRUTH from disk. Passing the
    # deliverable dir sent DAVIS' metric looking for
    # `<workspace>/DAVIS/JPEGImages/480p/...` and it failed loudly, which is
    # the good outcome; a metric that had silently found nothing there and
    # scored zero would not have been. Pets never noticed, because its truth
    # comes from the transported scope and its metric ignores this value —
    # so a Pets-only witness could not have caught it.
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

    Extracted so the task-owned route and the TIDMAD route emit through the
    same code: the same structured stderr on a refusal, the same exit 1, the
    same merged ``--output_json`` keys. A second emitter is how two routes
    start reporting differently.
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


def main(argv: list[str] | None = None) -> None:
    """Score ONE deliverable. The child's whole behaviour, in a function.

    Step 12 / PR-12d D4a — a BEHAVIOUR-PRESERVING restructure. Every
    statement below was previously executed at MODULE level, which meant
    this file could not be imported, could not be called twice, and — the
    reason D4a exists — had no place to put a branch. D4b makes the
    SEMANTIC change; this commit makes only the structural one, so the two
    are reviewable apart.

    Observables are identical by construction: the same statements in the
    same order, the same ``sys.exit(1)`` on a structured refusal, the same
    stdout and stderr text, the same merged ``--output_json`` keys and the
    same argv surface. A PRE/POST differential oracle over six argv cases
    is the evidence.
    """
    args = build_parser().parse_args(argv)

    # ---------------------------------------------------------------------------
    # Deprecation notices for legacy flags
    # ---------------------------------------------------------------------------

    if args.coarse:
        logging.warning(
            "--coarse flag is maintained for CLI compatibility; "
            "scoring now uses the Option B global alignment."
        )
    if args.weak:
        logging.warning(
            "--weak flag is maintained for CLI compatibility; "
            "scoring now uses the Option B global alignment."
        )

    # ---------------------------------------------------------------------------
    # Resolve defaults
    # ---------------------------------------------------------------------------

    from execute_tools.build_anchor_map import resolve_anchor_map_path
    from execute_tools.data_paths import resolve_dataset_dir
    from execute_tools.dataset_config import (
        load_dataset_profile,
        resolve_dataset_profile,
        tidmad_topology,
    )

    args.data_dir = resolve_dataset_dir(args.data_dir, purpose="scoring deliverables")
    args.raw_data_dir = resolve_dataset_dir(args.raw_data_dir, purpose="scoring source data")
    # Anchor map: an explicit --anchor_map override wins; otherwise use the
    # committed reference artifact (reference_data/segment_anchors.json), resolved
    # from the package location independently of the current working directory. The
    # artifact is never regenerated during scoring; load_anchor_map (below) fails
    # clearly if it is missing or malformed.
    args.anchor_map = resolve_anchor_map_path(args.anchor_map)

    # ---------------------------------------------------------------------------
    # Filename construction — through the Deliverable Contract (Step 06 C3)
    # ---------------------------------------------------------------------------

    # D14-1 C3/C4. A composed scoring child loads the exact implementation named
    # by the transported manifest and verifies the parent-pinned identity. The
    # uncomposed compatibility path is activated explicitly below.
    from execute_tools.deliverable_spec import derive_run_deliverable_spec
    from execute_tools.evaluation_metric import (
        NotScoreableResult,
        derive_tidmad_metric,
    )

    # Dataset Profile: supplied-but-broken fails closed, absent keeps Regime-A.
    if args.dataset_profile_json is not None:
        dataset_profile = load_dataset_profile(args.dataset_profile_json)
    else:
        dataset_profile = resolve_dataset_profile()

    # 05c §3.2a Option A: the child RECONSTRUCTS the run's deliverable spec and
    # metric from the profile that already crosses — one derivation, the same
    # value the parent holds; no spec or metric is serialized, no argv is added.
    # The two deliverable-name literals 05c left here for Step 06 now resolve
    # through the naming authority: byte-identical names, declared once.
    # Step 11 C6 — a composed run's DECLARED deliverable naming, bound before the
    # spec is derived so `derive_run_deliverable_spec` resolves the run's
    # template rather than the shipped one. Same transported manifest C5 uses,
    # same PRESENCE discrimination; an un-composed run binds nothing and derives
    # byte-identically. The Deliverable Contract remains the naming owner — this
    # child reads a declaration, it does not invent one (R-11-3).
    #
    # F-COV-8 — composed ONCE, into a VALUE, and bound at every naming
    # consumer in this child. The original form built a single `_naming_ctx`
    # and entered it around the ONE statement below; a context manager cannot
    # be entered twice, so every later consumer ran unbound. The directory
    # SCAN in `read_evaluation_payload` re-derives its spec inside the call
    # (`tidmad_data_path.py:571`) and therefore resolved the SHIPPED template
    # while `deliverable_spec` here carried the DECLARED one — two answers
    # inside one child, silent for every in-tree pack because they all
    # hand-roll their names.
    from execute_tools.deliverable_spec import declared_naming_binding
    from workflows.task_composition import compose_deliverable_naming_from_manifest

    _declared_naming = (
        compose_deliverable_naming_from_manifest(args.task_manifest)
        if args.task_manifest is not None
        else None
    )

    with declared_naming_binding(_declared_naming):
        deliverable_spec = derive_run_deliverable_spec(dataset_profile)

    # Step 11 C5 (R-11-4) — the METRIC half of that reconstruction is no longer
    # unconditional. Step 06 chose to re-derive TIDMAD's metric here because
    # nothing else crossed; that choice is exactly what made this child
    # TIDMAD-only, and it is superseded for a COMPOSED run.
    #
    # Discrimination is by the PRESENCE of the transported manifest, never by a
    # task name. A composed run composes its DECLARED metric through the same
    # declaration -> MetricSpec -> implementation authority the parent used; an
    # un-composed run keeps the derivation byte-for-byte.
    #
    # There is deliberately NO fallback: `compose_metric_from_manifest` raises
    # `TaskCompositionError` and this child lets it terminate the scoring
    # subprocess. A composed run must NEVER silently score with TIDMAD's
    # metric — that is the C-P56-1 failure class one layer down, and a
    # fallback here would be indistinguishable from success.
    if args.task_manifest is not None:
        from workflows.task_composition import compose_metric_from_manifest

        metric = compose_metric_from_manifest(args.task_manifest)
    else:
        metric = derive_tidmad_metric(dataset_profile, deliverable_spec)

    # Step 12 / PR-12d D4b — the TASK-OWNED scoring route.
    #
    # Everything below this block is TIDMAD physics: a validation-file name, an
    # anchor map, a global s_max, a SampleSet built from segments-per-file, and
    # a metric call carrying all five. A composed task that declares its own
    # scope scores through ITS OWN metric instead, and the framework hands that
    # metric only what the framework legitimately owns.
    if args.task_eval_scope_ref is not None:
        _emit_task_owned_score(args, dataset_profile, metric, declared_naming=_declared_naming)
        return

    if args.denoising_model == "none":
        # RAW validation file — Step-02-owned INPUT topology, from the profile.
        fname = tidmad_topology(dataset_profile).dataset.validation_file_name(args.file_index)
        full_path = os.path.join(args.data_dir, fname)
    elif args.mode == "fix":
        fname = deliverable_spec.naming.unqualified_name(
            model_type=args.denoising_model, input_identity=args.file_index
        )
        full_path = os.path.join(args.data_dir, fname)
    else:  # agent
        # D14-1 C4 — the production scoring read resolves the run's deliverables
        # THROUGH the task data path's decoded payload (child side of the
        # transport: SUPPLIED+unknown fails closed; ABSENT is regime-A). A file
        # the payload does not contain keeps its authority-derived EXPECTED path,
        # so the Step-06 scoreability contract still owns the structured
        # missing-deliverable refusal — the failure mode is byte-identical.
        from execute_tools.dataset_config import bind_dataset_profile
        from execute_tools.task_data_path import (
            EvaluationReadRequest,
            TaskDataPathResolutionError,
        )

        # C3: one resolution authority across all three children. Scoring already
        # had the manifest for its metric; the data path now reads it too, so an
        # out-of-tree task resolves the same way here as in training and inference.
        from workflows.task_composition import resolve_child_task_data_path

        if args.task_data_path_id is None:
            raise TaskDataPathResolutionError(
                "Scoring requires --task_data_path_id from an explicit task composition."
            )
        _data_path = resolve_child_task_data_path(
            args.task_data_path_id,
            identity=args.task_data_path_identity,
            manifest_path=args.task_manifest,
        )
        # F-COV-8 — THE SCAN. `read_evaluation_payload` re-derives its spec
        # inside the call (`tidmad_data_path.py:571`), so it reads the naming
        # ContextVar LIVE. Unbound, it scanned `deliverable_dir` for the
        # SHIPPED `abra_validation_denoised_*` template while the `else`
        # branch below builds its expected path from `deliverable_spec.naming`
        # — the DECLARED one. The scan then matched nothing and the fallback
        # quietly covered for it, so the disagreement never surfaced as an
        # error; it just made the payload-resolution authority dead code for
        # any run that declared its own template.
        with bind_dataset_profile(dataset_profile), declared_naming_binding(_declared_naming):
            _payload = _data_path.read_evaluation_payload(
                EvaluationReadRequest(
                    deliverable_dir=args.data_dir,
                    exp_id=args.exp_id,
                    run_name=args.run_name,
                    model_type=args.denoising_model,
                )
            )
        _resolved = _payload.get(args.file_index) if isinstance(_payload, dict) else None
        if _resolved is not None:
            full_path = _resolved
            fname = os.path.basename(_resolved)
        else:
            fname = deliverable_spec.naming.name(
                model_type=args.denoising_model,
                run_name=args.run_name,
                exp_id=args.exp_id,
                input_identity=args.file_index,
            )
            full_path = os.path.join(args.data_dir, fname)

    # ---------------------------------------------------------------------------
    # Score THROUGH the metric handle: scoreability first, then score_vector
    # ---------------------------------------------------------------------------

    from execute_tools.build_anchor_map import load_anchor_map
    from execute_tools.scoring_utils import coerce_nonfinite_to_none

    anchor_data = load_anchor_map(args.anchor_map)
    s_max = float(anchor_data["s_max"])
    anchors = anchor_data["anchors"]

    sample_set = {
        args.file_index: list(range(tidmad_topology(dataset_profile).dataset.segments_per_file))
    }

    def _denoised_fn(_fi: int) -> str:
        # score_vector calls this per file-index; we only have one file here.
        return fname

    def _merge_output_json(payload: dict) -> None:
        """Merge ``payload`` into ``--output_json`` (only when the parent pre-created it)."""
        if args.output_json and os.path.exists(args.output_json):
            with open(args.output_json) as f:
                data = json.load(f)
            data.update(payload)
            safe_data = coerce_nonfinite_to_none(data)
            with open(args.output_json, "w") as f:
                json.dump(safe_data, f, indent=4)
            print(f"Updated {args.output_json} with score.")

    print(f"Calculating score for [{args.mode.upper()}] mode: {fname}")
    print(f"  s_max (global, from anchor map) = {s_max:.4f}")

    # The metric's arithmetic receives exactly the keyword arguments score_vector
    # received before Step 06; the handle only puts the acceptance contract in
    # front of them (design §5, §9).
    outcome = metric.evaluate(
        {args.file_index: full_path},
        data_dir=args.data_dir,
        sample_set=sample_set,
        anchor_map=anchors,
        s_max=s_max,
        denoised_filename_fn=_denoised_fn,
        raw_data_dir=args.raw_data_dir,
        parallel=args.parallel,
        num_workers=args.num_workers,
        legacy_mode=False,
        profile=dataset_profile,
    )

    if isinstance(outcome, NotScoreableResult):
        # A STRUCTURED refusal, not a scorer traceback: named on stderr (always
        # captured by the parent's error formatter), persisted into the output
        # JSON when one was given, and exit 1 — the same exit the pre-Step-06
        # "File not found" pre-check used, so the parent's classifier ("error")
        # and every caller's handling are unchanged (design §19 C3 §6).
        for failure in outcome.verdict.failures:
            print(
                f"Deliverable not scoreable [{outcome.verdict.contract_id}] "
                f"{failure.requirement}: {failure.detail}",
                file=sys.stderr,
            )
        _merge_output_json(
            {
                "denoising_score": None,
                "file_vector": None,
                "not_scoreable": outcome.model_dump(mode="json"),
            }
        )
        sys.exit(1)

    file_vector, scalar = outcome.per_sample, outcome.scalar

    print(f"\nFinal Denoising Score: {scalar:.4f}")

    # ---------------------------------------------------------------------------
    # Optional: merge into output JSON
    # ---------------------------------------------------------------------------

    # The merged keys are exactly the pre-Step-06 two. The child's payload is
    # json-dumped into an LLM prompt by one caller path (the legacy skill route →
    # reflector), and Step 06 changes no prompt (design §8): the metric's identity
    # reaches the record through the tuner's own handle, not through this file.
    _merge_output_json({"denoising_score": scalar, "file_vector": file_vector})


if __name__ == "__main__":
    main()
