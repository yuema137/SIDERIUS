"""Oxford-IIIT Pet EXECUTION-level artifacts (D14-2 C2).

Derives, from the FROZEN identity manifests and the machine-local images:

* ``data/manifests/execution.json`` — the frozen decode/resize/crop/normalize
  rule in machine-readable form plus per-item float32-tensor SHA-256 probes
  (the FIRST train image of each of the 37 classes — class-covering, small).
  The transform implementation is `execute_tools.pets_data_path` — the ONE
  authority the runtime reader shares; the committed hashes are what keep a
  single authority honest (drift fails the pin, it is never regenerated
  away).
* ``data/manifests/gate2_{train,validation,final}.csv`` — the NESTED Gate
  subset manifests (§17.0.1 bounds): the first N per class IN THE COMMITTED
  MANIFEST ORDER (train 10 / validation 2 / final 10 per class), same row
  schema as the identity manifests, strict subsets by construction.

Regenerate (identity manifests and images must already exist)::

    .venv/bin/python -m tools.example_packs.oxford_iiit_pet_execution \
        --images-root /home/klz/Data/OXFORD_IIIT_PET/images
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from execute_tools.pets_data_path import (
    CROP_SIZE,
    NUM_CLASSES,
    RESIZE_SHORTER_SIDE,
    transform_probe_sha256,
)
from tools.example_packs._common import repo_root, write_json, write_text
from tools.example_packs.oxford_iiit_pet import (
    MANIFEST_RELDIR,
    PACK_DIRNAME,
    ManifestRow,
    parse_manifest_csv,
    render_manifest_csv,
)

EXECUTION_MANIFEST_NAME = "execution.json"
#: Gate-subset sizing: first N per class, in the committed manifest order.
GATE_SUBSET_PER_CLASS: dict[str, int] = {"train": 10, "validation": 2, "final": 10}


def first_n_per_class(rows: tuple[ManifestRow, ...], n: int) -> tuple[ManifestRow, ...]:
    """Deterministic nested subset: the first ``n`` rows of every class in
    the order the committed manifest lists them (already sorted by
    ``(class_index, image_id)`` — regeneration-stable)."""
    taken: dict[int, int] = defaultdict(int)
    out: list[ManifestRow] = []
    for row in rows:
        if taken[row.class_index] < n:
            out.append(row)
            taken[row.class_index] += 1
    return tuple(out)


def probe_rows(train_rows: tuple[ManifestRow, ...]) -> tuple[ManifestRow, ...]:
    """The 37 probe items: the first train image of every class."""
    return first_n_per_class(train_rows, 1)


def build_execution_manifest(images_root: Path, train_rows: tuple[ManifestRow, ...]) -> dict:
    probes = {
        row.image_id: transform_probe_sha256(images_root / f"{row.image_id}.jpg")
        for row in probe_rows(train_rows)
    }
    assert len(probes) == NUM_CLASSES
    return {
        "schema_version": 1,
        "transform": {
            "decode": "PIL.convert('RGB'); no EXIF transpose",
            "interpolation": "bilinear",
            "resize_shorter": RESIZE_SHORTER_SIDE,
            "crop": [CROP_SIZE, CROP_SIZE],
            "normalize": "div255",
            "layout": "CHW-RGB",
            "dtype": "float32",
            "authority": "execute_tools/pets_data_path.py::decode_and_transform",
        },
        "probe_hash": "sha256(tensor.numpy().tobytes()), float32 CHW contiguous",
        "probes": probes,
    }


def load_identity_rows(pack_root: Path) -> dict[str, tuple[ManifestRow, ...]]:
    manifest_dir = pack_root / MANIFEST_RELDIR
    return {
        scope: parse_manifest_csv((manifest_dir / f"{scope}.csv").read_text(encoding="utf-8"))
        for scope in ("train", "validation", "final")
    }


def write_execution_artifacts(pack_root: Path, images_root: Path) -> dict[str, Any]:
    rows = load_identity_rows(pack_root)
    manifest_dir = pack_root / MANIFEST_RELDIR
    execution = build_execution_manifest(images_root, rows["train"])
    write_json(manifest_dir / EXECUTION_MANIFEST_NAME, execution)
    written: dict[str, Any] = {EXECUTION_MANIFEST_NAME: execution}
    for scope, n in GATE_SUBSET_PER_CLASS.items():
        subset = first_n_per_class(rows[scope], n)
        name = f"gate2_{scope}.csv"
        write_text(manifest_dir / name, render_manifest_csv(subset))
        written[name] = subset
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--images-root",
        type=Path,
        required=True,
        help="machine-local extracted images directory (outside the tree)",
    )
    parser.add_argument("--root", type=Path, default=None, help="pack root (default: examples/…)")
    args = parser.parse_args(argv)
    pack_root = args.root or (repo_root() / "examples" / PACK_DIRNAME)
    written = write_execution_artifacts(pack_root, args.images_root.resolve())
    for name in written:
        print(f"wrote {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
