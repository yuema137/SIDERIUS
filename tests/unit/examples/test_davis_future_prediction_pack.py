"""`examples/davis_future_prediction/` — SEQUENCE-level identity + declarations (PR0 C3).

Design `pr0_persistent_example_baseline.md` §3.3 (frozen rule; clip identity
→ D14), §6, §15 C3. Every §22.9a value is pinned HERE as a literal — never
read back from the pack. Checkout root derived from ``__file__``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.schemas.model_io_contract import ModelIOContract
from execute_tools.evaluation_metric import PresenceScoreabilityContract
from ml_models.models_format_sandbox import OutputSemantic
from tools.example_packs._common import parse_sha256sums, sha256_of_file
from tools.example_packs.davis_future_prediction import (
    SequenceRow,
    declare_contracts,
    derive_sequence_manifest,
    parse_db_info,
    parse_manifest_csv,
    split_official_val,
)
from tools.example_packs.declarations import metric_spec_from_declared

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPO_ROOT / "examples" / "davis_future_prediction"
MANIFESTS = PACK_ROOT / "data" / "manifests"
DECLARED = PACK_ROOT / "declared"

# --- frozen literals (§22.9a) ---
TRAIN_SEQUENCES = 60
VALIDATION_SEQUENCES = 15
FINAL_SEQUENCES = 15
INPUT_RENDER = "[B, 3, 8, 128, 224] float32"
OUTPUT_RENDER = "[B, 3, 4, 128, 224] float32"
PSNR_DATA_RANGE = 1.0
PINNED_SHA256 = {
    "sequences.csv": "56ddf30f02c8d8cba0a4a4839a32e0c8e0d9e00609c81d93be6b5edf5e9656b2",
}
# The four frozen licence / provenance sentences (roadmap §22.9a; design C3).
LICENCE_PINS = (
    "DAVIS is released under the BSD License",
    "challenge-created annotations carry separate CC BY 4.0 terms",
    "consumes RGB FRAMES, not segmentation annotation masks",
    "no single licence is claimed for every DAVIS artifact",
    # PR0 pinned the OBLIGATION sentence ("D14 MUST verify and pin the exact
    # terms …"); D14-3 C1 DISCHARGED it, so the pin moves to the discharge —
    # the verdict, the primary sources it rests on, and the no-redistribution
    # fact. Losing any of these is the same defect PR0 guarded against.
    "D14-3 VERIFICATION",
    "Verdict: COMPATIBLE with this task's executable path",
    "BSD 3-Clause",
    "zero redistribution",
    "NOT consumed",
)
STATUS_SEAM_PINS = (
    "clip identity",
    "D14",
    "DatasetProfile",
    "DeliverableSpec",
    "Step 12",
    "Step 08",
)


def _rows() -> tuple[SequenceRow, ...]:
    return parse_manifest_csv((MANIFESTS / "sequences.csv").read_text(encoding="utf-8"))


def _by_scope(rows: tuple[SequenceRow, ...]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"train": [], "validation": [], "final": []}
    for row in rows:
        out[row.scope].append(row.sequence_name)
    return out


def _check_identity(rows: tuple[SequenceRow, ...]) -> None:
    """Counts 60/15/15 · exactly 90 rows · pairwise-disjoint scopes · unique names."""
    scoped = _by_scope(rows)
    assert len(rows) == TRAIN_SEQUENCES + VALIDATION_SEQUENCES + FINAL_SEQUENCES
    assert len(scoped["train"]) == TRAIN_SEQUENCES
    assert len(scoped["validation"]) == VALIDATION_SEQUENCES
    assert len(scoped["final"]) == FINAL_SEQUENCES
    names = [r.sequence_name for r in rows]
    assert len(names) == len(set(names)), "duplicate sequence name"
    assert not (set(scoped["train"]) & set(scoped["validation"]))
    assert not (set(scoped["train"]) & set(scoped["final"]))
    assert not (set(scoped["validation"]) & set(scoped["final"]))


# ---------------------------------------------------------------------------
# sequence manifest
# ---------------------------------------------------------------------------


def test_manifest_sha256_matches_pin_and_sums_file() -> None:
    """Defect caught: the manifest bytes differ from the reviewed pin
    (corruption, or a regeneration not carried through review)."""
    digest = sha256_of_file(MANIFESTS / "sequences.csv")
    assert digest == PINNED_SHA256["sequences.csv"]
    sums = parse_sha256sums((MANIFESTS / "SHA256SUMS").read_text(encoding="utf-8"))
    assert sums["sequences.csv"] == digest


def test_manifest_is_exactly_60_15_15_and_disjoint() -> None:
    """Defect caught: a sequence added / dropped / moved between scopes, a
    duplicate, or an overlap — identity mismatch with §22.9a."""
    _check_identity(_rows())


def test_tracked_val_split_is_exactly_the_frozen_rule_over_its_own_union() -> None:
    """Defect caught: the tracked validation/final assignment departs from the
    frozen §3.3 rule (sorted val names, i % 2 == 0 → validation). Re-derived
    over the union of the two tracked scopes — no fetch needed; identity is
    carried by the RULE, not by the pin alone."""
    scoped = _by_scope(_rows())
    validation, final = split_official_val(scoped["validation"] + scoped["final"])
    assert validation == sorted(scoped["validation"])
    assert final == sorted(scoped["final"])


def test_split_rule_on_synthetic_list_matches_the_frozen_positions() -> None:
    """Defect caught: `split_official_val` drifts from the frozen rule (residue,
    modulus, sort order). Synthetic, fetch-independent."""
    validation, final = split_official_val(["d", "b", "a", "c", "e"])
    assert validation == ["a", "c", "e"]  # positions 0, 2, 4
    assert final == ["b", "d"]
    rows = derive_sequence_manifest(["t2", "t1"], ["v2", "v1"])
    assert [(r.sequence_name, r.scope) for r in rows] == [
        ("t1", "train"),
        ("t2", "train"),
        ("v1", "validation"),
        ("v2", "final"),
    ]


def test_derivation_refuses_inconsistent_official_lists() -> None:
    """Defect caught: an official-list inconsistency (a name in both lists, or
    duplicated) is silently repaired instead of reported (design C3 §6: never
    'fix' the list)."""
    with pytest.raises(ValueError, match="both official"):
        derive_sequence_manifest(["a", "b"], ["b"])
    with pytest.raises(ValueError, match="duplicate"):
        derive_sequence_manifest(["a", "a"], ["b"])


def test_negative_identity_checks_fire_on_overlap_and_unknown_count() -> None:
    """Proves `_check_identity` catches an overlapping scope and a wrong count
    (a sequence outside the official 90 makes the count 91)."""
    rows = _rows()
    _check_identity(rows)
    overlap = (*rows, SequenceRow(sequence_name=rows[0].sequence_name, scope="final"))
    with pytest.raises(AssertionError):
        _check_identity(overlap)
    extra = (*rows, SequenceRow(sequence_name="not-an-official-sequence", scope="train"))
    with pytest.raises(AssertionError):
        _check_identity(extra)


def test_parse_db_info_reads_only_train_and_val_names() -> None:
    """Defect caught: the metadata parser starts consuming `test-dev` entries or
    frame counts (clip-level data → D14), or mis-keys the sets."""
    text = (
        "sequences:\n"
        "- {name: zeta, set: train, num_frames: 10, year: 2016}\n"
        "- {name: alpha, set: val, num_frames: 20, year: 2017}\n"
        "- {name: omega, set: test-dev, num_frames: 30, year: 2017}\n"
    )
    assert parse_db_info(text) == (["zeta"], ["alpha"])


def test_manifest_set_is_exactly_the_landed_identity_and_execution_artifacts() -> None:
    """[PR0 pin, RE-SCOPED BY D14-3 — the milestone that owns clip identity]

    Defect caught: an unexpected manifest appears under the pack, or ANY
    frame / archive bytes land in git. PR0 pinned "no clip manifest" because
    clip identity was D14's to define; D14-3 defined it, so the pin now
    enumerates the exact landed set. The raw-bytes prohibition is UNCHANGED
    and permanent (roadmap §22.23.10) — the dataset lives machine-local."""
    forbidden = {".jpg", ".jpeg", ".png", ".zip", ".tar", ".gz", ".h5", ".npy", ".pth", ".mp4"}
    assert [p for p in PACK_ROOT.rglob("*") if p.is_file() and p.suffix.lower() in forbidden] == []
    assert sorted(p.name for p in MANIFESTS.iterdir()) == [
        "SHA256SUMS",
        "clips.csv",
        "execution.json",
        "gate2_final.csv",
        "gate2_train.csv",
        "gate2_validation.csv",
        "sequences.csv",
    ]


# ---------------------------------------------------------------------------
# declarations through the REAL schemas
# ---------------------------------------------------------------------------


def test_declared_files_deep_equal_a_fresh_declaration() -> None:
    """Defect caught: a `declared/*.json` drifts from what the tooling declares."""
    fresh = declare_contracts()
    assert set(fresh) == {"model_io_contract", "metric_mse", "metric_psnr", "metric_mae"}
    for stem, payload in fresh.items():
        tracked = json.loads((DECLARED / f"{stem}.json").read_text(encoding="utf-8"))
        assert tracked == json.loads(json.dumps(payload)), f"{stem}.json drifted"


def test_model_io_declaration_is_the_frozen_davis_contract() -> None:
    """Defect caught: the declared contract no longer renders
    `[B, 3, 8, 128, 224] float32 → [B, 3, 4, 128, 224] float32`, or stops being
    CONTINUOUS with no class cardinality (differing input/output T extents are
    fixed dims — a schema that could not express that would fail here)."""
    contract = ModelIOContract(**json.loads((DECLARED / "model_io_contract.json").read_text()))
    assert contract.input.render() == INPUT_RENDER
    assert contract.output.render() == OUTPUT_RENDER
    assert contract.output_semantic is OutputSemantic.CONTINUOUS
    assert contract.class_cardinality is None


@pytest.mark.parametrize(
    "stem,metric_id,direction",
    [
        ("metric_mse", "mse", "lower"),
        ("metric_psnr", "psnr", "higher"),
        ("metric_mae", "mae", "lower"),
    ],
)
def test_metric_declarations_construct_with_frozen_directions(
    stem: str, metric_id: str, direction: str
) -> None:
    """Defect caught: a declared metric loses its identity / frozen direction, or
    its scoreability stops being a real framework contract; also that none is
    refused as loss-shaped (construction succeeds)."""
    spec = metric_spec_from_declared(json.loads((DECLARED / f"{stem}.json").read_text()))
    assert spec.id == metric_id
    assert spec.direction == direction
    assert isinstance(spec.scoreability, PresenceScoreabilityContract)


def test_mse_aggregation_is_the_frozen_global_mean_and_psnr_carries_data_range() -> None:
    """Defect caught: the golden aggregation identity stops naming the FROZEN
    global mean over clips × C × T × H × W (an unequal mean-of-means would be a
    task-semantics change), or PSNR loses `data_range = 1.0`."""
    mse = metric_spec_from_declared(json.loads((DECLARED / "metric_mse.json").read_text()))
    assert "global_mean" in mse.aggregation and "clips_x_C_x_T_x_H_x_W" in mse.aggregation
    psnr = metric_spec_from_declared(json.loads((DECLARED / "metric_psnr.json").read_text()))
    assert psnr.transform_params == {"data_range": PSNR_DATA_RANGE}
    assert psnr.aggregation == mse.aggregation


# ---------------------------------------------------------------------------
# honest STATUS + frozen provenance wording
# ---------------------------------------------------------------------------


def test_status_names_clip_identity_d14_and_the_unsupported_seams() -> None:
    """Defect caught: STATUS stops saying "clip identity → D14" or drops a seam
    the frozen §0.3 audit names — the pack would over-claim."""
    text = (PACK_ROOT / "STATUS.md").read_text(encoding="utf-8")
    for pin in STATUS_SEAM_PINS:
        assert pin in text, f"STATUS must name {pin!r}"


def test_provenance_carries_the_frozen_licence_sentences_and_source_hash() -> None:
    """Defect caught: PROVENANCE loses one of the frozen per-artifact licence /
    provenance sentences (§22.9a) or the SHA-256 of the metadata used."""
    text = " ".join((PACK_ROOT / "PROVENANCE.md").read_text(encoding="utf-8").split())
    for pin in LICENCE_PINS:
        assert pin in text, f"PROVENANCE must contain {pin!r}"
    assert "b14a9c264d04ffc6f99a92985fe024a388a7ee08e115f65e4005b72527420c4b" in text
    assert "davisvideochallenge/davis-2017" in text
