"""Oxford-IIIT Pet example pack — identity manifests + L0/L1 declarations (PR0, C2).

Track B (roadmap §22.9a): 37-way pet-BREED classification from real RGB JPEG
images. This module DERIVES the pack's IDENTITY manifests from the official
annotation lists by the FROZEN rule (design §3.2) and DECLARES, through the
real schemas, what the framework can honestly represent today (design §0.3):

* ``ModelIOContract``  ``[B, 3, 144, 144] float32 → [B, 37] float32``
  (``class`` axis fixed 37 → categorical, ``class_cardinality == 37``);
* ``MetricSpec``       ``accuracy`` (higher) — the golden metric on the
  final-eval scope; ``macro_f1`` (higher) — optional terminal.
  ``log_loss`` (lower) is INTENTIONALLY not declared: the Step-06 lexical
  rule refuses loss-shaped identities (D16); the pack documents it as
  blocked and the test asserts the refusal.

Frozen identity rule (§3.2, OD-PR0-2) — no RNG, no seed; the rule IS the
provenance:

    final       = the official ``test.txt`` list, verbatim (as a set);
    train /     = per class, sort the official ``trainval.txt`` image ids
    validation    lexicographically; position i (0-based) → validation iff
                  i % 5 == 4, else train.

Manifest row: ``image_id, class_index (0-based = official class id − 1),
official_class_id, scope``. Rows are written sorted by
``(class_index, image_id)`` so regeneration is byte-deterministic.

Nothing here reads, downloads or stores an image. The ~19 MB official
``annotations.tar.gz`` is fetched to a TEMPORARY location by the operator,
its lists are handed to this module, and only the derived manifests plus
SHA-256 pins are tracked (design §0.4).

Regenerate::

    .venv/bin/python -m tools.example_packs.oxford_iiit_pet --annotations-dir /tmp/x/annotations
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.model_io_contract import AxisRole, ModelIOContract
from execute_tools.evaluation_metric import MetricSpec, PresenceScoreabilityContract
from tools.example_packs._common import repo_root, write_json, write_sha256sums, write_text
from tools.example_packs.declarations import (
    batch_axis,
    fixed_axis,
    model_io_contract,
    tensor_contract,
)

PACK_DIRNAME = "oxford_iiit_pet"
MANIFEST_RELDIR = Path("data") / "manifests"
DECLARED_RELDIR = Path("declared")

Scope = Literal["train", "validation", "final"]
SCOPES: tuple[Scope, ...] = ("train", "validation", "final")

#: The frozen §22.9a instance values this pack owns (also pinned as literals
#: in ``tests/unit/examples/test_oxford_iiit_pet_pack.py`` — never read back).
NUM_CLASSES = 37
INPUT_SHAPE = (3, 144, 144)
VALIDATION_MODULUS = 5
VALIDATION_RESIDUE = 4

MANIFEST_HEADER = "image_id,class_index,official_class_id,scope"


class ManifestRow(BaseModel):
    """One image's identity: which image, which class, which scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    image_id: str = Field(min_length=1, description="Official image id, e.g. 'Abyssinian_100'.")
    class_index: int = Field(ge=0, le=NUM_CLASSES - 1, description="0-based class index.")
    official_class_id: int = Field(ge=1, le=NUM_CLASSES, description="Official CLASS-ID 1..37.")
    scope: Scope

    def as_csv(self) -> str:
        return f"{self.image_id},{self.class_index},{self.official_class_id},{self.scope}"


class Manifests(BaseModel):
    """The three scope manifests, each sorted by ``(class_index, image_id)``."""

    model_config = ConfigDict(frozen=True)

    train: tuple[ManifestRow, ...]
    validation: tuple[ManifestRow, ...]
    final: tuple[ManifestRow, ...]

    def rows(self, scope: Scope) -> tuple[ManifestRow, ...]:
        return getattr(self, scope)


def parse_official_list(text: str) -> list[tuple[str, int]]:
    """``(image_id, official_class_id)`` per non-comment line of an official list file.

    The official format is ``Image CLASS-ID SPECIES BREED-ID`` with ``#``
    comment lines; only the first two columns are identity for this task
    (species / breed-within-species are not inputs, §22.9a).
    """
    entries: list[tuple[str, int]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            raise ValueError(f"malformed official list line: {raw!r}")
        entries.append((parts[0], int(parts[1])))
    return entries


def _rows(entries: list[tuple[str, int]], scope: Scope) -> tuple[ManifestRow, ...]:
    rows = [
        ManifestRow(
            image_id=image_id,
            class_index=class_id - 1,
            official_class_id=class_id,
            scope=scope,
        )
        for image_id, class_id in entries
    ]
    return tuple(sorted(rows, key=lambda r: (r.class_index, r.image_id)))


def split_trainval(
    entries: list[tuple[str, int]],
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """The FROZEN §3.2 rule, pure: ``(train_entries, validation_entries)``.

    Per class, image ids sorted lexicographically; position ``i`` goes to
    validation iff ``i % 5 == 4``. Deterministic; no RNG.
    """
    by_class: dict[int, list[str]] = defaultdict(list)
    for image_id, class_id in entries:
        by_class[class_id].append(image_id)
    train: list[tuple[str, int]] = []
    validation: list[tuple[str, int]] = []
    for class_id in sorted(by_class):
        for i, image_id in enumerate(sorted(by_class[class_id])):
            target = validation if i % VALIDATION_MODULUS == VALIDATION_RESIDUE else train
            target.append((image_id, class_id))
    return train, validation


def derive_manifests(trainval_text: str, test_text: str) -> Manifests:
    """Manifests from the official ``trainval.txt`` / ``test.txt`` contents."""
    trainval = parse_official_list(trainval_text)
    test = parse_official_list(test_text)
    train, validation = split_trainval(trainval)
    return Manifests(
        train=_rows(train, "train"),
        validation=_rows(validation, "validation"),
        final=_rows(test, "final"),
    )


def derive_manifests_from_dir(annotations_dir: Path) -> Manifests:
    return derive_manifests(
        (annotations_dir / "trainval.txt").read_text(encoding="utf-8"),
        (annotations_dir / "test.txt").read_text(encoding="utf-8"),
    )


def render_manifest_csv(rows: tuple[ManifestRow, ...]) -> str:
    return MANIFEST_HEADER + "\n" + "".join(row.as_csv() + "\n" for row in rows)


def parse_manifest_csv(text: str) -> tuple[ManifestRow, ...]:
    lines = text.splitlines()
    if not lines or lines[0] != MANIFEST_HEADER:
        raise ValueError(f"manifest header must be {MANIFEST_HEADER!r}")
    rows: list[ManifestRow] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        image_id, class_index, official_class_id, scope = line.split(",")
        rows.append(
            ManifestRow(
                image_id=image_id,
                class_index=int(class_index),
                official_class_id=int(official_class_id),
                scope=scope,  # type: ignore[arg-type]  # validated by the Literal
            )
        )
    return tuple(rows)


# ---------------------------------------------------------------------------
# L0/L1 declarations through the real schemas (design §0.3, §6)
# ---------------------------------------------------------------------------


def declare_model_io_contract() -> ModelIOContract:
    """``[B, 3, 144, 144] float32 → [B, 37] float32`` — the class axis fixed 37."""
    channels, height, width = INPUT_SHAPE
    return model_io_contract(
        tensor_contract(
            [batch_axis(), fixed_axis(channels), fixed_axis(height), fixed_axis(width)],
            ["float32"],
        ),
        tensor_contract([batch_axis(), fixed_axis(NUM_CLASSES, AxisRole.CLASS)], ["float32"]),
    )


def declare_metric_specs() -> dict[str, MetricSpec]:
    """The two declarable terminal metrics (§22.9a). ``log_loss`` is D16-blocked."""
    return {
        "accuracy": MetricSpec(
            id="accuracy",
            direction="higher",
            aggregation="fraction_correct_over_final_eval_images",
            scoreability=PresenceScoreabilityContract(),
        ),
        "macro_f1": MetricSpec(
            id="macro_f1",
            direction="higher",
            aggregation="unweighted_mean_of_per_class_f1_over_37_classes",
            scoreability=PresenceScoreabilityContract(),
        ),
    }


def declare_contracts() -> dict[str, dict[str, Any]]:
    """JSON-ready ``{declared_file_stem: payload}`` for ``declared/``."""
    declared: dict[str, dict[str, Any]] = {
        "model_io_contract": declare_model_io_contract().model_dump(mode="json")
    }
    for name, spec in declare_metric_specs().items():
        declared[f"metric_{name}"] = spec.model_dump(mode="json")
    return declared


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_pack(pack_root: Path, manifests: Manifests) -> dict[str, str]:
    """Write manifests + SHA256SUMS + declared JSON; return the SHA-256 pins."""
    manifest_dir = pack_root / MANIFEST_RELDIR
    names: list[str] = []
    for scope in SCOPES:
        name = f"{scope}.csv"
        write_text(manifest_dir / name, render_manifest_csv(manifests.rows(scope)))
        names.append(name)
    pins = write_sha256sums(manifest_dir, names)
    for stem, payload in declare_contracts().items():
        write_json(pack_root / DECLARED_RELDIR / f"{stem}.json", payload)
    return pins


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--annotations-dir",
        type=Path,
        required=True,
        help="directory holding the OFFICIAL extracted trainval.txt / test.txt (temporary)",
    )
    parser.add_argument("--root", type=Path, default=None, help="pack root (default: examples/…)")
    args = parser.parse_args(argv)
    pack_root = args.root or (repo_root() / "examples" / PACK_DIRNAME)
    manifests = derive_manifests_from_dir(args.annotations_dir)
    for name, digest in write_pack(pack_root, manifests).items():
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
