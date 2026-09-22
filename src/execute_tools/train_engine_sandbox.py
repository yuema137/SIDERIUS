import argparse
import gc
import inspect
import json
import os
import random
import sys
import time
from collections.abc import Callable, Mapping, Sequence, Sized
from typing import Any, Literal, cast

import h5py
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

# D14-1 C3. The parent transports the resolved task id, implementation identity,
# and manifest. Composed children load that exact implementation from the
# manifest; real-task imports must not pre-register another implementation under
# the same id. The uncomposed compatibility path is activated explicitly below.
from agent.schemas.model_io_contract import ModelIOContract, load_model_io_contract
from agent.schemas.model_io_resolution import resolve_model_io_contract
from core.capability_registry import CapabilityContractSnapshot
from core.durable_io import publish_json_atomically
from core.runtime_control.budget_diagnostics import report_training_budget
from core.runtime_control.provenance import capture_storage_provenance
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.workload import ResolvedPhaseWorkload
from core.sandbox_layout import training_checkpoint_path
from core.target_standardization import TargetStandardizationReceipt
from execute_tools.checkpoint_selection import CheckpointSelector
from execute_tools.dataset_config import SEGMENT_LENGTH as PSD_SEGMENT_LENGTH
from execute_tools.dataset_config import (
    DatasetProfile,
    declares_tidmad_topology,
    load_dataset_profile,
    resolve_dataset_profile,
    tidmad_topology,
)
from execute_tools.model_input_dtype import (
    TRAINING_SITE_DTYPE,
    apply_contract_cardinality,
    resolve_input_dtype,
)
from execute_tools.observables import (
    active_observation_session,
    child_observables_binding,
)
from execute_tools.scope_artifact import load_transported_scope
from execute_tools.target_standardization import prepare_training_target_standardization

# D14-1 C2b/C3: TIDMADEpochDataset's owner is now execute_tools/tidmad_data_path.py
# (moved verbatim) and ValidationScopeError's is execute_tools/task_data_path.py.
# The explicit `as` aliases are compatibility re-exports — every pre-existing
# `from execute_tools.train_engine_sandbox import <name>` keeps resolving to the
# one moved object. The engine reaches datasets through the run-bound
# TaskDataPath (regime-A resolves to TIDMAD's implementation); TidmadScope is
# the legacy-argv scope assembly for that regime.
from execute_tools.task_data_path import (
    EpochSamplingParams,
    EvalMaterializationParams,
    SequentiallyGroupedTrainingDataset,
    TaskDataPath,
    TaskDataPathResolutionError,
    TrainingScopeError,
    bind_task_data_path,
    resolve_bound_task_data_path,
    resolve_storage_read_scope,
)
from execute_tools.task_data_path import (
    ValidationScopeError as ValidationScopeError,
)
from execute_tools.trained_model_artifact import (
    TrainingArtifactCandidate,
    certified_file_identity,
    training_artifact_candidate_path,
)
from execute_tools.training_budget_execution import (
    TrainingAllocationRejected,
    enforce_training_allocation,
    return_on_allocation_rejection,
)
from execute_tools.training_cli import build_training_parser
from execute_tools.training_history import (
    STATIC_OBSERVATIONS_KEY,
    TRAINING_HISTORY_KEY,
    TrainingHistory,
    objective_config_fingerprint,
    stamp_comparability,
)
from execute_tools.validation_execution import (
    child_validation_executor_binding,
    execute_validation_epoch,
)
from ml_models.loss_models_sandbox import get_criterion, get_target_torch_dtype
from ml_models.models_format_sandbox import LossConfig, TrainConfig, get_config_class

# Import your sandboxed components
from ml_models.models_sandbox import MODEL_REGISTRY
from ml_models.plugin_loader import get_output_type
from ml_models.target_standardization import target_standardization_implementation_sha256


def _write_training_artifact_candidate(
    *,
    args: argparse.Namespace,
    model_cfg: object,
    loss_cfg: LossConfig,
    model_io: ModelIOContract | None,
    sandbox_dirs: dict[str, str],
    result_directory: str,
    target_standardization_enabled: bool = False,
) -> None:
    """Record exact reconstruction inputs when this task declares inference.

    This sidecar is executor evidence, not the final public artifact.  The
    parent combines it with run-bound task identities and persists the
    immutable artifact before attaching its typed ref to ExperimentRecord.
    """

    if model_io is None or model_io.inference is None:
        return
    model_type = getattr(model_cfg, "model_type", None)
    if not isinstance(model_type, str) or not model_type:
        raise ValueError("trained model config must declare a non-empty model_type")
    model_class = MODEL_REGISTRY.get(model_type)
    config_source = inspect.getsourcefile(type(model_cfg))
    model_source = inspect.getsourcefile(model_class) if model_class is not None else None
    if (
        not config_source
        or not model_source
        or os.path.realpath(config_source) != os.path.realpath(model_source)
    ):
        raise ValueError(
            "standard historical inference requires model/config classes from one approved "
            "single-file registered-model plugin"
        )
    checkpoint_path = str(training_checkpoint_path(sandbox_dirs["models"], model_type, args.exp_id))
    checkpoint_sha, checkpoint_size = certified_file_identity(checkpoint_path)
    config_sha, config_size = certified_file_identity(args.model_cfg)
    plugin_sha, _ = certified_file_identity(model_source)
    candidate = TrainingArtifactCandidate(
        checkpoint_path=checkpoint_path,
        checkpoint_sha256=checkpoint_sha,
        checkpoint_byte_size=checkpoint_size,
        model_config_path=args.model_cfg,
        model_config_sha256=config_sha,
        model_config_byte_size=config_size,
        model_plugin_path=model_source,
        model_plugin_sha256=plugin_sha,
        model_plugin_member=os.path.basename(model_source),
        model_type=model_type,
        effective_loss_type=loss_cfg.loss_type,
        training_scope_path=args.task_scope_ref,
        training_scope_sha256=args.task_scope_digest,
        target_standardization_implementation_sha256=(
            target_standardization_implementation_sha256()
            if target_standardization_enabled
            else None
        ),
    )
    sidecar = str(training_artifact_candidate_path(result_directory, args.exp_id))
    publish_json_atomically(sidecar, candidate.model_dump(mode="json"))


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
        profile: DatasetProfile | None = None,
    ):
        self.filepath = fpath
        self.filelist = fname_list if isinstance(fname_list, list) else [fname_list]
        self.seg_size = segmentation_size
        self.sample_size = sample_size
        self.max_segments = max_segments
        self.sample_set = sample_set
        # Resolved Dataset Profile: filenames, decomposition geometry, channel
        # identity and value encoding all come from here. ``None`` resolves the
        # Regime-A adapter, so a caller predating the transport is unaffected.
        self.profile = profile or resolve_dataset_profile()
        self.idict = {}
        self.tdict = {}
        self.class_count = torch.ones(tidmad_topology(self.profile).encoding.num_classes)

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
        enc = tidmad_topology(self.profile).encoding
        return (
            input_data.astype(enc.compute_dtype) + enc.value_offset,
            target_data.astype(enc.compute_dtype) + enc.value_offset,
        )

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
            channels = tidmad_topology(self.profile).channels
            enc = tidmad_topology(self.profile).encoding
            with h5py.File(file_path, "r") as f:
                alltrain = np.array(
                    _h5_dataset(f, "timeseries", channels.input_channel, "timeseries")
                ).astype(enc.storage_dtype)
                alltarget = np.array(
                    _h5_dataset(f, "timeseries", channels.target_channel, "timeseries")
                ).astype(enc.compute_dtype)
                num_segments = len(alltrain) // (self.sample_size * self.seg_size)
                random_offset = np.random.randint(0, self.sample_size)
                self.idict[filename] = alltrain[
                    : num_segments * self.sample_size * self.seg_size
                ].reshape(num_segments, self.sample_size, self.seg_size)[:, random_offset, :]
                self.tdict[filename] = (
                    alltarget[: num_segments * self.sample_size * self.seg_size]
                    .reshape(num_segments, self.sample_size, self.seg_size)[:, random_offset, :]
                    .astype(enc.storage_dtype)
                )
                self.class_count += torch.Tensor(
                    np.bincount(alltarget + enc.value_offset, minlength=enc.num_classes)
                )
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
        dataset = tidmad_topology(self.profile).dataset
        channels = tidmad_topology(self.profile).channels
        enc = tidmad_topology(self.profile).encoding
        psd_len = dataset.psd_segment_length
        ml_segs_per_psd = psd_len // self.seg_size

        for file_index, psd_segment_indices in sorted(sample_set.items()):
            file_index = int(file_index)  # JSON keys may be strings
            filename = dataset.training_file_name(file_index)
            file_path = os.path.join(self.filepath, filename)
            if not os.path.exists(file_path):
                print(f"Warning: {file_path} not found, skipping.")
                continue

            with h5py.File(file_path, "r") as f:
                raw_ch1 = np.array(
                    _h5_dataset(f, "timeseries", channels.input_channel, "timeseries")
                ).astype(enc.storage_dtype)
                raw_ch2 = np.array(
                    _h5_dataset(f, "timeseries", channels.target_channel, "timeseries")
                ).astype(enc.compute_dtype)

            # Extract only the requested PSD segments and reshape to ML segments
            input_chunks = []
            target_chunks = []
            for psd_idx in psd_segment_indices:
                start = psd_idx * psd_len
                end = start + psd_len
                chunk_ch1 = raw_ch1[start:end].reshape(ml_segs_per_psd, self.seg_size)
                chunk_ch2 = (
                    raw_ch2[start:end]
                    .reshape(ml_segs_per_psd, self.seg_size)
                    .astype(enc.storage_dtype)
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
                np.bincount(
                    target_arr.flatten().astype(enc.compute_dtype) + enc.value_offset,
                    minlength=enc.num_classes,
                )
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


def validate_ordering_against_scope(
    order_strategy: str,
    file_order: list[int] | None,
    sample_set: dict | None,
) -> None:
    """Re-check resolved ordering at the execution boundary.

    Mirrors the DataScope enforcement pattern: the tuner validated this
    already, but the engine is directly invocable (and is a subprocess with
    its own CLI), so it never trusts its input. Violations terminate the run
    and are not retryable — an ordering that does not cover the sample set
    would change which files are trained on.

    Args:
        order_strategy: Resolved strategy, ``"shuffle"`` or ``"sequential"``.
        file_order:     Resolved file order, or ``None``.
        sample_set:     ``{file_index: [segment_indices]}`` for this round.

    Raises:
        ValueError: Unknown strategy, a file order supplied under
            ``shuffle``, or a file order that is not a permutation of the
            sample set's files.
    """
    if order_strategy not in ("shuffle", "sequential"):
        raise ValueError(
            f"order_strategy={order_strategy!r} is not recognized "
            f"(expected 'shuffle' or 'sequential')."
        )
    if order_strategy == "shuffle":
        if file_order is not None:
            raise ValueError(
                f"file_order={file_order} was supplied with order_strategy='shuffle'. "
                f"A file order is meaningful only for sequential ordering."
            )
        return
    if file_order is None:
        return  # ascending sample-set order, resolved at build time

    if sample_set is None:
        # Opaque task scopes are deliberately uninterpreted here. Their
        # materialized dataset validates this permutation against its declared
        # sequential groups below.
        return

    scope = {int(k) for k in sample_set}
    order = list(file_order)
    if sorted(order) != sorted(scope) or len(order) != len(set(order)):
        missing = sorted(scope - set(order))
        extra = sorted(set(order) - scope)
        duplicates = sorted({i for i in order if order.count(i) > 1})
        problems = []
        if missing:
            problems.append(f"missing {missing}")
        if extra:
            problems.append(f"outside the sample set {extra}")
        if duplicates:
            problems.append(f"duplicated {duplicates}")
        raise ValueError(
            f"file_order {order} is not a permutation of the training sample "
            f"set's files {sorted(scope)}: {'; '.join(problems)}. Ordering must "
            f"reorder the scope, never change it."
        )


def resolve_sequential_file_row_ranges(dataset: Dataset) -> dict[int, tuple[int, int]]:
    """Resolve the optional dataset capability required by sequential order.

    A task may opt in by exposing ``file_row_ranges`` on its materialized
    training dataset.  The framework treats the mapping as opaque group IDs
    and row spans: it never infers a task or dataset type from the attribute.

    Raises:
        TrainingScopeError: if sequential ordering was requested for a
            dataset that does not provide a valid grouping capability.
    """
    if not isinstance(dataset, SequentiallyGroupedTrainingDataset):
        raise TrainingScopeError(
            "order_strategy='sequential' requires the task's materialized "
            "training dataset to expose a non-empty file_row_ranges mapping"
        )
    raw = dataset.file_row_ranges
    if not isinstance(raw, Mapping) or not raw:
        raise TrainingScopeError(
            "order_strategy='sequential' requires the task's materialized "
            "training dataset to expose a non-empty file_row_ranges mapping"
        )
    resolved: dict[int, tuple[int, int]] = {}
    for group_id, span in raw.items():
        if (
            not isinstance(group_id, int)
            or not isinstance(span, tuple)
            or len(span) != 2
            or not all(isinstance(value, int) for value in span)
            or span[0] < 0
            or span[0] >= span[1]
            or span[1] > len(cast("Sized", dataset))
        ):
            raise TrainingScopeError(
                "order_strategy='sequential' received an invalid "
                "file_row_ranges mapping from the task's training dataset"
            )
        resolved[group_id] = span
    ordered_spans = sorted(resolved.values())
    cursor = 0
    for start, end in ordered_spans:
        if start != cursor:
            raise TrainingScopeError(
                "order_strategy='sequential' requires file_row_ranges to "
                "partition every materialized dataset row exactly once"
            )
        cursor = end
    if cursor != len(cast("Sized", dataset)):
        raise TrainingScopeError(
            "order_strategy='sequential' requires file_row_ranges to "
            "partition every materialized dataset row exactly once"
        )
    return resolved


def build_sequential_indices(
    file_row_ranges: dict[int, tuple[int, int]],
    file_order: list[int] | None,
    rng: "random.Random",
) -> list[int]:
    """Row indices for one epoch under ``sequential`` ordering.

    File blocks are visited in ``file_order``; the rows inside each block are
    shuffled with ``rng`` (operator decision: file order is fixed, samples
    within a file are shuffled per epoch). The result is a permutation of
    every row the dataset holds — ordering changes the visit sequence, never
    the selection.

    Files in ``file_order`` that contributed no rows (missing on disk, so
    skipped during construction) are passed over, preserving the loader's
    existing warn-and-continue behavior. Files present in the dataset but
    absent from ``file_order`` would be silently dropped, so they are a hard
    error instead — that would change selection.

    Args:
        file_row_ranges: ``{file_index: (start, end)}`` from the dataset.
        file_order:      Visit order; ``None`` = ascending file index.
        rng:             Epoch RNG (same seed discipline as subsampling).

    Returns:
        Row indices, ordered for this epoch.

    Raises:
        ValueError: ``file_order`` omits a file the dataset actually loaded.
    """
    order = list(file_order) if file_order is not None else sorted(file_row_ranges)
    duplicates = sorted(
        group_id
        for group_id in set(order)
        if group_id in file_row_ranges and order.count(group_id) > 1
    )
    if duplicates:
        raise ValueError(
            f"file_order {order} repeats loaded training group(s) {duplicates}; "
            "ordering must visit every materialized row exactly once."
        )
    missing = sorted(set(file_row_ranges) - set(order))
    if missing:
        raise ValueError(
            f"file_order {order} omits loaded training file(s) {missing}; their "
            f"samples would never be visited. Ordering must not change selection."
        )
    indices: list[int] = []
    for file_index in order:
        span = file_row_ranges.get(file_index)
        if span is None:
            continue  # file skipped during construction (missing on disk)
        block = list(range(*span))
        rng.shuffle(block)
        indices.extend(block)
    return indices


# ==========================================
# 2. Refactored Training Engine
# ==========================================


def build_training_optimizer(model, train_cfg: TrainConfig):
    """The optimizer production trains with, in one place.

    Extracted verbatim from the two identical blocks in ``run_experiment``
    and ``run_experiment_streaming`` -- same branches, same arguments, same
    order. Nothing about the choice changes here.

    It is extracted because V20 PR C2's pre-phase GPU measurement has to
    build the SAME optimizer the phase will really use, and the optimizer
    is a first-order term in the memory it is measuring: AdamW and Adam each
    keep two full-size moment buffers, SGD without momentum keeps none. A
    measurement taken against SGD for a run that trains with AdamW
    under-states the requirement by two parameter tensors -- the OOM
    direction. A fifth hand-written copy of this switch is exactly how that
    divergence would arrive, so there is now one.

    Args:
        model: the constructed module whose parameters are optimized.
        train_cfg: the validated training config; ``optimizer_type`` is a
            ``Literal["adam", "adamw", "sgd"]`` so the final branch is SGD.

    Returns:
        A ``torch.optim.Optimizer`` over ``model.parameters()``.
    """
    if train_cfg.optimizer_type == "adamw":
        return torch.optim.AdamW(
            model.parameters(), lr=train_cfg.lr, weight_decay=train_cfg.weight_decay
        )
    if train_cfg.optimizer_type == "adam":
        return torch.optim.Adam(model.parameters(), lr=train_cfg.lr)
    return torch.optim.SGD(model.parameters(), lr=train_cfg.lr)


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


# ==========================================
# 2a. Step 07a — the R3 validation pass (transactional observation)
# ==========================================


class ObjectiveStateMutationError(RuntimeError):
    """The training-objective module mutated its own state under validation.

    The frozen rule (design §3.2): validation MUST NOT mutate model,
    optimizer or training-objective state. The built-in criteria are
    stateless in ``forward``; a custom plugin loss is an arbitrary
    ``nn.Module``, so the rule is made executable by comparing the
    criterion's ``state_dict`` before/after the pass. Never restored
    silently — a plugin violating the contract fails closed.
    """


def clamp_validation_scope(
    eval_sample_set: dict, *, max_samples: int | None, ml_segs_per_psd: int
) -> dict:
    """The REQUESTED validation scope, bounded by ``validation_max_samples``.

    Step 07 / PR 07c C6. Applied BEFORE materialization, which is not a
    stylistic choice: ``TrainingHistory`` fails closed when
    ``validation_samples != validation_requested_samples``
    (``training_history.py``, design §3.4b), so a ceiling applied to the
    materialized rows would make every clamped run RAISE. Clamping the request
    keeps ``requested == materialized`` and leaves 07a's invariant untouched.

    **Whole PSD segments are the unit a SampleSet can express**, so the
    resolved row count is the largest multiple of ``ml_segs_per_psd`` that does
    not exceed the ceiling. A maximum is therefore never overshot, and the
    count equals ``min(natural, ceiling)`` exactly whenever the ceiling is a
    multiple of ``ml_segs_per_psd``.

    Deterministic by construction: files are visited in ascending numeric
    order and each file's segments keep their declared order, so the same
    input, config and ceiling always select the same rows in the same order —
    which is what makes a clamped R3 a reproducible observation rather than a
    sample of one.

    Args:
        eval_sample_set: ``{file_index: [psd_segment_indices]}``, the natural
            requested scope.
        max_samples: the ceiling in ML rows, or ``None`` for no ceiling.
        ml_segs_per_psd: ML rows per PSD segment
            (``psd_segment_length // seg_size``).

    Returns:
        The clamped scope, or ``eval_sample_set`` unchanged when no ceiling is
        configured or the ceiling does not bind. Files that lose every segment
        are dropped rather than left empty.

    Raises:
        ValidationScopeError: the ceiling is below one PSD segment's worth of
            rows, so no non-empty scope can honour it.
    """
    if max_samples is None:
        return eval_sample_set
    if ml_segs_per_psd <= 0:
        raise ValidationScopeError(
            f"cannot bound the validation scope: ml_segs_per_psd={ml_segs_per_psd} "
            "(psd_segment_length // seg_size) is not positive."
        )
    if max_samples < ml_segs_per_psd:
        raise ValidationScopeError(
            f"validation_max_samples={max_samples} is below one PSD segment's "
            f"{ml_segs_per_psd} ML rows, so no non-empty validation scope can honour "
            f"it. R3 does not exist for an empty scope, so this is refused rather "
            f"than silently resolved to zero rows — raise the ceiling to at least "
            f"{ml_segs_per_psd}."
        )

    budget_psd = max_samples // ml_segs_per_psd
    clamped: dict = {}
    for file_key in sorted(eval_sample_set.keys(), key=int):
        if budget_psd <= 0:
            break
        segments = list(eval_sample_set[file_key])
        keep = segments[:budget_psd]
        if keep:
            clamped[file_key] = keep
            budget_psd -= len(keep)
    return clamped


def _preflight_validation_scope(
    data_dir: str, eval_sample_set: dict, seg_size: int, profile: DatasetProfile
) -> int:
    """Check the declared validation scope BEFORE epoch 0 (design §3.4b).

    Every requested VALIDATION-family file must exist and every requested
    PSD segment index must lie within it (measured on the physical file:
    ``len(input channel) // psd_segment_length``); the total requested ML
    rows must be > 0. Cheap (HDF5 metadata only), so a mis-declared scope
    costs no training time.

    Returns:
        The total number of ML rows the scope requests (Σ segments × ML segs
        per PSD) — ``TrainingHistory.validation_requested_samples``.

    Raises:
        ValidationScopeError: on any violation.
    """
    dataset, channels = tidmad_topology(profile).dataset, tidmad_topology(profile).channels
    psd_len = dataset.psd_segment_length
    ml_segs_per_psd = psd_len // seg_size
    total_rows = 0
    for file_key in sorted(eval_sample_set.keys(), key=int):
        file_index = int(file_key)
        segments = list(eval_sample_set[file_key])
        file_path = os.path.join(data_dir, dataset.validation_file_name(file_index))
        if not os.path.exists(file_path):
            raise ValidationScopeError(
                f"validation scope requests file {file_index} but the VALIDATION-family file "
                f"{file_path!r} does not exist. The declared validation scope must materialize "
                f"exactly; the training path's skip-a-missing-file semantics do not apply."
            )
        with h5py.File(file_path, "r") as f:
            n_samples = len(_h5_dataset(f, "timeseries", channels.input_channel, "timeseries"))
        available = n_samples // psd_len
        bad = [s for s in segments if not (0 <= int(s) < available)]
        if bad:
            raise ValidationScopeError(
                f"validation scope requests PSD segment(s) {bad!r} of file {file_index}, but "
                f"{file_path!r} holds only {available} PSD segment(s)."
            )
        total_rows += len(segments) * ml_segs_per_psd
    if total_rows <= 0:
        raise ValidationScopeError(
            "validation scope requests zero ML rows — R3 (Σ n_i·L_i / Σ n_i) does not exist "
            "for an empty scope; the pass fails closed rather than emitting NaN."
        )
    return total_rows


def _snapshot_module_state(module: torch.nn.Module) -> dict[str, torch.Tensor]:
    return {k: v.detach().clone() for k, v in module.state_dict().items()}


def _module_state_equal(a: dict[str, torch.Tensor], b: dict[str, torch.Tensor]) -> bool:
    if a.keys() != b.keys():
        return False
    return all(torch.equal(a[k].cpu(), b[k].cpu()) for k in a)


def _validation_pass(
    *,
    model: torch.nn.Module,
    criterion: torch.nn.Module,
    model_cfg,
    loss_cfg: LossConfig,
    model_io: ModelIOContract | None,
    device: torch.device,
    data_path: TaskDataPath,
    task_eval_scope: object,
    data_dir: str,
    batch_size: int,
    verifier: Any = None,
    on_verified: Any = None,
    observables: Any = None,
    check_allocation: Callable[[], None] | None = None,
    resolved_custom_target_dtype: Literal["long", "float"] | None = None,
) -> tuple[float, int, float]:
    """One R3 observation: the run-resolved objective on the validation scope.

    A TRANSACTIONAL observation (design §3.2): ``model.eval()`` +
    ``torch.no_grad()`` + ``shuffle=False`` + ``train_portion=None`` (no RNG
    draw) + ``torch.random.fork_rng`` (torch CPU/CUDA RNG) + Python-``random``
    and NumPy global-state restore + ``try/finally`` mode restore + a
    criterion ``state_dict`` check. The training trajectory and every piece
    of observable training state are left exactly as found.

    R3 = Σ n_i·L_i / Σ n_i over the ENTIRE validation set (``drop_last=False``,
    weights = batch sample counts) — the SAME epoch estimator as R2
    (``EPOCH_STATISTIC``), exact under an unequal last batch.

    Args:
        resolved_custom_target_dtype: Already-resolved loss metadata for an
            isolated coordinator using numeric module proxies. The existing
            loss dtype authority validates/interprets it; no candidate plugin
            import is needed. Omitted on the ordinary local training route.
        verifier: optional ``AdaptiveUnitVerification`` for the ``validation``
            phase (Step 07 / PR 07c C5). When supplied, each COMPLETED
            validation batch's wall time is fed to it until it reaches a
            terminal verdict, which turns the first real batches into a
            measurement-backed prediction that protects THIS run. Feeding is
            observation only — it changes no tensor, no order and no value, so
            R3 is bit-identical with and without it.
        on_verified: called the INSTANT ``verifier`` reaches a verdict, while
            this pass is still running, so the run-time session can persist the
            prediction and the watchdog can see a refreshed deadline.

            **This is the Gate-2 attempt-1 defect.** The completion used to
            happen only after this function RETURNED. In the regime 07c exists
            to fix — where validation is long by construction — the pass cannot
            finish before the stale training-only deadline fires, so the
            refreshed deadline was never written and the attempt died exactly
            as it did in 07a: killed ~26 s into a validation pass whose term
            was absent from the deadline. The training phase never had this bug
            because it completes its verification INSIDE its batch loop; this
            now follows the same pattern.
        observables: `R-OBS-1` level 3 — an optional
            ``DynamicObservableEpoch``. This pass is the only place in the
            engine holding a model OUTPUT beside its TARGET on data the model
            was not trained on, which is why the dynamic family is fed here.
            Feeding is observation only: the accumulator swallows every
            implementation error, runs inside the same ``eval()`` /
            ``no_grad()`` / ``fork_rng`` envelope, and any criterion mutation
            it caused would still be caught by the state check below — so R3
            is bit-identical with and without it.

            The epoch LIFECYCLE deliberately stays with the CALLER, which
            calls ``start_epoch()`` before this pass and ``finish_epoch()``
            after. This function's only added responsibility is feeding the
            batches it already has, which is the one part only it can do.

    Returns:
        ``(r3_value, materialized_rows, seconds)``.

    Raises:
        ValidationScopeError: the materialized rows differ from the declared
            scope's request, per-file or in total (the disk changed mid-run).
            Raised INSIDE ``data_path.validation_dataset`` since D14-1 C3 —
            the exact-materialization obligation is each implementation's,
            discharged in its own scope vocabulary.
        ObjectiveStateMutationError: the criterion's state changed.
    """
    t0 = time.perf_counter()
    was_training = model.training
    py_state = random.getstate()
    np_state = np.random.get_state()
    criterion_state = _snapshot_module_state(criterion)
    fork_devices: list[int] = []
    if device.type == "cuda":
        fork_devices = [device.index if device.index is not None else torch.cuda.current_device()]
    weighted_sum = 0.0
    n_total = 0
    try:
        model.eval()
        with torch.no_grad(), torch.random.fork_rng(devices=fork_devices):
            val_dataset = data_path.validation_dataset(
                task_eval_scope, EvalMaterializationParams(data_dir=data_dir)
            )
            val_loader = DataLoader(
                val_dataset, batch_size=batch_size, shuffle=False, drop_last=False
            )
            input_dtype = resolve_input_dtype(
                model_cfg.model_type, model_io, site_preference=TRAINING_SITE_DTYPE
            )
            target_dtype = (
                get_target_torch_dtype(loss_cfg)
                if resolved_custom_target_dtype is None
                else get_target_torch_dtype(
                    loss_cfg, resolved_custom_dtype=resolved_custom_target_dtype
                )
            )
            use_cuda_sync = device.type == "cuda"
            val_iterator = iter(val_loader)
            while True:
                if check_allocation is not None:
                    check_allocation()
                # Include DataLoader.next(): compressed reads and collation are
                # part of this production batch's wall cost, not free setup.
                if verifier is not None:
                    if use_cuda_sync:
                        torch.cuda.synchronize()
                    t_batch = time.perf_counter()
                try:
                    input_batch, target_batch = next(val_iterator)
                except StopIteration:
                    break

                input_seq = input_batch.to(device).to(input_dtype)
                target_seq = target_batch.to(device).to(dtype=target_dtype)
                # Hoisted out of the `criterion(...)` call so the DECLARED
                # observables can see the same tensor the objective saw. The
                # forward pass is unchanged: one call, same inputs, same
                # order.
                output_seq = model(input_seq)
                loss = criterion(output_seq, target_seq)
                n_batch = int(input_batch.shape[0])
                weighted_sum += float(loss.item()) * n_batch
                n_total += n_batch
                if observables is not None:
                    observables.observe(output_seq, target_seq)

                if verifier is not None:
                    if use_cuda_sync:
                        torch.cuda.synchronize()
                    # The unit is one validation SAMPLE, so a partial final
                    # batch cannot bias the rate.
                    elapsed_ms = max((time.perf_counter() - t_batch) * 1000.0, 1e-6)
                    verifier.feed(elapsed_ms / max(n_batch, 1), elapsed_ms=elapsed_ms)
                    if verifier.is_terminal:
                        # PERSIST NOW, not when the pass ends. The deadline the
                        # watchdog is enforcing right now was built without a
                        # validation term; every batch after this one is
                        # running on borrowed time until the refreshed value
                        # reaches the sidecar.
                        if on_verified is not None:
                            on_verified()
                        verifier = None
            del val_dataset, val_loader
    finally:
        model.train(was_training)
        random.setstate(py_state)
        np.random.set_state(np_state)
    if not _module_state_equal(criterion_state, _snapshot_module_state(criterion)):
        raise ObjectiveStateMutationError(
            f"the training objective ({type(criterion).__name__}) mutated its own state during "
            f"the validation pass — validation must not mutate training-objective state."
        )
    gc.collect()
    r3 = weighted_sum / n_total  # n_total == requested_rows > 0 by the materialization contract
    return r3, n_total, time.perf_counter() - t0


# Public caller entry for isolated validation coordinators. This is an alias to
# the single native estimator/transaction, not a second validation algorithm.
# The legacy private spelling remains for existing engine callers and tests.
observe_validation = _validation_pass


def _build_training_history(
    *,
    loss_cfg: LossConfig,
    epochs_planned: int,
    train_objective: Sequence[float | None],
    validation_objective: Sequence[float | None] | None,
    validation_requested_samples: int | None,
    validation_samples: int | None,
    validation_seconds: list[float] | None,
    validation_requested_samples_before_limit: int | None = None,
    observations: dict[str, list[float]] | None = None,
    target_standardization: TargetStandardizationReceipt | None = None,
) -> TrainingHistory:
    """Assemble the additive ``training_history`` payload (design §3.5).

    The objective parameters are ``Sequence[float | None]`` only because the
    FIELDS accept the storage image of a non-finite epoch (``None``); this
    producer itself emits plain floats. ``Sequence`` (covariant) rather than
    ``list`` (invariant) so a ``list[float]`` accumulator still passes.

    ``observations`` is `R-OBS-1` level 4's dynamic leg. A series is carried
    only when it has ONE value per completed epoch: an observable that failed
    in some epoch and not others produced a SHORTER series, and a short series
    cannot be aligned to an epoch axis — the missing point is not at a known
    index. Such a series is DROPPED whole rather than padded, because a padded
    point would be a fabricated observation, and the schema's own
    length invariant would otherwise refuse the entire payload and cost the
    run its history. Defaulted to ``None`` so every existing caller — the
    legacy single-file path included — emits ``{}`` exactly as before.
    """
    comparability, reason = stamp_comparability(loss_cfg)
    epochs_completed = len(train_objective)
    aligned = {
        name: list(series)
        for name, series in (observations or {}).items()
        if len(series) == epochs_completed
    }
    return TrainingHistory(
        objective_kind=loss_cfg.loss_type,
        objective_config_fingerprint=objective_config_fingerprint(
            loss_cfg, target_standardization=target_standardization
        ),
        objective_reduction=loss_cfg.reduction,
        comparability=comparability,
        comparability_reason=reason,
        epochs_planned=epochs_planned,
        epochs_completed=epochs_completed,
        train_objective=list(train_objective),
        observations=aligned,
        validation_objective=None if validation_objective is None else list(validation_objective),
        validation_requested_samples=validation_requested_samples,
        validation_samples=validation_samples,
        validation_requested_samples_before_limit=validation_requested_samples_before_limit,
        validation_seconds=validation_seconds,
    )


def _declared_len(dataset: object) -> int | None:
    """The dataset's row count, or ``None`` when it does not declare one.

    Diagnostic support for :func:`refuse_zero_optimizer_steps` only. An
    iterable-style dataset legitimately has no length, and the refusal must
    never depend on being able to read one — that would make the guard
    silently inapplicable exactly where the step count is hardest to predict.
    """
    try:
        return len(cast("Sized", dataset))
    except TypeError:
        return None


def refuse_zero_optimizer_steps(
    steps_taken: int,
    *,
    epoch: int,
    batch_size: int,
    rows: int | None,
) -> None:
    """Refuse an epoch that completed without executing a single optimizer step.

    THE ground-truth zero-step guard for both engines: it reads the count of
    steps actually executed, so it holds for any task, any dataset style and
    any reason the epoch came up empty — not just the ``drop_last`` floor that
    is its common cause. It is called at the ONE place each engine used to
    fabricate ``float("nan")`` for an absent measurement.

    Args:
        steps_taken: optimizer steps executed in this epoch.
        epoch: zero-based epoch index, for the diagnostic.
        batch_size: the loader's batch size, for the diagnostic.
        rows: dataset rows the epoch drew from, or ``None`` when the dataset
            does not declare a length. Diagnostic only — never a condition.

    Raises:
        TrainingScopeError: when ``steps_taken`` is zero.
    """
    if steps_taken > 0:
        return
    geometry = (
        f"{rows} rows // batch_size {batch_size} == 0 batches"
        if rows is not None
        else f"an empty loader at batch_size {batch_size}"
    )
    raise TrainingScopeError(
        f"epoch {epoch} executed ZERO optimizer steps ({geometry}). "
        "DataLoader(drop_last=True) discards a final partial batch, so a "
        "training scope smaller than one batch trains nothing. Refusing "
        "rather than reporting an untrained model as a completed round — "
        "raise the scope or train_portion, or lower batch_size."
    )


def run_experiment(
    model_cfg,
    train_cfg: TrainConfig,
    loss_cfg: LossConfig,
    data_loader: DataLoader,
    sandbox_dirs: dict,
    exp_id: str,
    model_io: ModelIOContract | None = None,
    expected_custom_loss_snapshot: CapabilityContractSnapshot | None = None,
):
    CheckpointSelector(train_cfg.checkpoint_selection, has_validation=False)
    if train_cfg.target_standardization != "none":
        raise ValueError("target standardization requires the task-owned scoped training engine")
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
    criterion = get_criterion(
        loss_cfg,
        class_weights,
        expected_contract_snapshot=expected_custom_loss_snapshot,
    )

    # Optimizer Setup
    optimizer = build_training_optimizer(model, train_cfg)

    history = []
    for ep in range(train_cfg.epochs):
        model.train()
        batch_losses = []
        for input_batch, target_batch in tqdm(data_loader, desc=f"Epoch {ep}", file=sys.stdout):
            input_seq = input_batch.to(device)
            target_seq = target_batch.to(device)

            # --- Type conversion based on LOSS and MODEL requirements ---
            # 1. Input: resolved from the model's declared dtype ADMISSIBILITY
            # intersected with what the runtime supports (Step 03 §4a.1). This
            # line used to branch on `model_cfg.model_type == "fcnet"`; it now
            # mirrors the target-side routing on the line below it.
            input_seq = input_seq.to(
                resolve_input_dtype(
                    model_cfg.model_type, model_io, site_preference=TRAINING_SITE_DTYPE
                )
            )

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

        refuse_zero_optimizer_steps(
            len(batch_losses),
            epoch=ep,
            batch_size=train_cfg.batch_size,
            rows=_declared_len(data_loader.dataset),
        )
        avg_loss = np.mean(batch_losses)
        history.append(float(avg_loss))
        print(f"Epoch {ep} | Avg Loss: {avg_loss:.6f}")

    # Result Summary — the three legacy keys FIRST and byte-identical; the
    # additive Step-07a payload last. Legacy single-file mode has NO
    # validation scope, so R3 is honestly ABSENT (validation_objective=None
    # — the "not expected" case of design §3.4a), never fabricated.
    summary = {
        "final_loss": history[-1],
        "loss_history": history,
        "model_params": sum(p.numel() for p in model.parameters() if p.requires_grad),
        TRAINING_HISTORY_KEY: _build_training_history(
            loss_cfg=loss_cfg,
            epochs_planned=train_cfg.epochs,
            train_objective=history,
            validation_objective=None,
            validation_requested_samples=None,
            validation_samples=None,
            validation_seconds=None,
        ).model_dump(),
    }

    # --- KEY FIX: Save to TIDMAD_Sandbox/cached_models ---
    save_path = str(training_checkpoint_path(sandbox_dirs["models"], model_cfg.model_type, exp_id))
    _save_with_sentinel(model.state_dict(), save_path, exp_id)
    print(f"Model saved to: {save_path}")

    del model, optimizer, criterion
    torch.cuda.empty_cache()
    gc.collect()
    return summary


def _setup_storage_provenance(
    data_dir: str,
    sample_set: dict | None,
    profile: DatasetProfile,
    *,
    data_path: TaskDataPath | None = None,
    task_scope: object = None,
) -> dict:
    """RT2-B storage provenance for the measured setup window.

    Step 12 / PR-12d, seam C (B9). EXTRACTED so the declared-absence case
    costs ``run_experiment_streaming`` no branch nodes, and because "what did
    the setup read" is its own question.

    Under TIDMAD the answer is unchanged: the per-file paths the scope names,
    and the scoped byte volume (pre-Gate F2 — whole-file sizes misclassify a
    sparse read as warm). A task that declares no TIDMAD topology has neither
    a file-name template nor a PSD segment length, so it reports the dataset
    ROOT and no per-file claim — which is exactly true, and honest in the way
    ``F-12-2`` already made the runtime ESTIMATE honest: skip the term, never
    guess it.
    """
    if sample_set is None:
        task_read_scope = (
            resolve_storage_read_scope(data_path, data_dir, task_scope)
            if data_path is not None and task_scope is not None
            else None
        )
        if task_read_scope is not None:
            return capture_storage_provenance(
                data_dir,
                list(task_read_scope.file_paths),
                scoped_bytes=task_read_scope.expected_on_disk_bytes,
            )
        return capture_storage_provenance(data_dir, [])
    if not declares_tidmad_topology(profile):
        # No legacy SampleSet means no per-file scope to enumerate — the same
        # answer, and for the same reason, as a profile that declares no
        # TIDMAD topology: report the dataset ROOT and make no per-file claim.
        # (Composed TIDMAD can reach here with a topology AND no SampleSet:
        # it trains from its transported scope, whose per-file identity is the
        # task's to know, not this function's to guess.)
        return capture_storage_provenance(data_dir, [])
    dataset = tidmad_topology(profile).dataset
    file_paths = [
        os.path.join(data_dir, dataset.training_file_name(int(k)))
        for k in sorted(sample_set.keys(), key=int)
    ]
    # Estimate bytes on the same on-disk (compressed) ruler as /proc/self/io.
    # The prior logical ``samples * 3`` value was incommensurable with the
    # block-layer counter and labelled genuinely cold gzip reads as warm.
    scoped_on_disk_bytes = 0
    for key, segments in sample_set.items():
        path = os.path.join(data_dir, dataset.training_file_name(int(key)))
        if os.path.isfile(path):
            scoped_on_disk_bytes += round(
                os.path.getsize(path) * len(segments) / dataset.segments_per_file
            )
    return capture_storage_provenance(data_dir, file_paths, scoped_bytes=scoped_on_disk_bytes)


@return_on_allocation_rejection
def run_experiment_streaming(
    model_cfg,
    train_cfg: TrainConfig,
    loss_cfg: LossConfig,
    # `None` since F-12d-27: a COMPOSED run has no legacy SampleSet by
    # construction and trains from its transported task scope instead. The
    # annotation said `dict` while the dispatch already admitted `None`,
    # which CI pyright caught. Safe on every reachable path: the only
    # unguarded read is `validate_ordering_against_scope`'s `sequential`
    # branch, and `--order_strategy` is still emitted ONLY inside the
    # SampleSet block, so a composed child defaults to `shuffle` and
    # returns before it.
    sample_set: dict | None,
    data_dir: str,
    sandbox_dirs: dict,
    exp_id: str,
    train_portion: float | None = None,
    freeze_subsample: bool = False,
    train_base_seed: int | None = None,
    runtime_session: RuntimeVerificationSession | None = None,
    order_strategy: str = "shuffle",
    file_order: list[int] | None = None,
    profile: DatasetProfile | None = None,
    model_io: ModelIOContract | None = None,
    eval_sample_set: dict | None = None,
    task_scope: object | None = None,
    task_eval_scope: object | None = None,
    validation_requested_rows: int | None = None,
    expected_custom_loss_snapshot: CapabilityContractSnapshot | None = None,
):
    """
    Multi-file training: rebuild the epoch dataset each epoch, then train on it.

    Each epoch subsamples ``train_portion`` of the scope, loads those segments
    via HDF5 slicing, and concatenates them into one in-memory dataset. All
    scope files are resident simultaneously; the per-epoch rebuild is what
    varies the subsample.

    (The name is historical. An earlier implementation did hold one file at a
    time — the coupling ledger tracks the rename, which is deliberately not
    bundled with the ordering work.)

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
        order_strategy:    RESOLVED visitation order — ``"shuffle"`` (default,
                           global uniform shuffle: the pre-PR2 behavior) or
                           ``"sequential"`` (file blocks in ``file_order``,
                           rows shuffled within each block). Already resolved
                           upstream from the agent proposal and any operator
                           override; this engine never sees those levels and
                           does not re-derive precedence.
        file_order:        RESOLVED file visitation order for ``sequential``.
                           ``None`` = ascending file index. Must be a
                           permutation of ``sample_set``'s files — re-checked
                           here because the engine is directly invocable.
        eval_sample_set:   Step 07a. The tuner's EXISTING run-bound eval
                           SampleSet ``{file_index: [segment_indices]}``,
                           addressed on the VALIDATION file family. When
                           given, after every completed epoch the R3
                           validation pass evaluates the SAME resolved
                           objective on it (no backprop, transactional —
                           see ``_validation_pass``); the declared scope must
                           materialize exactly (``ValidationScopeError``
                           otherwise, checked BEFORE epoch 0). ``None`` →
                           no pass, R3 honestly absent (legacy tolerance).
                           The trainer never derives, resamples or re-splits
                           this set (no second split concept).
        task_scope:        D14-1 C3. The OPAQUE training scope handed to the
                           run-bound ``TaskDataPath`` (the engine never reads
                           inside it). ``None`` — every legacy caller — means
                           regime-A: the TIDMAD scope is assembled from the
                           legacy arguments (``sample_set`` / seg size /
                           profile), exactly the PRESENCE-based discrimination
                           the binding truth table uses.
        task_eval_scope:   Same, for the validation identity scope
                           (``eval_sample_set`` under regime-A). D14-2 C5b:
                           an EXPLICIT eval scope (without
                           ``eval_sample_set``) also triggers the R3 pass —
                           the generic condition — and then REQUIRES
                           ``validation_requested_rows``.
        validation_requested_rows: D14-2 C5b, explicit-eval-scope leg ONLY:
                           the caller-DECLARED total ML-row count of the
                           validation scope, in the task's own vocabulary.
                           The implementation's exact-materialization check
                           enforces it; ``TrainingHistory`` pins
                           requested == materialized exactly as under the
                           regime-A preflight. Refused alongside
                           ``eval_sample_set`` (the preflight is that leg's
                           ONLY authority) and required with an explicit
                           ``task_eval_scope`` (never a silently
                           unvalidated R3).

    Returns:
        The result summary dict — the three legacy keys byte-identical to the
        pre-07a form plus the additive ``training_history`` payload — or
        ``None`` when the runtime-verification admission decision rejected
        the attempt (the structured rejection lives in the session's
        observation sidecar).
    """
    # Boundary validation, in the DataScope tradition: the caller already
    # validated, but this engine is directly invocable, so it re-checks rather
    # than trusting its input. A violation terminates — an ordering that does
    # not cover the scope would silently change selection, which no retry
    # would fix.
    from execute_tools.training_budget_execution import TrainingBudgetExecution

    checkpoint_selector = CheckpointSelector(
        train_cfg.checkpoint_selection, has_validation=task_eval_scope is not None
    )
    if train_cfg.target_standardization != "none" and (
        get_output_type(model_cfg.model_type) not in {"regressor", "hybrid"}
        or not get_target_torch_dtype(loss_cfg).is_floating_point
    ):
        raise ValueError(
            "target standardization requires a regressor with continuous floating targets"
        )
    budget_execution = (
        TrainingBudgetExecution(
            runtime_session.policy.training_budget, proposed_epochs=train_cfg.epochs
        )
        if runtime_session is not None and runtime_session.policy.training_budget is not None
        else None
    )
    epoch_limit = budget_execution.envelope.max_epochs if budget_execution else train_cfg.epochs
    # The first measured epoch is the initial admission workload; later
    # allocations use observed full-epoch costs, never a fictitious fixed cap.
    prediction_epochs = 1 if budget_execution else train_cfg.epochs
    if budget_execution and budget_execution.decide().action == "stop":
        raise ValueError(
            "Training budget exhausted before setup; no room before downstream reserve"
        )
    validate_ordering_against_scope(order_strategy, file_order, sample_set)
    # One resolved profile for the whole run: the epoch datasets, the
    # storage provenance and the scoped-byte estimate must not be able to
    # disagree about topology or geometry.
    profile = profile or resolve_dataset_profile()

    device = torch.device(train_cfg.device if torch.cuda.is_available() else "cpu")
    seg_size = model_cfg.segmentation_size

    # D14-1 C3 — ONE data path for the whole run, from the run-scoped binding
    # binding installed by the caller / argv transport in main()). Scope
    # objects remain opaque to the engine and must come from that task.
    data_path = resolve_bound_task_data_path()
    if task_scope is None:
        raise TaskDataPathResolutionError(
            "Training requires a task-owned scope from the active task composition."
        )

    # Model initialization (once)
    model_class = MODEL_REGISTRY.get(model_cfg.model_type)
    if model_class is None:
        raise ValueError(f"Model type {model_cfg.model_type} not found in MODEL_REGISTRY")

    if model_cfg.model_type == "fcnet":
        model = model_class(model_cfg, loss_type=loss_cfg.loss_type).to(device)
    else:
        model = model_class(model_cfg).to(device)

    # Criterion — no class weights in streaming mode (matches legacy train.py)
    criterion = get_criterion(
        loss_cfg,
        class_weights=None,
        expected_contract_snapshot=expected_custom_loss_snapshot,
    )

    # Optimizer (once)
    optimizer = build_training_optimizer(model, train_cfg)

    # Deterministic base seed for reproducible per-epoch subsampling
    base_seed = train_base_seed if train_base_seed is not None else hash(exp_id) % (2**31)

    # VALIDATION POSTURE, None in every production campaign. The Gate's
    # workload envelope, applied where the epoch is BUILT: the dataset
    # reads fewer segments and the loader yields fewer batches, so the
    # bound is spent before expensive work starts rather than enforced by
    # killing a run that already cost 25 minutes. A mid-run stop produces
    # no evidence and wastes the whole attempt; this produces a small,
    # complete, real training execution.
    max_train_samples = (
        runtime_session.policy.validation_max_train_samples if runtime_session is not None else None
    )

    model, criterion, target_standardization = prepare_training_target_standardization(
        model,
        criterion,
        enabled=train_cfg.target_standardization != "none",
        data_path=data_path,
        scope=task_scope,
        sampling=EpochSamplingParams(
            data_dir=data_dir,
            epoch_seed=base_seed,
            train_portion=1.0,
            max_samples=max_train_samples,
        ),
        batch_size=train_cfg.batch_size,
        device=device,
        check_allocation=lambda: enforce_training_allocation(runtime_session, phase="training"),
    )

    history = []
    t_train_start: float | None = None
    verifier = None
    epoch0_dataset_seconds = 0.0
    use_cuda_sync = device.type == "cuda"

    # Step 07a — the R3 validation pass. Pre-flight the declared validation
    # scope ONCE, before epoch 0 and before any optimizer step (§3.4b): a
    # scope that cannot materialize exactly fails closed here, cheaply. The
    # per-epoch pass runs after each COMPLETED epoch, after the training
    # dataset is released (transient, never resident beside it — Q-07a-3),
    # and its wall time is accumulated separately so the training ACTUAL
    # below can exclude it (§3.9).
    # (`validation_requested_rows` is the function parameter: regime-A
    # OVERWRITES it from the preflight below; the explicit-scope leg
    # consumes the caller's declaration — D14-2 C5b.)
    validation_materialized_rows: int | None = None
    validation_history: list[float] | None = None
    validation_seconds: list[float] | None = None
    #: 07c C5 — the validation phase's adaptive verifier, live until it reaches
    #: a terminal verdict. `None` whenever runtime control is off.
    validation_verifier: Any = None
    validation_seconds_total = 0.0
    #: 07c C6 — the NATURAL scope, before `validation_max_samples` bound it.
    #: `None` when no ceiling is configured, which is every production run.
    validation_rows_before_limit: int | None = None
    # `R-OBS-1` level 3 — read from the RUN-SCOPED BINDING, not a parameter.
    # This function's argument list is frozen by an executable structural
    # guard, and a guard whose purpose is to stop it acquiring another
    # responsibility must not be satisfied by handing it one more argument.
    # Every call below is unconditional and a no-op for a run that declared
    # nothing, which is every run that exists today.
    observation = active_observation_session()
    # D14-2 C5b — one declaration authority per leg, refused crosswise.
    if eval_sample_set is not None and validation_requested_rows is not None:
        raise ValueError(
            "validation_requested_rows is the EXPLICIT-eval-scope declaration; "
            "under eval_sample_set (regime-A) the preflight is the only "
            "authority — refusing two."
        )
    if (
        eval_sample_set is None
        and task_eval_scope is not None
        and validation_requested_rows is None
    ):
        raise ValueError(
            "an explicit task_eval_scope requires validation_requested_rows "
            "(the caller-declared row count the implementation's "
            "exact-materialization check enforces) — never a silently "
            "unvalidated R3."
        )
    if eval_sample_set is not None:
        raise TaskDataPathResolutionError(
            "Validation requires a task-owned evaluation scope; the training "
            "engine does not interpret a task-specific sample-set format."
        )
    # D14-2 C5b — the SHARED validation-pass arming, one tail for both legs:
    # regime-A (declaration = the preflight, above) and an explicit
    # task_eval_scope (declaration = the caller's validation_requested_rows,
    # already required non-None by the startup refusal). The R3 machinery —
    # histories, workload, verifier, the per-epoch pass — keys on the
    # GENERIC condition from here on.
    if task_eval_scope is not None:
        assert validation_requested_rows is not None
        # Until a pass runs, the declared count is the materialized count
        # (the pass re-checks equality every epoch).
        validation_materialized_rows = validation_requested_rows
        validation_history = []
        validation_seconds = []
        if runtime_session is not None:
            # 07c C5. The validation phase's EXACT workload, in the unit the
            # verifier measures: one row per epoch, every epoch. Recorded here
            # because this is where the count becomes known, and before any
            # verification — `complete_phase_verification` raises on a
            # verified phase with no workload.
            runtime_session.record_phase_workload(
                "validation",
                ResolvedPhaseWorkload(
                    phase="validation",
                    unit="validation_sample",
                    unit_count=validation_requested_rows * prediction_epochs,
                    detail={
                        "rows_per_pass": validation_requested_rows,
                        "passes": prediction_epochs,
                        "batch_size": train_cfg.batch_size,
                        "derivation": "one forward-only pass over the eval SampleSet per epoch",
                    },
                ),
            )
            validation_verifier = runtime_session.start_phase_verification(
                "validation",
                unit="validation_sample",
                prior_expected_unit_ms=runtime_session.lookup_phase_prior("validation"),
            )

    def _finish_validation_verification() -> None:
        """Persist the validation verification through its normal owner.

        Step 07 / PR 07c, Gate-2 attempt-1 fix. ONE owner for the completion,
        called from two places: from INSIDE `_validation_pass` the instant the
        verifier reaches a verdict (the case that matters — the watchdog is
        still enforcing a deadline with no validation term), and once more
        after the pass for a verifier that never reached one, so the
        measurement is recorded even when the prediction cannot be (§6.2
        event log, §2.11 fail closed).

        Idempotent: it clears `validation_verifier`, so the second call is a
        no-op after the first. Persistence itself is
        `complete_phase_verification`'s own `_write_sidecar()` — this adds no
        second write path.

        `extra_predicted_seconds` stays 0: the prediction is
        `unit_count x unit_ms` over EVERY validation row of every epoch, and
        the measured batches are among those rows, so adding their cost would
        count the first batch twice.
        """
        nonlocal validation_verifier
        if runtime_session is None or validation_verifier is None:
            return
        prediction = runtime_session.complete_phase_verification(
            "validation",
            validation_verifier,
            source="real_validation_verification",
        )
        validation_verifier = None
        enforce_training_allocation(runtime_session, phase="validation", prediction=prediction)
        if (
            runtime_session.decide_admission(stage="post_validation_verification").decision
            == "rejected"
        ):
            raise TrainingAllocationRejected("validation calibration refused by runtime admission")

    def _finish_training_verification(decide_admission: bool) -> bool:
        """Record the training verification; optionally decide admission.

        Returns True when the admission decision REJECTED the attempt.
        The (epochs-1) × epoch-0 dataset-construction term is the
        engine's per-epoch reconstruction cost (audit finding) — an
        explicit additive prediction term, never hidden in unit time.
        """
        assert runtime_session is not None and verifier is not None
        runtime_session.complete_phase_verification(
            "training",
            verifier,
            source="real_training_verification",
            extra_predicted_seconds=(prediction_epochs - 1) * epoch0_dataset_seconds,
            extra_detail={"epoch0_dataset_seconds": epoch0_dataset_seconds},
        )
        report_training_budget(
            runtime_session, stage="post_training_verification", epochs=train_cfg.epochs
        )
        if decide_admission:
            adm = runtime_session.decide_admission(stage="post_training_verification")
            if adm.decision == "rejected":
                print(f"[runtime_control] REJECTED after training verification: {adm.reason}")
                return True
        return False

    for ep in range(epoch_limit):
        if budget_execution:
            budget_execution.start_epoch()
        model.train()

        # Build a fresh dataset each epoch — subsamples train_portion from the
        # scope, loads via HDF5 slicing, enables cross-file shuffling.
        # Reproducible: base_seed from exp_id, +ep for diversity across epochs.
        epoch_seed = base_seed if freeze_subsample else base_seed + ep
        t_dataset = time.perf_counter()
        # D14-1 C3: seam call. The implementation reconstructs
        # ``random.Random(epoch_seed)`` internally — stream-identical to the
        # pre-relocation call site (pinned per grid cell by the committed
        # parity manifest).
        dataset = data_path.training_dataset(
            task_scope,
            EpochSamplingParams(
                data_dir=data_dir,
                epoch_seed=epoch_seed,
                train_portion=train_portion,
                max_samples=max_train_samples,
            ),
        )
        # Every implementation returns a SIZED map-style dataset (the engine's
        # loops depend on it); the cast records that invariant for the type
        # checker — torch's Dataset stub deliberately omits __len__.
        dataset_size = len(cast("Sized", dataset))
        if max_train_samples is not None:
            print(
                f"[validation_envelope] epoch {ep}: {dataset_size} ML segments "
                f"(ceiling {max_train_samples})",
                flush=True,
            )
        if order_strategy == "sequential":
            # Independent RNG stream, seeded from the same epoch seed: the
            # dataset above consumes a variable number of draws depending on
            # train_portion and file count, so sharing its generator would
            # couple visit order to subsampling internals. The "order:" prefix
            # keeps epoch N's ordering stream from colliding with epoch N+1's
            # subsampling stream.
            order_rng = random.Random(f"order:{epoch_seed}")
            # Sequential ordering is an optional dataset capability. Tasks
            # that select it must expose the declared row groups.
            epoch_indices = build_sequential_indices(
                resolve_sequential_file_row_ranges(dataset), file_order, order_rng
            )
            # ONE global loader with the global drop_last, exactly as the
            # shuffle path: ordering changes the visit sequence only. Batches
            # may therefore span a file boundary, and the step count is
            # identical to shuffle's for the same selection.
            loader = DataLoader(
                dataset,
                batch_size=train_cfg.batch_size,
                sampler=epoch_indices,
                drop_last=True,
            )
        else:
            loader = DataLoader(
                dataset, batch_size=train_cfg.batch_size, shuffle=True, drop_last=True
            )
        print(
            f"[data_order] resolved={order_strategy} "
            f"file_order={'none' if file_order is None else file_order} "
            f"epoch={ep} epoch_seed={epoch_seed}"
        )
        if ep == 0:
            epoch0_dataset_seconds = time.perf_counter() - t_dataset

        if runtime_session is not None and ep == 0:
            # RT2-B post-setup boundary (§2.1/§2.2): everything up to here —
            # config load, model/optimizer/criterion init, CUDA context, the
            # epoch-0 dataset and DataLoader — is the measured setup. The
            # steps-per-epoch count comes from the MATERIALIZED loader
            # (drop_last floor), the production ground truth; ``n_keep`` is
            # deterministic per epoch, so every epoch runs the same count.
            steps_per_epoch = len(loader)
            runtime_session.complete_setup(
                storage_provenance=_setup_storage_provenance(
                    data_dir,
                    sample_set,
                    profile,
                    data_path=data_path,
                    task_scope=task_scope,
                ),
                training_workload=ResolvedPhaseWorkload(
                    phase="training",
                    unit="optimizer_step",
                    unit_count=steps_per_epoch * prediction_epochs,
                    detail={
                        "source": "materialized_epoch0_loader",
                        "steps_per_epoch": steps_per_epoch,
                        "epochs": prediction_epochs,
                        "epoch0_samples": len(cast("Sized", dataset)),
                        "batch_size": train_cfg.batch_size,
                        "train_portion": train_portion,
                        # Provenance only — ordering permutes the same rows,
                        # so it changes no term in the workload arithmetic.
                        # Recorded so observations stay attributable if
                        # ordering ever turns out to affect unit time.
                        "resolved_order_strategy": order_strategy,
                    },
                ),
                detail={"dataset_construction_seconds": epoch0_dataset_seconds},
            )
            report_training_budget(
                runtime_session, stage="before_optimizer", epochs=train_cfg.epochs
            )
            # §6a calibration-key inputs — recorded by the engine that
            # knows them. runtime_flags are literal facts of THIS loop
            # (no workers / pinning / accumulation / compile); flipping
            # any of them must update this record (§6a reserved field).
            # C-C5b: built through the SHARED definition, so the pre-launch
            # time gate can reconstruct this identity exactly. Two
            # independent constructions of this mapping would drift, and a
            # drifted hash never matches -- which looks identical to "no
            # calibration recorded yet".
            from core.runtime_control.calibration_context import (
                CalibrationContextInputs,
                build_calibration_context,
                model_precision,
                trainable_param_count,
            )

            runtime_session.set_calibration_context(
                build_calibration_context(
                    CalibrationContextInputs(
                        precision=model_precision(model),
                        optimizer_type=train_cfg.optimizer_type,
                        model_family=model_cfg.model_type,
                        param_count=trainable_param_count(model),
                        seg_size=seg_size,
                        batch_size=train_cfg.batch_size,
                    )
                )
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
            # measured during setup are the ones formal training uses. The
            # first production steps double as the adaptive training
            # verification (RT2-C, §2.5): timed with explicit CUDA sync
            # until a terminal verdict, untimed afterwards. The historical
            # prior (RT2-F store, RT2-G wiring) enables §2.5 early exit on
            # verified_match — never a verification substitute.
            t_train_start = time.perf_counter()
            verifier = runtime_session.start_phase_verification(
                "training",
                unit="optimizer_step",
                prior_expected_unit_ms=runtime_session.lookup_phase_prior("training"),
            )

        if budget_execution and not budget_execution.admit_materialized_epoch(
            optimizer_steps=len(loader)
        ):
            del dataset, loader
            gc.collect()
            break
        batch_losses = []
        rejected_mid_epoch = False
        batch_iterator = iter(loader)
        for _ in tqdm(range(len(loader)), desc=f"Epoch {ep}", file=sys.stdout):
            enforce_training_allocation(runtime_session, phase="training")
            if verifier is not None:
                if use_cuda_sync:
                    torch.cuda.synchronize()
                t_step = time.perf_counter()

            input_batch, target_batch = next(batch_iterator)
            input_seq = input_batch.to(device)
            target_seq = target_batch.to(device)

            input_seq = input_seq.to(
                resolve_input_dtype(
                    model_cfg.model_type, model_io, site_preference=TRAINING_SITE_DTYPE
                )
            )

            # I13 — see comment at the first occurrence above. Same
            # single-source-of-truth dispatch via get_target_torch_dtype.
            target_seq = target_seq.to(dtype=get_target_torch_dtype(loss_cfg))

            optimizer.zero_grad()
            output = model(input_seq)
            loss = criterion(output, target_seq)
            loss.backward()
            optimizer.step()
            batch_losses.append(loss.item())

            if verifier is not None:
                if use_cuda_sync:
                    torch.cuda.synchronize()
                state = verifier.feed(max((time.perf_counter() - t_step) * 1000.0, 1e-6))
                if state in ("verified", "failed_no_steady_state", "failed_pathological_unit"):
                    rejected_mid_epoch = _finish_training_verification(decide_admission=True)
                    verifier = None
                    if rejected_mid_epoch:
                        break

        del batch_iterator
        if verifier is not None:
            # Epoch-0 loader exhausted before a verdict: resolve from the
            # evidence collected. With a single epoch the training work is
            # already DONE — record evidence only; with more epochs ahead,
            # the admission decision still protects them.
            rejected_mid_epoch = _finish_training_verification(
                decide_admission=train_cfg.epochs > 1
            )
            verifier = None

        # Captured BEFORE the epoch's dataset is released, so the zero-step
        # refusal below can still name the geometry that produced the
        # empty epoch.
        epoch_rows = _declared_len(dataset)
        del dataset, loader
        gc.collect()

        if rejected_mid_epoch:
            del model, optimizer, criterion
            torch.cuda.empty_cache()
            gc.collect()
            return None

        refuse_zero_optimizer_steps(
            len(batch_losses),
            epoch=ep,
            batch_size=train_cfg.batch_size,
            rows=epoch_rows,
        )
        avg_loss = np.mean(batch_losses)
        history.append(float(avg_loss))
        print(f"Epoch {ep} | Avg Loss: {avg_loss:.6f}")

        # Step 07a — R3 for THIS completed epoch (one observation per R2
        # entry, so the two curves always agree in length). Sequencing call
        # only; the transactional pass lives in ``_validation_pass``.
        # D14-2 C5b: the GENERIC trigger — an armed eval scope, either leg.
        if task_eval_scope is not None:
            assert validation_history is not None and validation_seconds is not None
            assert validation_requested_rows is not None
            r3, n_val, val_secs = execute_validation_epoch(
                _validation_pass,
                expected_rows=validation_requested_rows,
                completed_epochs=ep + 1,
                optimizer_steps=len(batch_losses),
                model=model,
                criterion=criterion,
                model_cfg=model_cfg,
                loss_cfg=loss_cfg,
                model_io=model_io,
                device=device,
                data_path=data_path,
                task_eval_scope=task_eval_scope,
                data_dir=data_dir,
                batch_size=train_cfg.batch_size,
                verifier=validation_verifier,
                on_verified=_finish_validation_verification,
                observables=observation,
                check_allocation=lambda: enforce_training_allocation(
                    runtime_session, phase="validation"
                ),
            )
            validation_history.append(float(r3))
            validation_seconds.append(float(val_secs))
            validation_seconds_total += val_secs
            validation_materialized_rows = n_val

            # Normally already done INSIDE the pass, the instant the verifier
            # reached a verdict (that is the Gate-2 attempt-1 fix). Idempotent,
            # so this only fires for a pass that ended while still verifying.
            if validation_verifier is not None and validation_verifier.is_terminal:
                _finish_validation_verification()
            print(f"Epoch {ep} | Validation Loss: {r3:.6f} ({n_val} ML segments)")

            checkpoint_selector.observe(model, epoch=ep + 1, validation_loss=float(r3))

        if budget_execution:
            decision = budget_execution.finish_epoch(optimizer_steps=len(batch_losses))
            if decision.action == "stop":
                break

    if runtime_session is not None and budget_execution is not None:
        budget_execution.reconcile(
            runtime_session,
            validation_rows=validation_requested_rows,
            epoch0_dataset_seconds=epoch0_dataset_seconds,
        )

    if runtime_session is not None and t_train_start is not None:
        # The training ACTUAL spans admission → last optimizer step. It
        # includes epoch ≥ 1 dataset reconstructions — they are part of
        # what training costs in this engine (audit finding, §12 RT2-B).
        # Step 07a: it EXCLUDES the accumulated validation seconds — every
        # pass sits inside this window, and validation batches are not
        # optimizer steps, so leaving them in would inflate the observation
        # store's realized unit ms (actual ÷ unit_count) for every later
        # admission (design §3.9). The pass is not priced by admission /
        # prediction / the watchdog in 07a — 07c / runtime-control debt;
        # ``validation_seconds`` in the payload is the evidence.
        runtime_session.record_phase_actual(
            "training", (time.perf_counter() - t_train_start) - validation_seconds_total
        )

        # 07c C5 — the OTHER half of Q-07c-5. The seconds 07a already
        # accumulates become the validation phase's ACTUAL, so
        # `realized_unit_ms = actual ÷ unit_count` calibrates FUTURE runs.
        # The first-batch verification above protects THIS one; the two are
        # not redundant, they serve different runs.
        #
        # A verifier that never reached a verdict (a pass short enough that
        # the stopping policy was not satisfied) still leaves the ACTUAL
        # recorded — the measurement is worth keeping even when the
        # prediction is not, which is the §6.2 event-log rule. It is closed
        # out here so the failure is recorded rather than dropped silently.
        if validation_seconds:
            _finish_validation_verification()
            runtime_session.record_phase_actual("validation", validation_seconds_total)

        # V21 PR B2 — realized peak memory, the analogue of the ACTUAL
        # above. Read here, in the training subprocess, so the counters
        # are this candidate's and a peer on the same card cannot be
        # blamed for them. Observation only: no admission path reads it.
        from core.runtime_control.realized_memory import read_process_peak_mib

        _alloc, _reserved, _device = read_process_peak_mib()
        runtime_session.record_phase_peak_memory(
            "training",
            allocator_peak_mib=_alloc,
            reserved_peak_mib=_reserved,
            # Reached only after the training loop completed, so a value
            # read here is the phase's true peak. A process killed mid-loop
            # never arrives, and its record stays 'unavailable' rather than
            # acquiring a fabricated number.
            completeness="complete"
            if _alloc is not None or _reserved is not None
            else ("unavailable"),
            device_index=_device,
        )

    # `R-OBS-1` level 3, the STATIC family: after the final optimizer step and
    # BEFORE the model is serialized, so what is observed is the model this
    # attempt actually produced. Never raises — a failed observation is an
    # absence, not a failed training attempt.
    selected_checkpoint = checkpoint_selector.restore(model)
    observation.finalize(model)

    # Result summary — the three legacy keys FIRST and byte-identical to the
    # pre-07a form (values and presence; `final_loss` stays the LAST TRAINING
    # observation, OD-S7-3); the additive Step-07a `training_history` payload
    # last (design §3.5).
    summary = {
        "final_loss": history[-1] if history else float("nan"),
        "loss_history": history,
        "model_params": sum(p.numel() for p in model.parameters() if p.requires_grad),
        TRAINING_HISTORY_KEY: _build_training_history(
            loss_cfg=loss_cfg,
            epochs_planned=len(history) if budget_execution else train_cfg.epochs,
            target_standardization=target_standardization,
            train_objective=history,
            validation_objective=validation_history,
            validation_requested_samples=validation_requested_rows,
            validation_samples=validation_materialized_rows,
            validation_requested_samples_before_limit=validation_rows_before_limit,
            validation_seconds=validation_seconds,
            observations=observation.dynamic_series(),
        ).model_dump(),
    }
    # `R-OBS-1` level 4, static leg. `static_summary` returns an EMPTY mapping
    # unless the run declared static observables AND at least one produced a
    # value, so a run that declares none emits the same four-key summary it
    # emitted before this family — the `secondary_metrics` record precedent,
    # one layer up, expressed as an update rather than an `if`.
    summary.update(observation.static_summary(STATIC_OBSERVATIONS_KEY))
    if budget_execution is not None:
        summary["training_budget"] = budget_execution.receipt(
            checkpoint_selection=train_cfg.checkpoint_selection
        )
    if selected_checkpoint is not None:
        summary["selected_checkpoint"] = selected_checkpoint.model_dump()
    if target_standardization is not None:
        summary["target_standardization"] = target_standardization.model_dump()

    save_path = str(training_checkpoint_path(sandbox_dirs["models"], model_cfg.model_type, exp_id))
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


def _load_eval_sample_set_arg(path: str | None) -> dict | None:
    """Load ``--eval_sample_set_json`` fail-closed (design §3.4).

    ABSENT (``None`` / empty) → ``None`` (no validation pass, legacy
    tolerance). SUPPLIED → the file must be readable JSON holding a
    ``{file_index: [segment_indices]}`` mapping; anything else raises
    ``ValueError`` naming the path — a bound validation scope must never be
    silently dropped.
    """
    if not path:
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"--eval_sample_set_json {path!r} could not be read as JSON "
            f"({type(exc).__name__}: {exc})."
        ) from exc
    if not isinstance(payload, dict) or not all(
        isinstance(v, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in v)
        for v in payload.values()
    ):
        raise ValueError(
            f"--eval_sample_set_json {path!r} must contain a JSON object mapping file "
            f"indices to lists of integer PSD segment indices, got {type(payload).__name__}."
        )
    return payload


def _cross_check_model_io(model_io, dataset_profile: DatasetProfile) -> None:
    """The Step-03 contract-vs-dataset cross-check, at the child's boundary.

    EXTRACTED by PR-12d seam C: ``main``'s LOC budget is an inherited
    tripwire, and the rule it enforces is the same one §E.2 states — extract
    the responsibility rather than grow the orchestrator.

    The parent already resolves this against its own authority, but the child
    receives the two as SEPARATE argv files and cannot assume the parent
    paired them. Re-checking costs nothing and converts a contradiction into a
    typed refusal instead of an embedding index error thousands of steps into
    a forward pass — the difference Checkpoint C(iii) surfaced.

    ``dataset_num_classes`` is ``int | None`` BY DESIGN — its own docstring
    says a caller with no bound profile "is not forced to invent one" — so a
    task that declares no TIDMAD encoding passes the DECLARED ABSENCE rather
    than dying on the decode. The cross-check then simply has nothing to
    compare against, which is the honest state; the contract's own shape
    validation is unaffected.
    """
    if model_io is None:
        return
    resolve_model_io_contract(
        model_io,
        dataset_num_classes=(
            tidmad_topology(dataset_profile).encoding.num_classes
            if declares_tidmad_topology(dataset_profile)
            else None
        ),
    )


def _has_scope_to_train_from(args: Any, sample_set: dict | None) -> bool:
    """Does this invocation carry ANY scope to train from — F-12d-27.

    ``main``'s mode dispatch used to test ``sample_set is not None`` alone,
    which asks *"did a legacy TIDMAD SampleSet arrive?"* when the question it
    needs answered is *"do I have a scope to train from at all?"*. A composed
    contrast run has no SampleSet **by construction** — its profile declares
    no physical geometry — so it fell into the legacy branch and hit
    ``tidmad_topology(dataset_profile)``, which fails closed for a task that
    declares none.

    Only the transported scope REFERENCE is read here: argv, never bytes.
    Deserialization still happens inside the task binding in ``main``, because
    the bytes must be decoded by the implementation that wrote them.

    An un-composed TIDMAD run carries no ``--task_scope_ref``, so its dispatch
    is still decided by ``sample_set`` exactly as before.

    Extracted rather than inlined: ``main`` sits under a PR-12bc B0 structural
    LOC budget, and §E.2 requires new behaviour to arrive by EXTRACTION rather
    than by spending the allowance. Inlining these lines put it 94 over an
    80-line budget and the guard caught it.
    """
    return sample_set is not None or getattr(args, "task_scope_ref", None) is not None


def main():
    args = build_training_parser().parse_args()

    # Dataset Profile resolution — the child side of the parent's transport.
    #
    #   flag SUPPLIED but broken  -> fail closed, diagnostic names the path
    #   flag ABSENT               -> active task binding, or named refusal
    #
    # The two are deliberately different: a supplied file is decoded directly;
    # omission delegates to the already-established run binding. Neither path
    # may select scientific task semantics implicitly.
    if args.dataset_profile_json is not None:
        dataset_profile = load_dataset_profile(args.dataset_profile_json)
    else:
        dataset_profile = resolve_dataset_profile()

    # Model-I/O contract — same transport, same two-case rule (Step 03 §4a.1).
    model_io = (
        load_model_io_contract(args.model_io_json) if args.model_io_json is not None else None
    )
    expected_custom_loss_snapshot = None
    if args.custom_loss_contract_json is not None:
        with open(args.custom_loss_contract_json, encoding="utf-8") as handle:
            expected_custom_loss_snapshot = CapabilityContractSnapshot.model_validate(
                json.load(handle)
            )

    # Rung 3-E at the SUBPROCESS boundary. `load_task_config` already
    # cross-validates the contract's class axis against the dataset's
    # authority, but the child receives the two as SEPARATE argv files and
    # cannot assume the parent paired them. Re-checking here costs nothing
    # and converts a contradiction into a typed refusal instead of an
    # embedding index error thousands of steps into a forward pass — the
    # difference Checkpoint C(iii) surfaced.
    _cross_check_model_io(model_io, dataset_profile)

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
    from execute_tools.data_paths import resolve_dataset_dir

    args.data_dir = resolve_dataset_dir(args.data_dir, purpose="training child")

    # Define standard sandbox structure
    base_sandbox = args.sandbox_dir
    # Step 11 C7 (F-11-4) — the SAME authority the parent used. These were
    # independent literals on both sides; a mismatch surfaces as a FALSE
    # `error_training`, because the parent looks for the `_OK_<exp_id>`
    # sentinel somewhere the child never wrote one.
    from core.sandbox_executor import sandbox_models_dir, sandbox_records_dir

    sandbox_dirs = {
        "models": sandbox_models_dir(base_sandbox),
        "results": sandbox_records_dir(base_sandbox),  # Use records dir for final JSONs
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

    # Step 03 M6 — the class alphabet is DERIVED from the resolved contract,
    # never from a builtin literal. A config declaring a contradicting
    # count fails closed rather than winning (§4b).
    model_cfg = config_class(**apply_contract_cardinality(m_data, model_io))
    train_cfg = TrainConfig(**t_data)
    loss_cfg = LossConfig(**l_data)

    # Load sample set if provided, otherwise use single file (normal mode)
    sample_set = None
    if args.sample_set_json:
        with open(args.sample_set_json) as f:
            sample_set = json.load(f)

    file_order = None
    if args.file_order_json:
        with open(args.file_order_json) as f:
            file_order = json.load(f)
        if not isinstance(file_order, list) or not all(isinstance(i, int) for i in file_order):
            raise ValueError(
                f"--file_order_json {args.file_order_json!r} must contain a JSON "
                f"list of integers, got {type(file_order).__name__}."
            )

    # Step 07a — the child side of the eval-SampleSet transport, the same
    # two-case rule as the profile / model-I/O flags: SUPPLIED but broken
    # fails closed naming the path; ABSENT means no validation pass.
    eval_sample_set = _load_eval_sample_set_arg(args.eval_sample_set_json)

    if _has_scope_to_train_from(args, sample_set):
        # Multi-file mode: per-epoch concatenated dataset over the sample set.
        #
        # Task-data-path transport: SUPPLIED resolves the transported
        # id as an EXPLICIT binding (unknown -> fail closed, never a
        # fallback); ABSENT is invalid because execution has no task owner.
        if args.task_data_path_id is not None:
            # C3: imported here, not at module scope — the composition layer
            # sits ABOVE this one, and only a composed run ever reaches it.
            from workflows.task_composition import resolve_child_task_data_path

            binding_cm = bind_task_data_path(
                resolve_child_task_data_path(
                    args.task_data_path_id,
                    identity=args.task_data_path_identity,
                    manifest_path=args.task_manifest,
                )
            )
        else:
            raise TaskDataPathResolutionError(
                "Training requires --task_data_path_id from an explicit task composition."
            )
        with (
            binding_cm,
            child_observables_binding(args.task_manifest),
            child_validation_executor_binding(args.validation_executor_json),
        ):
            # Step 12 / PR-12bc B6 — the child side of the SCOPE transport, and
            # the close of the pairing gap. Before this the binding crossed and
            # the scope did not, so the engine fell into its regime-A branch and
            # built a `TidmadScope` that a non-TIDMAD implementation refused.
            # Resolved INSIDE the binding: the bytes must be deserialized by the
            # implementation that wrote them.
            task_scope = load_transported_scope(
                args.task_scope_ref, args.task_scope_digest, leg="training"
            )
            task_eval_scope = load_transported_scope(
                args.task_eval_scope_ref, args.task_eval_scope_digest, leg="evaluation"
            )
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
                order_strategy=args.order_strategy,
                file_order=file_order,
                profile=dataset_profile,
                model_io=model_io,
                eval_sample_set=eval_sample_set,
                task_scope=task_scope,
                task_eval_scope=task_eval_scope,
                validation_requested_rows=args.validation_requested_rows,
                expected_custom_loss_snapshot=expected_custom_loss_snapshot,
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
        if args.validation_executor_json is not None:
            raise ValueError("A validation deployment requires task-owned streaming scopes")
        dataset = TIDMADDataset(
            args.data_dir,
            [tidmad_topology(dataset_profile).dataset.training_file_name(args.file_index)],
            model_cfg.segmentation_size,
            profile=dataset_profile,
        )
        loader = DataLoader(dataset, batch_size=train_cfg.batch_size, shuffle=True, drop_last=True)
        results = run_experiment(
            model_cfg,
            train_cfg,
            loss_cfg,
            loader,
            sandbox_dirs,
            args.exp_id,
            model_io,
            expected_custom_loss_snapshot,
        )

    # Save final JSON
    final_res_dir = os.path.join(sandbox_dirs["results"], args.run_name)
    os.makedirs(final_res_dir, exist_ok=True)

    # use folder to separate runs
    res_filename = f"experiment_results_{model_cfg.model_type}_{args.exp_id}.json"
    res_path = os.path.join(final_res_dir, res_filename)

    _write_training_artifact_candidate(
        args=args,
        model_cfg=model_cfg,
        loss_cfg=loss_cfg,
        model_io=model_io,
        sandbox_dirs=sandbox_dirs,
        result_directory=final_res_dir,
        target_standardization_enabled=train_cfg.target_standardization != "none",
    )
    with open(res_path, "w") as f:
        json.dump(results, f, indent=4)
    print(f"Results saved to: {res_path}")


if __name__ == "__main__":
    main()
