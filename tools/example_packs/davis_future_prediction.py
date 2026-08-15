"""DAVIS 2017 future-frame-prediction pack — SEQUENCE-level identity + declarations (PR0, C3).

Track C (roadmap §22.9a): SIDERIUS-defined REAL-RGB future-frame prediction on
DAVIS 2017 TrainVal 480p — 8 context frames → next 4 frames, stride 1 —
NOT DAVIS's official segmentation benchmark. This module fixes the
SEQUENCE-level identity only (design §3.3, operator 2026-08-15):

    train       = the 60 official train sequences
    validation  = the 30 official val sequences sorted by name, 0-based
    final         position i → validation iff i % 2 == 0, else final (15 / 15)

**Clip identity ``(sequence_name, start_frame)`` — ALL of it — is D14's.** PR0
writes NO clip manifest and reads NO archive body; per-sequence frame counts
(present in the official metadata) are deliberately NOT consumed here.

Source: the official challenge tooling's ``data/db_info.yaml``
(github.com/davisvideochallenge/davis-2017) — only ``name`` and ``set`` for
``set ∈ {train, val}`` are read — or plain one-name-per-line list files.

Declarations through the real schemas (design §0.3):

* ``ModelIOContract``  ``[B, 3, 8, 128, 224] float32 → [B, 3, 4, 128, 224] float32``
  (no ``class`` axis → CONTINUOUS; the input/output T extents differ — fixed
  dims, only ``B`` shared);
* ``MetricSpec``       ``mse`` (lower; the golden metric — aggregation FROZEN as
  the global mean over clips × C × T × H × W), ``psnr`` (higher; the same
  global MSE aggregation with the ``psnr_db`` transform, ``data_range = 1.0``),
  ``mae`` (lower). None loss-shaped.

Regenerate::

    .venv/bin/python -m tools.example_packs.davis_future_prediction --db-info /tmp/davis/db_info.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.model_io_contract import ModelIOContract
from execute_tools.evaluation_metric import MetricSpec, PresenceScoreabilityContract
from tools.example_packs._common import repo_root, write_json, write_sha256sums, write_text
from tools.example_packs.declarations import (
    batch_axis,
    fixed_axis,
    model_io_contract,
    tensor_contract,
)

PACK_DIRNAME = "davis_future_prediction"
MANIFEST_RELDIR = Path("data") / "manifests"
MANIFEST_NAME = "sequences.csv"
DECLARED_RELDIR = Path("declared")

Scope = Literal["train", "validation", "final"]
SCOPES: tuple[Scope, ...] = ("train", "validation", "final")

#: Frozen §22.9a instance values (pinned as literals in the tests, never read back).
CHANNELS = 3
CONTEXT_FRAMES = 8
FUTURE_FRAMES = 4
HEIGHT = 128
WIDTH = 224
OFFICIAL_TRAIN_SEQUENCES = 60
OFFICIAL_VAL_SEQUENCES = 30
VALIDATION_MODULUS = 2
VALIDATION_RESIDUE = 0
PSNR_DATA_RANGE = 1.0

MANIFEST_HEADER = "sequence_name,scope"


class SequenceRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence_name: str = Field(min_length=1)
    scope: Scope

    def as_csv(self) -> str:
        return f"{self.sequence_name},{self.scope}"


def parse_sequence_list(text: str) -> list[str]:
    """One sequence name per non-empty, non-comment line (official ``train.txt`` form)."""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def parse_db_info(text: str) -> tuple[list[str], list[str]]:
    """``(train_names, val_names)`` from the official ``db_info.yaml``.

    Reads ONLY ``name`` and ``set``; ``num_frames`` (clip-level information)
    is deliberately ignored — clip identity is D14's.
    """
    payload = yaml.safe_load(text)
    sequences = payload["sequences"]
    train = [s["name"] for s in sequences if s["set"] == "train"]
    val = [s["name"] for s in sequences if s["set"] == "val"]
    return train, val


def split_official_val(val_names: list[str]) -> tuple[list[str], list[str]]:
    """The FROZEN §3.3 rule, pure: ``(validation_names, final_names)``.

    Sort by name; 0-based position ``i`` → validation iff ``i % 2 == 0``.
    """
    validation: list[str] = []
    final: list[str] = []
    for i, name in enumerate(sorted(val_names)):
        (validation if i % VALIDATION_MODULUS == VALIDATION_RESIDUE else final).append(name)
    return validation, final


def derive_sequence_manifest(
    train_names: list[str], val_names: list[str]
) -> tuple[SequenceRow, ...]:
    """Rows sorted by scope order (train, validation, final) then by name.

    Raises:
        ValueError: on a duplicate name or a name present in both official
            lists — an official-list inconsistency is reported, never repaired.
    """
    if len(set(train_names)) != len(train_names) or len(set(val_names)) != len(val_names):
        raise ValueError("duplicate sequence name in an official list")
    if set(train_names) & set(val_names):
        raise ValueError("a sequence appears in both official train and val lists")
    validation, final = split_official_val(val_names)
    rows: list[SequenceRow] = []
    for scope, names in (
        ("train", sorted(train_names)),
        ("validation", validation),
        ("final", final),
    ):
        rows.extend(SequenceRow(sequence_name=n, scope=scope) for n in names)  # type: ignore[arg-type]
    return tuple(rows)


def render_manifest_csv(rows: tuple[SequenceRow, ...]) -> str:
    return MANIFEST_HEADER + "\n" + "".join(row.as_csv() + "\n" for row in rows)


def parse_manifest_csv(text: str) -> tuple[SequenceRow, ...]:
    lines = text.splitlines()
    if not lines or lines[0] != MANIFEST_HEADER:
        raise ValueError(f"manifest header must be {MANIFEST_HEADER!r}")
    rows: list[SequenceRow] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        name, scope = line.split(",")
        rows.append(SequenceRow(sequence_name=name, scope=scope))  # type: ignore[arg-type]
    return tuple(rows)


# ---------------------------------------------------------------------------
# L0/L1 declarations through the real schemas
# ---------------------------------------------------------------------------


def declare_model_io_contract() -> ModelIOContract:
    """``[B, 3, 8, 128, 224] float32 → [B, 3, 4, 128, 224] float32``."""
    return model_io_contract(
        tensor_contract(
            [
                batch_axis(),
                fixed_axis(CHANNELS),
                fixed_axis(CONTEXT_FRAMES),
                fixed_axis(HEIGHT),
                fixed_axis(WIDTH),
            ],
            ["float32"],
        ),
        tensor_contract(
            [
                batch_axis(),
                fixed_axis(CHANNELS),
                fixed_axis(FUTURE_FRAMES),
                fixed_axis(HEIGHT),
                fixed_axis(WIDTH),
            ],
            ["float32"],
        ),
    )


MSE_AGGREGATION = "global_mean_squared_error_over_clips_x_C_x_T_x_H_x_W"
MAE_AGGREGATION = "global_mean_absolute_error_over_clips_x_C_x_T_x_H_x_W"


def declare_metric_specs() -> dict[str, MetricSpec]:
    """mse ↓ (golden) · psnr ↑ (optional) · mae ↓ (optional) — §22.9a."""
    return {
        "mse": MetricSpec(
            id="mse",
            direction="lower",
            aggregation=MSE_AGGREGATION,
            scoreability=PresenceScoreabilityContract(),
        ),
        "psnr": MetricSpec(
            id="psnr",
            direction="higher",
            aggregation=MSE_AGGREGATION,
            transform="psnr_db",
            transform_params={"data_range": PSNR_DATA_RANGE},
            scoreability=PresenceScoreabilityContract(),
        ),
        "mae": MetricSpec(
            id="mae",
            direction="lower",
            aggregation=MAE_AGGREGATION,
            scoreability=PresenceScoreabilityContract(),
        ),
    }


def declare_contracts() -> dict[str, dict[str, Any]]:
    declared: dict[str, dict[str, Any]] = {
        "model_io_contract": declare_model_io_contract().model_dump(mode="json")
    }
    for name, spec in declare_metric_specs().items():
        declared[f"metric_{name}"] = spec.model_dump(mode="json")
    return declared


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_pack(pack_root: Path, rows: tuple[SequenceRow, ...]) -> dict[str, str]:
    manifest_dir = pack_root / MANIFEST_RELDIR
    write_text(manifest_dir / MANIFEST_NAME, render_manifest_csv(rows))
    pins = write_sha256sums(manifest_dir, [MANIFEST_NAME])
    for stem, payload in declare_contracts().items():
        write_json(pack_root / DECLARED_RELDIR / f"{stem}.json", payload)
    return pins


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--db-info", type=Path, help="official davis-2017 tooling data/db_info.yaml (temporary)"
    )
    source.add_argument(
        "--lists",
        nargs=2,
        type=Path,
        metavar=("TRAIN_TXT", "VAL_TXT"),
        help="official one-name-per-line train.txt / val.txt",
    )
    parser.add_argument("--root", type=Path, default=None, help="pack root (default: examples/…)")
    args = parser.parse_args(argv)
    if args.db_info is not None:
        train, val = parse_db_info(args.db_info.read_text(encoding="utf-8"))
    else:
        train = parse_sequence_list(args.lists[0].read_text(encoding="utf-8"))
        val = parse_sequence_list(args.lists[1].read_text(encoding="utf-8"))
    pack_root = args.root or (repo_root() / "examples" / PACK_DIRNAME)
    for name, digest in write_pack(pack_root, derive_sequence_manifest(train, val)).items():
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
