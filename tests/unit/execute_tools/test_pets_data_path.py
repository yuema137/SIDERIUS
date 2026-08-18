"""Pets TaskDataPath implementation (D14-2 C3).

Synthetic-image tests are portable (tmp JPEGs); the probe-parity case runs
against the machine-local real dataset and SKIPS with a declared reason
elsewhere. What only this suite catches: a reader that skips a missing
manifest image instead of failing closed, an invented subsampling rule on a
frozen task, a deliverable codec that loses ordering/round-trip identity,
and a binding that resolves anything but the registered Pets implementation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import torch
from PIL import Image

from execute_tools.pets_data_path import (
    PETS_TASK_DATA_PATH_ID,
    PetsItem,
    PetsScope,
    PetsTaskDataPath,
    deliverable_name,
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
MANIFESTS = REPO_ROOT / "examples" / "oxford_iiit_pet" / "data" / "manifests"


def _write_images(root: Path, ids: list[str]) -> None:
    for i, image_id in enumerate(ids):
        Image.new("RGB", (200 + i, 180), (10 * i % 255, 20, 30)).save(
            root / f"{image_id}.jpg", "JPEG"
        )


def _scope(ids: list[str]) -> PetsScope:
    return PetsScope(
        rows=tuple(PetsItem(image_id=i, class_index=n % 37) for n, i in enumerate(ids))
    )


class TestResolutionAndScope:
    def test_explicit_binding_resolves_the_registered_pets_implementation(self):
        impl = resolve_task_data_path(TaskBindingContext(task_data_path_id=PETS_TASK_DATA_PATH_ID))
        assert isinstance(impl, PetsTaskDataPath)

    def test_foreign_scope_object_is_refused(self):
        with pytest.raises(TypeError, match="PetsScope"):
            PetsTaskDataPath().training_dataset(
                {"0": [1, 2]}, EpochSamplingParams(data_dir="/unused")
            )


class TestDatasets:
    def test_yields_amendment1_pairs_and_manifest_order(self, tmp_path):
        _write_images(tmp_path, ["b_2", "a_1"])
        ds = PetsTaskDataPath().training_dataset(
            _scope(["b_2", "a_1"]), EpochSamplingParams(data_dir=str(tmp_path))
        )
        assert len(ds) == 2
        tensor, target = ds[0]
        assert tensor.shape == (3, 144, 144) and tensor.dtype == torch.float32
        assert isinstance(target, int) and not isinstance(target, bool)
        # Scope order IS dataset order (no hidden resort).
        assert ds[0][1] == 0 and ds[1][1] == 1

    def test_train_portion_below_one_is_refused_not_invented(self, tmp_path):
        _write_images(tmp_path, ["x_1"])
        with pytest.raises(ValueError, match="refused rather than invented"):
            PetsTaskDataPath().training_dataset(
                _scope(["x_1"]), EpochSamplingParams(data_dir=str(tmp_path), train_portion=0.5)
            )

    def test_max_samples_is_a_deterministic_prefix(self, tmp_path):
        ids = ["a_1", "b_2", "c_3", "d_4"]
        _write_images(tmp_path, ids)
        ds = PetsTaskDataPath().training_dataset(
            _scope(ids), EpochSamplingParams(data_dir=str(tmp_path), max_samples=2)
        )
        assert len(ds) == 2 and ds[1][1] == 1  # first two rows, order kept

    def test_missing_image_fails_closed_naming_the_id(self, tmp_path):
        _write_images(tmp_path, ["present_1"])
        with pytest.raises(ValidationScopeError, match="absent_9"):
            PetsTaskDataPath().validation_dataset(
                _scope(["present_1", "absent_9"]),
                EvalMaterializationParams(data_dir=str(tmp_path)),
            )


class TestDeliverableCodec:
    def test_round_trip_sorted_and_exact(self, tmp_path):
        impl = PetsTaskDataPath()
        request = DeliverableWriteRequest(
            output_dir=str(tmp_path), exp_id="e1", run_name="r1", model_type="pets_reference_cnn"
        )
        impl.write_deliverable([("zeta_9", 36), ("alpha_1", 0)], request)
        name = deliverable_name(request)
        text = (tmp_path / name).read_text(encoding="utf-8")
        # Byte-deterministic: header + rows sorted by image_id.
        assert text == "image_id,predicted_class_index\nalpha_1,0\nzeta_9,36\n"
        payload = impl.read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=str(tmp_path),
                exp_id="e1",
                run_name="r1",
                model_type="pets_reference_cnn",
            )
        )
        assert payload == {"alpha_1": 0, "zeta_9": 36}

    def test_absent_deliverable_reads_as_empty_for_scoreability(self, tmp_path):
        payload = PetsTaskDataPath().read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=str(tmp_path), exp_id="e", run_name="r", model_type="m"
            )
        )
        assert payload == {}

    def test_foreign_csv_is_refused_not_misread(self, tmp_path):
        request = EvaluationReadRequest(
            deliverable_dir=str(tmp_path), exp_id="e", run_name="r", model_type="m"
        )
        (tmp_path / deliverable_name(request)).write_text("some,other,header\n", encoding="utf-8")
        with pytest.raises(ValueError, match="header"):
            PetsTaskDataPath().read_evaluation_payload(request)


class TestRealProbeParityThroughTheSeam:
    """The committed execution.json probes must reproduce THROUGH
    ``training_dataset`` — the reader path, not just the bare transform."""

    def test_probe_hashes_through_the_dataset(self):
        root = Path(
            os.environ.get("SIDERIUS_PETS_DATA_DIR", "/home/klz/Data/OXFORD_IIIT_PET/images")
        )
        if not root.is_dir():
            pytest.skip("real Pets images not present (set SIDERIUS_PETS_DATA_DIR)")
        execution = json.loads((MANIFESTS / "execution.json").read_text(encoding="utf-8"))
        items = list(execution["probes"].items())[:3]
        scope = PetsScope(rows=tuple(PetsItem(image_id=i, class_index=0) for i, _ in items))
        ds = PetsTaskDataPath().training_dataset(scope, EpochSamplingParams(data_dir=str(root)))
        for idx, (_image_id, expected) in enumerate(items):
            tensor, _ = ds[idx]
            assert hashlib.sha256(tensor.numpy().tobytes()).hexdigest() == expected


class TestProductionManifestParser:
    """`load_pets_manifest` is the PRODUCTION-owned parser (§22.23.9: the gate
    runner must not import pack tooling). Its rows must equal the tooling
    parser's on the committed manifests — one format, two sanctioned readers,
    drift caught here."""

    def test_parses_identically_to_the_tooling_parser_on_a_committed_csv(self):
        from execute_tools.pets_data_path import load_pets_manifest
        from tools.example_packs.oxford_iiit_pet import parse_manifest_csv

        path = MANIFESTS / "gate2_validation.csv"
        production = load_pets_manifest(path)
        tooling = parse_manifest_csv(path.read_text(encoding="utf-8"))
        assert [(r.image_id, r.class_index) for r in production] == [
            (r.image_id, r.class_index) for r in tooling
        ]
        assert len(production) == 74

    def test_foreign_header_is_refused(self, tmp_path):
        from execute_tools.pets_data_path import load_pets_manifest

        bad = tmp_path / "x.csv"
        bad.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        with pytest.raises(ValueError, match="header"):
            load_pets_manifest(bad)
