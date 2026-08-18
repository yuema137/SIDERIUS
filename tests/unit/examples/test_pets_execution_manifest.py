"""Pets execution manifest + gate subsets + frozen transform (D14-2 C2).

Three evidence families, each catching what nothing else does:

* PIN — the committed artifacts are byte-immutable for the life of the PR
  (a silent regeneration is the failure class; the pin makes it loud).
* STRUCTURE — the gate subsets are strict, class-covering, size-exact nested
  subsets of the FROZEN identity manifests (deterministic first-N-per-class
  in committed order).
* TRANSFORM — the frozen decode→resize→crop→/255 rule behaves as declared on
  SYNTHETIC in-memory images (portable, no dataset), and — when this machine
  has the real images (`SIDERIUS_PETS_DATA_DIR`) — the committed probe
  hashes reproduce IN A SECOND PROCESS (the PYTHONHASHSEED lesson: same
  item → same tensor bytes, twice, two processes).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import torch
from PIL import Image

from execute_tools.pets_data_path import (
    CROP_SIZE,
    NUM_CLASSES,
    decode_and_transform,
    transform_probe_sha256,
)
from tools.example_packs.oxford_iiit_pet import parse_manifest_csv
from tools.example_packs.oxford_iiit_pet_execution import (
    GATE_SUBSET_PER_CLASS,
    first_n_per_class,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFESTS = REPO_ROOT / "examples" / "oxford_iiit_pet" / "data" / "manifests"

#: BYTE-IMMUTABLE pins for the life of PR D14-2 (child §2.2).
PINNED = {
    "execution.json": "b26ac8756acda9319552acb5765e6b3cff64a3b0514c29dacc301f9c9c4c5be5",
    "gate2_train.csv": "0181b10d00130be755590b1074728829ff1744e417f55dc3ab38e12f9311170a",
    "gate2_validation.csv": "2cc0f99f8619c22e79588ccdafbdd9267b3503529a401373ab30cd89c9d2096c",
    "gate2_final.csv": "f00bdbbe6d434d37bba86018e14d35875ce58083d0c361326ba9a5402d448a67",
}

#: Machine-local images root for the REAL-probe tests (declared requirement;
#: absent → those tests SKIP with the reason, never a silent fallback).
DATA_DIR_ENV = "SIDERIUS_PETS_DATA_DIR"


def _images_root() -> Path | None:
    value = os.environ.get(DATA_DIR_ENV)
    if value is None:
        default = Path("/home/klz/Data/OXFORD_IIIT_PET/images")
        return default if default.is_dir() else None
    root = Path(value)
    if not root.is_dir():
        pytest.fail(f"{DATA_DIR_ENV}={value} is set but is not a directory")
    return root


class TestPins:
    @pytest.mark.parametrize("name", sorted(PINNED))
    def test_committed_artifact_matches_pin(self, name: str) -> None:
        digest = hashlib.sha256((MANIFESTS / name).read_bytes()).hexdigest()
        assert digest == PINNED[name], f"{name} drifted from its committed pin"


class TestGateSubsets:
    @pytest.mark.parametrize("scope", sorted(GATE_SUBSET_PER_CLASS))
    def test_subset_is_nested_class_covering_and_size_exact(self, scope: str) -> None:
        parent = parse_manifest_csv((MANIFESTS / f"{scope}.csv").read_text(encoding="utf-8"))
        subset = parse_manifest_csv((MANIFESTS / f"gate2_{scope}.csv").read_text(encoding="utf-8"))
        n = GATE_SUBSET_PER_CLASS[scope]
        assert len(subset) == n * NUM_CLASSES
        parent_ids = {r.image_id for r in parent}
        assert {r.image_id for r in subset} <= parent_ids
        per_class = {c: 0 for c in range(NUM_CLASSES)}
        for r in subset:
            per_class[r.class_index] += 1
        assert set(per_class.values()) == {n}
        # Deterministic derivation: re-deriving from the parent reproduces
        # the committed subset EXACTLY (order included).
        assert first_n_per_class(parent, n) == subset


def _synthetic_jpeg(width: int, height: int, color=(200, 100, 50)) -> Image.Image:
    return Image.new("RGB", (width, height), color)


class TestFrozenTransformSynthetic:
    def test_shape_dtype_range_and_layout(self, tmp_path):
        p = tmp_path / "img.jpg"
        _synthetic_jpeg(320, 240).save(p, "JPEG")
        t = decode_and_transform(p)
        assert t.shape == (3, CROP_SIZE, CROP_SIZE) and t.dtype == torch.float32
        assert 0.0 <= float(t.min()) and float(t.max()) <= 1.0

    def test_constant_image_maps_to_value_over_255(self, tmp_path):
        p = tmp_path / "flat.png"  # PNG: lossless, so the constant survives decode
        _synthetic_jpeg(200, 300, color=(255, 0, 0)).save(p, "PNG")
        t = decode_and_transform(p)
        assert torch.allclose(t[0], torch.ones_like(t[0]))
        assert torch.allclose(t[1], torch.zeros_like(t[1]))

    def test_portrait_and_landscape_resize_arithmetic(self, tmp_path):
        # 300x200 (landscape): shorter=200 -> 160, longer -> round(300*0.8)=240.
        # The crop then removes (240-144)//2 = 48 from each side; the transform
        # must not error on either orientation and must stay 144x144.
        for w, h in ((300, 200), (200, 300), (160, 160), (145, 4000)):
            p = tmp_path / f"img_{w}x{h}.png"
            _synthetic_jpeg(w, h).save(p, "PNG")
            assert decode_and_transform(p).shape == (3, CROP_SIZE, CROP_SIZE)

    def test_missing_file_fails_closed_naming_the_path(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="materialize exactly"):
            decode_and_transform(tmp_path / "absent.jpg")

    def test_same_bytes_same_hash_twice(self, tmp_path):
        p = tmp_path / "img.jpg"
        _synthetic_jpeg(320, 240).save(p, "JPEG")
        assert transform_probe_sha256(p) == transform_probe_sha256(p)


class TestRealProbeParity:
    """Requires the machine-local dataset; skips with the declared reason."""

    @pytest.fixture()
    def images_root(self) -> Path:
        root = _images_root()
        if root is None:
            pytest.skip(f"real Pets images not present (set {DATA_DIR_ENV})")
        return root

    def test_committed_probes_reproduce_in_this_process(self, images_root):
        execution = json.loads((MANIFESTS / "execution.json").read_text(encoding="utf-8"))
        for image_id, expected in list(execution["probes"].items())[:5]:
            assert transform_probe_sha256(images_root / f"{image_id}.jpg") == expected

    def test_committed_probes_reproduce_in_a_second_process(self, images_root):
        execution = json.loads((MANIFESTS / "execution.json").read_text(encoding="utf-8"))
        image_id, expected = next(iter(execution["probes"].items()))
        code = (
            "from execute_tools.pets_data_path import transform_probe_sha256;"
            f"print(transform_probe_sha256({str(images_root / (image_id + '.jpg'))!r}))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT
        )
        assert out.returncode == 0, out.stderr[-800:]
        assert out.stdout.strip().splitlines()[-1] == expected
