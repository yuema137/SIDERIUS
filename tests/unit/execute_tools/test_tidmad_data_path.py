"""TIDMAD TaskDataPath delegation parity (D14-1 C2b).

The relocated implementation's SEAM surface — ``TidmadTaskDataPath``'s four
methods — must reproduce the values pinned by the committed pre-relocation
manifest. Expected values are READ from that manifest (child §6 correction 3:
never recomputed at runtime); only the INPUTS are regenerated from the
recorded recipe. ``test_d14_tidmad_parity.py`` guards the manifest's own
immutability and the direct-construction path; this module guards the
delegation layer C3/C4 will wire the production call sites to.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from execute_tools.dataset_config import bind_dataset_profile
from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec
from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
)
from execute_tools.tidmad_data_path import TidmadScope, TidmadTaskDataPath
from tests.helpers.d14_tidmad_parity import (
    EPOCH_SEEDS,
    TRAIN_PORTIONS,
    _dataset_stream_sha,
    load_manifest,
)
from tests.helpers.two_family_profile import write_two_family_fixture


@pytest.fixture(scope="module")
def fixture_and_manifest(tmp_path_factory):
    fx = write_two_family_fixture(tmp_path_factory.mktemp("d14_c2b"))
    return fx, load_manifest()["evidence"]


class TestTrainingDelegationParity:
    def test_training_dataset_reproduces_every_manifest_grid_cell(self, fixture_and_manifest):
        """The seam reconstructs ``random.Random(epoch_seed)`` internally; if
        that reconstruction (or any delegated kwarg) drifted from the engine
        call site, the iteration-order stream hash of the affected cell
        changes and this comparison fails against the frozen manifest."""
        fx, evidence = fixture_and_manifest
        impl = TidmadTaskDataPath()
        scope = TidmadScope(
            sample_set=fx.full_sample_set(), seg_size=fx.seg_size, profile=fx.profile
        )
        with bind_dataset_profile(fx.profile):
            for seed in EPOCH_SEEDS:
                for portion in TRAIN_PORTIONS:
                    ds = impl.training_dataset(
                        scope,
                        EpochSamplingParams(
                            data_dir=fx.data_dir, epoch_seed=seed, train_portion=portion
                        ),
                    )
                    expected = evidence["training_streams"][f"seed={seed}|portion={portion}"]
                    assert len(ds) == expected["rows"], (seed, portion)
                    assert _dataset_stream_sha(ds) == expected["stream_sha256"], (seed, portion)


class TestValidationDelegationParity:
    def test_validation_dataset_reproduces_manifest_materialization(self, fixture_and_manifest):
        fx, evidence = fixture_and_manifest
        impl = TidmadTaskDataPath()
        scope = TidmadScope(
            sample_set=fx.full_sample_set(), seg_size=fx.seg_size, profile=fx.profile
        )
        with bind_dataset_profile(fx.profile):
            ds = impl.validation_dataset(scope, EvalMaterializationParams(data_dir=fx.data_dir))
        expected = evidence["validation"]
        assert len(ds) == expected["rows"]
        ranges = {str(k): list(v) for k, v in sorted(ds.file_row_ranges.items())}
        assert ranges == expected["file_row_ranges"]
        assert _dataset_stream_sha(ds) == expected["stream_sha256"]


class TestDeliverableDelegationParity:
    def test_write_deliverable_bytes_match_manifest_sha(self, fixture_and_manifest, tmp_path):
        """Inputs regenerated from the manifest's recorded recipe
        (``default_rng(1234)`` over the fixture geometry); the EXPECTED
        byte hash comes from the committed manifest. A drift in dtype cast,
        flattening, storage spec or writer delegation changes the bytes."""
        fx, evidence = fixture_and_manifest
        impl = TidmadTaskDataPath()
        with bind_dataset_profile(fx.profile):
            spec = derive_tidmad_deliverable_spec(fx.profile)
            storage_np = np.dtype(spec.storage.storage_dtype)
            rows = fx.segments_per_file * fx.ml_segs_per_psd
            n = max(rows, 1) * fx.seg_size
            rng = np.random.default_rng(1234)
            denoised = rng.integers(0, 255, size=n, dtype=np.uint8).astype(storage_np)
            injected = rng.integers(0, 255, size=n, dtype=np.uint8).astype(storage_np)

            request = DeliverableWriteRequest(
                output_dir=str(tmp_path), exp_id="e7", run_name="d14c2b", model_type="wavenet"
            )
            impl.write_deliverable([(3, denoised, injected)], request)

            expected_name = spec.naming.name(
                model_type="wavenet", run_name="d14c2b", exp_id="e7", file_index=3
            )
            written = tmp_path / expected_name
            assert written.exists(), "writer must use the naming authority"
            actual_sha = hashlib.sha256(written.read_bytes()).hexdigest()
            assert actual_sha == evidence["deliverable"]["file_sha256"]

    def test_read_evaluation_payload_resolves_exactly_this_runs_files(
        self, fixture_and_manifest, tmp_path
    ):
        fx, _ = fixture_and_manifest
        impl = TidmadTaskDataPath()
        with bind_dataset_profile(fx.profile):
            spec = derive_tidmad_deliverable_spec(fx.profile)
            storage_np = np.dtype(spec.storage.storage_dtype)
            arr = np.zeros(fx.seg_size, dtype=storage_np)
            request = DeliverableWriteRequest(
                output_dir=str(tmp_path), exp_id="e7", run_name="d14c2b", model_type="wavenet"
            )
            impl.write_deliverable([(0, arr, arr), (4, arr, arr)], request)
            # A foreign deliverable (another exp) and an unrelated file must
            # both be excluded by the exact round-trip name match.
            foreign = spec.naming.name(
                model_type="wavenet", run_name="d14c2b", exp_id="OTHER", file_index=1
            )
            (tmp_path / foreign).write_bytes(b"x")
            (tmp_path / "notes.txt").write_bytes(b"x")

            payload = impl.read_evaluation_payload(
                EvaluationReadRequest(
                    deliverable_dir=str(tmp_path),
                    exp_id="e7",
                    run_name="d14c2b",
                    model_type="wavenet",
                )
            )
        assert isinstance(payload, dict)
        assert sorted(payload) == [0, 4]
        assert all(Path(p).exists() for p in payload.values())


class TestScopeFailClosed:
    def test_foreign_scope_object_is_refused(self):
        impl = TidmadTaskDataPath()
        with pytest.raises(TypeError, match="TidmadScope"):
            impl.training_dataset(["not", "tidmad"], EpochSamplingParams(data_dir="/unused"))
