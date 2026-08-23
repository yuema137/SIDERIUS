"""`examples/oxford_iiit_pet/` — identity manifests + L0/L1 declarations (PR0 C2).

Design `pr0_persistent_example_baseline.md` §3.2 (frozen rule), §6, §15 C2.
Every §22.9a value is pinned HERE as a literal — never read back from the
pack. The checkout root is derived from ``__file__`` (portability).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.schemas.model_io_contract import ModelIOContract
from execute_tools.evaluation_metric import MetricSpec, PresenceScoreabilityContract
from ml_models.models_format_sandbox import OutputSemantic
from tools.example_packs._common import parse_sha256sums, sha256_of_file
from tools.example_packs.declarations import metric_spec_from_declared
from tools.example_packs.oxford_iiit_pet import (
    ManifestRow,
    declare_contracts,
    derive_manifests,
    parse_manifest_csv,
    split_trainval,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPO_ROOT / "examples" / "oxford_iiit_pet"
MANIFESTS = PACK_ROOT / "data" / "manifests"
DECLARED = PACK_ROOT / "declared"

# --- frozen literals (§22.9a + the official list counts confirmed 2026-08-15) ---
NUM_CLASSES = 37
TRAIN_ROWS = 2946
VALIDATION_ROWS = 734
FINAL_ROWS = 3669
TRAINVAL_ROWS = 3680
INPUT_RENDER = "[B, 3, 144, 144] float32"
OUTPUT_RENDER = "[B, 37] float32"
# Integrity / provenance pins of the reviewed manifest bytes (design §3.2). A
# regeneration that changes a manifest must change these literals in the same
# reviewed commit — the pin never floats with the pack.
PINNED_SHA256 = {
    "train.csv": "b58e8791460ab3d5b172e7a95d4841dd603db1ecbd38bf43dafcecec522546ea",
    "validation.csv": "6dfda127d8e44173064b8146600701135ea57d3a46d076859d9f91a300d7b16e",
    "final.csv": "f72580dcec11a5234904bacc1f98b3119c72d7bc374b9691169723502477d070",
}
STATUS_SEAM_PINS = ("DatasetProfile", "DeliverableSpec", "D14", "D16", "Step 12", "Step 08")


def _rows(name: str) -> tuple[ManifestRow, ...]:
    return parse_manifest_csv((MANIFESTS / name).read_text(encoding="utf-8"))


def _check_identity(
    train: tuple[ManifestRow, ...],
    validation: tuple[ManifestRow, ...],
    final: tuple[ManifestRow, ...],
) -> None:
    """The manifest RULE checks (design §8): counts · uniqueness · disjointness ·
    class coverage · class-index consistency. Factored so the negatives can call it."""
    scoped = (("train", train), ("validation", validation), ("final", final))
    ids = {scope: [r.image_id for r in rows] for scope, rows in scoped}
    for scope, rows in scoped:
        assert len(ids[scope]) == len(set(ids[scope])), f"duplicate image_id in {scope}"
        for row in rows:
            assert row.class_index == row.official_class_id - 1
    sets = {scope: set(v) for scope, v in ids.items()}
    assert not (sets["train"] & sets["validation"]), "train/validation overlap"
    assert not (sets["train"] & sets["final"]), "train/final overlap"
    assert not (sets["validation"] & sets["final"]), "validation/final overlap"
    for scope, rows in scoped:
        classes = {r.class_index for r in rows}
        assert classes == set(range(NUM_CLASSES)), f"{scope} does not cover all 37 classes"


# ---------------------------------------------------------------------------
# manifests: integrity pins, counts, rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PINNED_SHA256))
def test_manifest_sha256_matches_pin_and_sums_file(name: str) -> None:
    """Defect caught: a manifest's bytes differ from the reviewed pin
    (corruption, or a regeneration not carried through review) — both the
    literal here and `SHA256SUMS` must agree with the file."""
    digest = sha256_of_file(MANIFESTS / name)
    assert digest == PINNED_SHA256[name]
    sums = parse_sha256sums((MANIFESTS / "SHA256SUMS").read_text(encoding="utf-8"))
    assert sums[name] == digest


def test_manifest_counts_are_the_official_ones() -> None:
    """Defect caught: a manifest gains or loses rows (2 946 / 734 / 3 669;
    train ∪ validation = the official 3 680 trainval entries). Literals, not
    values read from the pack."""
    train, validation, final = _rows("train.csv"), _rows("validation.csv"), _rows("final.csv")
    assert (len(train), len(validation), len(final)) == (TRAIN_ROWS, VALIDATION_ROWS, FINAL_ROWS)
    assert len({r.image_id for r in train} | {r.image_id for r in validation}) == TRAINVAL_ROWS
    assert all(r.scope == "train" for r in train)
    assert all(r.scope == "validation" for r in validation)
    assert all(r.scope == "final" for r in final)


def test_manifests_pass_the_identity_rule_checks() -> None:
    """Defect caught: duplicate ids, a scope overlap, a class missing from a
    scope, or a class_index/official id mismatch in the tracked manifests."""
    _check_identity(_rows("train.csv"), _rows("validation.csv"), _rows("final.csv"))


def test_tracked_split_is_exactly_the_frozen_rule_over_its_own_union() -> None:
    """Defect caught: the tracked train/validation assignment departs from the
    frozen §3.2 rule (per class, sorted ids, i % 5 == 4 → validation) — e.g. a
    hand edit or a re-split with a seed. Re-derives the split from the union
    of the two tracked manifests, so it needs no fetch. Identity carried by
    the RULE, not by the pin alone (design §3.2)."""
    train, validation = _rows("train.csv"), _rows("validation.csv")
    union = [(r.image_id, r.official_class_id) for r in train + validation]
    rule_train, rule_validation = split_trainval(union)
    assert sorted(rule_train) == sorted((r.image_id, r.official_class_id) for r in train)
    assert sorted(rule_validation) == sorted((r.image_id, r.official_class_id) for r in validation)


def test_split_rule_on_synthetic_list_matches_the_frozen_positions() -> None:
    """Defect caught: `split_trainval` drifts from the frozen rule (residue,
    modulus, sort order, per-class stratification). Synthetic list, independent
    of the fetch: class 1 has 7 ids, class 2 has 5, class 3 has 4."""
    entries = [(f"a_{i}", 1) for i in (3, 1, 2, 7, 5, 4, 6)]  # sorted: a_1..a_7
    entries += [(f"b_{i}", 2) for i in (5, 4, 3, 2, 1)]  # sorted: b_1..b_5
    entries += [(f"c_{i}", 3) for i in (1, 2, 3, 4)]  # only 4 → no validation row
    train, validation = split_trainval(entries)
    assert validation == [("a_5", 1), ("b_5", 2)]  # positions 4 (0-based) per class
    assert len(train) == 16 - 2
    assert ("c_4", 3) in train  # position 3 → train
    # And the manifests builder keeps 'final' verbatim while re-scoping trainval.
    manifests = derive_manifests("#hdr\na_1 1 1 1\na_2 1 1 1\n", "z_9 37 2 12\n")
    assert [r.image_id for r in manifests.final] == ["z_9"]
    assert manifests.final[0].class_index == 36 and manifests.final[0].scope == "final"
    assert [r.image_id for r in manifests.train] == ["a_1", "a_2"] and not manifests.validation


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_id", "scope_overlap", "class_missing_from_validation"],
)
def test_negative_identity_rule_checks_fire(mutation: str) -> None:
    """Proves `_check_identity` catches each failure class it claims: a
    duplicated id, a scope overlap, a class absent from validation."""

    def row(i: int, c: int, scope: str) -> ManifestRow:
        return ManifestRow(image_id=f"x_{i}", class_index=c, official_class_id=c + 1, scope=scope)  # type: ignore[arg-type]

    train = tuple(row(i, i, "train") for i in range(NUM_CLASSES))
    validation = tuple(row(100 + i, i, "validation") for i in range(NUM_CLASSES))
    final = tuple(row(200 + i, i, "final") for i in range(NUM_CLASSES))
    _check_identity(train, validation, final)  # the healthy fixture passes
    if mutation == "duplicate_id":
        train = (*train, row(0, 0, "train"))
    elif mutation == "scope_overlap":
        final = (*final, row(0, 0, "final"))
    else:
        validation = validation[1:]
    with pytest.raises(AssertionError):
        _check_identity(train, validation, final)


# ---------------------------------------------------------------------------
# declarations through the REAL schemas (§0.3, §6)
# ---------------------------------------------------------------------------


def test_declared_files_deep_equal_a_fresh_declaration() -> None:
    """Defect caught: a `declared/*.json` drifts from what the tooling declares
    (hand edit, or a tooling change without regeneration)."""
    fresh = declare_contracts()
    assert set(fresh) == {"model_io_contract", "metric_accuracy", "metric_macro_f1"}
    for stem, payload in fresh.items():
        tracked = json.loads((DECLARED / f"{stem}.json").read_text(encoding="utf-8"))
        assert tracked == json.loads(json.dumps(payload)), f"{stem}.json drifted"


def test_model_io_declaration_is_the_frozen_pets_contract() -> None:
    """Defect caught: the declared contract no longer renders
    `[B, 3, 144, 144] float32 → [B, 37] float32`, or its DERIVED semantics stop
    being categorical with 37 classes. Constructs the REAL schema from the
    tracked JSON — the pack must be schema-valid, not merely JSON."""
    contract = ModelIOContract(**json.loads((DECLARED / "model_io_contract.json").read_text()))
    assert contract.input.render() == INPUT_RENDER
    assert contract.output.render() == OUTPUT_RENDER
    assert contract.output_semantic is OutputSemantic.CATEGORICAL
    assert contract.class_cardinality == NUM_CLASSES


@pytest.mark.parametrize(
    "stem,metric_id", [("metric_accuracy", "accuracy"), ("metric_macro_f1", "macro_f1")]
)
def test_metric_declarations_construct_with_direction_higher(stem: str, metric_id: str) -> None:
    """Defect caught: a declared metric loses its identity or its HIGHER
    direction, or its scoreability contract stops being a real framework
    contract (reconstruction by `contract_id` would fail)."""
    payload = json.loads((DECLARED / f"{stem}.json").read_text(encoding="utf-8"))
    spec = metric_spec_from_declared(payload)
    assert spec.id == metric_id
    assert spec.direction == "higher"
    assert isinstance(spec.scoreability, PresenceScoreabilityContract)


def test_log_loss_is_now_declarable_d16_closed() -> None:
    """The inverted pin FIRED, exactly as it was written to.

    This test used to assert `MetricSpec(id="log_loss", ...)` RAISES, and said
    so: "the day D16 is narrowed and `log_loss` becomes declarable, this test
    FAILS — forcing STATUS/README (which say 'blocked by D16') to change."
    Step 12 / PR-12a C5 narrowed it; the docs were forced to change in the same
    commit; and the assertion is now the positive one.

    `log_loss` is a legitimate evaluation-metric identity for a classifier
    whose deliverable is genuinely scored by it. That the framework refused it
    on SPELLING is what D16 named, and it is why the fourth graduation task is
    required to declare a `loss`-token metric id (parent §16).

    The pack still does not SHIP the declaration — declaring a metric is a
    scientific choice about what Pets is evaluated on, not a side effect of a
    schema change — so the artifact assertion is unchanged.
    """
    spec = MetricSpec(
        id="log_loss",
        direction="lower",
        aggregation="mean_over_final_eval_images",
        scoreability=PresenceScoreabilityContract(),
    )
    assert spec.id == "log_loss"
    assert spec.direction == "lower"
    assert not (DECLARED / "metric_log_loss.json").exists()


# ---------------------------------------------------------------------------
# honest STATUS + provenance
# ---------------------------------------------------------------------------


def test_status_names_the_unsupported_seams() -> None:
    """Defect caught: STATUS stops naming a seam the frozen §0.3 audit says is
    not representable / not landed (DatasetProfile, DeliverableSpec, D14, D16,
    Step 12, Step 08) — the pack would over-claim."""
    text = (PACK_ROOT / "STATUS.md").read_text(encoding="utf-8")
    for pin in STATUS_SEAM_PINS:
        assert pin in text, f"STATUS must name {pin!r}"


def test_provenance_records_the_official_source_and_archive_hash() -> None:
    """Defect caught: PROVENANCE loses the official URL or the archive SHA-256
    the manifests were derived from (identity would become unverifiable)."""
    text = (PACK_ROOT / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "https://www.robots.ox.ac.uk/~vgg/data/pets/" in text
    assert "52425fb6de5c424942b7626b428656fcbd798db970a937df61750c0f1d358e91" in text
    assert "Creative Commons Attribution-ShareAlike 4.0" in text


def test_no_image_or_archive_bytes_under_the_pack() -> None:
    """Defect caught: an image / archive / extracted annotation file lands under
    the pack (roadmap §22.23.10 — raw data never in git)."""
    forbidden = {".jpg", ".jpeg", ".png", ".tar", ".gz", ".zip", ".h5", ".npy", ".pth"}
    offenders = [p for p in PACK_ROOT.rglob("*") if p.is_file() and p.suffix.lower() in forbidden]
    assert offenders == []
    assert not (PACK_ROOT / "data" / "annotations").exists()
