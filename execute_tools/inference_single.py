import argparse
import contextlib
import gc
import json
import os
import time
from typing import Any, NamedTuple, cast

import h5py
import numpy as np
import torch
from tqdm import tqdm

# D14-1 C3. The parent transports the resolved task id, implementation identity,
# and manifest. Composed children load that exact implementation from the
# manifest; real-task imports must not pre-register another implementation under
# the same id. The uncomposed compatibility path is activated explicitly below.
from agent.schemas.model_io_contract import load_model_io_contract
from core.runtime_control.gpu_milestone_trace import tracer_from_environment
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from execute_tools.array2h5 import create_abra_file
from execute_tools.dataset_config import (
    DatasetProfile,
    bind_dataset_profile,
    declares_tidmad_topology,
    load_dataset_profile,
    resolve_dataset_profile,
    tidmad_topology,
)
from execute_tools.deliverable_spec import (
    DeliverableNaming,
    DeliverableSpec,
    DeliverableStorage,
    declared_naming_binding,
    default_deliverable_storage,
    derive_run_deliverable_spec,
)
from execute_tools.hdf5_deliverable import is_complete_hdf5_deliverable
from execute_tools.model_input_dtype import (
    INFERENCE_SITE_DTYPE,
    apply_contract_cardinality,
    resolve_input_dtype,
)
from execute_tools.scope_artifact import load_transported_scope
from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    TaskDataPathResolutionError,
    bind_task_data_path,
)
from execute_tools.workload_resolvers import resolve_inference_workload
from ml_models.loss_models_sandbox import get_target_torch_dtype
from ml_models.models_format_sandbox import LossConfig, get_config_class

# Import your sandboxed components for Agent Mode
from ml_models.models_sandbox import MODEL_REGISTRY
from ml_models.plugin_loader import UnknownOutputContractError, get_output_type

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


def _is_complete_trial_output(
    path: str,
    expected_samples: int,
    storage: DeliverableStorage | None = None,
) -> bool:
    """Compatibility name for declared HDF5 deliverable validation."""
    return is_complete_hdf5_deliverable(
        path,
        expected_samples,
        storage or default_deliverable_storage(),
    )


def _h5_dataset(f: h5py.File, *path: str) -> h5py.Dataset:
    """Type-only helper: walk an HDF5 path and narrow the final node to Dataset.

    h5py stubs declare ``__getitem__`` as ``Group | Dataset | Datatype``,
    which makes pyright reject chained indexing even though every site here
    ends on a real Dataset at runtime. Pure type-system shim — identical
    runtime semantics to ``f[a][b][c]``.
    """
    node: Any = f
    for k in path:
        node = node[k]
    return cast(h5py.Dataset, node)


def _persisted_storage(args: Any) -> DeliverableStorage:
    """The persisted-output representation in effect for this process.

    Step 05c. Carried on ``args`` for the same reason ``_model_io`` is
    (``:328``): ``process_batch`` already takes ``args``, and adding a
    parameter would ripple through every call site. Same two-case rule as the
    other contracts on this boundary — absent keeps the shipped default, which
    is what a caller predating 05c gets; present is authoritative.
    """
    spec = getattr(args, "_deliverable_spec", None)
    return spec.storage if spec is not None else default_deliverable_storage()


def _assert_training_sentinel(model_path: str, exp_id: str) -> None:
    """Raise ``error_training`` if the trainer-side ``_OK_<exp_id>`` sentinel
    is missing. The orchestrator pattern-matches the ``error_training:``
    prefix in the exception message to tag the failure category, so a
    silent training crash never gets misclassified as ``error_inference:
    FileNotFoundError`` on the .pth path. Phase 6.7 Fix 3.
    """
    sentinel_path = os.path.join(os.path.dirname(model_path), f"_OK_{exp_id}")
    if not os.path.exists(sentinel_path):
        raise RuntimeError(
            f"error_training: checkpoint never written: {model_path} "
            f"(missing sentinel: {sentinel_path})"
        )


def get_parser():
    """Defines the argument parser for both Fix and Agent modes."""
    parser = argparse.ArgumentParser(description="Inference with Fixed (Baseline) or Agent mode.")
    parser.add_argument("--mode", type=str, choices=["fix", "agent"], default="fix")
    parser.add_argument(
        "--task_data_path_id",
        type=str,
        default=None,
        help="D14-1: the child side of the task-data-path transport. Emitted "
        "by the parent process FROM its resolved run binding only — never an "
        "operator flag. SUPPLIED -> explicit binding (an unknown id fails "
        "closed, never falls back); ABSENT -> regime-A (TIDMAD compatibility).",
    )
    parser.add_argument(
        "--task_data_path_identity",
        type=str,
        default=None,
        help="Step 12 / PR-12bc C2: the PARENT-PINNED IDENTITY of the implementation named by --task_data_path_id. The id says WHICH implementation; this says WHICH CODE. Verified BEFORE the implementation is consumed, because a registry hit is never proof of identity — a stale registration answers to the right name while running different bytes. ABSENT -> a parent that predates this transport made no claim, and a child must not invent one.",
    )
    parser.add_argument(
        "--task_manifest",
        type=str,
        default=None,
        help="Step 12 / PR-12bc C3: the composed run's task-composition manifest, emitted by the parent FROM its resolved run binding only "
        "— never an operator flag. SUPPLIED -> a transported id that is not built into this child is composed from the run's OWN declaration, through the same authority the parent used, which is what lets an "
        "OUT-OF-TREE task reach a training or inference subprocess. ABSENT -> the id must already be registered here.",
    )
    # Step 12 / PR-12d seam C (B6). The SAME four flags the training child
    # already accepts, emitted by the SAME `_task_scope_argv`. The training
    # pair is accepted and ignored here — the parent emits both legs from one
    # acquisition, and a child that REFUSED a flag it does not consume would
    # make the emitter task- and child-aware, which is the coupling this seam
    # removes. What this child iterates is the EVALUATION scope.
    parser.add_argument("--task_scope_ref", type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--task_scope_digest", type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--task_eval_scope_ref",
        type=str,
        default=None,
        help=(
            "Step 12 / PR-12d: path to the run-scoped EVALUATION scope "
            "artifact. SUPPLIED -> this child iterates the TASK's own "
            "evaluation dataset and writes the TASK's own deliverable, "
            "instead of TIDMAD's SampleSet loop. Verified against "
            "--task_eval_scope_digest BEFORE deserialization. ABSENT -> "
            "regime-A, unchanged."
        ),
    )
    parser.add_argument(
        "--task_eval_scope_digest",
        type=str,
        default=None,
        help="Out-of-band sha256 of --task_eval_scope_ref. Half a pair is refused by name.",
    )
    parser.add_argument("--data_dir", "-d", type=str, default=None)
    parser.add_argument("--denoising_model", "-m", type=str, default="punet")
    parser.add_argument("--file_index", "-i", type=int, default=6)
    parser.add_argument(
        "--dataset_profile_json",
        type=str,
        default=None,
        help=(
            "Path to a resolved Dataset Profile JSON. OMITTED resolves the "
            "Regime-A TIDMAD adapter; SUPPLIED but broken fails closed."
        ),
    )

    # Agent Mode Specific Args
    parser.add_argument(
        "--model_io_json",
        type=str,
        default=None,
        help=(
            "Path to a resolved Model-I/O contract JSON. OMITTED means the "
            "Regime-A adapter (the model's own declaration, else this site's "
            "historical dtype). SUPPLIED but broken fails closed."
        ),
    )
    parser.add_argument("--model_cfg", type=str, help="Path to model config JSON")
    parser.add_argument("--loss_cfg", type=str, help="Path to loss config JSON")
    parser.add_argument("--exp_id", type=str, default="default_run")
    parser.add_argument(
        "--run_name", type=str, default="test_run", help="Run name for the auto-exploration."
    )
    parser.add_argument("--model_path", type=str, help="Path to the .pth state_dict")
    parser.add_argument(
        "--output_dir",
        type=str,
        default=None,
        help="Directory to write denoised H5 output. Defaults to data_dir.",
    )
    parser.add_argument(
        "--inference_batch_size",
        type=int,
        default=10,
        help="Number of segments per GPU forward pass. Per-model defaults set in sandbox_executor.py (punet/wavenet/fcnet=25, rnn=10, transformer=1).",
    )
    parser.add_argument(
        "--sample_set_json",
        type=str,
        default=None,
        help="Path to SampleSet JSON for trial mode. Overrides --file_index.",
    )
    parser.add_argument(
        "--timing_out_json",
        type=str,
        default=None,
        help="If set, write per-file inference timings to this JSON path. "
        "Trial-mode only; ignored in --mode fix or normal single-file mode.",
    )
    parser.add_argument(
        "--reuse_complete_outputs",
        action="store_true",
        help=(
            "In trial/sample-set mode, reuse exact attempt-named HDF5 outputs "
            "only after validating both channels against the deliverable "
            "contract's storage dtype and the expected length."
        ),
    )
    parser.add_argument(
        "--runtime_observation_out",
        type=str,
        default=None,
        help="RT2-D: per-attempt runtime-observation sidecar (trial mode "
        "only). When set, this subprocess RESUMES the attempt's "
        "observation (training components preserved) and records the "
        "inference component: workload, steady-state batch verification, "
        "output-write cost, and the phase actual.",
    )
    parser.add_argument(
        "--runtime_policy_json",
        type=str,
        default=None,
        help="RT2-D: RuntimeControlPolicy JSON. Only meaningful together "
        "with --runtime_observation_out.",
    )
    return parser


def process_batch(
    index,
    inputarr,
    targetarr,
    model,
    args,
    current_loss_type,
    current_loss_name=None,
    *,
    trace=None,
    batch_index=None,
):
    """
    Refactored batch processor to ensure dimension alignment across all models.
    Minimal change: ensures input is always [Batch, Time] before entering the model.

    I15 — ``current_loss_name`` (optional) plumbs the custom-loss declaration
    through so output decoding (regression vs argmax) reads the model's
    output-type contract via ``get_output_type`` plus the loss's declared
    target dtype, rather than the hardcoded ``loss_type == "smooth_l1"``
    check that broke for classifier-style custom losses.

    ``trace`` / ``batch_index`` (V20 PR C2, validation only) — when a
    milestone trace is active, three points of this batch's GPU lifecycle
    are recorded: input on device, the synchronized post-forward state with
    ``output`` still resident, and the state after the transfer to host.
    Both default to ``None`` and production passes neither, so the body is
    byte-for-byte the same sequence of operations it was before.
    """
    # 1. Base Pre-processing (ADC Offset)
    inputarr = inputarr.astype(np.int16) + 128
    targetarr = targetarr.astype(np.int16) + 128
    input_seq = torch.from_numpy(inputarr)  # Shape: [1, 1, Time] from main loop

    # 2. KEY FIX: Standardize Dimensions
    # Both PUNet (Embedding) and FCNet (Linear) expect [Batch, Time].
    # We remove the redundant channel dimension [1, 1, Time] -> [1, Time].
    if input_seq.dim() == 3:
        input_seq = input_seq.squeeze(1)

    # 3. Model-Specific Execution & Type Casting
    # Resolved from the model's declared dtype ADMISSIBILITY intersected with
    # what the runtime supports (Step 03 §4a.1) — this used to branch on
    # `args.denoising_model == "fcnet"`. The site preference is int64, which
    # is what inference has always fed the embedding arm (baseline A6) and
    # which differs from training's int32 (finding F-1).
    input_seq = input_seq.to(
        resolve_input_dtype(
            args.denoising_model,
            getattr(args, "_model_io", None),
            site_preference=INFERENCE_SITE_DTYPE,
        )
    ).to(DEVICE)

    if trace is not None:
        trace.record(
            "after_input_to_device",
            batch_index=batch_index,
            synchronize=True,
            model=model,
            model_input=input_seq,
        )

    with torch.no_grad():
        output = model(input_seq)

        # V20 PR C2, validation only. THE load-bearing milestone: the
        # forward has completed and synchronized, ``output`` is still bound
        # and still on the GPU, and nothing has been transferred, argmaxed
        # or released yet. Taken after ``.cpu()`` it would describe a
        # different state while looking identical, which is exactly the
        # comparison error this trace exists to rule out. It allocates
        # nothing and extends no lifetime — ``output`` is live here anyway,
        # because the decode below reads it.
        if trace is not None:
            trace.record(
                "after_forward_output_resident",
                batch_index=batch_index,
                synchronize=True,
                model=model,
                model_input=input_seq,
                output=output,
            )

        # 4. Decoding Output based on Task Type
        # I15 — output decoding is driven by the MODEL's output contract,
        # not the loss type. Built-in classifier models always emit
        # [B, 256, T]; built-in regressor models emit [B, T]; ``fcnet``
        # is "hybrid" — it adjusts its own forward shape based on
        # ``loss_type`` at construction time, so hybrid + float-target
        # loss is treated as regression.
        try:
            output_type = get_output_type(args.denoising_model)
        except UnknownOutputContractError as e:
            # V21 PR C1 — typed EXECUTION refusal in this module's idiom
            # (an `error_<category>:` prefix tags the failure class; see the
            # checkpoint-sentinel check above). `error_inference` is used
            # deliberately rather than a new category, because an
            # unrecognised status would not be handled downstream.
            #
            # Unreachable by construction today: `--denoising_model` is the
            # live `model_type` passed by `sandbox_executor.execute_inference`
            # AFTER `_validate_configs` has already resolved the contract for
            # that same model. Kept as defence in depth, because "currently
            # unreachable" is exactly what was believed about the registry
            # divergence that cost V20 two PRs.
            raise RuntimeError(f"error_inference: output contract unavailable — {e!s}") from e
        target_dtype = get_target_torch_dtype(
            LossConfig(loss_type=current_loss_type, loss_name=current_loss_name)
        )
        is_regression = output_type == "regressor" or (
            output_type == "hybrid" and target_dtype == torch.float32
        )
        if is_regression:
            # Regression task: Output is already [Batch, Time]
            output_seq = output.detach().cpu().numpy()
        else:
            # Classification task: Output is [Batch, 256, Time]
            # Convert logits to discrete ADC values via Argmax
            output_seq = output.argmax(dim=1).detach().cpu().numpy()

        if trace is not None:
            trace.record(
                "after_output_to_cpu",
                batch_index=batch_index,
                synchronize=True,
                model=model,
                model_input=input_seq,
                output=output,
            )

    # Return flattened results for H5 assembly, back in the PERSISTED
    # representation. Step 05c: the offset comes from the DeliverableSpec, not
    # from a literal. That the same `128` appears on the input-decode side at
    # :217-218 is a coincidence of one task made safe — the spec DERIVES its
    # offset from `DatasetProfile.encoding`, so the two now agree by
    # derivation rather than by two literals that happen to match. The input
    # side above is deliberately NOT migrated: it is an Input Dataset Contract
    # fact (§2.2).
    value_offset = _persisted_storage(args).value_offset
    return index, (output_seq - value_offset).flatten(), (targetarr - value_offset).flatten()


class _ChildTidmadFacts(NamedTuple):
    """The TIDMAD-physical facts this child decodes, or their declared absence.

    Step 12 / PR-12d D4b. Every field is ``None`` for a task that declares no
    TIDMAD topology, and every consumer of them sits on a TIDMAD-only code
    path — the SampleSet loop, the HDF5 channel reads, the PSD slicing and the
    legacy single-file modes. The generic route added at D3 touches none of
    them, so a contrast run simply never reads a ``None``.

    Extracted rather than inlined because ``main`` is HARD-CAPPED at its D0
    branch count (§E H1): four conditional expressions here would have spent
    the entire remaining budget on a declared absence.
    """

    dataset: Any = None
    channels: Any = None
    psd_segment_length: Any = None

    def storage_dtype(self, deliverable_spec: Any) -> Any:
        """The persisted storage dtype, or ``None`` when the task declares none."""
        return None if deliverable_spec is None else deliverable_spec.storage.storage_dtype


def _child_tidmad_facts(dataset_profile) -> _ChildTidmadFacts:
    """Decode TIDMAD's physical facts, or declare their absence BY NAME."""
    if not declares_tidmad_topology(dataset_profile):
        return _ChildTidmadFacts()
    topology = tidmad_topology(dataset_profile)
    return _ChildTidmadFacts(
        dataset=topology.dataset,
        channels=topology.channels,
        psd_segment_length=topology.dataset.psd_segment_length,
    )


def _emit_generic_inference(args, data_path, model, task_eval_scope) -> None:
    """Run the generic route and write the child's result JSON.

    Kept OUT of ``main`` for the reason §E H1 states: ``main`` is this PR's
    god function and may gain a call, not a branch family. The iteration
    itself lives one module further out again, in ``generic_inference``, so
    it is testable without this child's argv surface at all.
    """
    from execute_tools.generic_inference import run_generic_inference
    from execute_tools.task_data_path import DeliverableWriteRequest

    outcome = run_generic_inference(
        data_path=data_path,
        task_scope=task_eval_scope,
        model=model,
        device=DEVICE,
        data_dir=args.data_dir,
        batch_size=args.inference_batch_size,
        write_request=DeliverableWriteRequest(
            output_dir=args.output_dir if args.output_dir else args.data_dir,
            exp_id=args.exp_id,
            run_name=args.run_name,
            model_type=args.denoising_model,
        ),
    )
    print(
        f"[generic_inference] {outcome.samples} sample(s) in {outcome.batches} batch(es) "
        f"-> {outcome.deliverable_name} ({outcome.inference_seconds:.2f}s)"
    )
    if args.timing_out_json:
        with open(args.timing_out_json, "w") as fh:
            # This sidecar's existing parent-facing contract is a list of
            # task-specific per-file timing rows. Generic inference has no
            # framework-owned notion of a file or PSD segment, so it has no
            # honest row to emit. An empty list preserves the sidecar schema
            # and routes record construction through the existing
            # absent-measurement fallback.
            json.dump([], fh)


def _declared_deliverable_naming(manifest_path: str | None) -> DeliverableNaming | None:
    """The run's DECLARED indexed naming, composed from its manifest. F-COV-8.

    The inference child's half of what the scoring child has done since
    Step 11 C6 (``denoising_score_single.py:509``): the SAME authority, the
    SAME transported manifest, the SAME PRESENCE discrimination. ``None``
    means *this run declares no indexed naming* — an un-composed run, or a
    composed one whose task names its artifacts outright — and the caller
    binds nothing, so the honest ``NotApplicable`` refusal stays reachable.

    **Why this child had nothing to bind.** ``--task_manifest`` has reached
    all three children since Step 11 (``core/sandbox_executor.py:1444, 1831,
    2181``); this one simply never used it for naming. So a composed task
    that resolves its filename through the framework's own naming capability
    reached ``resolve_deliverable_naming()`` with the ContextVar unset and
    died with ``DeliverableNamingNotApplicableError`` — *while its manifest
    declared the very section the message says is missing*. No shipped pack
    consumes the capability (TIDMAD, Pets and DAVIS all hand-roll their
    names), which is why every Gate passed over it.

    This is the ``F-12d-28`` shape one capability over: an asymmetry between
    two sibling children, not a missing transport.

    Extracted rather than inlined because ``main`` is branch-capped
    (``tests/unit/guardrails/test_step12_pr12d_d0_baselines.py``:
    ``HARD_CAPPED_BRANCHES``), so a new route is paid for by extraction — the
    precedent ``_emit_generic_inference`` and ``_resume_runtime_session`` set.

    Args:
        manifest_path: the transported ``--task_manifest``, or ``None``.

    Returns:
        The declared :class:`DeliverableNaming`, or ``None``.

    Raises:
        TaskCompositionError: the manifest was transported but its
            ``deliverable:`` section could not be composed. Deliberately NOT
            caught: a composed run must never fall back to TIDMAD's shipped
            template, which is the C-P56-1 failure class one layer down.
    """
    if manifest_path is None:
        return None
    # Imported here, not at module scope, for the reason the sibling import
    # at the `resolve_child_task_data_path` site states: the composition
    # layer sits ABOVE this one, and only a composed run ever reaches it.
    from workflows.task_composition import compose_deliverable_naming_from_manifest

    return compose_deliverable_naming_from_manifest(manifest_path)


def _derive_spec_under_declared_naming(
    dataset_profile: DatasetProfile, declared: DeliverableNaming | None
) -> DeliverableSpec | None:
    """``derive_run_deliverable_spec`` with the run's DECLARED naming in force.

    F-COV-8. The derivation reads the naming ContextVar rather than taking it
    as an argument (``deliverable_spec.py:604`` —
    ``active_deliverable_naming() or DeliverableNaming()``), so *when* it runs
    decides *which* template the spec carries. Deriving it unbound handed a
    composed run the shipped TIDMAD template silently, which is the half of
    this defect that never raised.

    Extracted so ``main`` gains a CALL rather than a ``with`` — the §E.1 H1
    rule the branch cap enforces.
    """
    with declared_naming_binding(declared):
        return derive_run_deliverable_spec(dataset_profile)


def _resume_runtime_session(args, sample_set):
    """RT2-D: resume the attempt's observation sidecar, or return ``None``.

    EXTRACTED by Step 12 / PR-12d seam C. Behaviour is unchanged — same
    condition, same policy load, same ``resumed_status`` — but ``main`` is
    HARD-CAPPED at its pre-12d branch count (§E H1: the god function of this
    PR), so the generic-inference route below had to be paid for rather than
    simply added. This is the payment: four branch nodes leave ``main`` for a
    question that was always its own.
    """
    if not (args.runtime_observation_out and sample_set is not None):
        return None
    policy = None
    if args.runtime_policy_json:
        with open(args.runtime_policy_json) as f:
            policy = RuntimeControlPolicy(**json.load(f))
    return RuntimeVerificationSession.resume_or_start(
        args.runtime_observation_out,
        policy=policy,
        attempt_id=args.exp_id,
        resumed_status="inference_started",
    )


def main():
    # 1. Parse arguments locally to avoid NameError scope issues
    parser = get_parser()
    args = parser.parse_args()
    # Model-I/O contract — child side of the parent's transport, same two-case
    # rule as the training engine: supplied-but-broken fails closed, absent
    # keeps Regime A. Carried on `args` because `process_batch` already takes
    # `args` and adding a parameter would ripple through every call site.
    args._model_io = (
        load_model_io_contract(args.model_io_json) if args.model_io_json is not None else None
    )
    t_process_start = time.perf_counter()

    # Dataset Profile: supplied-but-broken fails closed; absent keeps the
    # Regime-A adapter (§5c). Same contract as the training engine.
    if args.dataset_profile_json is not None:
        dataset_profile = load_dataset_profile(args.dataset_profile_json)
    else:
        dataset_profile = resolve_dataset_profile()
    # Step 12 / PR-12d D4b — the child's TIDMAD facts, resolved through ONE
    # helper that answers a DECLARED ABSENCE instead of raising. These three
    # were decoded unconditionally here, so a Q-12-4-honest profile killed
    # this child ~300 lines before D3's generic route could run. Same B11
    # defect D2 closed in the tuner, left open in the children.
    _tidmad = _child_tidmad_facts(dataset_profile)
    profile_dataset = _tidmad.dataset
    profile_channels = _tidmad.channels
    psd_segment_length = _tidmad.psd_segment_length

    # Step 05c — the child's side of the Deliverable Contract. The spec is NOT
    # transported: it is RECONSTRUCTED here from the profile that already
    # crossed via `--dataset_profile_json`, through the same derivation the
    # parent calls (§3.2a, Option A). One function, two callers, no duplicated
    # literal and no third IPC mechanism. Note this consumes `dataset_profile`
    # as resolved above — it adds no second `resolve_dataset_profile()` call.
    #
    # F-COV-8 — composed ONCE here and bound around every naming consumer
    # below. `derive_run_deliverable_spec` reads the naming ContextVar
    # (`deliverable_spec.py:604`, `active_deliverable_naming() or
    # DeliverableNaming()`), so an unbound derivation silently resolved the
    # SHIPPED template for a run that declared its own.
    _declared_naming = _declared_deliverable_naming(args.task_manifest)
    deliverable_spec = _derive_spec_under_declared_naming(dataset_profile, _declared_naming)
    # Carried on `args` exactly as `_model_io` is, so `process_batch` can read
    # the persisted-output offset without a new parameter on every call site.
    args._deliverable_spec = deliverable_spec
    # The persisted storage dtype, bound once. Every output buffer allocation
    # and every writer-boundary cast in this module reads THIS name — not
    # `np.int8` — so the deliverable's storage representation has exactly one
    # source. The INPUT-side dtype work at :82-101 and :216-218 is a different
    # contract and is deliberately untouched (§2.2).
    _storage_dtype = _tidmad.storage_dtype(deliverable_spec)

    # D14-1 C4 — the run-bound TaskDataPath, resolved once (child side of the
    # transport: SUPPLIED+unknown fails closed; ABSENT is regime-A). The
    # production deliverable WRITE goes through it; naming for logging and the
    # reuse probe stays on the deliverable authority above, which the
    # implementation delegates to — one authority, same bytes.
    # C3: imported here, not at module scope — the composition layer sits
    # ABOVE this one, and only a composed run ever reaches it.
    from workflows.task_composition import resolve_child_task_data_path

    if args.task_data_path_id is None:
        raise TaskDataPathResolutionError(
            "Inference requires --task_data_path_id from an explicit task composition."
        )
    data_path = resolve_child_task_data_path(
        args.task_data_path_id,
        identity=args.task_data_path_identity,
        manifest_path=args.task_manifest,
    )

    # V20 PR C2, validation only. ``None`` — and therefore completely
    # inert — unless SIDERIUS_C2_INFERENCE_MILESTONE_TRACE names a channel,
    # which production never does. There is no CLI flag and no config key:
    # the absence of the tracer IS the disabled state.
    #
    # ``process_start`` and ``after_imports`` are both taken here, and that
    # is a real limitation rather than an oversight: this module imports
    # torch at module scope, so by the time any statement in ``main`` can
    # run, the import block has already executed. Recording them at module
    # scope would require a statement above the imports (E402) and a
    # first-party import ordered above the third-party ones (I001), and
    # this repository does not disable lint rules to make code fit. Both
    # sides therefore agree on what these two milestones MEAN — process
    # entry, torch available, CUDA not yet initialized — which is what the
    # comparison needs. The already-completed direct measurement puts both
    # at 0 MiB on both sides, so nothing load-bearing rests here.
    trace = tracer_from_environment(side="formal_inference")
    if trace is not None:
        trace.set_candidate(
            {"model_type": args.denoising_model, "mode": args.mode, "exp_id": args.exp_id},
            inference_batch_size=args.inference_batch_size,
        )
        trace.record(
            "process_start",
            detail="entry to main(); torch was imported at module scope",
        )
        trace.record("after_imports")
        # torch resolves DEVICE at module scope but creates no context: the
        # CUDA context is allocated lazily at the first device operation,
        # which on this path is the model transfer below. The record's
        # ``cuda_initialized`` field states which it is rather than the
        # milestone name implying it.
        trace.record("after_cuda_init", detail=f"DEVICE={DEVICE}")

    from execute_tools.data_paths import resolve_dataset_dir

    args.data_dir = resolve_dataset_dir(args.data_dir, purpose="inference child")

    # 2. Model Loading Logic
    if args.mode == "fix":
        # Baseline / Fixed mode logic remains largely the same
        model_map = {
            "punet": "PUNet_0_20.pth",
            "fcnet": "FCNet_0_20.pth",
            "transformer": "Transformer_0_20.pth",
        }
        model_file = model_map.get(args.denoising_model)
        if not model_file or not os.path.exists(model_file):
            raise FileNotFoundError(f"Baseline model file {model_file} not found.")

        model = torch.load(model_file, map_location=DEVICE, weights_only=False)
        input_size = 40000  # Default baseline size
        current_loss_type = "ce"
        current_loss_name: str | None = None

    else:
        # AGENT MODE: Dynamic loading using Registry and Factory
        if not args.model_cfg or not args.model_path:
            raise ValueError("Agent mode requires --model_cfg and --model_path")

        # Load Loss Type from Config
        loss_path = args.loss_cfg if args.loss_cfg else args.model_cfg.replace("model", "loss")
        with open(loss_path) as f:
            l_data = json.load(f)
        current_loss_type = l_data.get("loss_type", "ce")
        # I15 — read loss_name so output decoding can dispatch through
        # get_target_torch_dtype for classifier-style custom losses (the
        # registered PLUGIN_LOSS_TARGET_DTYPE drives the decision).
        current_loss_name = l_data.get("loss_name")

        # Load Model Config
        with open(args.model_cfg) as f:
            m_data = json.load(f)

        # --- MINIMAL CHANGE: Dynamic Initialization ---
        config_class = get_config_class(args.denoising_model)
        model_class = MODEL_REGISTRY.get(args.denoising_model)

        if config_class is None or model_class is None:
            raise ValueError(
                f"Model type '{args.denoising_model}' is not supported in MODEL_REGISTRY"
            )

        # Instantiate Pydantic config and then the Model
        # Step 03 M6 — same derivation as the training engine.
        m_cfg = config_class(**apply_contract_cardinality(m_data, args._model_io))

        # Special handling for AE (loss_type injection), others use standard config init
        #
        # Construction and transfer are two statements rather than one
        # chained expression so a milestone can sit between them (V20 PR
        # C2, validation only). This is not a behaviour change:
        # ``nn.Module.to()`` moves parameters in place and returns ``self``,
        # so both forms perform the identical sequence of operations on the
        # identical object — the split only binds a name in between.
        if args.denoising_model == "fcnet":
            model = model_class(m_cfg, loss_type=current_loss_type)
        else:
            model = model_class(m_cfg)

        if trace is not None:
            trace.record(
                "after_model_construction",
                model=model,
                detail="constructed on host; not yet transferred to the device",
            )

        model = model.to(DEVICE)

        if trace is not None:
            trace.record("after_model_to_device", synchronize=True, model=model)

        # Phase 6.7 Fix 3 — preflight the trainer sentinel. No retry loop:
        # the spec explicitly drops it because it would mask, not fix, the
        # silent-crash root cause.
        _assert_training_sentinel(args.model_path, args.exp_id)

        # Load weights from the agent's specific experiment run.
        #
        # HOST-SIDE, deliberately. `map_location=DEVICE` materialises a
        # SECOND full set of parameter tensors on the GPU before
        # `load_state_dict` copies them into the model. The temporary state
        # dict is then freed — but the CUDA caching allocator keeps the
        # freed segments RESERVED, and driver-visible memory counts
        # reserved, not allocated. So the process carries a checkpoint's
        # worth of dead pool for the rest of its life.
        #
        # Measured on a V20 PR C2 lifecycle trace (punet, 216.9 MiB
        # checkpoint), immediately after this line:
        #
        #     allocator reserved   236 -> 464 MiB   (+228)
        #     allocator allocated  218 -> 218 MiB   (unchanged)
        #
        # and the +228 MiB persisted through the forward, leaving formal
        # inference 208 MiB above an otherwise byte-identical process that
        # loads no checkpoint. Loading on the host and letting
        # `load_state_dict` copy parameter-by-parameter into the already
        # resident GPU model never allocates the second copy at all.
        #
        # `map_location="cpu"` is also the convention this repository
        # already uses everywhere else it reads a state dict
        # (`tests/integration/execute_tools/test_training_loop.py`).
        # Strictness is untouched: `weights_only` keeps its default and
        # `load_state_dict` keeps `strict=True`, so a mismatched or
        # malicious checkpoint fails exactly as it did before.
        state_dict = torch.load(args.model_path, map_location="cpu")
        model.load_state_dict(state_dict)
        del state_dict

        # The one step the pre-phase worker has no equivalent for — it
        # builds from the live MODEL_REGISTRY and loads no checkpoint —
        # which is why the milestone comparison isolated it (V20 PR C2,
        # validation only).
        #
        # Recorded AFTER the host copy is released, so it captures the
        # settled post-load state rather than a transient. Its job is now
        # the opposite of what found the defect: with the host-side load
        # above, allocator reserved must stay at the model-only baseline
        # here instead of rising by a checkpoint. A future regression that
        # put the load back on the device would show up at exactly this
        # milestone.
        if trace is not None:
            trace.record("after_checkpoint_load", synchronize=True, model=model)

        input_size = m_cfg.segmentation_size

    model.eval()

    # RT2-D (§2.6): everything up to here — config load, model
    # construction, weight load, device transfer — is the INFERENCE
    # setup, accounted inside the inference component (the attempt's
    # "setup" component belongs to the training subprocess).
    inference_setup_seconds = time.perf_counter() - t_process_start

    # 3. Load sample set if provided (trial mode)
    sample_set = None
    if args.sample_set_json:
        with open(args.sample_set_json) as f:
            sample_set = json.load(f)

    # Step 12 / PR-12d seam C (B6/B7) — the GENERIC route. A composed task
    # that declares its own scope iterates ITS OWN evaluation dataset and
    # writes ITS OWN deliverable, through two of the four FROZEN TaskDataPath
    # methods. `main` gains a CALL and one route selection, never a branch
    # family (§E H1): everything the route does lives in
    # `execute_tools/generic_inference.py`, independently testable.
    #
    # The scope arrives through the SAME artifact+digest ABI the training
    # child uses, read by the SAME `load_transported_scope` — verify BEFORE
    # deserialize, one implementation, no child-side copy.
    # F-12d-28 — deserialize INSIDE the binding, exactly as the training child
    # does (`train_engine_sandbox.py:2138`).
    #
    # This child already RESOLVED its task data path above, but never BOUND
    # it. `load_transported_scope` delegates to whichever implementation is
    # ACTIVE, so with no binding it reached the legacy registered one, which
    # refused the composed payload BY NAME — the scope object declaring one
    # task's kind while the active binding belonged to another.
    #
    # (The refusal text is deliberately paraphrased rather than quoted: the
    # §F item-9 census forbids naming a scope KIND anywhere in generic core,
    # and a verbatim error quote in a comment trips it just as a dispatch
    # would. The guard cannot tell prose from a branch, and should not have to.)
    #
    # That message is PR-12bc's pairing-gap guard firing correctly, one child
    # over: the scope crossed while the binding did not. Resolving is not
    # binding — the bytes must be decoded by the implementation that wrote
    # them, which is a run-scoped fact, not a local variable.
    #
    # An un-composed run has `task_data_path_id is None`, takes the
    # `nullcontext`, and behaves exactly as before.
    _binding_cm = (
        bind_task_data_path(data_path)
        if args.task_data_path_id is not None
        else contextlib.nullcontext()
    )
    # F-COV-8 — the generic route is where an unbound naming STOPPED the run
    # rather than merely mis-naming it: the task's own `write_deliverable` and
    # `task_declared_deliverable_name` (`generic_inference.py:133, 138`) call
    # `resolve_deliverable_naming()`, which REFUSES when the task names its
    # own artifacts and nothing is bound.
    with declared_naming_binding(_declared_naming), _binding_cm:
        task_eval_scope = load_transported_scope(
            args.task_eval_scope_ref, args.task_eval_scope_digest, leg="evaluation"
        )
        if task_eval_scope is not None:
            _emit_generic_inference(args, data_path, model, task_eval_scope)
            return

    # RT2-D: resume the attempt's observation (trial mode only).
    runtime_session = _resume_runtime_session(args, sample_set)
    verifier = None

    # Decomposition geometry comes from the resolved Dataset Profile.

    if sample_set is not None:
        # --- TRIAL MODE: denoise specific segments from multiple files ---
        out_dir = args.output_dir if args.output_dir else args.data_dir
        per_file_timings_ms: list[dict] = []
        use_cuda_sync = torch.cuda.is_available()
        write_seconds_per_psd: list[float] = []
        # Pre-Gate finding F1: input loading and the per-file fixed
        # residual (allocs, gc, sidecar writes) must be PRICED, not
        # hidden — at small scales they dominate the prediction error.
        read_seconds_per_psd: list[float] = []
        residual_seconds_per_file: list[float] = []
        total_psd_planned = sum(len(v) for v in sample_set.values())
        total_files_planned = len(sample_set)
        verification_completed = False
        # V20 PR C2, validation only: a GLOBAL batch ordinal, so the trace
        # bound counts forward passes rather than restarting at each file
        # and re-tracing the first batch of every one of them.
        traced_batch_ordinal = 0
        if runtime_session is not None:
            runtime_session.record_phase_workload(
                "inference",
                resolve_inference_workload(
                    sample_set,
                    seg_size=input_size,
                    inference_batch_size=args.inference_batch_size,
                    # Step 05b: the profile this subprocess already loaded at
                    # its argv boundary, not an ambient re-resolution. The
                    # clearest instance of the defect — the value was in
                    # scope and simply was not passed.
                    profile=dataset_profile,
                ),
            )
            verifier = runtime_session.start_phase_verification("inference", unit="inference_batch")

        def _complete_inference_verification() -> None:
            """Assemble the inference prediction once evidence suffices.

            §2.6 prediction = resolved batches × steady batch time
            + inference setup + input-read term + output-write term
            + per-file fixed residual. Read/write are extrapolated per
            PSD segment and the residual per file from measured file
            passes, so I/O and fixed costs are priced separately from
            compute, never hidden inside it (pre-Gate finding F1).
            """
            nonlocal verification_completed
            assert runtime_session is not None and verifier is not None

            def _mean(values: list[float]) -> float:
                return sum(values) / len(values) if values else 0.0

            write_per_psd = _mean(write_seconds_per_psd)
            read_per_psd = _mean(read_seconds_per_psd)
            residual_per_file = _mean(residual_seconds_per_file)
            runtime_session.complete_phase_verification(
                "inference",
                verifier,
                source="real_inference_verification",
                extra_predicted_seconds=(
                    inference_setup_seconds
                    + (read_per_psd + write_per_psd) * total_psd_planned
                    + residual_per_file * total_files_planned
                ),
                extra_detail={
                    "inference_setup_seconds": inference_setup_seconds,
                    "input_read_seconds_per_psd": read_per_psd,
                    "output_write_seconds_per_psd": write_per_psd,
                    "per_file_residual_seconds": residual_per_file,
                    "io_files_measured": len(write_seconds_per_psd),
                    "total_psd_planned": total_psd_planned,
                    "total_files_planned": total_files_planned,
                },
            )
            verification_completed = True

        for file_index_str, psd_segment_indices in sorted(sample_set.items()):
            file_index = int(file_index_str)
            out_name = os.path.join(
                out_dir,
                deliverable_spec.naming.name(
                    model_type=args.denoising_model,
                    run_name=args.run_name,
                    exp_id=args.exp_id,
                    input_identity=file_index,
                ),
            )
            expected_samples = len(psd_segment_indices) * psd_segment_length
            if args.reuse_complete_outputs and _is_complete_trial_output(
                out_name, expected_samples, deliverable_spec.storage
            ):
                print(
                    f"Reusing verified trial inference output: {out_name} "
                    f"({expected_samples} {_storage_dtype} samples/channel)"
                )
                per_file_timings_ms.append(
                    {
                        "file_index": file_index,
                        "n_psd_segs": len(psd_segment_indices),
                        "elapsed_ms": 0.0,
                        "reused": True,
                    }
                )
                continue

            # RAW validation input — Step-02 topology, from the declaration.
            fname = profile_dataset.validation_file_name(file_index)
            fpath = os.path.join(args.data_dir, fname)

            if not os.path.exists(fpath):
                print(f"Warning: {fpath} not found, skipping.")
                continue

            t_file_start = time.perf_counter()

            # Lazy indexed reads: keep the timeseries as h5py.Dataset handles
            # and slice only the PSD segments the sample_set requests. Eliminates
            # the ~1.6 GB-per-channel full-file materialization that dominated
            # both wall-time and RSS in trial mode (where eval_portion is small,
            # often only 1-2 PSD segments per file). Slices must be taken
            # inside the file-handle context — once the `with` block exits,
            # ds_ch1/ds_ch2 are invalid. The slice itself returns a numpy
            # array that survives the context exit, which is what we
            # concatenate below.
            with h5py.File(fpath, "r") as ABRAfile:
                ds_ch1 = _h5_dataset(
                    ABRAfile, "timeseries", profile_channels.input_channel, "timeseries"
                )
                ds_ch2 = _h5_dataset(
                    ABRAfile, "timeseries", profile_channels.target_channel, "timeseries"
                )

                total_psd_segments = ds_ch1.shape[0] // psd_segment_length

                input_chunks = []
                target_chunks = []
                for psd_idx in psd_segment_indices:
                    start = psd_idx * psd_segment_length
                    end = start + psd_segment_length
                    input_chunks.append(ds_ch1[start:end])
                    target_chunks.append(ds_ch2[start:end])

                print(
                    f"[perf] Lazy loading applied: read only "
                    f"{len(psd_segment_indices)} segments out of "
                    f"{total_psd_segments} total."
                )

            all_input = np.concatenate(input_chunks)  # flat array
            all_target = np.concatenate(target_chunks)  # flat array

            train_loader = all_input.reshape(-1, 1, input_size)
            target_loader = all_target.reshape(-1, 1, input_size)

            dim1 = train_loader.shape[0]
            denoised = np.zeros((dim1, input_size), dtype=_storage_dtype)
            injected = np.zeros((dim1, input_size), dtype=_storage_dtype)
            bs = args.inference_batch_size
            # F1: input-read window = file open → loop start (h5 slice,
            # concat, reshape, buffer alloc), priced per PSD segment.
            t_loop_start = time.perf_counter()
            file_read_seconds = t_loop_start - t_file_start

            for i in tqdm(
                range(0, dim1, bs),
                desc=f"Inference file {file_index} ({len(psd_segment_indices)} PSD segs)",
            ):
                timing_this_batch = verifier is not None and not verifier.is_terminal
                if timing_this_batch:
                    if use_cuda_sync:
                        torch.cuda.synchronize()
                    t_batch = time.perf_counter()
                batch_in = train_loader[i : i + bs]
                batch_tgt = target_loader[i : i + bs]
                _, dn, ij = process_batch(
                    i,
                    batch_in,
                    batch_tgt,
                    model,
                    args,
                    current_loss_type,
                    current_loss_name,
                    trace=trace,
                    batch_index=traced_batch_ordinal,
                )
                # Recorded HERE and not inside ``process_batch``: the point
                # of interest is after that call's locals — ``output``,
                # ``input_seq`` — have gone out of scope. Adding a ``del``
                # inside it would release them earlier than production does,
                # which is a change to cleanup semantics, not an observation
                # of them.
                if trace is not None:
                    trace.record("after_output_cleanup", batch_index=traced_batch_ordinal)
                traced_batch_ordinal += 1
                actual_n = batch_in.shape[0]
                denoised[i : i + actual_n] = dn.reshape(actual_n, input_size)
                injected[i : i + actual_n] = ij.reshape(actual_n, input_size)
                if timing_this_batch:
                    if use_cuda_sync:
                        torch.cuda.synchronize()
                    assert verifier is not None
                    verifier.feed(max((time.perf_counter() - t_batch) * 1000.0, 1e-6))
                    if verifier.is_terminal and write_seconds_per_psd:
                        # Terminal AND at least one measured file write →
                        # the §2.6 component split is complete. (Terminal
                        # WITHOUT a write yet: stop timing, hold completion
                        # until the first write cost is measured below.)
                        _complete_inference_verification()
                        verifier = None

            file_loop_seconds = time.perf_counter() - t_loop_start

            # Phase 6.7 Fix 2 (updated 2026-05-03) — release the
            # view-aliasing buffers BEFORE the deliverable write. The original
            # fix also dropped raw_ch1/raw_ch2 (~1.6 GB each from full-file
            # materialization), but the lazy-slice refactor above eliminates
            # those entirely; only the per-segment chunks remain. We still
            # drop train_loader/target_loader (views over all_input/
            # all_target) and the chunk lists, since the writer's
            # flatten/astype copies still inflate call peak otherwise.
            del train_loader, target_loader, all_input, all_target, input_chunks, target_chunks
            gc.collect()

            # D14-1 C4: seam call. The implementation resolves the SAME name
            # through the deliverable authority (out_name above is
            # logging/reuse addressing only), removes a stale file first, and
            # performs the identical flatten/storage-cast ABRA write — byte
            # parity pinned by the manifest-backed delegation suite. The
            # profile binding scopes the implementation's spec derivation to
            # the profile THIS child transported.
            t_write = time.perf_counter()
            # F-COV-8: the implementation re-derives its spec inside the call
            # (`tidmad_data_path.py:537`), so it reads the naming ContextVar
            # LIVE — binding it only around `derive_run_deliverable_spec`
            # above would leave the actual WRITE on the shipped template while
            # `out_name` said otherwise.
            with bind_dataset_profile(dataset_profile), declared_naming_binding(_declared_naming):
                data_path.write_deliverable(
                    [(file_index, denoised, injected)],
                    DeliverableWriteRequest(
                        output_dir=out_dir,
                        exp_id=args.exp_id,
                        run_name=args.run_name,
                        model_type=args.denoising_model,
                    ),
                )
            file_write_seconds = time.perf_counter() - t_write
            n_psd_this_file = max(len(psd_segment_indices), 1)
            write_seconds_per_psd.append(file_write_seconds / n_psd_this_file)
            read_seconds_per_psd.append(file_read_seconds / n_psd_this_file)
            print(f"Trial inference saved: {out_name}")

            del denoised, injected
            gc.collect()

            elapsed_ms = (time.perf_counter() - t_file_start) * 1000.0
            # F1: the per-file fixed residual — everything the read /
            # compute-loop / write windows do not cover (allocs, gc,
            # deletes, file bookkeeping) — priced per file.
            residual_seconds_per_file.append(
                max(
                    elapsed_ms / 1000.0
                    - file_read_seconds
                    - file_loop_seconds
                    - file_write_seconds,
                    0.0,
                )
            )
            per_file_timings_ms.append(
                {
                    "file_index": file_index,
                    "n_psd_segs": len(psd_segment_indices),
                    "elapsed_ms": elapsed_ms,
                }
            )

            if (
                runtime_session is not None
                and not verification_completed
                and verifier is not None
                and verifier.is_terminal
            ):
                # Verification went terminal mid-file before any write was
                # measured — complete now that this file's full I/O split
                # (read / write / residual) exists.
                _complete_inference_verification()
                verifier = None

        if args.timing_out_json:
            with open(args.timing_out_json, "w") as f:
                json.dump(per_file_timings_ms, f)

        if runtime_session is not None:
            if not verification_completed and verifier is not None:
                # Files exhausted before a verdict (tiny scopes, reused
                # outputs): resolve from the collected evidence — a failed
                # verification still records its measurement (§6.2).
                _complete_inference_verification()
                verifier = None
            # The inference ACTUAL covers this subprocess's real work:
            # setup + all file loops + output writes (§2.6).
            runtime_session.record_phase_actual("inference", time.perf_counter() - t_process_start)

            # V21 PR B2 — realized peak memory for this phase, read in the
            # inference subprocess so the counters are this candidate's.
            # See the training engine for the same call. Observation only.
            from core.runtime_control.realized_memory import read_process_peak_mib

            _alloc, _reserved, _device = read_process_peak_mib()
            runtime_session.record_phase_peak_memory(
                "inference",
                allocator_peak_mib=_alloc,
                reserved_peak_mib=_reserved,
                completeness="complete"
                if _alloc is not None or _reserved is not None
                else "unavailable",
                device_index=_device,
            )
            runtime_session.finalize("inference_complete")

    else:
        # --- NORMAL MODE: denoise all segments of a single file ---
        # RAW validation input. Note the pre-migration inconsistency this
        # removes: this site built the name with ``zfill(4)`` while every
        # other built it with ``:04d`` — equal only for non-negative ints.
        fname = profile_dataset.validation_file_name(args.file_index)
        fpath = os.path.join(args.data_dir, fname)

        if not os.path.exists(fpath):
            raise FileNotFoundError(f"Validation data missing at {fpath}")

        with h5py.File(fpath, "r") as ABRAfile:
            alltrain = np.array(
                _h5_dataset(ABRAfile, "timeseries", profile_channels.input_channel, "timeseries")
            )
            alltarget = np.array(
                _h5_dataset(ABRAfile, "timeseries", profile_channels.target_channel, "timeseries")
            )

            # Reshape according to input_size from config
            train_loader = alltrain.reshape(-1, 1, input_size)
            target_loader = alltarget.reshape(-1, 1, input_size)

            dim1 = train_loader.shape[0]
            denoised = np.zeros((dim1, input_size), dtype=_storage_dtype)
            injected = np.zeros((dim1, input_size), dtype=_storage_dtype)
            bs = args.inference_batch_size

            for i in tqdm(range(0, dim1, bs), desc=f"Inference ({args.mode})"):
                batch_in = train_loader[i : i + bs]
                batch_tgt = target_loader[i : i + bs]
                _, dn, ij = process_batch(
                    i, batch_in, batch_tgt, model, args, current_loss_type, current_loss_name
                )
                actual_n = batch_in.shape[0]
                denoised[i : i + actual_n] = dn.reshape(actual_n, input_size)
                injected[i : i + actual_n] = ij.reshape(actual_n, input_size)

        # Fix 3 (docs/optimize_inference_and_scoring.md §3) — free the raw
        # int8 buffers before the write phase. create_abra_file below emits
        # transient .flatten().astype(int8) copies of denoised + injected;
        # keeping alltrain/alltarget (~3.7 GB together on a 201-segment
        # validation file) live through that call inflates the call peak
        # unnecessarily. train_loader/target_loader are views over these
        # buffers, so the actual release comes from dropping the owners.
        # Measured effect: single-call peak 9.43 GB → 5.68 GB (−3.75 GB,
        # −40%) on abra_validation_0000.h5.
        del train_loader, target_loader, alltrain, alltarget
        gc.collect()

        # 4. Save Output
        out_dir = args.output_dir if args.output_dir else args.data_dir
        if args.mode == "fix":
            # The legacy fix-mode name predates run/exp scoping and omits both.
            # A different NAME SHAPE, not a different directory — preserved
            # rather than unified, because files carrying it exist on disk.
            out_name = os.path.join(
                out_dir,
                deliverable_spec.naming.unqualified_name(
                    model_type=args.denoising_model,
                    input_identity=args.file_index,
                ),
            )
        else:
            out_name = os.path.join(
                out_dir,
                deliverable_spec.naming.name(
                    model_type=args.denoising_model,
                    run_name=args.run_name,
                    exp_id=args.exp_id,
                    input_identity=args.file_index,
                ),
            )

        if args.mode == "agent":
            # D14-1 C4: run-identified (agent) writes go through the seam —
            # the implementation resolves the SAME authority name as out_name
            # above, removes a stale file, and performs the identical write.
            # F-COV-8: same live ContextVar read as the trial-mode write.
            with bind_dataset_profile(dataset_profile), declared_naming_binding(_declared_naming):
                data_path.write_deliverable(
                    [(args.file_index, denoised, injected)],
                    DeliverableWriteRequest(
                        output_dir=out_dir,
                        exp_id=args.exp_id,
                        run_name=args.run_name,
                        model_type=args.denoising_model,
                    ),
                )
        else:
            # Baseline (fix) deliverables carry no run/exp identity — the seam
            # request requires both — so the legacy unqualified write stays on
            # the deliverable authority directly (recorded C4 exemption).
            if os.path.exists(out_name):
                os.remove(out_name)
            create_abra_file(
                out_name,
                denoised.flatten().astype(_storage_dtype),
                injected.flatten().astype(_storage_dtype),
                indexed=False,
                storage=deliverable_spec.storage,
            )
        print(f"Inference complete. Saved to: {out_name}")

    # V20 PR C2, validation only. The last thing this process records: what
    # the driver still attributes to it once all inference work is done.
    if trace is not None:
        trace.record("before_exit", synchronize=True)


if __name__ == "__main__":
    main()
