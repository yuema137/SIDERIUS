"""Stage-3 INTEGRATION WITNESS — the three mechanisms against the REAL composer.

The three Stage-3 writers were built in parallel lanes, each stubbing the
shared ``compose_and_score`` boundary (contract §4). Every per-lane suite is
therefore green even if the lanes disagree about the boundary in practice.
This module is the subtree's one end-to-end witness: ONE synthetic campaign
workspace, all three production CLIs, the REAL ``scripts.stage3.stage3_common``
(resolution, refusals, anchor-ruler pin — no stubs), with exactly ONE patch at
the arithmetic boundary: ``stage3_common.score_vector`` is replaced by a
deterministic counting stub, because the frozen TIDMAD arithmetic needs real
ABRA HDF5 + the committed anchor map's data, which a unit test must not.
Composition, refusal, selection, and isolation logic are all real.

Defects only this witness catches (and how it fails when they break):

* a writer calling the composer in a shape the REAL composer refuses
  (per-lane stubs accept anything; here a wrong pooled set raises
  ``NotScoreableError`` and the mechanism's CLI exits 2, failing the rc
  assertion);
* the composer resolving a pooled set the writers did not intend
  (duplicate/missing file indices across pooled dirs — the call-count and
  per-call 20-distinct-paths assertions go red);
* ``score_vector`` invoked more or fewer than EXACTLY ONCE per composition
  (total-call-count assertion: 1 composed + 4 strict + 1 terminal = 6);
* strict selection ignoring ``MetricOrder`` direction (the planted scalars
  are all NEGATIVE with the winner nearest zero: a lower-is-better or
  ``min``-shaped bug selects rnnD instead of wavenetA);
* a terminal artifact escaping the isolation namespace (every emitted file
  that self-declares the terminal namespace marker must live under it, and
  the terminal writer's own read-closure guard must hold on the REAL final
  tree);
* a per-band scalar appearing in ANY Stage-3 artifact or stdout line
  (independent walker below — not the writers' own guards).

Fixture reuse: the Stage-1 campaign builder is writer C's own
(``test_stage3_composed_best._make_campaign`` — real locks, manifests,
effective health config, eligibility-authority-valid records), and the
Stage-2 tree builder is writer D's (``test_strict_best._build_tree``).
Reusing them keeps this witness from diverging from the per-lane contracts.

Q-S3-2 RULED A (supervisor, 2026-08-26): a unit's ``deliverables/`` carries
its TARGET-BAND files only — DS8's ``--data_scope`` behaviour already
produces exactly that, a design's four band dirs partition 0..19, and
whole-dir pooling composes with zero duplicates. This witness populates
units accordingly, and markers carry the band's file count (validated by
strict_best's marker schema).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import scripts.stage3.stage3_common as stage3_common
from execute_tools.dataset_config import NUM_FILES, SEGMENTS_PER_FILE
from scripts.stage3.stage3_composed_best import band_file_indices
from scripts.stage3.stage3_composed_best import main as composed_main
from scripts.stage3.stage3_strict_best import main as strict_main
from scripts.stage3.stage3_terminal_eval import (
    ARTIFACT_NAMESPACE_KEY,
    TERMINAL_NAMESPACE_MARKER,
    assert_terminal_read_closure,
)
from scripts.stage3.stage3_terminal_eval import main as terminal_main
from tests.unit.scripts.stage3.test_stage3_composed_best import (
    ARM,
    FULL_STAMP,
    NAMING,
    _make_campaign,
)
from tests.unit.scripts.stage3.test_strict_best import (
    BANDS,
    DESIGNS,
    _build_tree,
    _write_unit_workspaces,
)
from tests.unit.scripts.stage3.test_terminal_eval import _valid_record

# The strict-selection plant: all NEGATIVE, winner nearest zero. Under the
# production metric (higher-is-better) wavenetA wins; a min-shaped or
# direction-flipped bug selects rnnD (-30.0). The composed pool and the
# terminal champion resolve their own scalars (see _ArithmeticBoundaryStub).
_STRICT_PLANT: dict[str, float] = {
    "wavenetA": -5.0,
    "punetB": -12.0,
    "gatedfnoC": -20.0,
    "rnnD": -30.0,
}
_COMPOSED_SCALAR = -2.5

_BAND_TOKENS = ("0-3", "4-9", "10-14", "15-19")


class _ArithmeticBoundaryStub:
    """Counting stand-in for ``score_vector`` at the ONE allowed patch point.

    Verifies, per call, what the real arithmetic would rely on: the full
    sample set (files 0..19, every segment) and 20 DISTINCT EXISTING absolute
    deliverable paths resolved by the composer. Returns a scalar derived from
    WHERE the resolved paths live, so each mechanism's output is predictable.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> tuple[list[float], float]:
        sample_set = kwargs["sample_set"]
        assert sorted(sample_set) == list(range(NUM_FILES))
        assert all(
            list(segments) == list(range(SEGMENTS_PER_FILE)) for segments in sample_set.values()
        )
        fn = kwargs["denoised_filename_fn"]
        paths = [fn(index) for index in range(NUM_FILES)]
        assert len(set(paths)) == NUM_FILES, "composer must resolve 20 DISTINCT deliverables"
        for path in paths:
            assert Path(path).is_absolute(), f"composer must hand absolute paths: {path}"
            assert Path(path).exists(), f"resolved deliverable does not exist: {path}"
        first = Path(paths[0])
        if "composed_best" in first.parts:
            kind, scalar = "composed", _COMPOSED_SCALAR
        else:
            design = next(
                (d for d in _STRICT_PLANT if any(p.startswith(f"{d}_") for p in first.parts)),
                None,
            )
            assert design is not None, f"unclassifiable resolved path: {first}"
            kind, scalar = f"design:{design}", _STRICT_PLANT[design]
        self.calls.append({"kind": kind, "paths": paths})
        vector = [scalar + index * 1e-6 for index in range(NUM_FILES)]
        return vector, scalar


def _populate_stage2_deliverables(root: Path) -> None:
    """Give each Stage-2 unit its TARGET-BAND deliverables (Q-S3-2 reading).

    Named by the ONE ``DeliverableNaming`` authority, so the real composer's
    inverse parser resolves them; content is inert (arithmetic is stubbed).
    """
    for design in DESIGNS:
        for band in BANDS:
            deliverables = root / "stage2" / f"{design}_{band}" / "deliverables"
            for index in band_file_indices(band):
                name = NAMING.name(
                    model_type="wavenet",
                    run_name=f"retrain_{design}",
                    exp_id=f"exp_{design}_{band}",
                    input_identity=index,
                )
                (deliverables / name).write_bytes(b"synthetic")


def _band_scalar_violations(payload: Any, path: str = "$") -> list[str]:
    """Independent no-band-scalar walker (NOT the writers' own guards).

    A band token as a dict KEY mapping to a number (or to a subtree holding
    numbers) is a violation; a band token as a string VALUE (provenance
    labels) is legal.
    """
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            here = f"{path}.{key_text}"
            is_band_key = any(token in key_text for token in _BAND_TOKENS) or re.search(
                r"band[_\s]*\d", key_text, re.IGNORECASE
            )
            if is_band_key and _holds_number(value):
                found.append(here)
            found.extend(_band_scalar_violations(value, here))
    elif isinstance(payload, list):
        for position, value in enumerate(payload):
            found.extend(_band_scalar_violations(value, f"{path}[{position}]"))
    return found


def _holds_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, dict):
        return any(_holds_number(item) for item in value.values())
    if isinstance(value, list):
        return any(_holds_number(item) for item in value)
    return False


def test_three_mechanisms_end_to_end_against_real_composer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = _ArithmeticBoundaryStub()
    monkeypatch.setattr(stage3_common, "score_vector", stub)

    # ONE synthetic campaign workspace: Stage-1 (writer C's builder, real
    # authorities) + Stage-2 (writer D's builder + band-file population).
    _make_campaign(tmp_path)
    _build_tree(tmp_path)
    _populate_stage2_deliverables(tmp_path)
    # Post-gate-ruling: strict_best's production path RECONCILES the 09a
    # stamps persisted in the 16 units' chain workspaces.
    _write_unit_workspaces(tmp_path)

    # --- composed_best: production CLI, real composer ---
    assert composed_main(["--workspace_root", str(tmp_path), "--arm", ARM]) == 0

    # --- strict_best: production CLI, REAL stage3_common resolved lazily ---
    assert strict_main(["--workspace_root", str(tmp_path), "--designs", ",".join(DESIGNS)]) == 0

    # --- terminal_eval: production CLI; champion = the strict winner's units ---
    champion_path = tmp_path / "champion.json"
    winner_dirs = [
        str((tmp_path / "stage2" / f"wavenetA_{band}" / "deliverables").resolve()) for band in BANDS
    ]
    champion_path.write_text(
        json.dumps(
            {
                "identity": {
                    "exp_id": "exp_wavenetA_0-3",
                    "model_type": "wavenet",
                    "iteration": 1,
                    "experiment_arm": ARM,
                },
                "deliverable_dirs": winner_dirs,
                "provenance_records": [_valid_record()],
                # F-4: the run workspace whose PINNED effective HealthGate
                # config governs the provenance record — never the
                # repo-current shipped one.
                "provenance_workspace": str(
                    (tmp_path / "stage2" / f"wavenetA_{BANDS[0]}" / "workspace").resolve()
                ),
                # The champion's reconciled 09a stamp (§4 amendment): the
                # round-trip-safe MetricSpecField re-hydrates this dump.
                "metric_spec": FULL_STAMP,
            }
        ),
        encoding="utf-8",
    )
    assert (
        terminal_main(["--champion_json", str(champion_path), "--workspace_root", str(tmp_path)])
        == 0
    )
    stdout = capsys.readouterr().out

    # 1. The composed scalar exists, at full scope, in the composed namespace.
    composed_dir = tmp_path / "stage3" / "composed_best" / ARM
    provenance_files = list(composed_dir.rglob("*.json"))
    assert provenance_files, "composed_best emitted no provenance artifact"
    composed_payload = json.loads(
        max(provenance_files, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8")
    )
    assert composed_payload["denoising_score"] == pytest.approx(_COMPOSED_SCALAR, abs=1e-9)
    assert len(composed_payload["file_vector"]) == NUM_FILES

    # 2. Strict selection picks the PLANTED winner under the production
    #    MetricOrder (higher-is-better over negative scores).
    selection_path = tmp_path / "stage3" / "strict_best" / "strict_best_selection.json"
    assert selection_path.is_file(), "strict_best emitted no selection artifact"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    assert selection["selected_design"] == "wavenetA", (
        f"strict selection under the production MetricOrder must pick the plant "
        f"(-5.0, nearest zero among negatives); got {selection['selected_design']!r} "
        f"— a min-shaped or direction-flipped bug picks 'rnnD'"
    )
    assert selection["selected_strict_score"] == pytest.approx(_STRICT_PLANT["wavenetA"], abs=1e-9)
    assert selection["metric_direction"] == "higher"

    # 3. Terminal artifacts land ONLY in the terminal namespace: every JSON
    #    under the workspace that self-declares the terminal marker lives
    #    under stage3/terminal_eval/, and at least one such artifact exists.
    terminal_ns = tmp_path / "stage3" / "terminal_eval"
    declared: list[Path] = []
    for json_file in tmp_path.rglob("*.json"):
        try:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get(ARTIFACT_NAMESPACE_KEY) == TERMINAL_NAMESPACE_MARKER
        ):
            declared.append(json_file)
    assert declared, "terminal_eval emitted no self-declared artifact"
    escaped = [p for p in declared if not p.is_relative_to(terminal_ns)]
    assert escaped == [], f"terminal artifacts escaped the namespace: {escaped}"
    # The terminal writer's own read-closure guard holds on the REAL tree.
    assert_terminal_read_closure(tmp_path)

    # 4. Zero band scalars anywhere: every Stage-3 JSON artifact plus the
    #    three CLIs' combined stdout (independent walker, not the guards
    #    the writers ship).
    for json_file in (tmp_path / "stage3").rglob("*.json"):
        try:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        violations = _band_scalar_violations(payload)
        assert violations == [], f"band scalar in {json_file}: {violations}"
    for token in _BAND_TOKENS:
        for match in re.finditer(re.escape(token), stdout):
            window = stdout[match.end() : match.end() + 30]
            assert not re.match(r"\D{0,12}-?\d+\.\d", window), (
                f"stdout pairs band token {token!r} with a numeric value: "
                f"...{stdout[max(0, match.start() - 20) : match.end() + 30]!r}..."
            )

    # 5. score_vector ran EXACTLY once per composition: 1 composed + 4 strict
    #    (one per design) + 1 terminal.
    kinds = Counter(call["kind"] for call in stub.calls)
    expected = Counter({f"design:{design}": 1 for design in DESIGNS})
    expected["design:wavenetA"] += 1  # the terminal champion re-scores the winner's units
    expected["composed"] = 1
    assert kinds == expected, f"composition call census: {dict(kinds)}"
    assert sum(kinds.values()) == 6
