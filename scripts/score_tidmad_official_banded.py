#!/usr/bin/env python
"""Score the official band-split TIDMAD checkpoints with SIDERIUS.

The TIDMAD paper trains 4 separate models per architecture, one per
frequency band (``train.py``: ``ifile_checkpoint = [0, 4, 10, 15, 20]``):

- ``{Model}_0_4.pth``   -> validation files 0-3   (low frequency)
- ``{Model}_4_10.pth``  -> validation files 4-9   (medium frequency)
- ``{Model}_10_15.pth`` -> validation files 10-14 (medium-high frequency)
- ``{Model}_15_20.pth`` -> validation files 15-19 (high frequency)

This script mirrors ``score_tidmad_official_wavenet.py`` but applies the
band-matched checkpoint to each validation file, exactly as the paper's
``inference.py`` does. Per architecture it:

1. imports the legacy ``network.py`` classes from a read-only TIDMAD clone,
2. loads each band checkpoint by direct unpickling (full-module pickle,
   exactly like the paper's ``inference.py``) and runs inference over that
   band's validation files,
3. writes temporary ABRA-format HDF5 outputs,
4. scores all 20 files in one ``score_vector`` call with the canonical
   committed anchor map (global ``s_max`` ruler),
5. saves a summary JSON and deletes the temporary HDF5 files.

Inference parity with the paper's ``inference.py``:

- ``input_size = 40000`` for every model at inference time (the transformer's
  20,000-sample segments are a train-time-only memory reduction; legacy
  ``inference.py`` line 69 uses 40,000 unconditionally and ``network.py``'s
  ``SEQ_LEN = 40000`` positional-encoding buffer covers it),
- signed ADC ``[-128, 127]`` -> ``+128`` -> integer indices ``[0, 255]``,
- classifiers (punet / transformer / rnn): ``.long()`` input,
  ``argmax(dim=1)`` over ``[B, 256, T]`` logits, then ``-128`` back to int8,
- fcnet (AE regressor): ``.float()`` input (raw 0-255, no normalization),
  float output cast ``np.int8(output - 128)`` — the paper's exact C-style
  truncating cast, deliberately NOT rounded or clipped.

Batch size is a pure performance knob: every model is batch-independent in
eval mode, so batching cannot change the per-segment outputs.
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import importlib
import json
import math
import shutil
import sys
import time
import types
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import torch
from tqdm import tqdm

from execute_tools.build_anchor_map import default_anchor_map_path, load_anchor_map
from execute_tools.data_paths import TIDMAD_DATA_DIR
from execute_tools.dataset_config import NUM_FILES, SEGMENTS_PER_FILE
from execute_tools.scoring_helpers import file_vector_to_log_space
from execute_tools.scoring_utils import score_vector

TIDMAD_REPO = Path("/workspace/REPO/TIDMAD")
CHECKPOINT_DIR = Path("/workspace/DATA/TIDMAD_OFFICIAL_MODELS/TIDMAD_Model")
DEFAULT_WORK_DIR = Path("/workspace/DATA/SIDERIUS_DATA/tidmad_official_banded")

MODEL_SEGMENT_SIZE = 40_000
EXPECTED_S_MAX = 295715680.14248306

# Paper band boundaries: train.py ``ifile_checkpoint = [0, 4, 10, 15, 20]``.
BANDS: list[tuple[int, int]] = [(0, 4), (4, 10), (10, 15), (15, 20)]

ABRA_ATTRIBUTES = {
    "file_first_sample_index": 100000000000000,
    "input_coupling": 0,
    "input_impedance_ohm": 50,
    "sampling_frequency": 10000000,
    "voltage_range_mV": 80,
}


@dataclasses.dataclass(frozen=True)
class ModelSpec:
    """Static description of one paper architecture.

    Attributes:
        key: SIDERIUS model key (also used in output filenames).
        checkpoint_prefix: filename prefix of the official checkpoints.
        output_kind: "classifier" (argmax over 256 logits) or
            "regressor" (float output, truncating int8 cast).
        expected_class_name: legacy ``network.py`` class the unpickled
            checkpoint must be an instance of (validated at load time).
        default_batch_size: 40,000-sample sequences per forward pass.
    """

    key: str
    checkpoint_prefix: str
    output_kind: str
    expected_class_name: str
    default_batch_size: int


MODEL_SPECS: dict[str, ModelSpec] = {
    "punet": ModelSpec(
        key="punet",
        checkpoint_prefix="PUNet",
        output_kind="classifier",
        expected_class_name="PositionalUNet",
        default_batch_size=25,
    ),
    "fcnet": ModelSpec(
        key="fcnet",
        checkpoint_prefix="FCNet",
        output_kind="regressor",
        expected_class_name="AE",
        default_batch_size=25,
    ),
    "transformer": ModelSpec(
        key="transformer",
        checkpoint_prefix="Transformer",
        output_kind="classifier",
        expected_class_name="TransformerModel",
        default_batch_size=25,
    ),
    "rnn": ModelSpec(
        key="rnn",
        checkpoint_prefix="RNN",
        output_kind="classifier",
        expected_class_name="RNNSeq2Seq",
        # H100-measured: bs=250 halves the sequential-LSTM wall time vs
        # bs=100 (~4.5 vs ~9.3 min/file GPU-side); peak activation memory
        # ~35 GB, comfortably inside 80 GB. Batch size cannot change the
        # per-segment outputs (batch-independent model in eval mode).
        default_batch_size=250,
    ),
}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Score the official band-split TIDMAD checkpoints "
            "(0_4 / 4_10 / 10_15 / 15_20 per architecture) with the "
            "SIDERIUS scoring pipeline."
        )
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=sorted(MODEL_SPECS),
        default=["punet", "fcnet", "transformer", "rnn"],
        help="Architectures to score (default: all four non-wavenet models).",
    )
    parser.add_argument(
        "--tidmad-repo",
        type=Path,
        default=TIDMAD_REPO,
        help="Read-only TIDMAD reference repository (provides network.py).",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=CHECKPOINT_DIR,
        help="Directory holding the official {Model}_{low}_{high}.pth files.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(TIDMAD_DATA_DIR),
        help="Directory containing abra_validation_0000.h5 through 0019.h5.",
    )
    parser.add_argument(
        "--anchor-map",
        type=Path,
        default=Path(default_anchor_map_path()),
        help="Canonical segment_anchors.json (default: committed artifact).",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help="Parent directory for temporary HDF5 outputs and summary JSONs.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help=(
            "Override the per-model default batch size "
            "(number of 40,000-sample sequences per forward pass)."
        ),
    )
    parser.add_argument(
        "--file-indices",
        type=int,
        nargs="+",
        default=None,
        help=(
            "Subset of validation file indices to run (default: all 20). "
            "NOTE: with a subset the final scalar is a partial-scope "
            "aggregate and is NOT comparable to full-scope scores."
        ),
    )
    parser.add_argument(
        "--score-workers",
        type=int,
        default=8,
        help="Worker count for score_vector.",
    )
    parser.add_argument(
        "--delete-denoised-after-score",
        action="store_true",
        help=(
            "Delete each model's denoised HDF5 intermediates after its summary "
            "JSON is written (frees ~75 GiB/model). Default: KEEP them on disk."
        ),
    )
    parser.add_argument(
        "--device",
        default="cuda:0" if torch.cuda.is_available() else "cpu",
        help="Torch inference device.",
    )
    return parser.parse_args()


def validation_path(data_dir: Path, file_index: int) -> Path:
    """Return the raw validation path for one file index."""

    return data_dir / f"abra_validation_{file_index:04d}.h5"


def checkpoint_path(checkpoint_dir: Path, spec: ModelSpec, band: tuple[int, int]) -> Path:
    """Return the official checkpoint path for one architecture band."""

    low, high = band
    return checkpoint_dir / f"{spec.checkpoint_prefix}_{low}_{high}.pth"


def band_for_file(file_index: int) -> tuple[int, int]:
    """Return the (low, high) band containing ``file_index``."""

    for low, high in BANDS:
        if low <= file_index < high:
            return (low, high)
    raise ValueError(f"file_index {file_index} outside all bands {BANDS}")


def denoised_filename(model_key: str, file_index: int) -> str:
    """Return the temporary filename resolved by ``score_vector``."""

    return f"abra_validation_denoised_{model_key}_tidmad_official_banded_{file_index:04d}.h5"


def validate_inputs(args: argparse.Namespace, file_indices: list[int]) -> dict[str, Any]:
    """Validate every input before running any inference."""

    if args.batch_size is not None and args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    if args.score_workers <= 0:
        raise ValueError("--score-workers must be positive")
    if not file_indices:
        raise ValueError("--file-indices must not be empty")
    out_of_range = [i for i in file_indices if not 0 <= i < NUM_FILES]
    if out_of_range:
        raise ValueError(f"--file-indices outside [0, {NUM_FILES}): {out_of_range}")

    network_path = args.tidmad_repo / "network.py"
    if not network_path.is_file():
        raise FileNotFoundError(f"TIDMAD network.py not found: {network_path}")

    missing_checkpoints = [
        checkpoint_path(args.checkpoint_dir, MODEL_SPECS[key], band)
        for key in args.models
        for band in BANDS
        if not checkpoint_path(args.checkpoint_dir, MODEL_SPECS[key], band).is_file()
    ]
    if missing_checkpoints:
        formatted = "\n".join(f"  - {path}" for path in missing_checkpoints)
        raise FileNotFoundError(f"Official checkpoints are missing:\n{formatted}")

    missing_validation_files = [
        validation_path(args.data_dir, file_index)
        for file_index in file_indices
        if not validation_path(args.data_dir, file_index).is_file()
    ]
    if missing_validation_files:
        formatted = "\n".join(f"  - {path}" for path in missing_validation_files)
        raise FileNotFoundError(f"Required validation files are missing:\n{formatted}")

    if not args.anchor_map.is_file():
        raise FileNotFoundError(f"Canonical anchor map not found: {args.anchor_map}")

    anchor_data = load_anchor_map(str(args.anchor_map))
    required_keys = {"anchors", "s_max", "num_files", "segments_per_file"}
    missing_keys = required_keys - anchor_data.keys()
    if missing_keys:
        raise ValueError(f"Anchor map is missing keys: {sorted(missing_keys)}")

    anchors = anchor_data["anchors"]
    if not isinstance(anchors, dict) or len(anchors) != NUM_FILES:
        raise ValueError(f"Anchor map must contain {NUM_FILES} file entries")

    s_max = float(anchor_data["s_max"])
    if not math.isfinite(s_max) or s_max <= 0:
        raise ValueError(f"Anchor-map s_max must be finite and positive: {s_max}")
    if not math.isclose(s_max, EXPECTED_S_MAX, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError(
            "Canonical s_max differs from the audited value: "
            f"expected {EXPECTED_S_MAX}, received {s_max}"
        )
    return anchor_data


def import_tidmad_network(tidmad_repo: Path) -> Any:
    """Import ``network.py`` directly from the read-only TIDMAD repository."""

    repo_string = str(tidmad_repo)
    if repo_string not in sys.path:
        sys.path.insert(0, repo_string)

    try:
        return importlib.import_module("network")
    except ModuleNotFoundError as exc:
        if exc.name != "torchsnooper":
            raise

        # network.py imports torchsnooper although its decorators are commented
        # out. Supply a no-op in-memory module without changing the legacy repo.
        stub = types.ModuleType("torchsnooper")

        def noop_decorator(*decorator_args: Any, **decorator_kwargs: Any) -> Any:
            del decorator_kwargs
            if len(decorator_args) == 1 and callable(decorator_args[0]):
                return decorator_args[0]

            def decorate(callable_object: Any) -> Any:
                return callable_object

            return decorate

        stub.snoop = noop_decorator  # type: ignore[attr-defined]
        sys.modules["torchsnooper"] = stub
        return importlib.import_module("network")


def load_model(
    ckpt_path: Path,
    spec: ModelSpec,
    network_module: Any,
    device: torch.device,
) -> torch.nn.Module:
    """Load a full-module checkpoint by direct unpickling.

    The official checkpoints were saved with ``torch.save(model, ...)``
    (full-module pickle), so the pickle itself carries the exact trained
    architecture. We deliberately use the unpickled module directly — the
    same thing the paper's ``inference.py`` does (``model = torch.load(...)``)
    — instead of loading a ``state_dict`` into a fresh instance built from
    today's ``network.py``: the published ``network.py`` on GitHub has
    drifted from the code used to train the official checkpoints (e.g.
    ``DoubleConv`` kernel size 5 -> 9, ``TransformerEncoder`` 1 layer -> 2),
    so a strict ``state_dict`` load fails. ``network_module`` must already
    be imported so the pickle can resolve the ``network.*`` classes.

    Verified under torch 2.10: every downloaded checkpoint unpickles and
    forwards correctly (preflight 2026-07-23).
    """

    del network_module  # imported for its side effect: pickle class resolution

    model = torch.load(
        ckpt_path,
        map_location="cpu",
        weights_only=False,
    )
    if not isinstance(model, torch.nn.Module):
        raise TypeError(
            f"Expected torch.nn.Module in {ckpt_path}; received {type(model)!r}"
        )
    actual_class_name = type(model).__name__
    if actual_class_name != spec.expected_class_name:
        raise TypeError(
            f"{ckpt_path} contains {actual_class_name}; "
            f"expected {spec.expected_class_name}"
        )

    model.to(device)
    model.eval()
    return model


def get_h5_dataset(h5_file: h5py.File, *path: str) -> h5py.Dataset:
    """Resolve an HDF5 dataset path."""

    node: Any = h5_file
    for key in path:
        node = node[key]
    if not isinstance(node, h5py.Dataset):
        raise TypeError(f"HDF5 path {'/'.join(path)} is not a dataset")
    return node


def add_abra_channel(
    timeseries_group: h5py.Group,
    channel_name: str,
    sample_count: int,
) -> h5py.Dataset:
    """Create one channel matching SIDERIUS ``create_abra_file``."""

    channel_group = timeseries_group.create_group(channel_name)
    for key, value in ABRA_ATTRIBUTES.items():
        channel_group.attrs[key] = value
    return channel_group.create_dataset(
        "timeseries",
        shape=(sample_count,),
        dtype=np.int8,
        chunks=True,
    )


def create_temp_output(
    output_path: Path,
    sample_count: int,
) -> tuple[h5py.File, h5py.Dataset, h5py.Dataset]:
    """Create a two-channel ABRA-format temporary HDF5 file."""

    output_file = h5py.File(output_path, "w")
    timeseries_group = output_file.create_group("timeseries")
    denoised_dataset = add_abra_channel(timeseries_group, "channel0001", sample_count)
    injected_dataset = add_abra_channel(timeseries_group, "channel0002", sample_count)
    return output_file, denoised_dataset, injected_dataset


def denoise_batch(
    model: torch.nn.Module,
    spec: ModelSpec,
    class_indices: np.ndarray,
    device: torch.device,
) -> np.ndarray:
    """Run one batch and return flat int8 denoised samples.

    ``class_indices`` is int16 in [0, 255], shape ``[B, 40000]``.

    Classifier decode matches legacy ``inference.py::process_batch``:
    ``argmax(dim=1)`` then ``-128``. Regressor (fcnet) decode matches its
    ``np.int8(output_seq - 128)`` truncating cast exactly.
    """

    if spec.output_kind == "classifier":
        input_tensor = torch.from_numpy(class_indices).long().to(device, non_blocking=True)
        with torch.inference_mode():
            logits = model(input_tensor)
            predicted_classes = logits.argmax(dim=1)
        return (
            predicted_classes.to(torch.int16)
            .sub(128)
            .to(torch.int8)
            .cpu()
            .numpy()
            .reshape(-1)
        )

    if spec.output_kind == "regressor":
        input_tensor = torch.from_numpy(class_indices).float().to(device, non_blocking=True)
        with torch.inference_mode():
            output_seq = model(input_tensor)
        output_array = output_seq.detach().cpu().numpy()
        # Legacy parity: np.int8(output - 128) — C-style truncation, no
        # rounding, no clipping. Out-of-range values wrap exactly as the
        # paper's inference.py did.
        return (output_array - 128.0).astype(np.int8).reshape(-1)

    raise ValueError(f"Unknown output_kind: {spec.output_kind!r}")


def infer_file(
    model: torch.nn.Module,
    spec: ModelSpec,
    raw_path: Path,
    output_path: Path,
    device: torch.device,
    batch_size: int,
) -> float:
    """Run one complete validation file and write temporary HDF5 output."""

    samples_per_batch = batch_size * MODEL_SEGMENT_SIZE
    started = time.perf_counter()

    try:
        with h5py.File(raw_path, "r") as raw_file:
            raw_input = get_h5_dataset(raw_file, "timeseries", "channel0001", "timeseries")
            raw_target = get_h5_dataset(raw_file, "timeseries", "channel0002", "timeseries")
            sample_count = min(
                int(raw_input.shape[0]),
                int(raw_target.shape[0]),
            )
            if sample_count % MODEL_SEGMENT_SIZE != 0:
                raise ValueError(
                    f"{raw_path} contains {sample_count} samples; "
                    f"not divisible by seg_size={MODEL_SEGMENT_SIZE}"
                )

            # Whole-file read (one large sequential read per channel) instead
            # of 2010 tiny per-batch h5 slices. Over the network FUSE mount a
            # single sequential read runs at ~300 MiB/s; per-batch slices ran
            # at ~15 MiB/s (per-request latency dominated). The batch loop below
            # slices these in-RAM arrays, so the denoised output is numerically
            # identical to the per-slice path — only the source of each slice
            # changes from disk to RAM.
            #
            # Read both channels NATIVELY as int8 (their on-disk dtype): a
            # native read runs ~2.2x faster than asking h5py to widen to int16
            # during the read (measured 14.3s vs 30.9s per 2e9-sample channel),
            # because no per-element conversion happens on the read path. The
            # +128 widening to int16 is done per-batch in the loop instead.
            #
            # Memory bound (single file only — NOT the whole dataset): each
            # channel is sample_count bytes (~2 GiB for a 2e9-sample file), so
            # ~4 GiB per file, released before the next file is read. Denoised
            # output still streams incrementally to disk, never accumulated.
            raw_all_input = np.asarray(raw_input[:sample_count], dtype=np.int8)
            raw_all_target = np.asarray(raw_target[:sample_count], dtype=np.int8)

            output_file, denoised_h5, injected_h5 = create_temp_output(output_path, sample_count)
            try:
                total_batches = math.ceil(sample_count / samples_per_batch)
                for start in tqdm(
                    range(0, sample_count, samples_per_batch),
                    total=total_batches,
                    desc=f"{spec.key} {raw_path.stem}",
                ):
                    end = min(start + samples_per_batch, sample_count)
                    signed_adc = raw_all_input[start:end].astype(np.int16)
                    class_indices = signed_adc + 128
                    if class_indices.min() < 0 or class_indices.max() > 255:
                        raise ValueError(f"ADC values outside signed int8 range in {raw_path}")

                    denoised = denoise_batch(
                        model,
                        spec,
                        class_indices.reshape(-1, MODEL_SEGMENT_SIZE),
                        device,
                    )
                    denoised_h5[start:end] = denoised
                    injected_h5[start:end] = raw_all_target[start:end]

                    del class_indices, denoised
            finally:
                output_file.close()
                del raw_all_input, raw_all_target
                gc.collect()
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise

    return time.perf_counter() - started


def run_model(
    spec: ModelSpec,
    args: argparse.Namespace,
    anchor_data: dict[str, Any],
    network_module: Any,
    device: torch.device,
    file_indices: list[int],
    batch_size: int,
) -> dict[str, Any]:
    """Run band-matched inference + scoring for one architecture."""

    s_max = float(anchor_data["s_max"])
    anchors = anchor_data["anchors"]
    inference_seconds: dict[int, float] = {}
    checkpoint_by_file: dict[int, str] = {}

    def _denoised_fn(file_index: int) -> str:
        return denoised_filename(spec.key, file_index)

    # Denoised HDF5 outputs are INTERMEDIATE (the deliverable is scores). They
    # are written to a persistent directory on the network volume (disk, NOT
    # RAM — never /dev/shm), and are KEPT by default. Deletion is opt-in
    # (--delete-denoised-after-score) and, when enabled, happens only AFTER the
    # summary JSON is safely written (see end of this function). ~75 GiB/model.
    denoised_dir = args.work_dir / f"denoised_{spec.key}"
    denoised_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nDenoised output directory (persistent, on-disk): {denoised_dir}")

    for band in BANDS:
        low, high = band
        band_files = [i for i in file_indices if low <= i < high]
        if not band_files:
            continue

        ckpt = checkpoint_path(args.checkpoint_dir, spec, band)
        print(f"\nLoading checkpoint: {ckpt}")
        model = load_model(ckpt, spec, network_module, device)

        for file_index in band_files:
            elapsed = infer_file(
                model=model,
                spec=spec,
                raw_path=validation_path(args.data_dir, file_index),
                output_path=denoised_dir / _denoised_fn(file_index),
                device=device,
                batch_size=batch_size,
            )
            inference_seconds[file_index] = elapsed
            checkpoint_by_file[file_index] = ckpt.name
            print(f"  file {file_index:04d}: completed in {elapsed / 60.0:.2f} minutes")

        del model
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()

    sample_set = {
        file_index: list(range(SEGMENTS_PER_FILE)) for file_index in file_indices
    }
    missing_outputs = [
        denoised_dir / _denoised_fn(file_index)
        for file_index in file_indices
        if not (denoised_dir / _denoised_fn(file_index)).is_file()
    ]
    if missing_outputs:
        formatted = "\n".join(f"  - {path}" for path in missing_outputs)
        raise FileNotFoundError(f"Inference outputs are missing before scoring:\n{formatted}")

    print(f"\nScoring {len(file_indices)} denoised HDF5 files for {spec.key} ...")
    file_vector, denoising_score = score_vector(
        data_dir=str(denoised_dir),
        sample_set=sample_set,
        anchor_map=anchors,
        s_max=s_max,
        denoised_filename_fn=_denoised_fn,
        raw_data_dir=str(args.data_dir),
        parallel=args.score_workers > 1,
        num_workers=args.score_workers,
        legacy_mode=False,
    )

    file_vector_log = file_vector_to_log_space(file_vector)
    summary = {
        "model": f"TIDMAD official band-split {spec.checkpoint_prefix}",
        "model_key": spec.key,
        "output_kind": spec.output_kind,
        "bands": [list(band) for band in BANDS],
        "checkpoint_dir": str(args.checkpoint_dir),
        "checkpoint_by_file": {str(k): checkpoint_by_file[k] for k in sorted(checkpoint_by_file)},
        "data_dir": str(args.data_dir),
        "anchor_map": str(args.anchor_map),
        "s_max": s_max,
        "seg_size": MODEL_SEGMENT_SIZE,
        "batch_size": batch_size,
        "device": str(device),
        "file_indices": file_indices,
        "full_scope": file_indices == list(range(NUM_FILES)),
        "inference_seconds": {str(k): inference_seconds[k] for k in sorted(inference_seconds)},
        "file_vector_linear": file_vector,
        "file_vector_log": [
            None if v is None else (v if math.isfinite(v) else None) for v in file_vector_log
        ],
        "denoising_score": denoising_score if math.isfinite(denoising_score) else None,
        "computed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    summary_path = args.work_dir / f"tidmad_official_{spec.key}_banded_score.json"
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, allow_nan=False)

    # Retention (step-6 safe ordering): the summary JSON above is now on disk,
    # so scores are preserved regardless of what happens to the intermediates.
    # Only now, and only if explicitly requested, delete this model's denoised
    # HDF5 files. Default is KEEP.
    denoised_bytes = sum(
        p.stat().st_size for p in denoised_dir.glob("*.h5") if p.is_file()
    )
    if args.delete_denoised_after_score:
        if not summary_path.is_file():  # defensive: never delete without the summary
            raise RuntimeError(
                f"Refusing to delete denoised for {spec.key}: summary {summary_path} missing"
            )
        shutil.rmtree(denoised_dir)
        print(
            f"\nDeleted denoised intermediates for {spec.key} "
            f"({denoised_bytes / 2**30:.1f} GiB freed) at {denoised_dir}"
        )
    else:
        print(
            f"\nKEPT denoised intermediates for {spec.key} "
            f"({denoised_bytes / 2**30:.1f} GiB) at {denoised_dir}"
        )

    print("\n" + "=" * 88)
    print(f"TIDMAD OFFICIAL BAND-SPLIT {spec.checkpoint_prefix.upper()} SCORE")
    print("=" * 88)
    for file_index in file_indices:
        file_score = file_vector[file_index]
        log_score = file_vector_log[file_index]
        score_text = "None" if file_score is None else f"{file_score:.12g}"
        log_text = (
            "None"
            if log_score is None or not math.isfinite(log_score)
            else f"{log_score:.6f}"
        )
        elapsed_minutes = inference_seconds[file_index] / 60.0
        print(
            f"file {file_index:04d} [{checkpoint_by_file[file_index]:>22}] | "
            f"linear={score_text:>16} | log={log_text:>12} | "
            f"inference={elapsed_minutes:7.2f} min"
        )
    print("-" * 88)
    print(f"Final denoising_score: {denoising_score:.12g}")
    print(f"Summary JSON: {summary_path}")
    print("=" * 88)
    return summary


def main() -> None:
    """Run band-matched inference + scoring for each requested architecture."""

    args = parse_args()
    file_indices = (
        sorted(set(args.file_indices))
        if args.file_indices is not None
        else list(range(NUM_FILES))
    )
    anchor_data = validate_inputs(args, file_indices)

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(f"CUDA requested but unavailable: {device}")

    args.work_dir.mkdir(parents=True, exist_ok=True)

    # Startup stale-intermediate report (do NOT auto-remove — just surface them
    # so the operator can decide). Covers this feature's denoised dirs and any
    # abandoned temp dirs from older TemporaryDirectory-based runs.
    stale = sorted(
        p for p in args.work_dir.glob("denoised_*") if p.is_dir()
    ) + sorted(p for p in args.work_dir.glob("tidmad_official_*_*") if p.is_dir())
    if stale:
        print("NOTE: pre-existing intermediate directories under work_dir "
              "(left in place; remove manually if unwanted):")
        for p in stale:
            nbytes = sum(f.stat().st_size for f in p.glob("*.h5") if f.is_file())
            print(f"  - {p}  ({nbytes / 2**30:.1f} GiB)")

    network_module = import_tidmad_network(args.tidmad_repo)

    print("TIDMAD official band-split checkpoint scoring")
    print(f"TIDMAD repo:     {args.tidmad_repo}")
    print(f"Checkpoint dir:  {args.checkpoint_dir}")
    print(f"Raw data:        {args.data_dir}")
    print(f"Work dir:        {args.work_dir}")
    print(f"Anchor map:      {args.anchor_map}")
    print(f"s_max:           {float(anchor_data['s_max']):.12f}")
    print(f"seg_size:        {MODEL_SEGMENT_SIZE}")
    print(f"Models:          {args.models}")
    print(f"File indices:    {file_indices}")
    print(f"Device:          {device}")

    for key in args.models:
        spec = MODEL_SPECS[key]
        batch_size = args.batch_size if args.batch_size is not None else spec.default_batch_size
        started = time.perf_counter()
        run_model(
            spec=spec,
            args=args,
            anchor_data=anchor_data,
            network_module=network_module,
            device=device,
            file_indices=file_indices,
            batch_size=batch_size,
        )
        elapsed_minutes = (time.perf_counter() - started) / 60.0
        print(f"\n{spec.key} finished in {elapsed_minutes:.1f} minutes.\n")

    retention = (
        "deleted after scoring"
        if args.delete_denoised_after_score
        else "KEPT on disk"
    )
    print(f"All requested models scored. Denoised intermediates: {retention}.")


if __name__ == "__main__":
    main()
