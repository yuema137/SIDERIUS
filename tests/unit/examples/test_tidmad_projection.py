"""`examples/tidmad/` is a READ-ONLY projection of production — never a second authority.

Step-07 PR0 commit C1 (design `pr0_persistent_example_baseline.md` §5, §15 C1).
CI is the validation CONSUMER of the pack (§4): every tracked snapshot is
regenerated from the owning production accessor and deep-compared, and the
read-only UX invariant (§3.6) is pinned as text.

The checkout root is derived from ``__file__`` (CLAUDE.md portability) — the
tests read THIS checkout's pack, never another clone's.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent.schemas.model_io_contract import ModelIOContract
from tools.example_packs.projection import (
    SNAPSHOT_KEYS,
    project_tidmad,
    render_resolved_banner,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPO_ROOT / "examples" / "tidmad"
RESOLVED = PACK_ROOT / "resolved"

# Frozen §22.9a / Step-06 literals — pinned HERE, never read back from the pack.
TIDMAD_METRIC_ID_LITERAL = "tidmad_denoising_score"
TIDMAD_METRIC_DIRECTION_LITERAL = "higher"
TIDMAD_INPUT_RENDER = "[B, T] int64"
TIDMAD_OUTPUT_RENDER = "[B, 256, T] float32"
TIDMAD_CLASS_EXTENT = 256

READ_ONLY_PINS = ("DO NOT EDIT", "does not read")


def _tracked(resolved_dir: Path, key: str) -> dict:
    path = resolved_dir / f"{key}.json"
    assert path.is_file(), f"snapshot missing: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_snapshots_equal(resolved_dir: Path, projection: dict[str, dict]) -> None:
    """The deep-compare every snapshot must pass; factored so a negative test can call it."""
    for key, fresh in projection.items():
        assert _tracked(resolved_dir, key) == json.loads(json.dumps(fresh)), (
            f"{key}.json drifted from the production authority — regenerate with "
            f"`.venv/bin/python -m tools.example_packs.projection` in the SAME commit "
            f"as the authority change"
        )


@pytest.fixture(scope="module")
def projection() -> dict[str, dict]:
    return project_tidmad(REPO_ROOT)


# ---------------------------------------------------------------------------
# (a) projection equality — the "no second authority" acceptance, machine-checked
# ---------------------------------------------------------------------------


def test_projection_covers_every_snapshot_key(projection: dict[str, dict]) -> None:
    """Defect caught: `configs/task_config.yaml` stops declaring `model_io` (the
    generator would silently write no `model_io_contract.json`), or a snapshot
    key is dropped from the generator. Not caught elsewhere: no production
    consumer notices a missing pack file."""
    assert tuple(projection.keys()) == SNAPSHOT_KEYS


@pytest.mark.parametrize("key", SNAPSHOT_KEYS)
def test_tracked_snapshot_deep_equals_fresh_projection(
    key: str, projection: dict[str, dict]
) -> None:
    """Defect caught: a tracked `resolved/<key>.json` drifts from what production
    resolves (authority changed without regeneration, or a hand edit) — the
    pack would become a stale parallel copy. Fails on any value / key
    difference after JSON normalisation."""
    _assert_snapshots_equal(RESOLVED, {key: projection[key]})


def test_negative_mutated_snapshot_is_detected(tmp_path: Path, projection: dict[str, dict]) -> None:
    """Proves the deep-compare fires: one value mutated in a tmp copy of the
    metric snapshot → the equality assertion raises. Without this the family
    could pass vacuously (e.g. comparing a snapshot to itself)."""
    mirror = tmp_path / "resolved"
    shutil.copytree(RESOLVED, mirror)
    payload = json.loads((mirror / "metric_spec.json").read_text())
    payload["direction"] = "lower"
    (mirror / "metric_spec.json").write_text(json.dumps(payload))
    with pytest.raises(AssertionError, match="drifted"):
        _assert_snapshots_equal(mirror, {"metric_spec": projection["metric_spec"]})


# ---------------------------------------------------------------------------
# (b) frozen literals pinned in the test, never read back from the pack
# ---------------------------------------------------------------------------


def test_metric_snapshot_pins_the_frozen_identity_and_direction() -> None:
    """Defect caught: the golden-metric identity or direction projected for
    TIDMAD changes (`derive_tidmad_metric_spec` or the tracked snapshot). The
    values are hardcoded here from Step 06 / roadmap §22.9a — a test reading
    them back from the pack would pass for any value."""
    metric = _tracked(RESOLVED, "metric_spec")
    assert metric["id"] == TIDMAD_METRIC_ID_LITERAL
    assert metric["direction"] == TIDMAD_METRIC_DIRECTION_LITERAL


def test_model_io_snapshot_renders_the_frozen_tidmad_contract() -> None:
    """Defect caught: the projected contract no longer renders
    `[B, T] int64 → [B, 256, T] float32` or loses the fixed-256 `class` axis —
    the pack would misdescribe the task. Constructs the REAL schema from the
    tracked JSON (the projection must be schema-valid, not merely JSON)."""
    payload = _tracked(RESOLVED, "model_io_contract")
    contract = ModelIOContract(**payload)
    assert contract.input.render() == TIDMAD_INPUT_RENDER
    assert contract.output.render() == TIDMAD_OUTPUT_RENDER
    assert contract.class_cardinality == TIDMAD_CLASS_EXTENT
    class_axes = [a for a in payload["output"]["axes"] if a["role"] == "class"]
    assert len(class_axes) == 1 and class_axes[0]["dimension"]["fixed"] == TIDMAD_CLASS_EXTENT


# ---------------------------------------------------------------------------
# (c) references resolve to the owning paths — prose cites, never copies
# ---------------------------------------------------------------------------


def test_readme_cites_the_owning_paths_and_they_exist() -> None:
    """Defect caught: the README stops naming the owning YAML paths (a reader
    would take the pack for the authority), or an owning path named there no
    longer exists in the checkout (stale reference)."""
    readme = (PACK_ROOT / "README.md").read_text(encoding="utf-8")
    for owning in ("configs/task_config.yaml", "configs/health_checks.yaml"):
        assert owning in readme, f"README must cite the owning path {owning!r}"
        assert (REPO_ROOT / owning).is_file(), f"cited owning path missing: {owning}"


# ---------------------------------------------------------------------------
# (d) read-only snapshot UX invariant (§3.6)
# ---------------------------------------------------------------------------


def test_resolved_banner_is_the_generated_one(projection: dict[str, dict]) -> None:
    """Defect caught: `resolved/README.md` is hand-edited or the generator's
    banner text changes without regeneration — the banner is generated with the
    snapshots precisely so it cannot drift from them."""
    tracked = (RESOLVED / "README.md").read_text(encoding="utf-8")
    assert tracked == render_resolved_banner(tuple(projection.keys()))


@pytest.mark.parametrize("relpath", ["resolved/README.md", "README.md", "STATUS.md"])
def test_read_only_statement_present(relpath: str) -> None:
    """Defect caught: a pack document loses the DO-NOT-EDIT / runtime-does-not-
    read statement, inviting a user to edit a snapshot expecting a runtime
    effect (§3.6 UX invariant)."""
    # Whitespace-normalised so a Markdown line wrap cannot hide a present pin.
    text = " ".join((PACK_ROOT / relpath).read_text(encoding="utf-8").split())
    for pin in READ_ONLY_PINS:
        assert pin in text, f"{relpath} must state {pin!r}"


def test_negative_banner_without_read_only_statement_is_detected() -> None:
    """Proves the string pin is not vacuous: a banner lacking the runtime-does-
    not-read sentence fails the same check the tracked banner passes."""
    banner = render_resolved_banner().replace("does not read", "reads")
    assert not all(pin in banner for pin in READ_ONLY_PINS)
