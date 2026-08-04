import argparse
import gc
import json
import os
import time
from typing import Any, cast

import h5py
import numpy as np
import torch
from tqdm import tqdm

from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from execute_tools.array2h5 import create_abra_file
from execute_tools.dataset_config import SEGMENT_LENGTH as PSD_SEGMENT_LENGTH
from execute_tools.workload_resolvers import resolve_inference_workload
from ml_models.loss_models_sandbox import get_target_torch_dtype
from ml_models.models_format_sandbox import LossConfig, get_config_class

# Import your sandboxed components for Agent Mode
from ml_models.models_sandbox import MODEL_REGISTRY
from ml_models.plugin_loader import get_output_type

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


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


def _is_complete_trial_output(path: str, expected_samples: int) -> bool:
    """Return whether an attempt-scoped trial HDF5 is safe to reuse.

    A CUDA/host failure can leave earlier files from the same inference
    subprocess fully flushed while later files are absent or incomplete.
    Reuse is deliberately opt-in and requires both ABRA channels to be
    readable int8 vectors of the exact expected length.
    """
    try:
        with h5py.File(path, "r") as handle:
            channel1 = _h5_dataset(handle, "timeseries", "channel0001", "timeseries")
            channel2 = _h5_dataset(handle, "timeseries", "channel0002", "timeseries")
            expected_shape = (expected_samples,)
            if (
                channel1.shape != expected_shape
                or channel2.shape != expected_shape
                or channel1.dtype != np.dtype(np.int8)
                or channel2.dtype != np.dtype(np.int8)
            ):
                return False
            # Force reads at both allocation boundaries. Opening metadata alone
            # is insufficient evidence that the final chunks were flushed.
            if expected_samples:
                channel1[0]
                channel1[-1]
                channel2[0]
                channel2[-1]
        return True
    except (KeyError, OSError, ValueError):
        return False


def get_parser():
    """Defines the argument parser for both Fix and Agent modes."""
    parser = argparse.ArgumentParser(description="Inference with Fixed (Baseline) or Agent mode.")
    parser.add_argument("--mode", type=str, choices=["fix", "agent"], default="fix")
    parser.add_argument("--data_dir", "-d", type=str, default=None)
    parser.add_argument("--denoising_model", "-m", type=str, default="punet")
    parser.add_argument("--file_index", "-i", type=int, default=6)

    # Agent Mode Specific Args
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
            "only after validating both int8 channels and expected length."
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
    index, inputarr, targetarr, model, args, current_loss_type, current_loss_name=None
):
    """
    Refactored batch processor to ensure dimension alignment across all models.
    Minimal change: ensures input is always [Batch, Time] before entering the model.

    I15 — ``current_loss_name`` (optional) plumbs the custom-loss declaration
    through so output decoding (regression vs argmax) reads the model's
    output-type contract via ``get_output_type`` plus the loss's declared
    target dtype, rather than the hardcoded ``loss_type == "smooth_l1"``
    check that broke for classifier-style custom losses.
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
    # The forward contract is [B, T] int64 for all embedding-based models.
    # Only fcnet (AE) uses float input for regression.
    if args.denoising_model == "fcnet":
        input_seq = input_seq.float().to(DEVICE)
    else:
        input_seq = input_seq.long().to(DEVICE)

    with torch.no_grad():
        output = model(input_seq)

        # 4. Decoding Output based on Task Type
        # I15 — output decoding is driven by the MODEL's output contract,
        # not the loss type. Built-in classifier models always emit
        # [B, 256, T]; built-in regressor models emit [B, T]; ``fcnet``
        # is "hybrid" — it adjusts its own forward shape based on
        # ``loss_type`` at construction time, so hybrid + float-target
        # loss is treated as regression.
        output_type = get_output_type(args.denoising_model)
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

    # Return flattened results for H5 assembly
    return index, (output_seq - 128).flatten(), (targetarr - 128).flatten()


def main():
    # 1. Parse arguments locally to avoid NameError scope issues
    parser = get_parser()
    args = parser.parse_args()
    t_process_start = time.perf_counter()

    if args.data_dir is None:
        from execute_tools.data_paths import TIDMAD_DATA_DIR

        args.data_dir = TIDMAD_DATA_DIR

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
        m_cfg = config_class(**m_data)

        # Special handling for AE (loss_type injection), others use standard config init
        if args.denoising_model == "fcnet":
            model = model_class(m_cfg, loss_type=current_loss_type).to(DEVICE)
        else:
            model = model_class(m_cfg).to(DEVICE)

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

    # RT2-D: resume the attempt's observation (trial mode only).
    runtime_session = None
    verifier = None
    if args.runtime_observation_out and sample_set is not None:
        policy = None
        if args.runtime_policy_json:
            with open(args.runtime_policy_json) as f:
                policy = RuntimeControlPolicy(**json.load(f))
        runtime_session = RuntimeVerificationSession.resume_or_start(
            args.runtime_observation_out,
            policy=policy,
            attempt_id=args.exp_id,
            resumed_status="inference_started",
        )

    # PSD_SEGMENT_LENGTH imported from dataset_config

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
        if runtime_session is not None:
            runtime_session.record_phase_workload(
                "inference",
                resolve_inference_workload(
                    sample_set,
                    seg_size=input_size,
                    inference_batch_size=args.inference_batch_size,
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
                f"abra_validation_denoised_{args.denoising_model}_{args.run_name}_{args.exp_id}_{file_index:04d}.h5",
            )
            expected_samples = len(psd_segment_indices) * PSD_SEGMENT_LENGTH
            if args.reuse_complete_outputs and _is_complete_trial_output(
                out_name, expected_samples
            ):
                print(
                    f"Reusing verified trial inference output: {out_name} "
                    f"({expected_samples} int8 samples/channel)"
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

            fname = f"abra_validation_{file_index:04d}.h5"
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
                ds_ch1 = _h5_dataset(ABRAfile, "timeseries", "channel0001", "timeseries")
                ds_ch2 = _h5_dataset(ABRAfile, "timeseries", "channel0002", "timeseries")

                total_psd_segments = ds_ch1.shape[0] // PSD_SEGMENT_LENGTH

                input_chunks = []
                target_chunks = []
                for psd_idx in psd_segment_indices:
                    start = psd_idx * PSD_SEGMENT_LENGTH
                    end = start + PSD_SEGMENT_LENGTH
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
            denoised = np.zeros((dim1, input_size), dtype=np.int8)
            injected = np.zeros((dim1, input_size), dtype=np.int8)
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
                    i, batch_in, batch_tgt, model, args, current_loss_type, current_loss_name
                )
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

            if os.path.exists(out_name):
                os.remove(out_name)

            # Phase 6.7 Fix 2 (updated 2026-05-03) — release the
            # view-aliasing buffers BEFORE create_abra_file. The original fix
            # also dropped raw_ch1/raw_ch2 (~1.6 GB each from full-file
            # materialization), but the lazy-slice refactor above eliminates
            # those entirely; only the per-segment chunks remain. We still
            # drop train_loader/target_loader (views over all_input/
            # all_target) and the chunk lists, since create_abra_file's
            # flatten/astype copies still inflate call peak otherwise.
            del train_loader, target_loader, all_input, all_target, input_chunks, target_chunks
            gc.collect()

            t_write = time.perf_counter()
            create_abra_file(
                out_name,
                denoised.flatten().astype(np.int8),
                injected.flatten().astype(np.int8),
                indexed=False,
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
            runtime_session.finalize("inference_complete")

    else:
        # --- NORMAL MODE: denoise all segments of a single file ---
        fname = f"abra_validation_{str(args.file_index).zfill(4)}.h5"
        fpath = os.path.join(args.data_dir, fname)

        if not os.path.exists(fpath):
            raise FileNotFoundError(f"Validation data missing at {fpath}")

        with h5py.File(fpath, "r") as ABRAfile:
            alltrain = np.array(_h5_dataset(ABRAfile, "timeseries", "channel0001", "timeseries"))
            alltarget = np.array(_h5_dataset(ABRAfile, "timeseries", "channel0002", "timeseries"))

            # Reshape according to input_size from config
            train_loader = alltrain.reshape(-1, 1, input_size)
            target_loader = alltarget.reshape(-1, 1, input_size)

            dim1 = train_loader.shape[0]
            denoised = np.zeros((dim1, input_size), dtype=np.int8)
            injected = np.zeros((dim1, input_size), dtype=np.int8)
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
        idx_str = str(args.file_index).zfill(4)
        out_dir = args.output_dir if args.output_dir else args.data_dir
        if args.mode == "fix":
            out_name = os.path.join(
                out_dir, f"abra_validation_denoised_{args.denoising_model}_{idx_str}.h5"
            )
        else:
            out_name = os.path.join(
                out_dir,
                f"abra_validation_denoised_{args.denoising_model}_{args.run_name}_{args.exp_id}_{idx_str}.h5",
            )

        # Clean up old files before writing new one
        if os.path.exists(out_name):
            os.remove(out_name)

        create_abra_file(
            out_name,
            denoised.flatten().astype(np.int8),
            injected.flatten().astype(np.int8),
            indexed=False,
        )
        print(f"Inference complete. Saved to: {out_name}")


if __name__ == "__main__":
    main()
