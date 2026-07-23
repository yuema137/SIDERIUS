import argparse
import gc
import json
import os
import random
import sys
import time
from typing import Any, cast

import h5py
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

from core.runtime_control.provenance import capture_storage_provenance
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.workload import ResolvedPhaseWorkload
from execute_tools.dataset_config import SEGMENT_LENGTH as PSD_SEGMENT_LENGTH
from ml_models.loss_models_sandbox import get_criterion, get_target_torch_dtype
from ml_models.models_format_sandbox import LossConfig, TrainConfig, get_config_class

# Import your sandboxed components
from ml_models.models_sandbox import MODEL_REGISTRY


def _h5_dataset(f: h5py.File, *path: str) -> h5py.Dataset:
    """Type-only helper: walk an HDF5 path and narrow the final node to Dataset.

    h5py stubs declare ``__getitem__`` as ``Group | Dataset | Datatype``,
    which makes pyright reject chained indexing even though every site here
    ends on a real Dataset at runtime. The walk uses ``Any`` to short-circuit
    the union; the final ``cast`` records the invariant the call site relies
    on. Pure type-system shim — identical runtime semantics to ``f[a][b][c]``.
    """
    node: Any = f
    for k in path:
        node = node[k]
    return cast(h5py.Dataset, node)


# ==========================================
# 1. Dataset Logic
# ==========================================


class TIDMADDataset(Dataset):
    """
    TIDMAD training dataset.

    Supports two modes:
      - **Normal mode** (default): load all segments from a single training file.
        Pass ``fname_list=["abra_training_0006.h5"]``.
      - **Trial mode**: load specific PSD segments from multiple training files.
        Pass ``sample_set={file_index: [segment_indices], ...}`` and leave
        ``fname_list`` empty.  Each PSD segment (10M samples) is subdivided
        into ML segments of size ``segmentation_size``.
    """

    # Number of raw samples per PSD segment (1 second at 10 MS/s)

    def __init__(
        self,
        fpath: str,
        fname_list: list,
        segmentation_size: int,
        sample_size: int = 20,
        max_segments: int | None = None,
        sample_set: dict | None = None,
    ):
        self.filepath = fpath
        self.filelist = fname_list if isinstance(fname_list, list) else [fname_list]
        self.seg_size = segmentation_size
        self.sample_size = sample_size
        self.max_segments = max_segments
        self.sample_set = sample_set
        self.idict = {}
        self.tdict = {}
        self.class_count = torch.ones(256)

        if self.sample_set is not None:
            self.train_events = self._pull_events_from_sample_set()
        else:
            self.train_events = self.pull_event_from_dir(self.filelist)
        self.size = len(self.train_events)

    def __len__(self):
        return self.size

    def __getitem__(self, idx):
        filename, row_idx = self.train_events[idx]
        input_data = self.idict[filename][row_idx]
        target_data = self.tdict[filename][row_idx]
        return (input_data.astype(np.int16) + 128), (target_data.astype(np.int16) + 128)

    def get_class_weight(self):
        weights = self.class_count.sum() / (len(self.class_count) * self.class_count)
        weights = weights / weights.sum() * len(self.class_count)
        return weights

    def pull_event_from_dir(self, filelist):
        """Original loading path: all segments from the given file(s)."""
        evlist = []
        for filename in tqdm(filelist, desc="Indexing H5 Data"):
            file_path = os.path.join(self.filepath, filename)
            if not os.path.exists(file_path):
                continue
            with h5py.File(file_path, "r") as f:
                alltrain = np.array(
                    _h5_dataset(f, "timeseries", "channel0001", "timeseries")
                ).astype(np.int8)
                alltarget = np.array(
                    _h5_dataset(f, "timeseries", "channel0002", "timeseries")
                ).astype(np.int16)
                num_segments = len(alltrain) // (self.sample_size * self.seg_size)
                random_offset = np.random.randint(0, self.sample_size)
                self.idict[filename] = alltrain[
                    : num_segments * self.sample_size * self.seg_size
                ].reshape(num_segments, self.sample_size, self.seg_size)[:, random_offset, :]
                self.tdict[filename] = (
                    alltarget[: num_segments * self.sample_size * self.seg_size]
                    .reshape(num_segments, self.sample_size, self.seg_size)[:, random_offset, :]
                    .astype(np.int8)
                )
                self.class_count += torch.Tensor(np.bincount(alltarget + 128, minlength=256))
                for i in range(num_segments):
                    evlist.append((filename, i))
                del alltrain, alltarget
                gc.collect()
        if self.max_segments is not None:
            evlist = evlist[: self.max_segments]
        return evlist

    def _pull_events_from_sample_set(self):
        """
        Trial-mode loading: load specific PSD segments from multiple files.

        Each PSD segment (10M samples) is subdivided into ML-level segments
        of size ``self.seg_size``, producing ``PSD_SEGMENT_LENGTH // seg_size``
        ML segments per PSD segment.

        Precondition: ``self.sample_set`` must be populated. The constructor
        only dispatches here under the ``is not None`` branch (see ``__init__``
        above), but this method surfaces the contract explicitly so a future
        caller that bypasses ``__init__`` fails fast instead of crashing inside
        ``sorted(None.items())``.
        """
        if self.sample_set is None:
            raise ValueError(
                "_pull_events_from_sample_set requires self.sample_set to be set "
                "(got None) — callers must narrow before dispatching."
            )
        sample_set = self.sample_set
        evlist = []
        ml_segs_per_psd = PSD_SEGMENT_LENGTH // self.seg_size

        for file_index, psd_segment_indices in sorted(sample_set.items()):
            file_index = int(file_index)  # JSON keys may be strings
            filename = f"abra_training_{file_index:04d}.h5"
            file_path = os.path.join(self.filepath, filename)
            if not os.path.exists(file_path):
                print(f"Warning: {file_path} not found, skipping.")
                continue

            with h5py.File(file_path, "r") as f:
                raw_ch1 = np.array(
                    _h5_dataset(f, "timeseries", "channel0001", "timeseries")
                ).astype(np.int8)
                raw_ch2 = np.array(
                    _h5_dataset(f, "timeseries", "channel0002", "timeseries")
                ).astype(np.int16)

            # Extract only the requested PSD segments and reshape to ML segments
            input_chunks = []
            target_chunks = []
            for psd_idx in psd_segment_indices:
                start = psd_idx * PSD_SEGMENT_LENGTH
                end = start + PSD_SEGMENT_LENGTH
                chunk_ch1 = raw_ch1[start:end].reshape(ml_segs_per_psd, self.seg_size)
                chunk_ch2 = (
                    raw_ch2[start:end].reshape(ml_segs_per_psd, self.seg_size).astype(np.int8)
                )
                input_chunks.append(chunk_ch1)
                target_chunks.append(chunk_ch2)

            if not input_chunks:
                continue

            input_arr = np.concatenate(input_chunks, axis=0)  # [N_ml_segs, seg_size]
            target_arr = np.concatenate(target_chunks, axis=0)  # [N_ml_segs, seg_size]

            self.idict[filename] = input_arr
            self.tdict[filename] = target_arr
            self.class_count += torch.Tensor(
                np.bincount(target_arr.flatten().astype(np.int16) + 128, minlength=256)
            )

            for i in range(len(input_arr)):
                evlist.append((filename, i))

            del raw_ch1, raw_ch2
            gc.collect()

        if self.max_segments is not None:
            evlist = evlist[: self.max_segments]
        return evlist


class TIDMADSingleFileDataset(Dataset):
    """
    Lightweight dataset that loads segments from ONE HDF5 file.

    Uses HDF5 direct slicing — never loads the full 2 GB file into memory.

    Peak memory: ``len(psd_segment_indices) * PSD_SEGMENT_LENGTH / seg_size * seg_size``
    bytes per channel. E.g. 20 PSD segments × 10M / 10000 × 10000 = 200 MB.
    """

    def __init__(self, file_path: str, psd_segment_indices: list[int], seg_size: int):
        """
        Args:
            file_path:            Path to a single HDF5 training file.
            psd_segment_indices:  Which PSD segments (0-based) to load from this file.
            seg_size:             ML segmentation size (e.g. 10000).
        """
        ml_segs_per_psd = PSD_SEGMENT_LENGTH // seg_size
        chunks_ch1, chunks_ch2 = [], []

        with h5py.File(file_path, "r") as f:
            ch1 = _h5_dataset(f, "timeseries", "channel0001", "timeseries")
            ch2 = _h5_dataset(f, "timeseries", "channel0002", "timeseries")
            for psd_idx in psd_segment_indices:
                start = psd_idx * PSD_SEGMENT_LENGTH
                end = start + PSD_SEGMENT_LENGTH
                chunks_ch1.append(
                    np.array(ch1[start:end], dtype=np.int8).reshape(ml_segs_per_psd, seg_size)
                )
                chunks_ch2.append(
                    np.array(ch2[start:end], dtype=np.int8).reshape(ml_segs_per_psd, seg_size)
                )

        self.inputs = np.concatenate(chunks_ch1, axis=0)
        self.targets = np.concatenate(chunks_ch2, axis=0)

    def __len__(self):
        return len(self.inputs)

    def __getitem__(self, idx):
        return (
            self.inputs[idx].astype(np.int16) + 128,
            self.targets[idx].astype(np.int16) + 128,
        )


class TIDMADEpochDataset(Dataset):
    """
    Dataset that loads subsampled segments from multiple HDF5 files.

    Created and destroyed each epoch. Collects ``train_portion`` of each
    file's segments, loads them via HDF5 direct slicing, and concatenates
    into a single shuffleable dataset. Cross-file shuffling happens
    naturally via the DataLoader's ``shuffle=True``.

    Peak memory: ``train_portion * sum(segments_per_file) * seg_size`` bytes
    per channel. E.g. train_portion=0.1, 20 files × 10 segs = 200 PSD segs
    → 200 × 1000 × 10000 = 200 MB per channel.
    """

    def __init__(
        self,
        data_dir: str,
        sample_set: dict,
        seg_size: int,
        train_portion: float | None = None,
        rng: "random.Random | None" = None,
    ):
        """
        Args:
            data_dir:       Directory containing ``abra_training_XXXX.h5``.
            sample_set:     ``{file_index: [segment_indices]}`` — the data scope.
            seg_size:       ML segmentation size (e.g. 10000).
            train_portion:  Fraction of each file's segments to use. When None
                            or 1.0, all segments in the scope are loaded.
            rng:            Random instance for reproducible subsampling.
        """
        if rng is None:
            rng = random.Random()

        ml_segs_per_psd = PSD_SEGMENT_LENGTH // seg_size
        all_ch1, all_ch2 = [], []

        for file_key in sorted(sample_set.keys(), key=int):
            file_index = int(file_key)
            file_path = os.path.join(data_dir, f"abra_training_{file_index:04d}.h5")
            if not os.path.exists(file_path):
                print(f"Warning: {file_path} not found, skipping.")
                continue

            scope_segments = sample_set[file_key]
            # Inline the subsample predicate so pyright narrows ``train_portion``
            # to ``float`` inside this branch (previous ``use_subsample`` helper
            # broke that narrowing). The else-leg preserves the original
            # "full-scope when train_portion is None or >= 1.0" semantics.
            if train_portion is not None and train_portion < 1.0:
                n_keep = max(1, round(train_portion * len(scope_segments)))
                segments = rng.sample(scope_segments, n_keep)
            else:
                segments = scope_segments

            with h5py.File(file_path, "r") as f:
                ch1 = _h5_dataset(f, "timeseries", "channel0001", "timeseries")
                ch2 = _h5_dataset(f, "timeseries", "channel0002", "timeseries")
                for psd_idx in segments:
                    start = psd_idx * PSD_SEGMENT_LENGTH
                    end = start + PSD_SEGMENT_LENGTH
                    all_ch1.append(
                        np.array(ch1[start:end], dtype=np.int8).reshape(ml_segs_per_psd, seg_size)
                    )
                    all_ch2.append(
                        np.array(ch2[start:end], dtype=np.int8).reshape(ml_segs_per_psd, seg_size)
                    )

            gc.collect()

        self.inputs = (
            np.concatenate(all_ch1, axis=0) if all_ch1 else np.empty((0, seg_size), dtype=np.int8)
        )
        self.targets = (
            np.concatenate(all_ch2, axis=0) if all_ch2 else np.empty((0, seg_size), dtype=np.int8)
        )

    def __len__(self):
        return len(self.inputs)

    def __getitem__(self, idx):
        return (
            self.inputs[idx].astype(np.int16) + 128,
            self.targets[idx].astype(np.int16) + 128,
        )


# ==========================================
# 2. Refactored Training Engine
# ==========================================


def _save_with_sentinel(state_dict, save_path: str, exp_id: str) -> None:
    """Save the state_dict and atomically mark training as complete.

    Writes a zero-byte sibling ``_OK_<exp_id>`` next to ``save_path`` ONLY
    after ``torch.save`` returns successfully. If ``torch.save`` raises,
    control flow never reaches the sentinel write, so a save failure
    cannot leave an orphan sentinel — the contract Commit 4's
    orchestrator depends on to distinguish silent training crashes from
    genuine inference-side failures.

    Phase 6.7 Fix 3 (producer side). Consumed by
    ``execute_tools.inference_single._assert_training_sentinel`` and (in
    Commit 4) by the post-subprocess sentinel check in
    ``nodes.ml_hyperparameter_tune_agent``.
    """
    torch.save(state_dict, save_path)
    sentinel_path = os.path.join(os.path.dirname(save_path), f"_OK_{exp_id}")
    with open(sentinel_path, "wb"):
        pass  # zero-byte file


def run_experiment(
    model_cfg,
    train_cfg: TrainConfig,
    loss_cfg: LossConfig,
    data_loader: DataLoader,
    sandbox_dirs: dict,
    exp_id: str,
):
    device = torch.device(train_cfg.device if torch.cuda.is_available() else "cpu")

    # Model Initialization
    model_class = MODEL_REGISTRY.get(model_cfg.model_type)
    if model_class is None:
        raise ValueError(f"Model type {model_cfg.model_type} not found in MODEL_REGISTRY")

    # Pass loss_type only for AE (as per your current AE implementation)
    if model_cfg.model_type == "fcnet":
        model = model_class(model_cfg, loss_type=loss_cfg.loss_type).to(device)
    else:
        model = model_class(model_cfg).to(device)

    # Criterion Setup
    # `DataLoader.dataset` is typed `Dataset[Unknown]` in torch stubs, but
    # every caller in this engine wraps a `TIDMADDataset` (the only one
    # exposing `get_class_weight`). Cast is a pure type-system shim.
    class_weights = (
        cast(TIDMADDataset, data_loader.dataset).get_class_weight().to(device)
        if loss_cfg.use_class_weights
        else None
    )
    criterion = get_criterion(loss_cfg, class_weights)

    # Optimizer Setup
    if train_cfg.optimizer_type == "adamw":
        optimizer = torch.optim.AdamW(
            model.parameters(), lr=train_cfg.lr, weight_decay=train_cfg.weight_decay
        )
    elif train_cfg.optimizer_type == "adam":
        optimizer = torch.optim.Adam(model.parameters(), lr=train_cfg.lr)
    else:
        optimizer = torch.optim.SGD(model.parameters(), lr=train_cfg.lr)

    history = []
    for ep in range(train_cfg.epochs):
        model.train()
        batch_losses = []
        for input_batch, target_batch in tqdm(data_loader, desc=f"Epoch {ep}", file=sys.stdout):
            input_seq = input_batch.to(device)
            target_seq = target_batch.to(device)

            # --- Type conversion based on LOSS and MODEL requirements ---
            # 1. Input: Based on Architecture
            # The forward contract is [B, T] int64 for all embedding-based models.
            # Only fcnet (AE) uses float input for regression.
            input_seq = input_seq.float() if model_cfg.model_type == "fcnet" else input_seq.int()

            # 2. Target: Based on Loss Type
            # I13 — single source of truth for target dtype routing. Built-in
            # ce/focal/focal_cw use long; smooth_l1 uses float; custom losses
            # consult LOSS_TARGET_DTYPE_REGISTRY populated from each plugin's
            # PLUGIN_LOSS_TARGET_DTYPE declaration (default "long" preserves
            # the int64 classifier contract documented in proposing_stage.md).
            target_seq = target_seq.to(dtype=get_target_torch_dtype(loss_cfg))

            optimizer.zero_grad()
            output = model(input_seq)
            loss = criterion(output, target_seq)
            loss.backward()
            optimizer.step()
            batch_losses.append(loss.item())

        avg_loss = np.mean(batch_losses)
        history.append(float(avg_loss))
        print(f"Epoch {ep} | Avg Loss: {avg_loss:.6f}")

    # Result Summary
    summary = {
        "final_loss": history[-1],
        "loss_history": history,
        "model_params": sum(p.numel() for p in model.parameters() if p.requires_grad),
    }

    # --- KEY FIX: Save to TIDMAD_Sandbox/cached_models ---
    save_path = os.path.join(
        sandbox_dirs["models"], f"model_{model_cfg.model_type}_{exp_id}_agent.pth"
    )
    _save_with_sentinel(model.state_dict(), save_path, exp_id)
    print(f"Model saved to: {save_path}")

    del model, optimizer, criterion
    torch.cuda.empty_cache()
    gc.collect()
    return summary


def run_experiment_streaming(
    model_cfg,
    train_cfg: TrainConfig,
    loss_cfg: LossConfig,
    sample_set: dict,
    data_dir: str,
    sandbox_dirs: dict,
    exp_id: str,
    train_portion: float | None = None,
    freeze_subsample: bool = False,
    train_base_seed: int | None = None,
    runtime_session: RuntimeVerificationSession | None = None,
):
    """
    Streaming training: process one file at a time, never hold multiple files in RAM.

    Follows the legacy ``train.py`` pattern: for each epoch, iterate through files
    in shuffled order, load one file's segments, train on them, free memory, move
    to the next file. Model weights carry over across files.

    ``sample_set`` defines the data **scope** (which files and segments are in play).
    ``train_portion`` controls how much of each file's scope is subsampled per epoch.
    By default, a different random subsample is drawn each epoch for diversity.

    Args:
        model_cfg:         Pydantic model config.
        train_cfg:         Pydantic training config.
        loss_cfg:          Pydantic loss config.
        sample_set:        ``{file_index: [segment_indices]}`` — the data scope.
        data_dir:          Directory containing ``abra_training_XXXX.h5`` files.
        sandbox_dirs:      ``{"models": ..., "results": ...}`` for saving outputs.
        exp_id:            Experiment identifier for file naming.
        train_portion:     Fraction of each file's segments to use per epoch (0.01-1.0).
                           When None or 1.0, all segments in the scope are used.
        freeze_subsample:  When True, every epoch uses the same subsample (same seed).
                           When False (default), each epoch draws a different subsample.
        train_base_seed:   Base seed for per-epoch subsampling. Epoch n uses
                           ``train_base_seed + n`` (or just ``train_base_seed`` if
                           ``freeze_subsample=True``). When None, derived from
                           ``hash(exp_id)``.
        runtime_session:   Optional in-subprocess runtime-verification session
                           (RT2-B, design §2.1). When provided, the epoch-0
                           dataset/DataLoader construction closes the measured
                           setup window, the post-setup admission decision is
                           made, and a rejection cleans up and returns ``None``
                           WITHOUT saving a model or sentinel. When admitted,
                           execution continues directly into this same epoch-0
                           loop with the same dataset/model/optimizer/CUDA
                           context — verification is the first part of formal
                           execution, never a separate pass. ``None`` →
                           behavior identical to pre-RT2-B code.

    Returns:
        The result summary dict, or ``None`` when the runtime-verification
        admission decision rejected the attempt (the structured rejection
        lives in the session's observation sidecar).
    """
    device = torch.device(train_cfg.device if torch.cuda.is_available() else "cpu")
    seg_size = model_cfg.segmentation_size

    # Model initialization (once)
    model_class = MODEL_REGISTRY.get(model_cfg.model_type)
    if model_class is None:
        raise ValueError(f"Model type {model_cfg.model_type} not found in MODEL_REGISTRY")

    if model_cfg.model_type == "fcnet":
        model = model_class(model_cfg, loss_type=loss_cfg.loss_type).to(device)
    else:
        model = model_class(model_cfg).to(device)

    # Criterion — no class weights in streaming mode (matches legacy train.py)
    criterion = get_criterion(loss_cfg, class_weights=None)

    # Optimizer (once)
    if train_cfg.optimizer_type == "adamw":
        optimizer = torch.optim.AdamW(
            model.parameters(), lr=train_cfg.lr, weight_decay=train_cfg.weight_decay
        )
    elif train_cfg.optimizer_type == "adam":
        optimizer = torch.optim.Adam(model.parameters(), lr=train_cfg.lr)
    else:
        optimizer = torch.optim.SGD(model.parameters(), lr=train_cfg.lr)

    # Deterministic base seed for reproducible per-epoch subsampling
    base_seed = train_base_seed if train_base_seed is not None else hash(exp_id) % (2**31)
    history = []
    t_train_start: float | None = None

    for ep in range(train_cfg.epochs):
        model.train()

        # Build a fresh dataset each epoch — subsamples train_portion from the
        # scope, loads via HDF5 slicing, enables cross-file shuffling.
        # Reproducible: base_seed from exp_id, +ep for diversity across epochs.
        epoch_seed = base_seed if freeze_subsample else base_seed + ep
        epoch_rng = random.Random(epoch_seed)
        dataset = TIDMADEpochDataset(
            data_dir=data_dir,
            sample_set=sample_set,
            seg_size=seg_size,
            train_portion=train_portion,
            rng=epoch_rng,
        )
        loader = DataLoader(dataset, batch_size=train_cfg.batch_size, shuffle=True, drop_last=True)

        if runtime_session is not None and ep == 0:
            # RT2-B post-setup boundary (§2.1/§2.2): everything up to here —
            # config load, model/optimizer/criterion init, CUDA context, the
            # epoch-0 dataset and DataLoader — is the measured setup. The
            # steps-per-epoch count comes from the MATERIALIZED loader
            # (drop_last floor), the production ground truth; ``n_keep`` is
            # deterministic per epoch, so every epoch runs the same count.
            steps_per_epoch = len(loader)
            file_paths = [
                os.path.join(data_dir, f"abra_training_{int(k):04d}.h5")
                for k in sorted(sample_set.keys(), key=int)
            ]
            runtime_session.complete_setup(
                storage_provenance=capture_storage_provenance(data_dir, file_paths),
                training_workload=ResolvedPhaseWorkload(
                    phase="training",
                    unit="optimizer_step",
                    unit_count=steps_per_epoch * train_cfg.epochs,
                    detail={
                        "source": "materialized_epoch0_loader",
                        "steps_per_epoch": steps_per_epoch,
                        "epochs": train_cfg.epochs,
                        "epoch0_samples": len(dataset),
                        "batch_size": train_cfg.batch_size,
                        "train_portion": train_portion,
                    },
                ),
            )
            admission = runtime_session.decide_admission()
            if admission.decision == "rejected":
                print(f"[runtime_control] REJECTED before formal training: {admission.reason}")
                del dataset, loader
                del model, optimizer, criterion
                torch.cuda.empty_cache()
                gc.collect()
                return None
            # Admitted: continue directly into THIS loop — the very objects
            # measured during setup are the ones formal training uses.
            t_train_start = time.perf_counter()

        batch_losses = []
        for input_batch, target_batch in tqdm(
            loader,
            desc=f"Epoch {ep}",
            file=sys.stdout,
        ):
            input_seq = input_batch.to(device)
            target_seq = target_batch.to(device)

            input_seq = input_seq.float() if model_cfg.model_type == "fcnet" else input_seq.int()

            # I13 — see comment at the first occurrence above. Same
            # single-source-of-truth dispatch via get_target_torch_dtype.
            target_seq = target_seq.to(dtype=get_target_torch_dtype(loss_cfg))

            optimizer.zero_grad()
            output = model(input_seq)
            loss = criterion(output, target_seq)
            loss.backward()
            optimizer.step()
            batch_losses.append(loss.item())

        del dataset, loader
        gc.collect()

        avg_loss = np.mean(batch_losses) if batch_losses else float("nan")
        history.append(float(avg_loss))
        print(f"Epoch {ep} | Avg Loss: {avg_loss:.6f}")

    if runtime_session is not None and t_train_start is not None:
        # The training ACTUAL spans admission → last optimizer step. It
        # includes epoch ≥ 1 dataset reconstructions — they are part of
        # what training costs in this engine (audit finding, §12 RT2-B).
        runtime_session.record_phase_actual("training", time.perf_counter() - t_train_start)

    # Result summary
    summary = {
        "final_loss": history[-1] if history else float("nan"),
        "loss_history": history,
        "model_params": sum(p.numel() for p in model.parameters() if p.requires_grad),
    }

    save_path = os.path.join(
        sandbox_dirs["models"], f"model_{model_cfg.model_type}_{exp_id}_agent.pth"
    )
    _save_with_sentinel(model.state_dict(), save_path, exp_id)
    print(f"Model saved to: {save_path}")

    if runtime_session is not None:
        runtime_session.finalize("completed")

    del model, optimizer, criterion
    torch.cuda.empty_cache()
    gc.collect()
    return summary


# ==========================================
# 3. Main Entry Point
# ==========================================


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_cfg", type=str, required=True)
    parser.add_argument("--train_cfg", type=str, required=True)
    parser.add_argument("--loss_cfg", type=str, required=True)
    parser.add_argument(
        "--data_dir",
        type=str,
        default=None,
        help="Directory with TIDMAD training files. Default: from tidmad_data_config.json.",
    )
    parser.add_argument("--sandbox_dir", type=str, default=None, help="Sandbox output directory.")
    parser.add_argument("--file_index", type=int, default=6)
    parser.add_argument("--exp_id", type=str, default="default_exp")
    parser.add_argument(
        "--run_name", type=str, default="test_run", help="Run name for the auto-exploration."
    )
    parser.add_argument(
        "--sample_set_json",
        type=str,
        default=None,
        help="Path to SampleSet JSON for trial mode. Overrides --file_index.",
    )
    parser.add_argument(
        "--train_portion",
        type=float,
        default=None,
        help="Fraction of segments per file to subsample each epoch (0.01-1.0). "
        "When None, uses all segments in the scope.",
    )
    parser.add_argument(
        "--freeze_subsample",
        action="store_true",
        help="Use the same subsample every epoch instead of resampling.",
    )
    parser.add_argument(
        "--train_base_seed",
        type=int,
        default=None,
        help="Base seed for per-epoch subsampling. Epoch n uses seed = base + n. "
        "When None, derived from exp_id hash.",
    )
    parser.add_argument(
        "--runtime_observation_out",
        type=str,
        default=None,
        help="RT2-B: path for the runtime-verification observation sidecar "
        "(streaming mode only). When set, the in-subprocess verification "
        "session records setup/admission/actuals progressively to this file.",
    )
    parser.add_argument(
        "--runtime_policy_json",
        type=str,
        default=None,
        help="RT2-B: path to a RuntimeControlPolicy JSON (operator budget). "
        "Only meaningful together with --runtime_observation_out.",
    )
    args = parser.parse_args()

    # RT2-B: create the verification session FIRST so the measured setup
    # window covers config load and everything after — main() entry is the
    # earliest in-subprocess point (§2.2; process import cost is the
    # orchestration phase, RT2-E).
    runtime_session = None
    if args.runtime_observation_out:
        policy = None
        if args.runtime_policy_json:
            with open(args.runtime_policy_json) as f:
                policy = RuntimeControlPolicy(**json.load(f))
        runtime_session = RuntimeVerificationSession(
            args.runtime_observation_out, policy=policy, attempt_id=args.exp_id
        )

    # Resolve defaults from config file
    if args.data_dir is None:
        from execute_tools.data_paths import TIDMAD_DATA_DIR

        args.data_dir = TIDMAD_DATA_DIR

    # Define standard sandbox structure
    base_sandbox = args.sandbox_dir
    sandbox_dirs = {
        "models": os.path.join(base_sandbox, "cached_models"),
        "results": os.path.join(base_sandbox, "records"),  # Use records dir for final JSONs
    }
    os.makedirs(sandbox_dirs["models"], exist_ok=True)
    os.makedirs(sandbox_dirs["results"], exist_ok=True)

    with open(args.model_cfg) as f:
        m_data = json.load(f)
    with open(args.train_cfg) as f:
        t_data = json.load(f)
    with open(args.loss_cfg) as f:
        l_data = json.load(f)

    # Initialize Pydantic Configs
    model_type = m_data.get("model_type")
    config_class = get_config_class(model_type)
    if config_class is None:
        raise ValueError(f"Unknown model_type in config: {model_type}")

    model_cfg = config_class(**m_data)
    train_cfg = TrainConfig(**t_data)
    loss_cfg = LossConfig(**l_data)

    # Load sample set if provided, otherwise use single file (normal mode)
    sample_set = None
    if args.sample_set_json:
        with open(args.sample_set_json) as f:
            sample_set = json.load(f)

    if sample_set is not None:
        # Streaming mode: one file at a time, memory-efficient
        results = run_experiment_streaming(
            model_cfg,
            train_cfg,
            loss_cfg,
            sample_set=sample_set,
            data_dir=args.data_dir,
            sandbox_dirs=sandbox_dirs,
            exp_id=args.exp_id,
            train_portion=args.train_portion,
            freeze_subsample=args.freeze_subsample,
            train_base_seed=args.train_base_seed,
            runtime_session=runtime_session,
        )
        if results is None:
            # Runtime verification rejected the attempt: the structured
            # provenance lives in the observation sidecar; deliberately no
            # results JSON, no model, no _OK_ sentinel. Clean exit 0 — the
            # parent distinguishes rejection from crash via the sidecar.
            print("[runtime_control] attempt rejected — no experiment results written.")
            return
    else:
        # Legacy single-file mode: pre-load entire file into TIDMADDataset
        dataset = TIDMADDataset(
            args.data_dir,
            [f"abra_training_{str(args.file_index).zfill(4)}.h5"],
            model_cfg.segmentation_size,
        )
        loader = DataLoader(dataset, batch_size=train_cfg.batch_size, shuffle=True, drop_last=True)
        results = run_experiment(model_cfg, train_cfg, loss_cfg, loader, sandbox_dirs, args.exp_id)

    # Save final JSON
    final_res_dir = os.path.join(sandbox_dirs["results"], args.run_name)
    os.makedirs(final_res_dir, exist_ok=True)

    # use folder to separate runs
    res_filename = f"experiment_results_{model_cfg.model_type}_{args.exp_id}.json"
    res_path = os.path.join(final_res_dir, res_filename)

    with open(res_path, "w") as f:
        json.dump(results, f, indent=4)
    print(f"Results saved to: {res_path}")


if __name__ == "__main__":
    main()
