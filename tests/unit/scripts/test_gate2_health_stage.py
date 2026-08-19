# tests/unit/scripts/test_gate2_health_stage.py
"""Step 08c C5 — the ONE shared runner Health evidence stage.

The §2.8 audit found NO existing test owns the two D14 runners, so THIS
module is the first owner of the runner evidence contract:

* the binding is EXPLICIT state C and threaded end-to-end (the block
  records the pack path; the pinned effective sha in the block equals the
  materialized artifact's own sha; the pack plugin's canonical identity is
  present);
* EVERY selected gate is evaluated and persisted — evidence collection,
  not tuner round control: on the collapsed Pets fixture the FIRST
  blocking gate resolves ``invalidate_round`` and the SECOND gate's
  evidence must still be present, with the thresholds and decisive
  metrics needed to interpret both;
* a missing binding file refuses LOUDLY before any evaluation;
* the runners' evidence stays ADDITIVE: each runner's evidence keys are
  exactly the pre-C5 D14 set plus ``health`` (structural census over both
  runner sources);
* the stage is task-agnostic (the DAVIS pack flows through the same
  helper).
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from execute_tools.davis_data_path import DavisClip, DavisTaskDataPath
from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.config import read_effective_config_body_sha
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from execute_tools.task_data_path import DeliverableWriteRequest
from scripts._gate2_health_stage import run_health_stage

REPO_ROOT = Path(__file__).resolve().parents[3]

PETS_PACK = REPO_ROOT / "examples" / "oxford_iiit_pet"
PETS_BINDING = PETS_PACK / "declared" / "task_health.yaml"
PETS_FIXTURE = PETS_PACK / "expected" / "d14_gate2_collapse_predictions.csv"

DAVIS_PACK = REPO_ROOT / "examples" / "davis_future_prediction"
DAVIS_BINDING = DAVIS_PACK / "declared" / "task_health.yaml"

RUNNERS = {
    "pets": REPO_ROOT / "scripts" / "run_pets_gate2.py",
    "davis": REPO_ROOT / "scripts" / "run_davis_gate2.py",
}

#: The D14 evidence keys as they existed BEFORE C5 (golden, hardcoded from
#: the merged D14 runners at 70eb21b9). Additivity means: exactly these
#: plus ``health``, nothing renamed, nothing removed.
PRE_C5_EVIDENCE_KEYS = {
    "gate",
    "commit",
    "device",
    "subsets",
    "epochs",
    "batch_size",
    "training",
    "inference",
    "metric",
    "verdict",
}


@pytest.fixture(autouse=True)
def _isolated_registries_and_run_scope():
    registry_snapshot = dict(_REGISTRY)
    provider_snapshot = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry_snapshot)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(provider_snapshot)
        _plugin_binding.reset_run_scope()


class TestExplicitBindingThreadedEndToEnd:
    def test_the_block_records_the_binding_the_pin_and_the_plugin(self, tmp_path):
        block = run_health_stage(
            workspace=tmp_path,
            task_health_binding=PETS_BINDING,
            deliverable_path=PETS_FIXTURE,
            model_name="pets_reference_cnn",
            run_name="t",
        )

        assert block["task_health_binding"] == str(PETS_BINDING)
        effective = tmp_path / "health_checks_effective.yaml"
        assert effective.is_file()
        assert block["effective_config_sha256"] == read_effective_config_body_sha(str(effective))
        (plugin,) = block["resolved_plugins"]
        assert plugin["configured_ref"] == "../plugins/_pets_health_views.py"
        assert len(plugin["content_sha256"]) == 64

    def test_a_missing_binding_refuses_loudly_before_evaluation(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="EXPLICIT state-C binding"):
            run_health_stage(
                workspace=tmp_path,
                task_health_binding=tmp_path / "absent" / "task_health.yaml",
                deliverable_path=PETS_FIXTURE,
                model_name="m",
                run_name="t",
            )
        assert not (tmp_path / "health_checks_effective.yaml").exists()


class TestEverySelectedGateIsPersisted:
    """Evidence collection, not round control (§3.5 amendment 9)."""

    def test_both_pets_gates_present_even_though_the_first_blocks(self, tmp_path):
        block = run_health_stage(
            workspace=tmp_path,
            task_health_binding=PETS_BINDING,
            deliverable_path=PETS_FIXTURE,
            model_name="pets_reference_cnn",
            run_name="t",
        )

        gates = block["gates"]
        assert [g["gate_id"] for g in gates] == [
            "pets_distinct_symbols_blocking",
            "pets_dominant_fraction_blocking",
        ]
        first, second = gates
        # The first blocking gate FAILS the collapsed fixture and resolves
        # invalidate_round — and the second gate's evidence is STILL here.
        assert first["check_verdicts"] == {"categorical_distinct_symbols": "failed"}
        assert first["resolved_action"] == "invalidate_round"
        assert second["check_verdicts"] == {"categorical_dominant_fraction": "failed"}
        assert second["resolved_action"] == "invalidate_round"

        # The thresholds needed to interpret the result travel in the block.
        assert first["check_configs"]["categorical_distinct_symbols"]["min_distinct_symbols"] == 5
        assert (
            second["check_configs"]["categorical_dominant_fraction"]["max_dominant_fraction"]
            == 0.95
        )
        assert first["check_configs"]["categorical_distinct_symbols"]["symbol_cardinality"] == 37

        # The decisive metrics — the §2.5 values.
        distinct_metrics = first["metrics"]["categorical_distinct_symbols"]
        assert distinct_metrics["distinct_symbols"] == 2
        assert distinct_metrics["occupancy"] == 0.05405405405405406
        dominant_metrics = second["metrics"]["categorical_dominant_fraction"]
        assert dominant_metrics["dominant_fraction"] == 0.9972972972972973

    def test_the_block_is_json_serializable(self, tmp_path):
        import json

        block = run_health_stage(
            workspace=tmp_path,
            task_health_binding=PETS_BINDING,
            deliverable_path=PETS_FIXTURE,
            model_name="pets_reference_cnn",
            run_name="t",
        )
        round_tripped = json.loads(json.dumps(block))
        assert round_tripped["gates"][0]["gate_id"] == "pets_distinct_symbols_blocking"


class TestTheStageIsTaskAgnostic:
    def test_the_davis_pack_flows_through_the_same_helper(self, tmp_path):
        deliverable_dir = tmp_path / "out"
        deliverable_dir.mkdir()
        DavisTaskDataPath().write_deliverable(
            [
                (DavisClip(sequence_name="a", start_frame=0), np.array([[0.0, 2.0]])),
                (DavisClip(sequence_name="b", start_frame=0), np.array([[4.0, 6.0]])),
            ],
            DeliverableWriteRequest(
                output_dir=str(deliverable_dir),
                exp_id="e1",
                run_name="t",
                model_type="davis_reference_predictor",
            ),
        )
        deliverable = deliverable_dir / "predictions_davis_reference_predictor_t_e1.npz"

        block = run_health_stage(
            workspace=tmp_path,
            task_health_binding=DAVIS_BINDING,
            deliverable_path=deliverable,
            model_name="davis_reference_predictor",
            run_name="t",
        )

        (gate,) = block["gates"]
        assert gate["gate_id"] == "davis_dispersion_blocking"
        assert gate["check_verdicts"] == {"sample_dispersion_floor": "passed"}
        assert gate["metrics"]["sample_dispersion_floor"]["dispersion"] == pytest.approx(
            np.sqrt(5.0)
        )
        assert gate["check_configs"]["sample_dispersion_floor"]["min_dispersion"] == 0.04
        (plugin,) = block["resolved_plugins"]
        assert plugin["configured_ref"] == "../plugins/_davis_health_views.py"


class TestRunnerEvidenceStaysAdditive:
    """Structural census over both runner sources (golden pre-C5 key set)."""

    @staticmethod
    def _evidence_keys(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        keys: set[str] = set()
        for node in ast.walk(tree):
            # evidence["<key>"] = …
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "evidence"
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                    ):
                        keys.add(target.slice.value)
                # evidence: dict = {…literal…}  /  evidence = {…literal…}
                if (
                    isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "evidence"
                    and isinstance(node.value, ast.Dict)
                ):
                    keys.update(
                        k.value
                        for k in node.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    )
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "evidence"
                and isinstance(node.value, ast.Dict)
            ):
                keys.update(
                    k.value
                    for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                )
        return keys

    @pytest.mark.parametrize("task", sorted(RUNNERS))
    def test_the_runner_evidence_keys_are_the_pre_c5_set_plus_health(self, task):
        keys = self._evidence_keys(RUNNERS[task])
        assert keys == PRE_C5_EVIDENCE_KEYS | {"health"}, (
            f"{task} runner evidence keys drifted: {sorted(keys)}"
        )

    def test_the_key_extractor_actually_finds_keys(self):
        """Guards the guard: an extractor returning ∅ makes equality vacuous."""
        for path in RUNNERS.values():
            assert "metric" in self._evidence_keys(path)
