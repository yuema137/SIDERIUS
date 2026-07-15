#!/usr/bin/env python
"""Score the official generalist TIDMAD WaveNet checkpoint with SIDERIUS.

The script imports the legacy ``SimpleWaveNet`` directly, runs the official
checkpoint on all validation files, writes temporary ABRA-format HDF5
outputs, scores them with SIDERIUS's canonical anchor map, and removes the
temporary inference files after scoring.

WaveNet is an embedding classifier. Its input transformation is signed ADC
``[-128, 127]`` -> add 128 -> integer indices ``[0, 255]``. It must not receive
voltage-normalized floating-point input.
"""

from __future__ import annotations

import argparse
import gc
import importlib
import json
import math
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import torch
from tqdm import tqdm

from execute_tools.build_anchor_map import load_anchor_map
from execute_tools.data_paths import TIDMAD_DATA_DIR
from execute_tools.dataset_config import NUM_FILES, SEGMENTS_PER_FILE
from execute_tools.scoring_utils import score_vector

TIDMAD_REPO = Path("/home/tidmad/TIDMAD")
TIDMAD_CHECKPOINT = TIDMAD_REPO / "WaveNet_0_20.pth"
CANONICAL_ANCHOR_MAP = Path("/home/klz/Data/TIDMAD/segment_anchors.json")
DEFAULT_WORK_DIR = Path("/home/klz/Data/SIDEREIS_DATA/wavenet/tidmad_official")

MODEL_SEGMENT_SIZE = 40_000
EXPECTED_S_MAX = 295715680.14248306

ABRA_ATTRIBUTES = {
    "file_first_sample_index": 100000000000000,
    "input_coupling": 0,
    "input_impedance_ohm": 50,
    "sampling_frequency": 10000000,
    "voltage_range_mV": 80,
}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Score the official generalist TIDMAD WaveNet checkpoint "
            "with the SIDERIUS scoring pipeline."
        )
    )
    parser.add_argument(
        "--tidmad-repo",
        type=Path,
        default=TIDMAD_REPO,
        help="Read-only TIDMAD reference repository.",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=TIDMAD_CHECKPOINT,
        help="Official WaveNet checkpoint used for all 20 files.",
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
        default=CANONICAL_ANCHOR_MAP,
        help="Canonical segment_anchors.json.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help="Parent directory for temporary HDF5 outputs and the summary JSON.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Number of 40,000-sample sequences per GPU forward pass.",
    )
    parser.add_argument(
        "--score-workers",
        type=int,
        default=8,
        help="Worker count for score_vector.",
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


def denoised_filename(file_index: int) -> str:
    """Return the temporary filename resolved by ``score_vector``."""

    return f"abra_validation_denoised_wavenet_tidmad_official_{file_index:04d}.h5"


def validate_inputs(
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Validate every input before creating temporary outputs."""

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    if args.score_workers <= 0:
        raise ValueError("--score-workers must be positive")

    network_path = args.tidmad_repo / "network.py"
    if not network_path.is_file():
        raise FileNotFoundError(f"TIDMAD network.py not found: {network_path}")
    if not args.checkpoint.is_file():
        raise FileNotFoundError(f"Official WaveNet checkpoint not found: {args.checkpoint}")

    missing_validation_files = [
        validation_path(args.data_dir, file_index)
        for file_index in range(NUM_FILES)
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
    checkpoint_path: Path,
    network_module: Any,
    device: torch.device,
) -> torch.nn.Module:
    """Load a serialized checkpoint into a fresh ``SimpleWaveNet``."""

    checkpoint_object = torch.load(
        checkpoint_path,
        map_location="cpu",
        weights_only=False,
    )
    if not isinstance(checkpoint_object, torch.nn.Module):
        raise TypeError(
            f"Expected torch.nn.Module in {checkpoint_path}; received {type(checkpoint_object)!r}"
        )

    state_dict = checkpoint_object.state_dict()
    del checkpoint_object
    gc.collect()

    model = network_module.SimpleWaveNet()
    model.load_state_dict(state_dict, strict=True)
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


def infer_file(
    model: torch.nn.Module,
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

            output_file, denoised_h5, injected_h5 = create_temp_output(output_path, sample_count)
            try:
                total_batches = math.ceil(sample_count / samples_per_batch)
                for start in tqdm(
                    range(0, sample_count, samples_per_batch),
                    total=total_batches,
                    desc=f"Inference {raw_path.stem}",
                ):
                    end = min(start + samples_per_batch, sample_count)
                    signed_adc = np.asarray(raw_input[start:end], dtype=np.int16)
                    class_indices = signed_adc + 128
                    if class_indices.min() < 0 or class_indices.max() > 255:
                        raise ValueError(f"ADC values outside signed int8 range in {raw_path}")

                    input_tensor = torch.from_numpy(
                        class_indices.reshape(-1, MODEL_SEGMENT_SIZE)
                    ).long()
                    input_tensor = input_tensor.to(device, non_blocking=True)

                    with torch.inference_mode():
                        logits = model(input_tensor)
                        predicted_classes = logits.argmax(dim=1)

                    denoised = (
                        predicted_classes.to(torch.int16)
                        .sub(128)
                        .to(torch.int8)
                        .cpu()
                        .numpy()
                        .reshape(-1)
                    )
                    denoised_h5[start:end] = denoised
                    injected_h5[start:end] = np.asarray(raw_target[start:end], dtype=np.int8)

                    del (
                        signed_adc,
                        class_indices,
                        input_tensor,
                        logits,
                        predicted_classes,
                        denoised,
                    )
            finally:
                output_file.close()
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise

    return time.perf_counter() - started


def print_configuration(
    args: argparse.Namespace,
    device: torch.device,
    s_max: float,
) -> None:
    """Print the resolved configuration."""

    print("TIDMAD official generalist WaveNet scoring")
    print(f"TIDMAD repo:    {args.tidmad_repo}")
    print(f"Checkpoint:     {args.checkpoint}")
    print(f"Raw data:       {args.data_dir}")
    print(f"Work dir:       {args.work_dir}")
    print(f"Anchor map:     {args.anchor_map}")
    print(f"s_max:          {s_max:.12f}")
    print(f"seg_size:       {MODEL_SEGMENT_SIZE}")
    print(f"Batch size:     {args.batch_size}")
    print(f"Device:         {device}")
    print()


def main() -> None:
    """Run inference, score temporary files, and print the report."""

    args = parse_args()
    anchor_data = validate_inputs(args)

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(f"CUDA requested but unavailable: {device}")

    s_max = float(anchor_data["s_max"])
    anchors = anchor_data["anchors"]
    args.work_dir.mkdir(parents=True, exist_ok=True)
    print_configuration(args, device, s_max)
    network_module = import_tidmad_network(args.tidmad_repo)

    inference_seconds: dict[int, float] = {}

    # TemporaryDirectory removes all inference HDF5 files after scoring and
    # also cleans them up if inference or scoring raises an exception.
    with tempfile.TemporaryDirectory(
        prefix="tidmad_official_wavenet_",
        dir=args.work_dir,
    ) as temp_dir_string:
        temp_dir = Path(temp_dir_string)
        print(f"Temporary inference directory: {temp_dir}\n")

        print(f"Loading checkpoint: {args.checkpoint}")
        model = load_model(args.checkpoint, network_module, device)
        for file_index in range(NUM_FILES):
            elapsed = infer_file(
                model=model,
                raw_path=validation_path(args.data_dir, file_index),
                output_path=temp_dir / denoised_filename(file_index),
                device=device,
                batch_size=args.batch_size,
            )
            inference_seconds[file_index] = elapsed
            print(f"file {file_index:04d}: completed in {elapsed / 60.0:.2f} minutes")

        del model
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()

        sample_set = {file_index: list(range(SEGMENTS_PER_FILE)) for file_index in range(NUM_FILES)}
        missing_outputs = [
            temp_dir / denoised_filename(file_index)
            for file_index in range(NUM_FILES)
            if not (temp_dir / denoised_filename(file_index)).is_file()
        ]
        if missing_outputs:
            formatted = "\n".join(f"  - {path}" for path in missing_outputs)
            raise FileNotFoundError(f"Inference outputs are missing before scoring:\n{formatted}")

        print("\nScoring all 20 temporary HDF5 files...")
        # score_vector has no denoised_paths parameter. It joins data_dir with
        # each filename returned by denoised_filename_fn.
        file_vector, denoising_score = score_vector(
            data_dir=str(temp_dir),
            sample_set=sample_set,
            anchor_map=anchors,
            s_max=s_max,
            denoised_filename_fn=denoised_filename,
            raw_data_dir=str(args.data_dir),
            parallel=args.score_workers > 1,
            num_workers=args.score_workers,
            legacy_mode=False,
        )

        summary = {
            "model": "TIDMAD official generalist SimpleWaveNet",
            "checkpoint": str(args.checkpoint),
            "data_dir": str(args.data_dir),
            "anchor_map": str(args.anchor_map),
            "s_max": s_max,
            "seg_size": MODEL_SEGMENT_SIZE,
            "device": str(device),
            "inference_seconds": {
                str(index): inference_seconds[index] for index in range(NUM_FILES)
            },
            "file_vector": file_vector,
            "denoising_score": denoising_score,
        }
        summary_path = args.work_dir / "tidmad_official_wavenet_score.json"
        with summary_path.open("w", encoding="utf-8") as file:
            json.dump(summary, file, indent=2, allow_nan=False)

        print("\n" + "=" * 88)
        print("TIDMAD OFFICIAL GENERALIST WAVENET SCORE")
        print("=" * 88)
        for file_index, file_score in enumerate(file_vector):
            score_text = "None" if file_score is None else f"{file_score:.12g}"
            elapsed_minutes = inference_seconds[file_index] / 60.0
            print(
                f"file {file_index:04d} | score={score_text:>16} | "
                f"inference={elapsed_minutes:8.2f} min"
            )
        print("-" * 88)
        print(f"Final denoising_score: {denoising_score:.12g}")
        print(f"Summary JSON: {summary_path}")
        print("=" * 88)

    print("Temporary inference HDF5 files deleted.")


if __name__ == "__main__":
    main()
