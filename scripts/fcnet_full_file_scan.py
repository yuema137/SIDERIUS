"""
FCNet full-file inference across all 20 TIDMAD validation files.

Uses the paper's split models (FCNet_0_4, FCNet_4_10, FCNet_10_15, FCNet_15_20)
following the paper's inference.py pipeline verbatim:

    input_size = 40000
    batchsize = 25
    reshape to (num_batches, batchsize, input_size)  # 2000 * 25 * 40000 = 2e9
    input_seq = input_seq.float().to(DEVICE)          # int8 -> float, NO +128 shift
    output_seq = model(input_seq).detach().cpu().numpy()
    denoised = np.int8(output_seq - 128).flatten()   # -128 shift, cast to int8

Output HDF5s at /tmp/fcnet_full_scan/abra_validation_denoised_fcnet_XXXX.h5
with the same channel layout as the existing tidmad_reproduction files:
    timeseries/channel0001/timeseries  = denoised CH1 (2e9 int8)
    timeseries/channel0002/timeseries  = passthrough CH2 (2e9 int8)

Skips files 10-14 by default (they already exist under
tidmad_reproduction/fcnet/official_10_15/inference/). Use --include-10-14 to
regenerate them for sanity-checking against the reference.

DIAGNOSTIC SCRIPT — do not commit.
"""

from __future__ import annotations

import argparse
import gc
import sys
import time
from pathlib import Path

import h5py
import numpy as np
import torch

# Paper's AE class must be importable so torch.load can unpickle the .pth
sys.path.insert(0, "/home/tidmad/TIDMAD/")
from network import AE

# torch.load needs paper's AE class in sys.modules to unpickle the
# saved model. Reference the import here so lint understands it is
# intentionally kept in scope for the unpickle path.
_UNPICKLE_TARGET = AE

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
INPUT_SIZE = 40_000
BATCH_SIZE = 25
MAX_INDEX = 2_000_000_000  # 2e9 samples per file = 2000 batches * 25 * 40000

TIDMAD_DATA_DIR = Path("/home/klz/Data/TIDMAD/")
MODELS_DIR = Path("/tmp/tidmad_paper_models/TIDMAD_Model/")
OUT_DIR = Path("/tmp/fcnet_full_scan/")

# Paper's ifile_checkpoint = [0, 4, 10, 15, 20] → 4 bands.
# Format: (low, high) — half-open range of file indices.
BANDS: list[tuple[int, int]] = [(0, 4), (4, 10), (10, 15), (15, 20)]

# Files that already have reference denoised outputs at
# tidmad_reproduction — skipped by default to save inference time and
# because they've been used as the FCNet reference throughout M8.
REFERENCE_ALREADY_EXISTS = {10, 11, 12, 13, 14}


def _model_path(low: int, high: int) -> Path:
    return MODELS_DIR / f"FCNet_{low}_{high}.pth"


def _validation_path(file_index: int) -> Path:
    return TIDMAD_DATA_DIR / f"abra_validation_{file_index:04d}.h5"


def _output_path(file_index: int) -> Path:
    return OUT_DIR / f"abra_validation_denoised_fcnet_{file_index:04d}.h5"


def _band_for_file(file_index: int) -> tuple[int, int]:
    for low, high in BANDS:
        if low <= file_index < high:
            return (low, high)
    raise ValueError(f"file_index {file_index} out of [0, 20) range")


def _run_inference_on_file(model: torch.nn.Module, file_index: int) -> None:
    """Read validation file, run FCNet, write denoised HDF5."""
    src = _validation_path(file_index)
    dst = _output_path(file_index)
    print(f"  [file {file_index:02d}] src={src.name} → dst={dst.name}", flush=True)

    t0 = time.time()
    with h5py.File(str(src), "r") as fin:
        # Read raw int8, verbatim per paper's inference.py read_loader.
        alltrain = np.array(fin["timeseries/channel0001/timeseries"])
        alltarget = np.array(fin["timeseries/channel0002/timeseries"])
        # Also copy the channel attrs so downstream scoring picks up
        # sampling_frequency / voltage_range_mV.
        ch1_attrs = dict(fin["timeseries/channel0001"].attrs)
        ch2_attrs = dict(fin["timeseries/channel0002"].attrs)
    read_t = time.time() - t0

    t0 = time.time()
    # Truncate to the full paper's max_index (may be exactly file length).
    alltrain_r = alltrain[:MAX_INDEX].reshape(-1, BATCH_SIZE, INPUT_SIZE)
    n_batches = alltrain_r.shape[0]
    denoised_batches: list[np.ndarray] = []
    with torch.no_grad():
        for i in range(n_batches):
            arr = alltrain_r[i]  # shape (BATCH_SIZE, INPUT_SIZE), int8
            input_seq = torch.from_numpy(arr).float().to(DEVICE)
            output_seq = model(input_seq).detach().cpu().numpy()
            # -128 shift per paper's inference.py process_batch line 128.
            denoised_batches.append(np.int8(output_seq - 128))
    denoised = np.concatenate([b.flatten() for b in denoised_batches])
    infer_t = time.time() - t0

    # If MAX_INDEX < len(alltrain), pad the tail with zeros so the output
    # matches the original file length (matches the paper's rreshape which
    # drops trailing samples). Existing tidmad_reproduction files have
    # length exactly 2e9, so this is a no-op for standard TIDMAD data.
    if len(denoised) < len(alltrain):
        pad = np.zeros(len(alltrain) - len(denoised), dtype=np.int8)
        denoised = np.concatenate([denoised, pad])

    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()  # h5py can't overwrite an existing file cleanly
    with h5py.File(str(dst), "w") as fout:
        ts = fout.create_group("timeseries")
        c1 = ts.create_group("channel0001")
        for k, v in ch1_attrs.items():
            c1.attrs[k] = v
        c1.create_dataset("timeseries", data=denoised[:MAX_INDEX], chunks=True)
        c2 = ts.create_group("channel0002")
        for k, v in ch2_attrs.items():
            c2.attrs[k] = v
        c2.create_dataset("timeseries", data=alltarget[:MAX_INDEX], chunks=True)
    write_t = time.time() - t0

    print(
        f"  [file {file_index:02d}] "
        f"read={read_t:.1f}s infer={infer_t:.1f}s write={write_t:.1f}s "
        f"total={read_t + infer_t + write_t:.1f}s   "
        f"denoised_len={len(denoised[:MAX_INDEX])} "
        f"denoised unique_int8={len(np.unique(denoised[:1_000_000]))} "
        f"std_int8={float(np.std(denoised[:1_000_000].astype(np.float64))):.2f}",
        flush=True,
    )

    del alltrain, alltarget, alltrain_r, denoised_batches, denoised
    gc.collect()
    torch.cuda.empty_cache()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-10-14",
        action="store_true",
        help="Also regenerate files 10-14 (default skip: reference already exists).",
    )
    parser.add_argument(
        "--files",
        type=str,
        default=None,
        help="Comma-separated list of file indices to run (overrides band-based selection).",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[fcnet_full_file_scan] device={DEVICE}", flush=True)

    if args.files is not None:
        files = [int(x) for x in args.files.split(",") if x.strip()]
    else:
        files = list(range(20))
        if not args.include_10_14:
            files = [i for i in files if i not in REFERENCE_ALREADY_EXISTS]

    # Group files by band so we load each model only once.
    per_band: dict[tuple[int, int], list[int]] = {}
    for i in files:
        band = _band_for_file(i)
        per_band.setdefault(band, []).append(i)

    total_t0 = time.time()
    for (low, high), band_files in sorted(per_band.items()):
        model_path = _model_path(low, high)
        print(
            f"\n=== band {low}-{high} — model {model_path.name} — files {band_files} ===",
            flush=True,
        )
        t0 = time.time()
        model = torch.load(str(model_path), map_location=DEVICE, weights_only=False)
        model.eval()
        print(
            f"  loaded in {time.time() - t0:.1f}s; params={sum(p.numel() for p in model.parameters())}",
            flush=True,
        )

        for fi in band_files:
            _run_inference_on_file(model, fi)

        del model
        gc.collect()
        torch.cuda.empty_cache()

    print(f"\n[fcnet_full_file_scan] all done in {time.time() - total_t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
