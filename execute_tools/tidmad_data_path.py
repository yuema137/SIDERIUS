"""TIDMAD's TaskDataPath implementation (D14-1 C2b).

OWNERSHIP. This module owns TIDMAD's executable data path: how training and
validation samples materialize from the HDF5 archives, and how model outputs
become the persisted ABRA deliverable / are read back for evaluation.
``TIDMADEpochDataset`` was MOVED VERBATIM here from
``execute_tools/train_engine_sandbox.py`` (D14-1 C2b; the engine re-exports
it, so every pre-existing import keeps resolving). Behaviour is pinned by the
committed pre-relocation manifest
``tests/unit/execute_tools/goldens/d14_tidmad_parity_manifest.json`` —
expected values are READ from that artifact, never recomputed.

BOUNDARIES (parent Amendment 2). Codec only: no metric arithmetic, no
scoreability thresholds, no objective semantics. The output path terminates
at the Step-06 evaluation authority — ``write_deliverable`` delegates to the
deliverable-spec naming/storage authorities and ``create_abra_file`` (imports,
not copies); ``read_evaluation_payload`` resolves the persisted deliverables
for the Step-06 handle and nothing more.

REGISTRATION. Importing this module registers the implementation under
``TIDMAD_COMPATIBILITY_ID`` (regime-A legacy resolution, child §4.2 row 1).
Until C3/C4 rewire the production call sites the registration is inert.

NOTE: no ``from __future__ import annotations`` here — under lazy annotations
ruff (UP037) would force de-quoting an annotation INSIDE the verbatim-moved
class block, breaking the C2b byte-parity guarantee. Eager annotations keep
the moved block byte-identical.
"""

import gc
import os
import random
from collections.abc import Iterable
from typing import Any, ClassVar, Literal, cast

import h5py
import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from torch.utils.data import Dataset

from execute_tools.array2h5 import create_abra_file
from execute_tools.dataset_config import DatasetProfile, resolve_dataset_profile
from execute_tools.deliverable_spec import (
    DeliverableStorage,
    default_deliverable_storage,
    derive_tidmad_deliverable_spec,
)
from execute_tools.task_data_path import (
    TIDMAD_COMPATIBILITY_ID,
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    ValidationScopeError,
    register_task_data_path,
)


def _h5_dataset(f: h5py.File, *path: str) -> h5py.Dataset:
    """Type-only helper: walk an HDF5 path and narrow the final node to Dataset.

    Per-module copy, mirroring the identical shims in
    ``train_engine_sandbox.py``, ``inference_single.py`` and
    ``scoring_utils.py`` (the established per-module pattern — a shared import
    from the engine would recreate the cycle the C2b move exists to avoid).
    """
    node: Any = f
    for k in path:
        node = node[k]
    return cast(h5py.Dataset, node)


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
        profile: DatasetProfile | None = None,
        max_samples: int | None = None,
        file_family: Literal["training", "validation"] = "training",
    ):
        """
        Args:
            data_dir:       Directory containing ``abra_training_XXXX.h5``.
            sample_set:     ``{file_index: [segment_indices]}`` — the data scope.
            seg_size:       ML segmentation size (e.g. 10000).
            train_portion:  Fraction of each file's segments to use. When None
                            or 1.0, all segments in the scope are loaded.
            rng:            Random instance for reproducible subsampling.
            max_samples:    VALIDATION POSTURE ONLY. Absolute ceiling on the ML
                            segments this epoch may contain. ``None`` (every
                            production campaign) loads the full selection.
            file_family:    Which file family of the Dataset Profile the
                            indices address — ``"training"`` (default; the
                            pre-07a behaviour, byte-for-byte) or
                            ``"validation"`` (Step 07a: the R3 validation pass
                            reads the eval SampleSet from the VALIDATION
                            family through ``DatasetConfig.validation_file_name``).
                            The family is the ONLY thing that changes; the
                            geometry, subsampling and row layout are shared.

        **Why an absolute ceiling exists beside ``train_portion``.** A
        fraction cannot bound the epoch, because what it is a fraction OF
        is not harness-owned: ``ml_segs_per_psd`` is
        ``psd_segment_length // seg_size`` and ``seg_size`` comes from the
        planner's model config, so 1 % of the scope at ``seg_size=1000``
        is ten times the samples it is at ``seg_size=10000``. During
        Step 03 a 1 %-portion plan resolved to 12,500 optimizer steps.

        Enforced by reading LESS, not by stopping later: files stop being
        opened once the budget is met, and the concatenated arrays are cut
        to exactly ``max_samples``. Both the HDF5 reads and the optimizer
        steps shrink, so the epoch is small rather than merely truncated —
        the whole point of bounding before execution instead of killing
        during it.
        """
        if rng is None:
            rng = random.Random()

        # Regime-A when no profile is supplied (§5c).
        self.profile = profile or resolve_dataset_profile()
        dataset = self.profile.dataset
        channels = self.profile.channels
        enc = self.profile.encoding
        psd_len = dataset.psd_segment_length
        ml_segs_per_psd = psd_len // seg_size
        all_ch1, all_ch2 = [], []
        # Row span each file occupies in the concatenated arrays, recorded as
        # the rows are appended. Sequential ordering needs to address one
        # file's rows without re-deriving the layout — and re-deriving it
        # would be wrong anyway, since a missing file is skipped below and
        # contributes no rows at all.
        self.file_row_ranges: dict[int, tuple[int, int]] = {}
        rows_so_far = 0
        #: PSD segments actually READ from disk. The envelope's claim is
        #: that it avoids work rather than discarding it, and the row
        #: count alone cannot show that — the post-hoc cut leaves the same
        #: length whether one PSD segment was read or a hundred were.
        self.psd_segments_read = 0

        for file_key in sorted(sample_set.keys(), key=int):
            if max_samples is not None and rows_so_far >= max_samples:
                break
            file_index = int(file_key)
            file_name = (
                dataset.training_file_name(file_index)
                if file_family == "training"
                else dataset.validation_file_name(file_index)
            )
            file_path = os.path.join(data_dir, file_name)
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

            if max_samples is not None:
                # Stop READING once the budget is met. Ceiling division, so
                # the last PSD needed to reach the cap is still read and the
                # exact cut happens on the concatenated rows below.
                needed = max_samples - rows_so_far
                segments = segments[: -(-needed // ml_segs_per_psd)]

            with h5py.File(file_path, "r") as f:
                ch1 = _h5_dataset(f, "timeseries", channels.input_channel, "timeseries")
                ch2 = _h5_dataset(f, "timeseries", channels.target_channel, "timeseries")
                for psd_idx in segments:
                    start = psd_idx * psd_len
                    end = start + psd_len
                    all_ch1.append(
                        np.array(ch1[start:end], dtype=enc.storage_dtype).reshape(
                            ml_segs_per_psd, seg_size
                        )
                    )
                    all_ch2.append(
                        np.array(ch2[start:end], dtype=enc.storage_dtype).reshape(
                            ml_segs_per_psd, seg_size
                        )
                    )

            self.psd_segments_read += len(segments)
            file_rows = len(segments) * ml_segs_per_psd
            if file_rows:
                self.file_row_ranges[file_index] = (rows_so_far, rows_so_far + file_rows)
                rows_so_far += file_rows

            gc.collect()

        self.inputs = (
            np.concatenate(all_ch1, axis=0)
            if all_ch1
            else np.empty((0, seg_size), dtype=enc.storage_dtype)
        )
        self.targets = (
            np.concatenate(all_ch2, axis=0)
            if all_ch2
            else np.empty((0, seg_size), dtype=enc.storage_dtype)
        )

        if max_samples is not None and len(self.inputs) > max_samples:
            self.inputs = self.inputs[:max_samples]
            self.targets = self.targets[:max_samples]
            # Sequential ordering addresses rows through these ranges, so a
            # range extending past the cut would index rows that no longer
            # exist. Clip the straddling file and drop any that start beyond
            # the cut (a file loop can only ever leave one of each).
            self.file_row_ranges = {
                idx: (start, min(end, max_samples))
                for idx, (start, end) in self.file_row_ranges.items()
                if start < max_samples
            }

    def __len__(self):
        return len(self.inputs)

    def __getitem__(self, idx):
        enc = self.profile.encoding
        return (
            self.inputs[idx].astype(enc.compute_dtype) + enc.value_offset,
            self.targets[idx].astype(enc.compute_dtype) + enc.value_offset,
        )


def is_complete_trial_output(
    path: str, expected_samples: int, storage: DeliverableStorage | None = None
) -> bool:
    """Return whether an attempt-scoped trial HDF5 is safe to reuse.

    A CUDA/host failure can leave earlier files from the same inference
    subprocess fully flushed while later files are absent or incomplete.
    Reuse is deliberately opt-in and requires both channels to be readable
    vectors of the exact expected length in the persisted storage dtype.

    Step 05c — this is a READER of the deliverable and it restated both facts
    the producer writes: the two channel-group names and the storage dtype.
    Left inlined, a task whose profile named different channels would have had
    every output declared incomplete and silently re-inferred. ``storage``
    defaults to the shipped representation, so a caller predating 05c is
    unaffected.

    D14-1 C4: moved verbatim from ``inference_single`` (which re-exports it) —
    a deliverable READER belongs with the deliverable codec.
    """
    resolved = storage if storage is not None else default_deliverable_storage()
    try:
        with h5py.File(path, "r") as handle:
            channel1 = _h5_dataset(handle, "timeseries", resolved.input_channel_group, "timeseries")
            channel2 = _h5_dataset(
                handle, "timeseries", resolved.target_channel_group, "timeseries"
            )
            expected_shape = (expected_samples,)
            expected_dtype = np.dtype(resolved.storage_dtype)
            if (
                channel1.shape != expected_shape
                or channel2.shape != expected_shape
                or channel1.dtype != expected_dtype
                or channel2.dtype != expected_dtype
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


class TidmadScope(BaseModel):
    """TIDMAD's opaque ``scope`` (child §3: scope is task-owned vocabulary).

    Carries exactly what the two engine construction sites pass beyond the
    framework-level ``*Params`` knobs: the DataScope-validated sample set
    (``{file_index: [psd_segment_indices]}``), the planner's ML segmentation
    size, and the dataset-profile identity. ``profile=None`` preserves the
    class's own regime-A fallback (``resolve_dataset_profile()``).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    sample_set: dict
    seg_size: int = Field(ge=1)
    profile: DatasetProfile | None = None


class TidmadTaskDataPath:
    """The registered TIDMAD implementation of the four-method seam.

    ``training_dataset`` / ``validation_dataset`` construct the (moved)
    ``TIDMADEpochDataset`` exactly as the engine call sites do today —
    parity with the pre-relocation manifest is asserted per grid cell.
    ``write_deliverable`` / ``read_evaluation_payload`` delegate to the
    deliverable-spec authorities (naming + storage) and ``create_abra_file``.
    """

    task_data_path_id: ClassVar[str] = TIDMAD_COMPATIBILITY_ID

    @staticmethod
    def _scope(scope: object) -> TidmadScope:
        if not isinstance(scope, TidmadScope):
            raise TypeError(
                "TIDMAD data path requires a TidmadScope, got "
                f"{type(scope).__name__} — the binding and the scope object "
                "must come from the same task."
            )
        return scope

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset[Any]:
        s = self._scope(scope)
        # The caller's freeze-subsample choice is already folded into
        # ``epoch_seed`` (child §3); a None seed preserves the class's own
        # unseeded default.
        rng = random.Random(params.epoch_seed) if params.epoch_seed is not None else None
        return TIDMADEpochDataset(
            data_dir=params.data_dir,
            sample_set=s.sample_set,
            seg_size=s.seg_size,
            train_portion=params.train_portion,
            rng=rng,
            profile=s.profile,
            max_samples=params.max_samples,
        )

    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset[Any]:
        """Materialize the validation scope EXACTLY, failing closed.

        The exact-materialization check relocated verbatim from the engine's
        R3 pass (D14-1 C3; same ``ValidationScopeError``, same message, same
        trigger conditions — pinned by the 07a suite, which passes UNCHANGED).
        The requested side is pure arithmetic over the declared scope —
        identical to the engine preflight's formula — so a disk that changed
        mid-run surfaces as materialized ≠ requested, exactly as before.
        """
        s = self._scope(scope)
        ds = TIDMADEpochDataset(
            data_dir=params.data_dir,
            sample_set=s.sample_set,
            seg_size=s.seg_size,
            train_portion=None,
            rng=None,
            profile=s.profile,
            file_family="validation",
        )
        profile = s.profile or resolve_dataset_profile()
        ml_segs_per_psd = profile.dataset.psd_segment_length // s.seg_size
        per_file_requested = {
            int(k): len(segments) * ml_segs_per_psd for k, segments in s.sample_set.items()
        }
        requested_rows = sum(per_file_requested.values())
        materialized = len(ds)
        per_file_materialized = {
            idx: end - start for idx, (start, end) in ds.file_row_ranges.items()
        }
        if materialized != requested_rows or per_file_materialized != per_file_requested:
            raise ValidationScopeError(
                f"validation scope materialized {materialized} ML rows "
                f"({per_file_materialized!r}) but {requested_rows} were requested "
                f"({per_file_requested!r}) — the declared scope must materialize exactly."
            )
        return ds

    def write_deliverable(
        self,
        outputs: Iterable[tuple[int, np.ndarray, np.ndarray]],
        request: DeliverableWriteRequest,
    ) -> None:
        """Persist ``(file_index, denoised, injected)`` items as ABRA files.

        Byte-identical delegation to the two pre-relocation writer sites
        (``inference_single.py:824,983``): name from the naming authority,
        remove a stale file first, flatten + storage-dtype cast, and
        ``create_abra_file(..., indexed=False, storage=spec.storage)``.
        """
        profile = resolve_dataset_profile()
        spec = derive_tidmad_deliverable_spec(profile)
        storage_np = np.dtype(spec.storage.storage_dtype)
        for file_index, denoised, injected in outputs:
            out_name = os.path.join(
                request.output_dir,
                spec.naming.name(
                    model_type=request.model_type,
                    run_name=request.run_name,
                    exp_id=request.exp_id,
                    file_index=file_index,
                ),
            )
            if os.path.exists(out_name):
                os.remove(out_name)
            create_abra_file(
                out_name,
                denoised.flatten().astype(storage_np),
                injected.flatten().astype(storage_np),
                indexed=False,
                storage=spec.storage,
            )

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        """Resolve this run/experiment's persisted deliverables.

        Returns ``{file_index: absolute_path}`` for every file in
        ``deliverable_dir`` whose name round-trips EXACTLY through the naming
        authority for this (model_type, run_name, exp_id) — path resolution
        only; the Step-06 authority owns everything downstream. A missing
        directory yields ``{}`` (zero deliverables): absence is DATA for the
        Step-06 scoreability contract, which owns the structured refusal —
        never an infrastructure traceback here.
        """
        profile = resolve_dataset_profile()
        spec = derive_tidmad_deliverable_spec(profile)
        payload: dict[int, str] = {}
        if not os.path.isdir(request.deliverable_dir):
            return payload
        for entry in sorted(os.listdir(request.deliverable_dir)):
            file_index = spec.naming.file_index_of(entry)
            if file_index is None:
                continue
            expected = spec.naming.name(
                model_type=request.model_type,
                run_name=request.run_name,
                exp_id=request.exp_id,
                file_index=file_index,
            )
            if entry != expected:
                continue
            payload[file_index] = os.path.join(request.deliverable_dir, entry)
        return payload


register_task_data_path(TidmadTaskDataPath())
