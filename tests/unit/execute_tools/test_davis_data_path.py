"""DAVIS TaskDataPath implementation (D14-3 C4).

Synthetic frames make the reader/codec cases portable; the probe-parity case
uses the machine-local dataset and skips with a declared reason elsewhere.
What only this suite catches: a reader that tolerates a missing frame mid
window, an invented subsampling rule, an npz codec that loses clip identity
or dtype, and a scope filter that could hand one scope's clips to another.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

from execute_tools.davis_data_path import (
    CONTEXT_FRAMES,
    DAVIS_TASK_DATA_PATH_ID,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    FUTURE_FRAMES,
    WINDOW_FRAMES,
    DavisClip,
    DavisScope,
    DavisTaskDataPath,
    clip_key,
    deliverable_name,
    load_davis_clips,
    truth_windows,
)
from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    TaskBindingContext,
    ValidationScopeError,
    resolve_task_data_path,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFESTS = REPO_ROOT / "examples" / "davis_future_prediction" / "data" / "manifests"


def _sequence(root: Path, name: str, frames: int) -> None:
    seq = root / "DAVIS" / "JPEGImages" / "480p" / name
    seq.mkdir(parents=True, exist_ok=True)
    for i in range(frames):
        Image.new("RGB", (854, 480), (i * 7 % 255, 40, 80)).save(seq / f"{i:05d}.jpg", "JPEG")


def _scope(names_and_starts) -> DavisScope:
    return DavisScope(
        rows=tuple(DavisClip(sequence_name=n, start_frame=s) for n, s in names_and_starts)
    )


class TestResolutionAndScope:
    def test_explicit_binding_resolves_the_registered_davis_implementation(self):
        impl = resolve_task_data_path(TaskBindingContext(task_data_path_id=DAVIS_TASK_DATA_PATH_ID))
        assert isinstance(impl, DavisTaskDataPath)

    def test_foreign_scope_object_is_refused(self):
        with pytest.raises(TypeError, match="DavisScope"):
            DavisTaskDataPath().training_dataset(
                ["not", "davis"], EpochSamplingParams(data_dir="/unused")
            )


class TestDatasets:
    def test_yields_context_target_pairs_of_the_frozen_shapes(self, tmp_path):
        _sequence(tmp_path, "alpha", WINDOW_FRAMES + 3)
        ds = DavisTaskDataPath().training_dataset(
            _scope([("alpha", 0), ("alpha", 3)]), EpochSamplingParams(data_dir=str(tmp_path))
        )
        assert len(ds) == 2
        context, target = ds[0]
        assert context.shape == (3, CONTEXT_FRAMES, FRAME_HEIGHT, FRAME_WIDTH)
        assert target.shape == (3, FUTURE_FRAMES, FRAME_HEIGHT, FRAME_WIDTH)
        assert context.dtype == torch.float32 and target.dtype == torch.float32
        # Amendment 1: input and target are DIFFERENT shapes.
        assert context.shape != target.shape

    def test_a_clip_whose_window_runs_past_the_last_frame_fails_closed(self, tmp_path):
        _sequence(tmp_path, "alpha", WINDOW_FRAMES)  # only start 0 is legal
        with pytest.raises(ValidationScopeError, match="materialize exactly"):
            DavisTaskDataPath().validation_dataset(
                _scope([("alpha", 0), ("alpha", 1)]),
                EvalMaterializationParams(data_dir=str(tmp_path)),
            )

    def test_train_portion_below_one_is_refused_not_invented(self, tmp_path):
        _sequence(tmp_path, "alpha", WINDOW_FRAMES)
        with pytest.raises(ValueError, match="refused rather than invented"):
            DavisTaskDataPath().training_dataset(
                _scope([("alpha", 0)]),
                EpochSamplingParams(data_dir=str(tmp_path), train_portion=0.25),
            )

    def test_max_samples_is_a_deterministic_prefix(self, tmp_path):
        _sequence(tmp_path, "alpha", WINDOW_FRAMES + 5)
        ds = DavisTaskDataPath().training_dataset(
            _scope([("alpha", 0), ("alpha", 2), ("alpha", 5)]),
            EpochSamplingParams(data_dir=str(tmp_path), max_samples=2),
        )
        assert len(ds) == 2


class TestDeliverableCodec:
    def test_npz_round_trip_preserves_clip_identity_and_dtype(self, tmp_path):
        impl = DavisTaskDataPath()
        request = DeliverableWriteRequest(
            output_dir=str(tmp_path),
            exp_id="e1",
            run_name="r1",
            model_type="davis_reference_predictor",
        )
        clip_a = DavisClip(sequence_name="alpha", start_frame=0)
        clip_b = DavisClip(sequence_name="beta", start_frame=7)
        pred_a = torch.rand(3, FUTURE_FRAMES, FRAME_HEIGHT, FRAME_WIDTH)
        pred_b = np.zeros((3, FUTURE_FRAMES, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.float64)
        impl.write_deliverable([(clip_a, pred_a), (clip_b, pred_b)], request)

        payload = impl.read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=str(tmp_path),
                exp_id="e1",
                run_name="r1",
                model_type="davis_reference_predictor",
            )
        )
        assert set(payload) == {clip_key(clip_a), clip_key(clip_b)}
        assert payload[clip_key(clip_a)].dtype == np.float32  # cast at the codec
        assert payload[clip_key(clip_b)].dtype == np.float32  # float64 input narrowed
        np.testing.assert_allclose(payload[clip_key(clip_a)], pred_a.numpy())
        assert payload[clip_key(clip_a)].shape == (3, FUTURE_FRAMES, FRAME_HEIGHT, FRAME_WIDTH)

    def test_absent_deliverable_reads_as_empty_for_scoreability(self, tmp_path):
        payload = DavisTaskDataPath().read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=str(tmp_path), exp_id="e", run_name="r", model_type="m"
            )
        )
        assert payload == {}

    def test_the_name_rule_is_one_rule_both_directions(self, tmp_path):
        write = DeliverableWriteRequest(
            output_dir=str(tmp_path), exp_id="e", run_name="r", model_type="m"
        )
        read = EvaluationReadRequest(
            deliverable_dir=str(tmp_path), exp_id="e", run_name="r", model_type="m"
        )
        assert deliverable_name(write) == deliverable_name(read)


class TestScopeFilterIsTheLeakageGuard:
    def test_a_scope_request_never_returns_another_scopes_clips(self):
        """Reader half of the guard: the committed manifest carries the
        scope on every row, so a caller asking for 'validation' can never be
        handed a train or final clip — even though all 600 live in one
        file."""
        train_names = {
            c.sequence_name for c in load_davis_clips(MANIFESTS / "clips.csv", scope="train")
        }
        val_names = {
            c.sequence_name for c in load_davis_clips(MANIFESTS / "clips.csv", scope="validation")
        }
        final_names = {
            c.sequence_name for c in load_davis_clips(MANIFESTS / "clips.csv", scope="final")
        }
        assert train_names & val_names == set()
        assert train_names & final_names == set()
        assert val_names & final_names == set()
        assert len(train_names) == 60 and len(val_names) == 15 and len(final_names) == 15


class TestRealProbeParityThroughTheSeam:
    def test_probe_hashes_through_the_dataset(self):
        root = Path(os.environ.get("SIDERIUS_DAVIS_DATA_DIR", "/home/klz/Data/DAVIS_2017"))
        if not (root / "DAVIS" / "JPEGImages" / "480p").is_dir():
            pytest.skip("real DAVIS frames not present (set SIDERIUS_DAVIS_DATA_DIR)")
        import hashlib

        probes = json.loads((MANIFESTS / "execution.json").read_text(encoding="utf-8"))["probes"]
        items = list(probes.items())[:2]
        rows = []
        for key, _expected in items:
            name, start = key.rsplit(":", 1)
            rows.append(DavisClip(sequence_name=name, start_frame=int(start)))
        ds = DavisTaskDataPath().training_dataset(
            DavisScope(rows=tuple(rows)), EpochSamplingParams(data_dir=str(root))
        )
        for idx, (_key, expected) in enumerate(items):
            context, target = ds[idx]
            digest = hashlib.sha256()
            digest.update(context.numpy().tobytes())
            digest.update(target.numpy().tobytes())
            assert digest.hexdigest() == expected

    def test_truth_windows_decode_through_the_same_authority(self):
        root = Path(os.environ.get("SIDERIUS_DAVIS_DATA_DIR", "/home/klz/Data/DAVIS_2017"))
        if not (root / "DAVIS" / "JPEGImages" / "480p").is_dir():
            pytest.skip("real DAVIS frames not present (set SIDERIUS_DAVIS_DATA_DIR)")
        clips = load_davis_clips(MANIFESTS / "gate2_final.csv")[:2]
        truth = truth_windows(root, clips)
        assert set(truth) == {clip_key(c) for c in clips}
        ds = DavisTaskDataPath().validation_dataset(
            DavisScope(rows=tuple(clips)), EvalMaterializationParams(data_dir=str(root))
        )
        for idx, clip in enumerate(clips):
            _context, target = ds[idx]
            np.testing.assert_array_equal(truth[clip_key(clip)], target.numpy())
