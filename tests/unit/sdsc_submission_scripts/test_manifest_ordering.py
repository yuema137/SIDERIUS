"""Iteration manifests record ordering PER EXPERIMENT, never collapsed.

Ordering can resolve differently for different rounds of one iteration —
the agent may propose differently each round when no operator override is
in force. A single iteration-level ordering value would therefore
misreport every round but one, so the manifest keeps a keyed list
(``docs/design/v19_priorities/pr2_data_ordering.md`` §3.7 granularity
rule).
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_spec = importlib.util.spec_from_file_location(
    "run_one_iteration_for_test",
    _REPO / "src" / "workflows" / "run_one_iteration.py",
)
roi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roi)

from agent.schemas.hyperparam_tuning import (  # noqa: E402
    ExperimentMemory,
    ExperimentRecord,
    HyperparamTuningOutput,
)

PERMUTATION = [4, 6, 5, 9, 7, 8]


def _record(exp_id: str, round_index: int, **ordering) -> ExperimentRecord:
    return ExperimentRecord(
        exp_id=exp_id,
        status="success",
        model_type="wavenet",
        timestamp="2026-07-28T00:00:00Z",
        params={},
        denoising_score=1.0,
        memory=ExperimentMemory(
            expert_advice_followed="n/a",
            hypothesis="n/a",
            round_index=round_index,
        ),
        **ordering,
    )


def _output(*records) -> HyperparamTuningOutput:
    return HyperparamTuningOutput(
        run_name="manifest_ordering_test",
        model_type="wavenet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        started_at="2026-07-28T00:00:00Z",
        finished_at="2026-07-28T01:00:00Z",
        best_denoising_score=1.0,
        all_records=list(records),
    )


def test_two_rounds_with_different_ordering_yield_two_keyed_entries(tmp_path):
    """The load-bearing granularity case."""
    output = _output(
        _record(
            "r1",
            1,
            resolved_order_strategy="sequential",
            resolved_file_order=PERMUTATION,
            ordering_resolution_source="agent_proposal",
            proposed_order_strategy="sequential",
        ),
        _record(
            "r2",
            2,
            resolved_order_strategy="shuffle",
            ordering_resolution_source="default",
        ),
    )
    manifest = roi.write_manifest(str(tmp_path), "manifest_ordering_test", [output])

    entries = manifest["ordering_by_experiment"]
    assert len(entries) == 2, "each round must appear separately"

    first, second = entries
    assert first["exp_id"] == "r1"
    assert first["round_index"] == 1
    assert first["resolved_order_strategy"] == "sequential"
    assert first["resolved_file_order"] == PERMUTATION
    assert first["ordering_resolution_source"] == "agent_proposal"

    assert second["exp_id"] == "r2"
    assert second["round_index"] == 2
    assert second["resolved_order_strategy"] == "shuffle"
    assert second["resolved_file_order"] is None
    assert second["ordering_resolution_source"] == "default"


def test_no_iteration_level_ordering_key_exists(tmp_path):
    """Guard against a future 'simplification' that collapses the list."""
    manifest = roi.write_manifest(
        str(tmp_path),
        "manifest_ordering_test",
        [_output(_record("r1", 1, resolved_order_strategy="sequential"))],
    )
    collapsed = [
        key for key in manifest if "order" in key.lower() and key != "ordering_by_experiment"
    ]
    assert collapsed == [], f"iteration-level ordering keys are forbidden: {collapsed}"


def test_a_rejected_proposal_reaches_the_manifest(tmp_path):
    manifest = roi.write_manifest(
        str(tmp_path),
        "manifest_ordering_test",
        [
            _output(
                _record(
                    "r1",
                    1,
                    proposed_order_strategy="sequential",
                    proposed_file_order=[4, 4, 4],
                    ordering_proposal_rejected=True,
                    ordering_proposal_rejection_reason="duplicate file indices [4]",
                    resolved_order_strategy="shuffle",
                    ordering_resolution_source="default",
                )
            )
        ],
    )
    entry = manifest["ordering_by_experiment"][0]
    assert entry["ordering_proposal_rejected"] is True
    assert "duplicate" in entry["ordering_proposal_rejection_reason"]
    assert entry["proposed_order_strategy"] == "sequential"
    assert entry["resolved_order_strategy"] == "shuffle"


def test_an_overridden_proposal_keeps_both_sides(tmp_path):
    manifest = roi.write_manifest(
        str(tmp_path),
        "manifest_ordering_test",
        [
            _output(
                _record(
                    "r1",
                    1,
                    proposed_order_strategy="sequential",
                    proposed_file_order=PERMUTATION,
                    override_order_strategy="shuffle",
                    resolved_order_strategy="shuffle",
                    ordering_resolution_source="operator_override",
                )
            )
        ],
    )
    entry = manifest["ordering_by_experiment"][0]
    assert entry["proposed_order_strategy"] == "sequential"
    assert entry["override_order_strategy"] == "shuffle"
    assert entry["resolved_order_strategy"] == "shuffle"
    assert entry["ordering_resolution_source"] == "operator_override"


def test_legacy_records_read_as_legacy_default(tmp_path):
    manifest = roi.write_manifest(
        str(tmp_path), "manifest_ordering_test", [_output(_record("legacy", 1))]
    )
    entry = manifest["ordering_by_experiment"][0]
    assert entry["resolved_order_strategy"] == "shuffle"
    assert entry["ordering_resolution_source"] == "legacy_default"
    assert entry["proposed_order_strategy"] is None


def test_manifest_is_written_as_json_on_disk(tmp_path):
    """The block must survive serialization — it is a cross-process handoff."""
    roi.write_manifest(
        str(tmp_path),
        "manifest_ordering_test",
        [
            _output(
                _record(
                    "r1",
                    1,
                    resolved_order_strategy="sequential",
                    resolved_file_order=PERMUTATION,
                    ordering_resolution_source="operator_override",
                )
            )
        ],
    )
    with open(os.path.join(str(tmp_path), "manifest.json")) as f:
        on_disk = json.load(f)
    assert on_disk["ordering_by_experiment"][0]["resolved_file_order"] == PERMUTATION


@pytest.mark.parametrize("crashed", [True, False])
def test_degenerate_manifests_do_not_carry_the_block(tmp_path, crashed):
    """A crashed or record-less iteration has no ordering to report; the key
    is simply absent rather than an empty-but-present claim."""
    manifest = roi.write_manifest(
        str(tmp_path), "manifest_ordering_test", results=[], crashed=crashed
    )
    assert "ordering_by_experiment" not in manifest
